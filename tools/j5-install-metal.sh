#!/bin/bash
# Install the j5y17lte Mali-T830 Metal userland into the iOS root HFS image.
#
#   j5-install-metal.sh ROOT.img PAYLOAD_DIR
#
# PAYLOAD_DIR is the unpacked "metal-ios" CI artifact:
#   plugin/A5MaliMetal.bundle, compiler/a5shader-compile, compiler/a5shader/*,
#   compiler/compiler-launchdaemon.plist
#
# Installs
#   /System/Library/Extensions/A5MaliMetal.bundle
#   /usr/libexec/a5shader-compile, /usr/libexec/a5shader/ (+ generic603.json
#   and companions.json, generated from the image's QuartzCore metallib)
#   /System/Library/LaunchDaemons/com.orhunnx.a5shader-compile.plist
# adds that job (plus CA_IGNORE_MACH_SEND_ERRORS=1 for backboardd, as on the
# A5) to the launchd cache /System/Library/xpc/launchd.plist (one-time backup
# launchd.plist.j5-orig) and drops stale compiler publications.
#
# Everything is prepared as the user (image files are read with j5-hfs.py);
# only the fixed root helper /usr/local/sbin/j5-root-install (tools/
# j5-root-install.sh, see its header) mounts the image and copies the stage.
# The phone is not touched: flash afterwards with
#   tools/j5-flash-userdata.sh --changed ROOT.img
set -euo pipefail
img=$(realpath "$1")
payload=$(realpath "$2")
here=$(cd "$(dirname "$0")/.." && pwd -P)
hfs="$here/tools/j5-hfs.py"
bundle="$payload/plugin/A5MaliMetal.bundle"
comp="$payload/compiler"
for f in "$bundle/A5MaliMetal" "$bundle/Info.plist" "$comp/a5shader-compile" \
         "$comp/a5shader/metal2vulkan" "$comp/a5shader/midgard-compile" \
         "$comp/a5shader/spirv-val" "$comp/a5shader/pairs.json" \
         "$comp/a5shader/profile.json" "$comp/compiler-launchdaemon.plist"; do
	[ -f "$f" ] || { echo "missing $f" >&2; exit 2; }
done
helper=/usr/local/sbin/j5-root-install
[ -x "$helper" ] || { echo "install $helper first (see tools/j5-root-install.sh)" >&2; exit 2; }
# The stage must live under the helper's allowed tree, next to the image.
stage=$(mktemp -d "$(dirname "$img")/.j5stage.XXXXXX")
trap 'rm -rf "$stage"' EXIT
root="$stage/root"
tmp="$stage/tmp"
mkdir -p "$tmp"

echo "== bundle"
install -d -m 0755 "$root/System/Library/Extensions"
cp -r "$bundle" "$root/System/Library/Extensions/A5MaliMetal.bundle"
chmod -R u+rwX,go+rX,go-w "$root/System/Library/Extensions/A5MaliMetal.bundle"

echo "== compiler service"
install -d -m 0755 "$root/usr/libexec/a5shader" "$root/System/Library/LaunchDaemons" \
	"$root/private/var/log" "$root/System/Library/xpc"
install -m 0755 "$comp/a5shader-compile" "$root/usr/libexec/a5shader-compile"
for t in metal2vulkan midgard-compile midgard-generic602 spirv-val; do
	[ -f "$comp/a5shader/$t" ] && install -m 0755 "$comp/a5shader/$t" "$root/usr/libexec/a5shader/$t"
done
for j in pairs.json profile.json; do
	install -m 0644 "$comp/a5shader/$j" "$root/usr/libexec/a5shader/$j"
done
install -m 0644 "$comp/compiler-launchdaemon.plist" \
	"$root/System/Library/LaunchDaemons/com.orhunnx.a5shader-compile.plist"
python3 "$hfs" "$img" get /System/Library/Frameworks/QuartzCore.framework/default.metallib "$tmp/default.metallib"
python3 "$here/tools/j5-make-scaffold603.py" "$tmp/default.metallib" "$root/usr/libexec/a5shader/generic603.json"
python3 "$here/tools/j5-make-companions.py" "$tmp/default.metallib" "$root/usr/libexec/a5shader/companions.json"
chmod 0644 "$root/usr/libexec/a5shader/"*.json

echo "== launchd cache"
xpc=/System/Library/xpc
if ! python3 "$hfs" "$img" get "$xpc/launchd.plist.j5-orig" "$tmp/orig.plist" 2>/dev/null; then
	python3 "$hfs" "$img" get "$xpc/launchd.plist" "$tmp/orig.plist"
	install -m 0644 "$tmp/orig.plist" "$root$xpc/launchd.plist.j5-orig"
fi
python3 - "$tmp/orig.plist" "$comp/compiler-launchdaemon.plist" "$root$xpc/launchd.plist" <<'PY'
import plistlib, sys
cache = plistlib.loads(open(sys.argv[1], 'rb').read())
job = plistlib.loads(open(sys.argv[2], 'rb').read())
jobs = cache['LaunchDaemons']
jobs['/System/Library/LaunchDaemons/com.orhunnx.a5shader-compile.plist'] = job
bb = jobs.get('/System/Library/LaunchDaemons/com.apple.backboardd.plist')
if not bb or bb.get('Label') != 'com.apple.backboardd':
    raise SystemExit('backboardd job not found in the launchd cache')
env = dict(bb.get('EnvironmentVariables', {}))
env['CA_IGNORE_MACH_SEND_ERRORS'] = '1'
bb['EnvironmentVariables'] = env
open(sys.argv[3], 'wb').write(plistlib.dumps(cache, fmt=plistlib.FMT_BINARY, sort_keys=False))
print('launchd cache: %d jobs, compiler job added' % len(jobs))
PY
chmod 0644 "$root$xpc/launchd.plist"

# Accessibility > Reduce Transparency (default on, J5_REDUCE_TRANSPARENCY=0
# leaves it): CoreAnimation draws solid materials instead of the large blur
# passes, which the T830 path cannot run yet and which cost the most GPU.
if [ "${J5_REDUCE_TRANSPARENCY:-1}" = 1 ]; then
	echo "== reduce transparency"
	ax=/private/var/mobile/Library/Preferences/com.apple.Accessibility.plist
	python3 "$hfs" "$img" get "$ax" "$tmp/ax.plist" 2>/dev/null || rm -f "$tmp/ax.plist"
	install -d -m 0755 "$root$(dirname "$ax")"
	python3 - "$tmp/ax.plist" "$root$ax" <<'PY2'
import os, plistlib, sys
src, dst = sys.argv[1:]
prefs = plistlib.loads(open(src, 'rb').read()) if os.path.exists(src) else {}
prefs['EnhancedBackgroundContrastEnabled'] = True
open(dst, 'wb').write(plistlib.dumps(prefs, fmt=plistlib.FMT_BINARY))
print('accessibility: %d keys, EnhancedBackgroundContrastEnabled=1' % len(prefs))
PY2
	chmod 0600 "$root$ax"
	echo "mobile $ax" >> "$stage/owners"
fi

# Replace whole trees; compiler publications (also failures) belong to the
# previous compiler, so pending requests are compiled again.
cat > "$stage/delete" <<'EOF'
/System/Library/Extensions/A5MaliMetal.bundle
/usr/libexec/a5shader
/private/var/tmp/a5mali-shader-compiled
/private/var/db/a5shader-cache
EOF
rm -rf "$tmp"
sudo -n "$helper" "$img" "$stage"
echo "installed; now flash: $here/tools/j5-flash-userdata.sh --changed $img"
