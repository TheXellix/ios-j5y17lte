#!/bin/sh
# Write an iOS root image to the SM-J530F USERDATA partition from TWRP, in
# verified chunks: adb push CHUNK to /tmp, dd at its exact MiB offset, md5sum
# readback on the phone, retry on mismatch. A single "adb exec-in | dd"
# stream once lost the final 1.5 MB (the HFS alternate volume header)
# without any error.
#
#   j5-flash-userdata.sh IMAGE [FIRST_CHUNK]
# Only ever talk to the J5 (other phones may be attached over USB).
export ANDROID_SERIAL="${ANDROID_SERIAL:-5200479dc6a79451}"
set -eu
img=$1
first=${2:-0}
part=/dev/block/by-name/USERDATA
chunk_mib=256
size=$(stat -c %s "$img")
psize=$(adb shell "blockdev --getsize64 $part" | tr -d '\r')
[ "$size" -le "$psize" ] || { echo "image $size > partition $psize" >&2; exit 1; }
adb shell 'umount /data 2>/dev/null; umount /sdcard 2>/dev/null; true'
if adb shell 'grep -q " /data " /proc/mounts'; then
	echo "/data is still mounted on the phone" >&2
	exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"; adb shell rm -f /tmp/j5chunk >/dev/null 2>&1 || true' EXIT
count=$(( (size + chunk_mib * 1048576 - 1) / (chunk_mib * 1048576) ))
i=$first
while [ "$i" -lt "$count" ]; do
	dd if="$img" of="$tmp/c" bs=1M skip=$((i * chunk_mib)) count=$chunk_mib status=none
	want=$(md5sum "$tmp/c" | cut -c1-32)
	bytes=$(stat -c %s "$tmp/c")
	for attempt in 1 2 3; do
		adb push "$tmp/c" /tmp/j5chunk >/dev/null
		adb shell "dd if=/tmp/j5chunk of=$part bs=1048576 seek=$((i * chunk_mib)) conv=fsync 2>/dev/null; sync; echo 3 > /proc/sys/vm/drop_caches"
		got=$(adb shell "dd if=$part bs=1048576 skip=$((i * chunk_mib)) count=$chunk_mib 2>/dev/null | head -c $bytes | md5sum" | cut -c1-32)
		[ "$got" = "$want" ] && break
		echo "chunk $i attempt $attempt mismatch ($got != $want)" >&2
		[ "$attempt" = 3 ] && exit 1
	done
	echo "chunk $((i + 1))/$count ok"
	i=$((i + 1))
done
echo "USERDATA written and verified: $img"
