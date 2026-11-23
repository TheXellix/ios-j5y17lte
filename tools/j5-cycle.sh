#!/bin/sh
# One unattended j5y17lte test cycle, starting from TWRP:
#   flash the changed USERDATA chunks (optional), flash BOOT with j5twrp=N,
#   let iOS run N seconds (the kernel then reboots into TWRP by itself),
#   wait for TWRP and collect the logs into OUTDIR.
#
#   j5-cycle.sh [--image ROOT.img] [--seconds N] KERNEL BOOT.img OUTDIR [boot-args...]
#
# Collected: kmsg.bin + k.txt (/proc/last_kmsg), compile.log, crash list and
# the newest backboardd/SpringBoard crash reports (tools/j5-hfs.py, no full
# partition copy). Only ever talks to the J5 serial.
export ANDROID_SERIAL="${ANDROID_SERIAL:-5200479dc6a79451}"
set -eu
here=$(cd "$(dirname "$0")" && pwd -P)
image=
seconds=600
while [ $# -gt 0 ]; do
	case $1 in
	--image) image=$2; shift 2 ;;
	--seconds) seconds=$2; shift 2 ;;
	*) break ;;
	esac
done
kernel=$1 boot=$2 out=$3
shift 3
mkdir -p "$out"
state() { adb devices | awk -v s="$ANDROID_SERIAL" '$1 == s { print $2 }'; }
[ "$(state)" = recovery ] || { echo "the J5 is not in TWRP" >&2; exit 1; }
if [ -n "$image" ]; then
	"$here/j5-flash-userdata.sh" --changed "$image" | tail -1
fi
"$here/j5-boot.sh" "$kernel" "$boot" --flash "j5twrp=$seconds" "$@" | tail -1
echo "booted $(date +%T); back in TWRP after ~$seconds s"
# Leave recovery first, then wait for it again (boot + timer + restart).
t=0
while [ "$(state)" = recovery ] && [ $t -lt 120 ]; do sleep 5; t=$((t + 5)); done
t=0
limit=$((seconds + 900))
until [ "$(state)" = recovery ]; do
	[ $t -lt $limit ] || { echo "no TWRP after $limit s (hung? hold Power+Vol- then Power+Vol+ +Home)" >&2; exit 2; }
	sleep 10; t=$((t + 10))
done
sleep 5
echo "TWRP again $(date +%T)"
adb exec-out 'cat /proc/last_kmsg' > "$out/kmsg.bin"
python3 "$here/j5-readlog.py" "$out/kmsg.bin" > "$out/k.txt" 2>&1 || true
adb shell 'umount /data 2>/dev/null; true'
hfs="$here/j5-hfs.py"
python3 "$hfs" phone get /private/var/log/a5shader-compile.log "$out/compile.log" 2>/dev/null || true
crashes=/private/var/mobile/Library/Logs/CrashReporter
python3 "$hfs" phone ls "$crashes" > "$out/crashes.txt" 2>/dev/null || true
for proc in backboardd SpringBoard; do
	newest=$(awk -v p="$proc-" 'index($4, p) == 1 { print $3, $4 }' "$out/crashes.txt" | sort | tail -1 | cut -d' ' -f2)
	[ -n "$newest" ] && python3 "$hfs" phone get "$crashes/$newest" "$out/$newest" || true
done
grep -a "J5 autotwrp\|CRASH .* reason\|Metal pipeline\|dynamic link\|G3D.*fault" "$out/k.txt" | sort | uniq -c | sort -rn | head -20 || true
