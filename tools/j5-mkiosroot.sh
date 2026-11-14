#!/bin/bash
# Build the j5y17lte (SM-J530F) iOS 16 root on Linux: one journaled,
# case-sensitive HFS+ (HFSX) image exactly as large as the phone's USERDATA
# partition, to be written there from TWRP.
#
#   j5-mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img
#
# Based on tools/mkiosroot.sh (SWEET, Linux) with the file selection of
# tools/a5xelte-stage-ios-root.sh (A5XELTE, macOS): no stock apps except the
# launchd-managed UI services, no large optional asset families. Then applies
# tools/sweet-root-tweaks.py, as the A5XELTE root did.
#
# Needs apfs-fuse, hfsprogs (mkfs.hfsplus, fsck.hfsplus), rsync, python3 and
# sudo (it asks for your password). Reads only the three .dmg files and writes
# only OUT.img and temporary mount points; it never touches the phone.
set -euo pipefail

# blockdev --getsize64 /dev/block/by-name/USERDATA on this phone (TWRP).
USERDATA_BYTES=12912147968

[[ $# -eq 4 ]] || { sed -n '2,15p' "$0"; exit 2; }
os=$(realpath "$1") sysos=$(realpath "$2") appos=$(realpath "$3") out=$4
here=$(cd "$(dirname "$0")" && pwd -P)
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }
for tool in apfs-fuse mkfs.hfsplus fsck.hfsplus rsync python3; do
	command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

work=$(mktemp -d)
mounts=()
cleanup() {
	local busy=0
	for m in "${mounts[@]}"; do
		mountpoint -q "$m" && sudo umount "$m" 2>/dev/null || true
		mountpoint -q "$m" && busy=1
	done
	if [[ $busy == 0 ]]; then
		rm -f "$work"/*.dmg
		rmdir "$work"/* "$work" 2>/dev/null || true
	else
		echo "still mounted under $work: left in place" >&2
	fi
}
trap cleanup EXIT

apfs_mount() {
	ln -s "$1" "$work/$2.dmg"
	mkdir "$work/$2"
	sudo "$(command -v apfs-fuse)" "$work/$2.dmg" "$work/$2"
	mounts+=("$work/$2")
}
apfs_mount "$os" os
apfs_mount "$sysos" sysos
apfs_mount "$appos" appos
src_os="$work/os/root"

ui_apps=(PosterBoard PaperBoard PreBoard InputUI MediaRemoteUI ClockAngel)
for app in "${ui_apps[@]}"; do
	sudo test -f "$src_os/Applications/$app.app/$app" || { echo "missing UI source: $app" >&2; exit 1; }
done
[[ $(sudo stat -c %u "$src_os/sbin/launchd") == 0 ]] || { echo "OS image owners not visible" >&2; exit 1; }

truncate -s "$USERDATA_BYTES" "$out"
mkfs.hfsplus -s -J -v J5IOSROOT "$out"
mkdir "$work/root"
sudo mount -t hfsplus -o loop,force "$out" "$work/root"
mounts=("$work/root" "${mounts[@]}")
root="$work/root"

app_filters=('--include=/Applications/')
for app in "${ui_apps[@]}"; do app_filters+=("--include=/Applications/$app.app/***"); done
app_filters+=('--exclude=/Applications/***')
omit=(
	'--exclude=/System/Library/LinguisticData/***'
	'--exclude=/System/Library/PreinstalledAssetsV2/***'
	'--exclude=/System/Library/Health/***'
	'--exclude=/System/Library/NanoTimeKit/***'
	'--exclude=/System/Library/Assistant/***'
	'--exclude=/System/Library/OnBoardingBundles/***'
	'--exclude=/System/Library/Audio/***'
)
echo "== copying selected OS files"
sudo rsync -aH --numeric-ids "${app_filters[@]}" "${omit[@]}" "$src_os/" "$root/"
echo "== copying SystemOS and AppOS cryptexes"
sudo mkdir -p "$root/private/preboot/Cryptexes/OS" "$root/private/preboot/Cryptexes/App"
sudo rsync -aH --numeric-ids "$work/sysos/root/" "$root/private/preboot/Cryptexes/OS/"
sudo rsync -aH --numeric-ids "$work/appos/root/" "$root/private/preboot/Cryptexes/App/"

echo "== shared cache and cryptex hard links"
dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
sudo mkdir -p "$root/System/Library/Caches/com.apple.dyld"
for f in "$root/$dsc"/*; do
	sudo ln "$f" "$root/System/Library/Caches/com.apple.dyld/${f##*/}"
done
for c in OS App; do
	(cd "$root/private/preboot/Cryptexes/$c" && sudo find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*') |
	while IFS= read -r f; do
		f=${f#./}
		if ! sudo test -e "$root/$f" && ! sudo test -L "$root/$f"; then
			sudo mkdir -p "$root/$(dirname "$f")"
			s="$root/private/preboot/Cryptexes/$c/$f"
			if sudo test -L "$s"; then sudo cp -P "$s" "$root/$f"; else sudo ln "$s" "$root/$f"; fi
		fi
	done
done

echo "== logd stores and system keybag"
db="$root/private/var/db"
sudo install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
sudo install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
	sudo install -o 272 -g 272 -m 0644 /dev/null "$db/$d/.migrated"
done
sudo install -d -m 0700 -o 0 -g 0 "$root/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' |
	sudo install -m 0600 -o 0 -g 0 /dev/stdin "$root/private/var/keybags/systembag.kb"

echo "== bring-up tweaks"
sudo python3 "$here/sweet-root-tweaks.py" "$root"

echo "== checks"
[[ $(sudo stat -c %u "$root/sbin/launchd") == 0 ]] || { echo "launchd owner lost" >&2; exit 1; }
sudo test -f "$root/System/Library/CoreServices/SpringBoard.app/SpringBoard"
sudo test -f "$root/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64"
df -h "$root"
sudo umount "$root"
mounts=("${mounts[@]:1}")
fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
fsck.hfsplus -f -n "$out"
ls -l "$out"
echo "J5 iOS root ready: $out (not written to the phone)"
