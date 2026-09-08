#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
jar="$root/qemu-cli-linux-x86_64.jar"
disk="$root/guest-images/windows95.raw"
media=""
for candidate in "$root/guest-images/windows95.iso" "$root/guest-images/windows95.img"; do
    if [[ -r "$candidate" ]]; then media="$candidate"; break; fi
done

test -r "$jar" || { echo "missing $jar" >&2; exit 2; }
if [[ -z "$media" && ! -e "$disk.preinstalled" ]]; then
    echo "place licensed Windows 95 installation media at $root/guest-images/windows95.iso" >&2
    echo "or a bootable disk image at $root/guest-images/windows95.img" >&2
    exit 2
fi
if [[ ! -e "$disk" ]]; then
    truncate -s 2G "$disk"
fi

drive_args=(-drive "file=$disk,format=raw,if=ide,index=0")
media_args=()
if [[ "$media" == *.iso ]]; then
    media_args=(-cdrom "$media" -boot menu=on)
elif [[ -n "$media" ]]; then
    drive_args=(-drive "file=$media,format=raw,if=ide,index=0"
                -drive "file=$disk,format=raw,if=ide,index=1")
fi
exec env QEMU_GUEST=i386 java -jar "$jar" \
    -machine pc,acpi=off \
    -m 128M -smp 1 -cpu pentium \
    -vga cirrus -device sb16 -nic user,ipv6=off,model=ne2k_isa \
    "${drive_args[@]}" \
    "${media_args[@]}" "$@"
