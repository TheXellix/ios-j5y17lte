#!/bin/sh
# Package an XNU kernel for the SM-J530F BOOT partition (host only, no flash).
#
#   j5-mkboot.sh KERNEL REFERENCE_BOOT.img OUT_BOOT.img [RAMDISK.img] [CMDLINE]
#
# REFERENCE_BOOT is the phone's own BOOT backup: its Android header and DTBH
# (rev07 FDT, which S-Boot passes to the loader) are kept; the kernel slot gets
# the J5 EL1 loader and the ramdisk slot the SWEETXNU payload (XNU + J5 ADT +
# boot args [+ md0 root]).
set -eu
here=$(cd "$(dirname "$0")/.." && pwd -P)
kernel=$1 ref=$2 out=$3 ramdisk=${4:-}
cmdline=${5:-"debug=0x8 serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress wdt=-1 a5touch=0 a5touchprobe=0 a5keys=0"}
[ ! -e "$out" ] || { echo "refusing to overwrite $out" >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

: "${CC:=clang}" "${LD:=ld.lld}" "${OBJCOPY:=llvm-objcopy}"
: "${A5_TARGET_FLAGS:=--target=aarch64-none-elf}"
export CC LD OBJCOPY A5_TARGET_FLAGS
sh "$here/shim/j5y17lte/build-xnu-boot.sh" >/dev/null
python3 "$here/tools/mkadt_j5y17lte.py" "$tmp/j5.adt" >/dev/null
if [ -n "$ramdisk" ]; then
	case "$cmdline" in *rd=*) ;; *) cmdline="$cmdline rd=md0" ;; esac
	python3 "$here/tools/mkpayload.py" --cmdline "$cmdline" --ramdisk "$ramdisk" "$kernel" "$tmp/j5.adt" "$tmp/payload.bin"
else
	python3 "$here/tools/mkpayload.py" --cmdline "$cmdline" "$kernel" "$tmp/j5.adt" "$tmp/payload.bin"
fi
python3 "$here/tools/j5-pack-probe.py" --ramdisk "$tmp/payload.bin" "$ref" "$here/shim/j5y17lte/outxnu/Image" "$out"
echo "cmdline: $cmdline"
