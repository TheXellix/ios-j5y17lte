#!/bin/bash
# Root half of the j5y17lte image install. Installed root-owned as
#   /usr/local/sbin/j5-root-install   (mode 0755)
# and allowed without a password by /etc/sudoers.d/j5-root-install.
#
#   j5-root-install IMAGE STAGE
#
# It runs no other program from the user's tree. It:
#   - accepts only IMAGE = a regular *.img and STAGE = a directory, both
#     under /run/media/beppe/HDD/ios-j5/work
#   - repairs the HFS+ image (fsck until it verifies) and mounts it
#   - removes the absolute paths listed in STAGE/delete (one per line,
#     no "..", confined to the mounted image)
#   - copies STAGE/root/ into the image, owned by root:wheel, keeping the
#     metadata of directories that already exist; STAGE/owners may hand
#     staged files under /private/var/mobile/ back to mobile (501:501)
#   - unmounts, checks again and restores the image size
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 022
base=/run/media/beppe/HDD/ios-j5/work
[ $# -eq 2 ] || { echo "usage: j5-root-install IMAGE STAGE" >&2; exit 2; }
img=$(realpath -e -- "$1")
stage=$(realpath -e -- "$2")
case $img in "$base"/*.img) ;; *) echo "image outside $base" >&2; exit 2 ;; esac
case $stage in "$base"/*) ;; *) echo "stage outside $base" >&2; exit 2 ;; esac
[ -f "$img" ] && [ ! -L "$img" ] || { echo "not a regular image" >&2; exit 2; }
[ -d "$stage/root" ] || { echo "missing $stage/root" >&2; exit 2; }
size=$(stat -c %s -- "$img")
mnt=$(mktemp -d /run/j5root.XXXXXX)
cleanup() { mountpoint -q "$mnt" && umount "$mnt" || true; rmdir "$mnt" 2>/dev/null || true; }
trap cleanup EXIT
check() {
	for pass in 1 2 3 4; do
		if fsck.hfsplus -f -y "$img"; then break; fi
		echo "fsck pass $pass repaired the volume, checking again"
	done
	[ "$(stat -c %s -- "$img")" = "$size" ] || truncate -s "$size" -- "$img"
}
check
mount -t hfsplus -o loop,force,rw,nodev,nosuid -- "$img" "$mnt"
grep -q " $mnt hfsplus rw" /proc/mounts || { echo "image mounted read-only" >&2; exit 4; }
[ -f "$mnt/System/Library/xpc/launchd.plist" ] || { echo "not an iOS root" >&2; exit 3; }
# Every destination must resolve inside the mounted image: no symlinks in
# the stage, and no image symlink may lead a path out of the mount.
inside() {
	local r
	r=$(realpath -m -- "$mnt$1") || return 1
	case $r in "$mnt"|"$mnt"/*) return 0 ;; esac
	echo "refusing $1: resolves to $r" >&2
	return 1
}
if [ -n "$(find "$stage/root" -type l -print -quit)" ]; then
	echo "symlinks are not allowed in the stage" >&2; exit 5
fi
(cd "$stage/root" && find . -mindepth 1 -print0) | while IFS= read -r -d '' rel; do
	inside "${rel#.}" || exit 5
done
if [ -f "$stage/delete" ]; then
	while IFS= read -r p; do
		case $p in /*) ;; *) continue ;; esac
		case /$p/ in */../*|*/./*) continue ;; esac
		[ "$p" = / ] && continue
		inside "$(dirname -- "$p")" || exit 5
		rm -rf --one-file-system -- "$mnt$p"
	done < "$stage/delete"
fi
tar -C "$stage/root" --owner=0 --group=0 -cf - . | tar -C "$mnt" --no-overwrite-dir -xpf -
# Optional STAGE/owners: "mobile PATH" lines give staged files under
# /private/var/mobile/ back to the iOS user mobile (501:501), e.g. its
# preference plists. Nothing else can be re-owned.
if [ -f "$stage/owners" ]; then
	while read -r who p; do
		[ "$who" = mobile ] || continue
		case $p in /private/var/mobile/*) ;; *) continue ;; esac
		case /$p/ in */../*|*/./*) continue ;; esac
		[ -e "$stage/root$p" ] || continue
		inside "$p" || exit 5
		[ -L "$mnt$p" ] && exit 5
		chown -h 501:501 -- "$mnt$p"
	done < "$stage/owners"
fi
sync
umount "$mnt"
check
echo "j5-root-install: done"
