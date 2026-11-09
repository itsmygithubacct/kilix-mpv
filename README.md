# kilix-mpv fork

kilix-mpv is a narrowly maintained fork of [mpv](https://github.com/mpv-player/mpv)
0.40.0 for playing video inside a Kilix terminal pane: it keeps mpv's decoders
and playback clock and changes the Kitty-graphics terminal output, mouse input
and resizing. The upstream mpv README follows this Kilix section unchanged.

**Status:** ships in Plebian-OS 0.2.3. Firstboot installs the Debian package
`kilix-mpv_0.40.0+kilix.7_amd64.deb` from this repository's
`v0.40.0-kilix.7-test.1` release, named by `PLEBIAN_OS_MPV_URL` in
`releases/0.2.3.env` and pinned there to source commit `d743a367` (the current
`main`) and to the Kilix launcher commit recorded in
[kilix/LAUNCHER.json](kilix/LAUNCHER.json). The package installs
`/usr/bin/kilix-mpv` and `/usr/bin/kilix-video`; it does not replace
`/usr/bin/mpv`.

## What it changes

- Lossless inline RGB transport over the Kitty graphics protocol, with zlib
  used only when a sample frame compresses well.
- Synchronized presentation with two owned image IDs, and cleanup that deletes
  only those images.
- An optional bounded shared-memory ring (`--vo-kitty-use-shm=yes`) for local
  playback, skipping a frame rather than overwriting unread pixels.
- SGR and pixel-precise (DEC 1016) mouse input mapped through the letterbox,
  paused-video resizing, and Kilix fullscreen from the OSC button or `f`.
- Frame sizing from `KILIX_MPV_CELL_SIZE` when the PTY reports no pixel size
  (WSL panes).

## Quick start

On Debian 13, with the build dependencies listed in
[kilix/README.md](kilix/README.md#build-and-check), from a clean checkout:

```sh
bash kilix/build-package.sh /absolute/output/directory
kilix-mpv FILE          # inline Kitty video in the current pane
kilix-video FILE        # the Kilix launcher, with terminal recovery
```

## Usage

| Command or option | What it does |
|---|---|
| `kilix-mpv FILE` | Play inline in the terminal; config files and options such as `--vo=tct` still override. |
| `kilix-video FILE [--transport auto\|inline\|shm]` | Play through the launcher, with a warning/error panel and crash recovery. |
| `kilix video FILE` | The same launcher from the Kilix command. |
| `--vo-kitty-compression=0..9`, `--vo-kitty-compression-threshold=1..100` | Tune or disable zlib transport. |
| `--vo-kitty-use-shm=yes` | Shared-memory frames (local only, not over SSH or tmux). |
| `--vo-kitty-config-clear=no` | Do not clear the screen on reconfiguration. |
| `bash kilix/build-package.sh DIR` | Build, test and package (`.deb`, source archive, SHA256SUMS). |

## How it works

```
kilix-video / kilix video FILE   (launcher from kilix, pinned in LAUNCHER.json)
   |  chooses shm or inline transport, restores the terminal on exit or crash
   v
kilix-mpv  (mpv 0.40.0 decoders, clock and scaler)
   |  vo=kitty: base64 RGB (optionally zlib) or /dev/shm frame objects
   v
Kilix pane  (Kitty graphics protocol, image layer z=-1, SGR/1016 mouse)
```

The changes live in mpv's Kitty video output and terminal input code; the
patches are summarised in [kilix/UPSTREAM.json](kilix/UPSTREAM.json). The
package build stages the player without root, runs the terminal tests in
private PTYs, bundles the pinned launcher files with their licence, and writes
the Debian package next to its exact source archive. Details are in
[kilix/README.md](kilix/README.md).

## Documentation

- [kilix/README.md](kilix/README.md): Kilix build, packaging, terminal
  transport, controls, measurements and maintenance.
- [kilix/UPSTREAM.json](kilix/UPSTREAM.json) and
  [kilix/LAUNCHER.json](kilix/LAUNCHER.json): the upstream tag and commit, and
  the launcher source pin.
- [DOCS/](DOCS/): upstream mpv documentation, including the manual sources
  under [DOCS/man/](DOCS/man/).

## Related repositories

- [kilix](https://github.com/itsmygithubacct/kilix#readme): `kilix video` and
  the launcher (`config/terminal_video.py`) packaged here.
- [kitty-framebuffer](https://github.com/itsmygithubacct/kitty-framebuffer#readme):
  the presentation approach the Kitty output adapts.
- [kilix-amp](https://github.com/itsmygithubacct/kilix-amp#readme): the Amp
  player, which needs kilix-mpv with lavfi/LADSPA filters.
- [plebian-os](https://github.com/itsmygithubacct/plebian-os#readme): installs
  the package.

## Part of Plebian-OS

kilix-mpv is one of the repositories behind
[Plebian-OS](https://github.com/itsmygithubacct/plebian-os#readme), a Debian
install whose desktop is [Kilix](https://github.com/itsmygithubacct/kilix#readme)
running the [Kilix 95](https://github.com/itsmygithubacct/kilix-95#readme)
desktop through [Pleb](https://github.com/itsmygithubacct/pleb#readme).
Plebian-OS installs its Debian package from this repository's releases at
firstboot. The map of every repository and how it ships is on the
[components page](https://github.com/itsmygithubacct/plebian-os/blob/main/docs/components.md).

## Licence and upstream attribution

kilix-mpv is mpv, by the mpv developers, based on MPlayer and mplayer2; see the
upstream text below and [Copyright](Copyright). The package uses upstream's
default GPL configuration and installs the GPL and LGPL notices with the
launcher's licence. Upstream licence: GPLv2 "or later" by default, LGPLv2.1
"or later" with `-Dgpl=false`.

See [Kilix build, packaging, and maintenance](kilix/README.md).
The upstream documentation follows.


![mpv logo](https://raw.githubusercontent.com/mpv-player/mpv.io/master/source/images/mpv-logo-128.png)

# mpv


* [External links](#external-links)
* [Overview](#overview)
* [System requirements](#system-requirements)
* [Downloads](#downloads)
* [Changelog](#changelog)
* [Compilation](#compilation)
* [Release cycle](#release-cycle)
* [Bug reports](#bug-reports)
* [Contributing](#contributing)
* [License](#license)
* [Contact](#contact)


## External links


* [Wiki](https://github.com/mpv-player/mpv/wiki)
* [User Scripts](https://github.com/mpv-player/mpv/wiki/User-Scripts)
* [FAQ][FAQ]
* [Manual](https://mpv.io/manual/master/)


## Overview


**mpv** is a free (as in freedom) media player for the command line. It supports
a wide variety of media file formats, audio and video codecs, and subtitle types.

There is a [FAQ][FAQ].

Releases can be found on the [release list][releases].

## System requirements

- A not too ancient Linux (usually, only the latest releases of distributions
  are actively supported), Windows 10 1607 or later, or macOS 10.15 or later.
- A somewhat capable CPU. Hardware decoding might help if the CPU is too slow to
  decode video in realtime, but must be explicitly enabled with the `--hwdec`
  option.
- A not too crappy GPU. mpv's focus is not on power-efficient playback on
  embedded or integrated GPUs (for example, hardware decoding is not even
  enabled by default). Low power GPUs may cause issues like tearing, stutter,
  etc. On such GPUs, it's recommended to use `--profile=fast` for smooth playback.
  The main video output uses shaders for video rendering and scaling,
  rather than GPU fixed function hardware. On Windows, you might want to make
  sure the graphics drivers are current. In some cases, ancient fallback video
  output methods can help (such as `--vo=xv` on Linux), but this use is not
  recommended or supported.

mpv does not go out of its way to break on older hardware or old, unsupported
operating systems, but development is not done with them in mind. Keeping
compatibility with such setups is not guaranteed. If things work, consider it
a happy accident.

## Downloads


For semi-official builds and third-party packages please see
[mpv.io/installation](https://mpv.io/installation/).

## Changelog


There is no complete changelog; however, changes to the player core interface
are listed in the [interface changelog][interface-changes].

Changes to the C API are documented in the [client API changelog][api-changes].

The [release list][releases] has a summary of most of the important changes
on every release.

Changes to the default key bindings are indicated in
[restore-old-bindings.conf][restore-old-bindings].

Changes to the default OSC bindings are indicated in
[restore-osc-bindings.conf][restore-osc-bindings].

## Compilation


Compiling with full features requires development files for several
external libraries. Mpv requires [meson](https://mesonbuild.com/index.html)
to build. Meson can be obtained from your distro or PyPI.

After creating your build directory (e.g. `meson setup build`), you can view a list
of all the build options via `meson configure build`. You could also just simply
look at the `meson_options.txt` file. Logs are stored in `meson-logs` within
your build directory.

Example:

    meson setup build
    meson compile -C build
    meson install -C build

For libplacebo, meson can use a git check out as a subproject for a convenient
way to compile mpv if a sufficient libplacebo version is not easily available
in the build environment. It will be statically linked with mpv. Example:

    mkdir -p subprojects
    git clone https://code.videolan.org/videolan/libplacebo.git --depth=1 --recursive subprojects/libplacebo

Essential dependencies (incomplete list):

- gcc or clang
- X development headers (xlib, xrandr, xext, xscrnsaver, xpresent, libvdpau,
  libGL, GLX, EGL, xv, ...)
- Audio output development headers (libasound/ALSA, pulseaudio)
- FFmpeg libraries (libavutil libavcodec libavformat libswscale libavfilter
  and either libswresample or libavresample)
- libplacebo
- zlib
- iconv (normally provided by the system libc)
- libass (OSD, OSC, text subtitles)
- Lua (optional, required for the OSC pseudo-GUI and youtube-dl integration)
- libjpeg (optional, used for screenshots only)
- uchardet (optional, for subtitle charset detection)
- nvdec and vaapi libraries for hardware decoding on Linux (optional)

Libass dependencies (when building libass):

- gcc or clang, nasm on x86 and x86_64
- fribidi, freetype, fontconfig development headers (for libass)
- harfbuzz (required for correct rendering of combining characters, particularly
  for correct rendering of non-English text on macOS, and Arabic/Indic scripts on
  any platform)

FFmpeg dependencies (when building FFmpeg):

- gcc or clang, nasm on x86 and x86_64
- OpenSSL or GnuTLS (have to be explicitly enabled when compiling FFmpeg)
- libx264/libmp3lame/libfdk-aac if you want to use encoding (have to be
  explicitly enabled when compiling FFmpeg)
- For native DASH playback, FFmpeg needs to be built with --enable-libxml2
  (although there are security implications, and DASH support has lots of bugs).
- AV1 decoding support requires dav1d.
- For good nvidia support on Linux, make sure nv-codec-headers is installed
  and can be found by configure.

Most of the above libraries are available in suitable versions on normal
Linux distributions. For ease of compiling the latest git master of everything,
you may wish to use the separately available build wrapper ([mpv-build][mpv-build])
which first compiles FFmpeg libraries and libass, and then compiles the player
statically linked against those.

If you want to build a Windows binary, see [Windows compilation][windows_compilation].


## Release cycle

Once or twice a year, a release is cut off from the current development state
and is assigned a 0.X.0 version number. No further maintenance is done, except
in the event of security issues.

The goal of releases is to make Linux distributions happy. Linux distributions
are also expected to apply their own patches in case of bugs.

Releases other than the latest release are unsupported and unmaintained.

See the [release policy document][release-policy] for more information.

## Bug reports


Please use the [issue tracker][issue-tracker] provided by GitHub to send us bug
reports or feature requests. Follow the template's instructions or the issue
will likely be ignored or closed as invalid.

Questions can be asked in the [discussions][discussions] or on IRC (see
[Contact](#Contact) below).

## Contributing


Please read [contribute.md][contribute.md].

For small changes you can just send us pull requests through GitHub. For bigger
changes come and talk to us on IRC before you start working on them. It will
make code review easier for both parties later on.

You can check [the wiki](https://github.com/mpv-player/mpv/wiki/Stuff-to-do)
or the [issue tracker](https://github.com/mpv-player/mpv/issues?q=is%3Aopen+is%3Aissue+label%3Ameta%3Afeature-request)
for ideas on what you could contribute with.

## License

GPLv2 "or later" by default, LGPLv2.1 "or later" with `-Dgpl=false`.
See [details.](https://github.com/mpv-player/mpv/blob/master/Copyright)

## History

This software is based on the MPlayer project. Before mpv existed as a project,
the code base was briefly developed under the mplayer2 project. For details,
see the [FAQ][FAQ].

## Contact


Most activity happens on the IRC channel and the GitHub issue tracker.

- **GitHub issue tracker**: [issue tracker][issue-tracker] (report bugs here)
- **Discussions**: [discussions][discussions]
- **User IRC Channel**: `#mpv` on `irc.libera.chat`
- **Developer IRC Channel**: `#mpv-devel` on `irc.libera.chat`

[FAQ]: https://github.com/mpv-player/mpv/wiki/FAQ
[releases]: https://github.com/mpv-player/mpv/releases
[mpv-build]: https://github.com/mpv-player/mpv-build
[issue-tracker]:  https://github.com/mpv-player/mpv/issues
[discussions]: https://github.com/mpv-player/mpv/discussions
[release-policy]: https://github.com/mpv-player/mpv/blob/master/DOCS/release-policy.md
[windows_compilation]: https://github.com/mpv-player/mpv/blob/master/DOCS/compile-windows.md
[interface-changes]: https://github.com/mpv-player/mpv/blob/master/DOCS/interface-changes.rst
[api-changes]: https://github.com/mpv-player/mpv/blob/master/DOCS/client-api-changes.rst
[restore-old-bindings]: https://github.com/mpv-player/mpv/blob/master/etc/restore-old-bindings.conf
[restore-osc-bindings]: https://github.com/mpv-player/mpv/blob/master/etc/restore-osc-bindings.conf
[contribute.md]: https://github.com/mpv-player/mpv/blob/master/DOCS/contribute.md
