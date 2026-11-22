#!/bin/sh
# Read the iOS root back from the SM-J530F USERDATA partition (TWRP), reusing
# a local reference image: OUT starts as a copy of REF and only the 256 MiB
# chunks whose md5 differs on the phone are pulled (md5-verified). Inspect the
# result without root, e.g. 7z l OUT / 7z x OUT path/inside.
#
#   j5-pull-userdata.sh REF.img OUT.img
# Only ever talk to the J5 (other phones may be attached over USB).
export ANDROID_SERIAL="${ANDROID_SERIAL:-5200479dc6a79451}"
set -eu
ref=$1
out=$2
part=/dev/block/by-name/USERDATA
chunk_mib=256
size=$(stat -c %s "$ref")
adb shell 'umount /data 2>/dev/null; umount /sdcard 2>/dev/null; true'
[ -f "$out" ] && [ "$(stat -c %s "$out")" = "$size" ] || cp --reflink=auto "$ref" "$out"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"; adb shell rm -f /tmp/j5chunk >/dev/null 2>&1 || true' EXIT
count=$(( (size + chunk_mib * 1048576 - 1) / (chunk_mib * 1048576) ))
i=0
while [ "$i" -lt "$count" ]; do
	dd if="$out" of="$tmp/c" bs=1M skip=$((i * chunk_mib)) count=$chunk_mib status=none
	bytes=$(stat -c %s "$tmp/c")
	local_md5=$(md5sum "$tmp/c" | cut -c1-32)
	have=$(adb shell "dd if=$part bs=1048576 skip=$((i * chunk_mib)) count=$chunk_mib 2>/dev/null | head -c $bytes | md5sum" | cut -c1-32)
	if [ "$have" = "$local_md5" ]; then
		echo "chunk $((i + 1))/$count same"
	else
		for attempt in 1 2 3; do
			adb shell "dd if=$part bs=1048576 skip=$((i * chunk_mib)) count=$chunk_mib 2>/dev/null | head -c $bytes > /tmp/j5chunk"
			adb pull /tmp/j5chunk "$tmp/p" >/dev/null
			[ "$(md5sum "$tmp/p" | cut -c1-32)" = "$have" ] && break
			echo "chunk $i attempt $attempt mismatch" >&2
			[ "$attempt" = 3 ] && exit 1
		done
		dd if="$tmp/p" of="$out" bs=1M seek=$((i * chunk_mib)) conv=notrunc status=none
		echo "chunk $((i + 1))/$count pulled"
	fi
	i=$((i + 1))
done
echo "USERDATA read back: $out"
