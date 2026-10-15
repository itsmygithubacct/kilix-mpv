# kilix-mpv

A narrowly maintained mpv fork for `kilix video`, targeted at the next
Plebian-OS release (provisionally 0.2.2), not RC6. The upstream version and
commit are recorded in UPSTREAM.json. The initial fork resets a freed Kitty
command buffer on resize; upstream decoding and controls remain intact.

The Debian package installs `/usr/bin/kilix-mpv`. It does not provide, replace,
or conflict with `/usr/bin/mpv`. Kilix owns terminal cleanup and prefers this
named player. Running it directly retains upstream mpv's configuration behavior.

## Build and check

On Debian 13, install `build-essential meson ninja-build pkg-config git dpkg-dev
python3 ffmpeg libavcodec-dev libavfilter-dev libavformat-dev libavutil-dev
libswresample-dev libswscale-dev libplacebo-dev libass-dev libluajit-5.1-dev
libpulse-dev` and their package dependencies. Then, from a clean checkout:

```sh
bash kilix/build-package.sh /absolute/output/directory
```

This builds terminal playback with Lua controls and PulseAudio, stages without
root, removes build-tree runtime paths through Meson's install step, tests the
staged executable in private PTYs, and creates a Debian package, corresponding
source archive, metadata and SHA256SUMS. Dependencies are derived from the binary
using dpkg-shlibdeps. The output directory must be outside the checkout.
`KILIX_MPV_BUILD_JOBS` controls parallel compilation (default 2).

The tests exercise mouse input, resizing, seeking with the keyboard and normal
exit. They do not prove visual seek-bar geometry or audio on every device. Full
release acceptance still requires native visual/mouse/audio checks and a clean
Debian image install. Package builds are ABI-specific; publish only after those
checks, and pin both source commit and package checksum in the stack release.

## Maintenance and distribution

Keep upstream history and license notices. Review upstream releases and security
fixes; this fork does not promise a frozen upstream version indefinitely. Rebase
or merge deliberately, rerun terminal tests, and bump VERSION for every published
package. Each binary release must accompany its exact source archive and
checksums. Preserve GPL/LGPL notices; this build uses upstream's default GPL
configuration. The named binary avoids changing other applications' mpv behavior.

No RC6 release pin is changed by this repository. The next-release host branch
and release staging notes must be merged through the coordinated release process.
