# kilix-mpv

A narrowly maintained mpv fork for `kilix video`, required for Plebian-OS 0.2.2
after the frozen RC6 candidate. Package publication, coordinated OS integration,
and target-image playback acceptance remain pending. The upstream version and
commit are recorded in UPSTREAM.json. Version `0.40.0+kilix.2` improves terminal
transport, input, and presentation while retaining mpv's decoder and playback clock.
Version `0.40.0+kilix.3` keeps the visible image during reconfiguration and clears
the screen only inside the synchronized replacement frame, preventing a paused
resize from erasing the video and persistent diagnostics prematurely.
Version `0.40.0+kilix.4` negotiates pixel mouse coordinates for small OSC targets,
connects fullscreen toggles to Kilix, and counts frames skipped by a busy SHM ring.
Version `0.40.0+kilix.5` sizes frames from `KILIX_MPV_CELL_SIZE=<width>x<height>`
when the PTY reports cells but no pixels, as in WSL panes behind ConPTY. Without
it (or with a malformed value) mpv still assumes 9x18-pixel cells.

The Debian package installs `/usr/bin/kilix-mpv`. It does not provide, replace,
or conflict with `/usr/bin/mpv`. Kilix owns terminal cleanup and prefers this
named player. Running it directly retains upstream mpv's configuration behavior.

The package also installs `kilix-video FILE`, the matching Kilix launcher with
terminal recovery and a persistent warning/error panel. The first four distinct
messages stay visible until exit; additional diagnostics are printed after the
terminal is restored. The launcher automatically selects shared memory when it
can verify a local Kitty/Kilix process with the same `/dev/shm` directory; otherwise
it uses inline transfer. `--transport inline` and `--transport shm` override this. The launcher source revision and file hashes are pinned in `LAUNCHER.json`.
Its GPL license and provenance are installed beside the player notices, and its
exact source archive accompanies the package. `kilix video FILE` in the matching
next-release host uses the same launcher.

## Build and check

On Debian 13, install `build-essential meson ninja-build pkg-config git dpkg-dev
python3 ffmpeg libavcodec-dev libavfilter-dev libavformat-dev libavutil-dev
libswresample-dev libswscale-dev libplacebo-dev libass-dev libluajit-5.1-dev
libpulse-dev zlib1g-dev` and their package dependencies. Then, from a clean checkout:

```sh
bash kilix/build-package.sh /absolute/output/directory
```

This builds terminal playback with Lua controls and PulseAudio, stages without
root, removes build-tree runtime paths through Meson's install step, tests the
staged executable in private PTYs, and creates a Debian package, corresponding
source archive, metadata and SHA256SUMS. Dependencies are derived from the binary
using dpkg-shlibdeps. The output directory must be outside the checkout.
`KILIX_MPV_BUILD_JOBS` controls parallel compilation (default 2).
The build fetches the pinned launcher commit. For an offline build, set
`KILIX_LAUNCHER_SOURCE` to a Git repository containing that commit; files are read
from the pinned Git objects and verified against their hashes.

The tests exercise mouse actions, paused resizing, keyboard seek, tiny graphics
packets, missing pixel geometry with and without a measured cell size, bounded
shared-memory backpressure and normal exit. Native visual/OSC checks are available separately. Full release acceptance
still requires physical display/audio checks and a clean
Debian image install. Package builds are ABI-specific; publish only after those
checks, and pin both source commit and package checksum in the stack release.

## Terminal transport and controls

Inline RGB transport is lossless. By default a distributed 8 KiB sample decides
whether zlib level 1 compression is worthwhile (sample must shrink below 70%).
Incompressible footage stays raw, avoiding a full-frame compression pass.
`--vo-kitty-compression=0` disables compression; levels 1–9 and
`--vo-kitty-compression-threshold=1..100` are available for experiments.
This changes the wire representation, not the scaled RGB pixels.

