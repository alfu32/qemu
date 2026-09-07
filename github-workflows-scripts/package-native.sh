#!/usr/bin/env bash
# Run on the target host; Windows uses MSYS2 CLANG64/CLANGARM64.
# Usage: bash github-workflows-scripts/package-native.sh <host-id> <output-dir>
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
target=${1:?host id required}
case "$target" in
    linux-x86_64|linux-aarch64|macos-x86_64|macos-aarch64|windows-x86_64|windows-aarch64) ;;
    *) echo "unsupported host: $target" >&2; exit 2 ;;
esac
output=${2:?output directory required}
mkdir -p "$output"
output=$(cd "$output" && pwd)
build="$root/build/release-$target"
mkdir -p "$build"
stage=$(mktemp -d "$build/stage.XXXXXX")
trap 'rm -rf "$stage"' EXIT

options=(--prefix=/qemu --bindir=bin --libdir=lib --datadir=share
    --without-default-features --enable-system --disable-user --with-suffix=qemu
    --enable-tcg --enable-fdt --enable-slirp --enable-pixman
    --enable-vnc --enable-install-blobs --disable-docs --disable-tools
    --disable-guest-agent --disable-rust --disable-modules --disable-plugins
    --disable-debug-info --enable-strip --disable-werror -Dcli_dll=true -Db_staticpic=true
    -Dbackend_max_links=2)
# Default configure target list contains every system guest available on this host.
if [[ -n ${QEMU_TARGET_LIST:-} ]]; then
    options+=("--target-list=$QEMU_TARGET_LIST")
fi
case "$target" in
    linux-*) suffix=so; jni_os=linux; shared=(-shared -fPIC -ldl) ;;
    macos-*) suffix=dylib; jni_os=darwin; shared=(-dynamiclib -fPIC)
        # A JVM can already own the hardened runtime's sole MAP_JIT region.
        # TCI also works with Python installations lacking JIT entitlements.
        options+=(--enable-tcg-interpreter)
        export PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:$PATH"
        export PKG_CONFIG_PATH="$(brew --prefix libffi)/lib/pkgconfig:${PKG_CONFIG_PATH:-}" ;;
    windows-*) suffix=dll; jni_os=win32; shared=(-shared)
        export CC=clang CXX=clang++
        JAVA_HOME=$(cygpath -u "$JAVA_HOME")
        # An explicit Windows drive avoids MSYS2 rewriting /qemu to its own
        # installation root. Meson's DESTDIR strips this drive when staging.
        options+=(--prefix=C:/qemu --cc=clang --cxx=clang++) ;;
    *) echo "unsupported host: $target" >&2; exit 2 ;;
esac
cd "$build"
"$root/configure" "${options[@]}"
jobs=${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)}
make -j"$jobs"
DESTDIR="$stage" "$build/pyvenv/bin/meson" install --no-rebuild
payload="$stage/qemu"
test -d "$payload/bin"
"${CC:-cc}" -O2 "$root/bindings/native/qemu_jni.c" \
    -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/$jni_os" \
    "${shared[@]}" -o "$payload/bin/libqemu_jni.$suffix"
mkdir -p "$payload/include" "$payload/licenses"
cp "$root/bindings/native/qemu-cli.h" "$payload/include/"
cp "$root/COPYING" "$root/COPYING.LIB" "$root/LICENSE" "$payload/licenses/"
cp "$root/bindings/README.md" "$payload/README.md"
python3 "$root/github-workflows-scripts/bundle-native.py" "$target" "$payload" "$output"
