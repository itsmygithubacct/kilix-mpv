#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 1 && $1 == /* ]] || { echo 'usage: kilix/build-package.sh /absolute/output/directory' >&2; exit 2; }
out="$(realpath -m -- "$1")"
case "$out/" in "$root/"*) echo 'output must be outside the source checkout' >&2; exit 2;; esac
[[ -z $(git -C "$root" status --porcelain) ]] || { echo 'package from a clean committed tree' >&2; exit 2; }
version="$(cat "$root/kilix/VERSION")"
revision="$(git -C "$root" rev-parse HEAD)"
SOURCE_DATE_EPOCH="$(git -C "$root" show -s --format=%ct HEAD)"
export SOURCE_DATE_EPOCH
arch="$(dpkg --print-architecture)"
mkdir -p "$out"
work="$(mktemp -d "$out/.build.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT
meson setup "$work/build" "$root" --prefix=/usr/local --buildtype=release \
  -Dauto_features=disabled -Dgl=disabled -Dlibmpv=false -Dlua=luajit -Dpulse=enabled
ninja -C "$work/build" -j "${KILIX_MPV_BUILD_JOBS:-2}"
meson install -C "$work/build" --no-rebuild --destdir "$work/stage"
python3 "$root/kilix/test-terminal.py" "$work/stage/usr/local/bin/mpv"
package="$work/package"
mkdir -p "$package/usr/bin" "$package/usr/share/doc/kilix-mpv" "$package/DEBIAN" "$work/debian"
install -m 755 "$work/stage/usr/local/bin/mpv" "$package/usr/bin/kilix-mpv"
cp "$root/Copyright" "$package/usr/share/doc/kilix-mpv/copyright"
cp "$root/LICENSE.GPL" "$root/LICENSE.LGPL" "$root/kilix/UPSTREAM.json" "$package/usr/share/doc/kilix-mpv/"
printf 'Source: kilix-mpv\nSection: video\nPriority: optional\nMaintainer: itsmygithubacct <itsmygithubacct@users.noreply.github.com>\n\nPackage: kilix-mpv\nArchitecture: any\nDescription: Kilix terminal media player\n' > "$work/debian/control"
deps="$(cd "$work" && dpkg-shlibdeps -O -e"$package/usr/bin/kilix-mpv" | sed -n 's/^shlibs:Depends=//p')"
[[ -n $deps ]] || { echo 'could not derive runtime dependencies' >&2; exit 1; }
cat > "$package/DEBIAN/control" <<EOF
Package: kilix-mpv
Version: $version
Architecture: $arch
Section: video
Priority: optional
Maintainer: itsmygithubacct <itsmygithubacct@users.noreply.github.com>
Depends: $deps
Description: Kilix terminal media player based on mpv
 Separately named player with the Kitty terminal resize fix.
EOF
stem="kilix-mpv_${version}_${arch}"
dpkg-deb --root-owner-group --build "$package" "$out/$stem.deb"
git -C "$root" archive --format=tar --prefix="kilix-mpv-$version/" "$revision" | gzip -n > "$out/kilix-mpv_$version.source.tar.gz"
printf '{"package":"kilix-mpv","version":"%s","source_commit":"%s","architecture":"%s","stack_target":"next release; not RC6"}\n' "$version" "$revision" "$arch" > "$out/$stem.json"
(cd "$out" && sha256sum "$stem.deb" "kilix-mpv_$version.source.tar.gz" "$stem.json" > SHA256SUMS)
printf 'Package and source: %s\n' "$out"
