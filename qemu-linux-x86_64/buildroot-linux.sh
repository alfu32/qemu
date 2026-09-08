#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
jar="$root/qemu-cli-linux-x86_64.jar"
kernel="$root/guest-images/buildroot-bzimage68.bin"
disk="$root/guest-images/buildroot-linux.raw"

test -r "$jar" || { echo "missing $jar" >&2; exit 2; }
test -r "$kernel" || { echo "missing $kernel" >&2; exit 2; }
if [[ ! -e "$disk" ]]; then
    truncate -s 1G "$disk"
fi

exec env QEMU_GUEST=i386 java -jar "$jar" \
    -machine pc \
    -m 512M -smp 1 \
    -kernel "$kernel" \
    -append 'console=ttyS0' \
    -drive "file=$disk,format=raw,if=ide" \
    -nographic "$@"
