/*
 * Video output device using the kitty terminal graphics protocol
 * See https://sw.kovidgoyal.net/kitty/graphics-protocol/
 *
 * This file is part of mpv.
 *
 * mpv is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * mpv is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with mpv.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>

#include "config.h"
#if HAVE_ZLIB
#include <zlib.h>
#endif

#if HAVE_POSIX
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#include <libswscale/swscale.h>
#include <libavutil/base64.h>
#include <libavutil/random_seed.h>

#include "options/m_config.h"
#include "input/input.h"
#include "osdep/terminal.h"
#include "osdep/timer.h"
#include "sub/osd.h"
#include "vo.h"
#include "video/sws_utils.h"
#include "video/mp_image.h"

#define IMGFMT IMGFMT_RGB24
#define BYTES_PER_PX 3
#define DEFAULT_WIDTH_PX  320
#define DEFAULT_HEIGHT_PX 240
#define DEFAULT_WIDTH 80
#define DEFAULT_HEIGHT 25

static inline void write_bstr(bstr bs)
{
    // On POSIX platforms, write() is the fastest method. It also is the only
    // one that allows atomic writes so mpv’s output will not be interrupted
    // by other processes or threads that write to stdout, which would cause
    // screen corruption. POSIX does not guarantee atomicity for writes
    // exceeding PIPE_BUF, but at least Linux does seem to implement it that
    // way.
#if HAVE_POSIX
    size_t remain = bs.len;
    unsigned char *pos = bs.start;
    while (remain > 0) {
        ssize_t written = write(STDOUT_FILENO, pos, remain);
        if (written < 0 && errno == EINTR)
            continue;
        if (written <= 0)
            return;
        remain -= written;
        pos += written;
    }
#else
    fwrite(bs.start, 1, bs.len, stdout);
    fflush(stdout);
#endif
}

static inline void write_str(unsigned char* s)
{
    write_bstr(bstr0(s));
}

#define KITTY_ESC_CONTINUE   "\033_Gm=%d;"
static const bstr KITTY_ESC_END = bstr0_lit("\033\\");

struct vo_kitty_opts {
    int width, height, top, left, rows, cols;
    bool config_clear, alt_screen;
    bool use_shm;
    int compression, compression_threshold;
};

struct priv {
    struct vo_kitty_opts opts;

    uint8_t *buffer;
    char    *output;
    char    *shm_path, *shm_path_b64;
    char    *shm_names[3];
    bool shm_owned[3];
    unsigned shm_slot;
    int     buffer_size, output_size, output_length;
    uint8_t *compressed;
    size_t compressed_capacity;
    bool frame_compressed, frame_ready;
    unsigned image_ids[2], image_index;
    bool has_image;
    int     shm_fd;
    bstr    cmd;

    int left, top, width, height, cols, rows;
    double display_par;

    struct mp_rect src;
    struct mp_rect dst;
    struct mp_osd_res osd;
    struct mp_image *frame;
    struct mp_sws_context *sws;
};

static void close_shm(struct priv *p)
{
#if HAVE_POSIX_SHM
    if (p->buffer != NULL) {
        munmap(p->buffer, p->buffer_size);
        p->buffer = NULL;
    }
    if (p->shm_fd != -1) {
        close(p->shm_fd);
        p->shm_fd = -1;
    }
#endif
}

static void free_bufs(struct vo* vo)
{
    struct priv* p = vo->priv;

    TA_FREEP(&p->frame);
    TA_FREEP(&p->output);
    TA_FREEP(&p->compressed);
    p->frame_ready = false;
    talloc_free(p->cmd.start);
    p->cmd = (bstr){0};

    if (p->opts.use_shm) {
        close_shm(p);
    } else {
        TA_FREEP(&p->buffer);
    }
}

static void delete_images(struct vo *vo)
{
    struct priv *p = vo->priv;
    char command[160];
    snprintf(command, sizeof(command),
             "\033_Ga=d,d=I,i=%u,q=2;\033\\"
             "\033_Ga=d,d=I,i=%u,q=2;\033\\",
             p->image_ids[0], p->image_ids[1]);
    write_str((unsigned char *)command);
    p->has_image = false;
}

static void get_win_size(struct vo *vo, int *out_rows, int *out_cols,
                         int *out_width, int *out_height)
{
    struct priv *p = vo->priv;
    *out_rows = DEFAULT_HEIGHT;
    *out_cols = DEFAULT_WIDTH;
    *out_width = DEFAULT_WIDTH_PX;
    *out_height = DEFAULT_HEIGHT_PX;

    terminal_get_size2(out_rows, out_cols, out_width, out_height);

    *out_rows = p->opts.rows > 0 ? p->opts.rows : *out_rows;
    *out_cols = p->opts.cols > 0 ? p->opts.cols : *out_cols;
    *out_width = p->opts.width > 0 ? p->opts.width : *out_width;
    *out_height = p->opts.height > 0 ? p->opts.height : *out_height;
}

static void set_out_params(struct vo *vo)
{
    struct priv *p = vo->priv;

    vo_get_src_dst_rects(vo, &p->src, &p->dst, &p->osd);

    p->width  = p->dst.x1 - p->dst.x0;
    p->height = p->dst.y1 - p->dst.y0;
    p->top  = p->opts.top > 0 ?
        p->opts.top : p->rows * p->dst.y0 / vo->dheight;
    p->left = p->opts.left > 0 ?
        p->opts.left : p->cols * p->dst.x0 / vo->dwidth;
    p->display_par = p->osd.display_par;
    // The terminal reports mouse positions in the whole pane, while the OSC
    // is drawn into the scaled video rectangle. Use the cell-snapped origin
    // actually sent on the wire, including letterbox offsets.
    struct mp_rect mouse_area = {
        .x0 = p->left * vo->dwidth / p->cols,
        .y0 = p->top * vo->dheight / p->rows,
    };
    mouse_area.x1 = mouse_area.x0 + p->width;
    mouse_area.y1 = mouse_area.y0 + p->height;
    mp_input_set_mouse_transform(vo->input_ctx, &mouse_area, NULL);
}

static int reconfig(struct vo *vo, struct mp_image_params *params)
{
    struct priv *p = vo->priv;

    vo->want_redraw = true;
    delete_images(vo);
    if (p->opts.config_clear)
        write_str(TERM_ESC_CLEAR_SCREEN);

    // Release using the OLD mapping size before updating geometry.
    free_bufs(vo);
    get_win_size(vo, &p->rows, &p->cols, &vo->dwidth, &vo->dheight);
    set_out_params(vo);
    if (p->width <= 0 || p->height <= 0 ||
        p->width > (INT_MAX - 4) / 4 / p->height)
        return -1;
    p->buffer_size = 3 * p->width * p->height;
    p->output_size = AV_BASE64_SIZE(p->buffer_size);

    p->sws->src = *params;
    p->sws->src.w = mp_rect_w(p->src);
    p->sws->src.h = mp_rect_h(p->src);
    p->sws->dst = (struct mp_image_params) {
        .imgfmt = IMGFMT,
        .w = p->width,
        .h = p->height,
        .p_w = 1,
        .p_h = 1,
    };

    p->frame = mp_image_alloc(IMGFMT, p->width, p->height);
    if (!p->frame)
        return -1;

    if (mp_sws_reinit(p->sws) < 0)
        return -1;

    if (!p->opts.use_shm) {
        p->buffer = talloc_array(NULL, uint8_t, p->buffer_size);
        p->output = talloc_array(NULL, char, p->output_size);
#if HAVE_ZLIB
        if (p->opts.compression) {
            p->compressed_capacity = compressBound(p->buffer_size);
            p->compressed = talloc_array(NULL, uint8_t, p->compressed_capacity);
        }
#endif
    }

    return 0;
}

static int create_shm(struct vo *vo)
{
#if HAVE_POSIX_SHM
    struct priv *p = vo->priv;
    // Like kitty-framebuffer, retain a bounded ring of immutable objects.
    // Kitty unlinks a name after reading it; never overwrite an unread frame.
    for (unsigned tries = 0; tries < 3; tries++) {
        unsigned slot = (p->shm_slot + tries) % 3;
        int fd = shm_open(p->shm_names[slot], O_CREAT | O_EXCL | O_RDWR,
                          S_IRUSR | S_IWUSR);
        if (fd < 0)
            continue;
        p->shm_slot = (slot + 1) % 3;
        p->shm_owned[slot] = true;
        p->shm_path = p->shm_names[slot];
        p->shm_fd = fd;
        int size = strlen(p->shm_path + 1);
        av_base64_encode(p->shm_path_b64, 256, p->shm_path + 1, size);
        break;
    }
    if (p->shm_fd < 0)
        return 0; // Backpressure: skip this frame without blocking the clock.

    if (ftruncate(p->shm_fd, p->buffer_size) == -1) {
        MP_ERR(vo, "Failed to truncate shared memory object");
        shm_unlink(p->shm_path);
        close(p->shm_fd);
        p->shm_fd = -1;
        return 0;
    }

    p->buffer = mmap(NULL, p->buffer_size,
                        PROT_READ | PROT_WRITE, MAP_SHARED, p->shm_fd, 0);

    if (p->buffer == MAP_FAILED) {
        p->buffer = NULL;
        MP_ERR(vo, "Failed to mmap shared memory object");
        shm_unlink(p->shm_path);
        close(p->shm_fd);
        p->shm_fd = -1;
        return 0;
    }
    return 1;
#else
    return 0;
#endif
}

static bool draw_frame(struct vo *vo, struct vo_frame *frame)
{
    struct priv *p = vo->priv;
    mp_image_t *mpi = NULL;

    p->frame_ready = false;
    if (!p->frame)
        return VO_FALSE;

    if (frame->current) {
        mpi = mp_image_new_ref(frame->current);
        struct mp_rect src_rc = p->src;
        src_rc.x0 = MP_ALIGN_DOWN(src_rc.x0, mpi->fmt.align_x);
        src_rc.y0 = MP_ALIGN_DOWN(src_rc.y0, mpi->fmt.align_y);
        mp_image_crop_rc(mpi, src_rc);

        mp_sws_scale(p->sws, p->frame, mpi);
    } else {
        mp_image_clear(p->frame, 0, 0, p->width, p->height);
    }

    struct mp_osd_res res = { .w = p->width, .h = p->height, .display_par = p->display_par };
    osd_draw_on_image(vo->osd, res, mpi ? mpi->pts : 0, 0, p->frame);

    if (p->opts.use_shm && !create_shm(vo))
        goto done;

    memcpy_pic(p->buffer, p->frame->planes[0], p->width * BYTES_PER_PX,
               p->height, p->width * BYTES_PER_PX, p->frame->stride[0]);

    if (!p->opts.use_shm) {
        const uint8_t *pixels = p->buffer;
        size_t length = p->buffer_size;
        p->frame_compressed = false;
#if HAVE_ZLIB
        if (p->opts.compression) {
            // A small distributed sample avoids spending a full zlib pass on
            // photographic/noisy frames that barely shrink. Transport remains
            // lossless: this chooses between raw RGB and the same RGB deflated.
            uint8_t sample[8192];
            size_t sample_length = MPMIN(sizeof(sample), length);
            const uint8_t *probe = pixels;
            if (sample_length < length) {
                for (size_t part = 0; part < 4; part++)
                    memcpy(sample + part * 2048,
                           pixels + part * (length - 2048) / 3, 2048);
                probe = sample;
            }
            uLongf probe_length = p->compressed_capacity;
            bool worthwhile = compress2(p->compressed, &probe_length, probe,
                                        sample_length, p->opts.compression) == Z_OK &&
                probe_length * 100 < sample_length * p->opts.compression_threshold;
            if (worthwhile) {
                uLongf compressed_length = p->compressed_capacity;
                if (compress2(p->compressed, &compressed_length, pixels, length,
                              p->opts.compression) == Z_OK && compressed_length < length) {
                    pixels = p->compressed;
                    length = compressed_length;
                    p->frame_compressed = true;
                }
            }
        }
#endif
        av_base64_encode(p->output, p->output_size, pixels, length);
        // Capacity includes the C string terminator; the wire payload must not.
        p->output_length = AV_BASE64_SIZE(length) - 1;
    }
    p->frame_ready = true;

done:
    talloc_free(mpi);
    return VO_TRUE;
}

static void flip_page(struct vo *vo)
{
    struct priv *p = vo->priv;
    if (!p->frame_ready)
        return;

    p->cmd.len = 0;
    unsigned next = p->image_index ^ 1;
    // Follow kitty-framebuffer's synchronized double-buffer presentation:
    // complete the new image before deleting only the previous owned image.
    bstr_xappend(NULL, &p->cmd, bstr0("\033[?2026h"));
    bstr_xappend_asprintf(NULL, &p->cmd, TERM_ESC_GOTO_YX, p->top + 1, p->left + 1);
    if (p->opts.use_shm) {
        bstr_xappend_asprintf(NULL, &p->cmd,
            "\033_Ga=T,t=s,f=24,s=%d,v=%d,i=%u,z=-1,C=1,q=2;%s\033\\",
            p->width, p->height, p->image_ids[next], p->shm_path_b64);
    } else {
        for (int offset = 0; offset < p->output_length;) {
            int chunk = MPMIN(4096, p->output_length - offset);
            int more = offset + chunk < p->output_length;
            if (offset == 0) {
                bstr_xappend_asprintf(NULL, &p->cmd,
                    "\033_Ga=T,f=24,s=%d,v=%d,i=%u,z=-1,C=1,q=2,%sm=%d;",
                    p->width, p->height, p->image_ids[next],
                    p->frame_compressed ? "o=z," : "", more);
            } else {
                bstr_xappend_asprintf(NULL, &p->cmd, KITTY_ESC_CONTINUE, more);
            }
            bstr_xappend(NULL, &p->cmd, (bstr){(unsigned char *)p->output + offset, chunk});
            bstr_xappend(NULL, &p->cmd, KITTY_ESC_END);
            offset += chunk;
        }
    }
    if (p->has_image)
        bstr_xappend_asprintf(NULL, &p->cmd, "\033_Ga=d,d=I,i=%u,q=2;\033\\",
                              p->image_ids[p->image_index]);
    bstr_xappend(NULL, &p->cmd, bstr0("\033[?2026l"));
    write_bstr(p->cmd);
    p->image_index = next;
    p->has_image = true;
    p->frame_ready = false;

#if HAVE_POSIX
    if (p->opts.use_shm)
        close_shm(p);
#endif
}

static int preinit(struct vo *vo)
{
    struct priv *p = vo->priv;

    p->image_ids[0] = 0x40000000u | (av_get_random_seed() & 0x3ffffffeu);
    p->image_ids[1] = p->image_ids[0] + 1;
    p->sws = mp_sws_alloc(vo);
    p->sws->log = vo->log;
    mp_sws_enable_cmdline_opts(p->sws, vo->global);

#if HAVE_POSIX_SHM
    if (p->opts.use_shm) {
        unsigned nonce = av_get_random_seed();
        for (unsigned i = 0; i < 3; ++i)
            p->shm_names[i] = talloc_asprintf(vo, "/kilix-mpv-%ld-%08x-%u",
                                             (long)getpid(), nonce, i);
        p->shm_path_b64 = talloc_array(vo, char, 256);
    }
#else
    if (p->opts.use_shm) {
        MP_ERR(vo, "Shared memory support is not available on this platform.");
        return -1;
    }
#endif

    write_str(TERM_ESC_HIDE_CURSOR);
    terminal_set_mouse_input(true);
    if (p->opts.alt_screen)
        write_str(TERM_ESC_ALT_SCREEN);

    return 0;
}

static int query_format(struct vo *vo, int format)
{
    return format == IMGFMT;
}

static int control(struct vo *vo, uint32_t request, void *data)
{
    if (request == VOCTRL_CHECK_EVENTS && vo->config_ok) {
        struct priv *p = vo->priv;
        int rows, cols, width, height;
        get_win_size(vo, &rows, &cols, &width, &height);
        if (rows != p->rows || cols != p->cols ||
            width != vo->dwidth || height != vo->dheight) {
            if (reconfig(vo, vo->params) < 0)
                return VO_FALSE;
            vo_event(vo, VO_EVENT_RESIZE);
        }
        return VO_TRUE;
    }
    if (request == VOCTRL_SET_PANSCAN)
        return (vo->config_ok && !reconfig(vo, vo->params)) ? VO_TRUE : VO_FALSE;
    return VO_NOTIMPL;
}

static void wait_events(struct vo *vo, int64_t until_time_ns)
{
    // A paused video must resize without waiting for another decoded frame or
    // mouse event. Polling also works when the PTY does not deliver SIGWINCH.
    vo_wait_default(vo, MPMIN(until_time_ns, mp_time_ns() + MP_TIME_MS_TO_NS(100)));
}

static void uninit(struct vo *vo)
{
    struct priv *p = vo->priv;

    write_str((unsigned char *)"\033[?2026l");
    delete_images(vo);
    write_str(TERM_ESC_RESTORE_CURSOR);
    terminal_set_mouse_input(false);
    mp_input_set_mouse_transform(vo->input_ctx, NULL, NULL);

    if (p->opts.alt_screen) {
        write_str(TERM_ESC_NORMAL_SCREEN);
    } else {
        char *cmd = talloc_asprintf(vo, TERM_ESC_GOTO_YX, p->rows, 1);
        write_str(cmd);
    }

    free_bufs(vo);
#if HAVE_POSIX_SHM
    for (unsigned i = 0; i < 3; ++i)
        if (p->shm_owned[i])
            shm_unlink(p->shm_names[i]);
#endif
}

#define OPT_BASE_STRUCT struct priv

const struct vo_driver video_out_kitty = {
    .name = "kitty",
    .description = "Kitty terminal graphics protocol",
    .preinit = preinit,
    .query_format = query_format,
    .reconfig = reconfig,
    .control = control,
    .draw_frame = draw_frame,
    .flip_page = flip_page,
    .uninit = uninit,
    .wait_events = wait_events,
    .priv_size = sizeof(struct priv),
    .priv_defaults = &(const struct priv) {
        .shm_fd = -1,
        .opts.config_clear = true,
        .opts.alt_screen = true,
#if HAVE_ZLIB
        .opts.compression = 1,
        .opts.compression_threshold = 70,
#endif
    },
    .options = (const m_option_t[]) {
        {"width", OPT_INT(opts.width)},
        {"height", OPT_INT(opts.height)},
        {"top", OPT_INT(opts.top)},
        {"left", OPT_INT(opts.left)},
        {"rows", OPT_INT(opts.rows)},
        {"cols", OPT_INT(opts.cols)},
        {"config-clear", OPT_BOOL(opts.config_clear), },
        {"alt-screen", OPT_BOOL(opts.alt_screen), },
        {"use-shm", OPT_BOOL(opts.use_shm), },
#if HAVE_ZLIB
        {"compression", OPT_INT(opts.compression), M_RANGE(0, 9)},
        {"compression-threshold", OPT_INT(opts.compression_threshold), M_RANGE(1, 100)},
#endif
        {0}
    },
    .options_prefix = "vo-kitty",
};