The presenter adapts `kitty-framebuffer`'s synchronized updates, two named image
IDs, targeted deletion and bounded shared-memory approach. It uses mpv's own
clock and scaler instead of adding the library's second presentation thread.
The compatible image layer is `z=-1`; the framebuffer library's deeper negative
layer was invisible in the tested engine. Frame replacement and exit delete only
owned image IDs. The existing alternate-screen and config-clear behavior still
applies: use `--vo-kitty-config-clear=no` to avoid clearing the screen on
reconfiguration. Private objects are cleaned up on normal exit.

Local playback can use `--vo-kitty-use-shm=yes` to bypass base64 and PTY pixel
copies. Three randomly named, owner-only objects hold immutable frames; terminal
unlink acknowledges consumption. A busy ring skips a frame rather than
overwriting unread pixels. The terminal and player must share a POSIX shared-memory namespace; shared
memory cannot cross SSH. The launcher defaults to `--transport auto`, proving
local process ownership and the shared directory before choosing SHM. Unknown
terminals, separate namespaces, SSH and tmux retain inline transfer. Explicit
`--transport shm` still requires a local shared namespace.

SGR input supports large terminal coordinates, release, modifiers, wheel and
motion, while retaining legacy X10 input. Mouse positions account for the
cell-snapped letterbox origin. DEC mode 1016 is enabled and queried; supporting
terminals report exact pixel positions, while other terminals retain SGR cell
coordinates. Both modes are disabled on exit and supervisor recovery. Paused
video checks geometry every 100 ms; it redraws without waiting for playback.
Use Kilix's native mouse cursor (`software_mouse_cursor none`, `mouse_hide_wait 0`).
The host disables text status overlays and restores synchronized-update and
mouse modes even after a player crash.

The launcher enables `--vo-kitty-terminal-fullscreen=yes` in a Kilix context when
the selected player supports it. The OSC fullscreen button and `f` then send
Kilix's existing self-scoped fullscreen toggle over the calling tty. Requests are
serialized with graphics on the VO thread. This needs Kilix's existing remote
control permission (or an equivalent Kitty configuration). It toggles the terminal
window; mpv does not own that window or track fullscreen changes made outside mpv.

## Repeatable measurements

```sh
python3 -B kilix/benchmark-terminal.py /path/to/candidate comparison.json \
  --baseline /path/to/baseline --fixtures /path/to/fixtures
python3 -B kilix/test-protocol.py /path/to/candidate
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I . \
  kilix/test-mouse.c -o /tmp/kilix-mpv-test-mouse
/tmp/kilix-mpv-test-mouse
python3 -B kilix/test-native.py /path/to/candidate /path/to/kilix-engine \
  /path/to/fixtures/pattern.mkv /path/to/native-evidence
# Add --launcher /path/to/config/terminal_video.py to test the host supervisor.
# Repeat the native check with --shm for local shared-memory transport.
```

The benchmark interleaves baseline and candidate across deterministic patterned
and noisy clips at 640×360 and 1280×720, three repetitions by default. It decodes
every graphics packet, validates byte count/base64/zlib and compares full RGB
frame hashes (consecutive duplicate redraws are collapsed). It records wall and
child CPU time, first frame, wire bytes, image lifetimes and protocol defects.
Reported throughput includes the Python PTY consumer and is **not display FPS**.
The native check uses a private Xvfb display, clicks the actual OSC before/after
resize, verifies time-position changes, saves screenshots, and checks SHM cleanup.
Requires Xvfb, xdotool and ImageMagick; it does not touch the caller's window.

`resize-fix.patch` preserves the initial fork's historical minimal fix. The
maintained source and `UPSTREAM.json` describe the current broader changes.

## Maintenance and distribution

Keep upstream history and license notices. Review upstream releases and security
fixes; this fork does not promise a frozen upstream version indefinitely. Rebase
or merge deliberately, rerun terminal tests, and bump VERSION for every published
package. Each binary release must accompany its exact source archive and
checksums. Preserve GPL/LGPL notices; this build uses upstream's default GPL
configuration. The named binary avoids changing other applications' mpv behavior.

No RC6 release pin is changed by this repository. The next-release host branch
and release staging notes must be merged through the coordinated release process.
