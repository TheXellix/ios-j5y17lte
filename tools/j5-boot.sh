#!/bin/sh
# Build a J5 BOOT image with the current defaults and optionally flash it from
# TWRP and reboot.   j5-boot.sh KERNEL OUT.img [--flash] [EXTRA BOOT ARGS...]
# Defaults: iPhone 8 userland ADT, 736 MiB RAM (loader RAM_MIB=736),
# 32-sector eMMC transfers, 4 CPUs.
# Only ever talk to the J5 (other phones may be attached over USB).
export ANDROID_SERIAL="${ANDROID_SERIAL:-5200479dc6a79451}"
set -eu
here=$(cd "$(dirname "$0")/.." && pwd -P)
kernel=$1 out=$2; shift 2
flash=0
if [ "${1:-}" = --flash ]; then flash=1; shift; fi
model=${J5_MODEL:-iphone8}
args="debug=0x8 serial=3 cpus=${CPUS:-8} j5cpufreq=1586 keepsyms=1 -enable_kprintf_spam -noprogress wdt=-1 wdt_test=no_user_checkin a5touch=0 a5touchprobe=0 a5fb_perf=0 a5fb_noconsole=1 a5emmc_blocks=32 a5gpu=8 a5fb_gpu=1 rd=emmcroot0 emmcroot=USERDATA emmcwrite=1 rootrw=1 launchd_unsecure_cache=1 cs_enforcement_disable=1 unentitled_ios_sim_launch=1 ignition_level=1 $*"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export CC=${CC:-clang} LD=${LD:-ld.lld} OBJCOPY=${OBJCOPY:-llvm-objcopy} A5_TARGET_FLAGS=${A5_TARGET_FLAGS:---target=aarch64-none-elf}
RAM_MIB=736 sh "$here/shim/j5y17lte/build-xnu-boot.sh" >/dev/null
cp "$here/shim/j5y17lte/outxnu/Image" "$tmp/loader"
python3 "$here/tools/mkadt_j5y17lte.py" --model "$model" --ram-mib 736 "$tmp/j5.adt" >/dev/null
python3 "$here/tools/mkpayload.py" --cmdline "$args" "$kernel" "$tmp/j5.adt" "$tmp/payload.bin" >/dev/null
rm -f "$out"
python3 "$here/tools/j5-pack-probe.py" --embed "$tmp/payload.bin" "$here/../../backup/BOOT.img" "$tmp/loader" "$out" | tail -1
echo "args: $args"
[ "$flash" = 1 ] || exit 0
adb push "$out" /tmp/boot.img >/dev/null
adb shell 'dd if=/tmp/boot.img of=/dev/block/by-name/BOOT bs=1048576 conv=fsync 2>/dev/null; sync'
sleep 2
want=$(sha256sum "$out" | cut -c1-64)
got=$(adb shell "head -c $(stat -c %s "$out") /dev/block/by-name/BOOT | sha256sum; rm -f /tmp/boot.img" | cut -c1-64)
[ "$want" = "$got" ] || { echo "BOOT readback mismatch" >&2; exit 1; }
echo "BOOT verified, rebooting"
adb reboot
