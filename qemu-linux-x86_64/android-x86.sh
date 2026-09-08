#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
jar="$root/qemu-cli-linux-x86_64.jar"
iso="$root/guest-images/android-x86_64-8.1-r6.iso"
disk="$root/guest-images/android-x86.raw"

test -r "$jar" || { echo "missing $jar" >&2; exit 2; }
test -r "$iso" || { echo "missing $iso" >&2; exit 2; }
if [[ ! -e "$disk" ]]; then
    truncate -s 16G "$disk"
fi

exec env QEMU_GUEST=x86_64 java -jar "$jar" \
    -machine pc \
    -m 4G -smp 4 \
    -drive "file=$disk,format=raw,if=ide" \
    -cdrom "$iso" -boot menu=on "$@"
