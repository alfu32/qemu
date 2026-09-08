#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
jar="$root/qemu-cli-linux-x86_64.jar"
disk="$root/guest-images/XP.qcow2"
smp=${QEMU_XP_SMP:-1}

test -r "$jar" || { echo "missing $jar" >&2; exit 2; }
test -r "$disk" || { echo "missing $disk" >&2; exit 2; }

exec env QEMU_GUEST=i386 java -jar "$jar" \
    -machine pc \
    -m 2G -smp "$smp" -cpu pentium3 \
    -vga cirrus \
    -nic user,model=rtl8139 \
    -drive "file=$disk,format=qcow2,if=ide" "$@"
