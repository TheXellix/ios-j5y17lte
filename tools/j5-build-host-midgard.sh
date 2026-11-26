#!/bin/sh
# Build the same midgard-generic602 dynamic-stage backend the phone runs
# (userland/a5xelte-air-translation/families/misc_backend.c on Mesa 26.2.4),
# natively for this PC, for tools/j5-precompile.py.
#
#   j5-build-host-midgard.sh MESA_26.2.4_SOURCE OUTDIR
#
# Mirrors ios/build_midgard_ios.py (full NIR, private a5-ios integration),
# without the iOS cross file or codesigning. The Mesa tree is copied.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd -P)
fam="$here/userland/a5xelte-air-translation/families"
if [ "${1:-}" = --fingerprint ]; then
	# Sources that decide the backend's output (as the CI toolchain key).
	cat "$fam/misc_backend.c" "$fam"/misc_*.h \
		"$here/userland/a5xelte-air-translation/generic/ios_602_profile.h" | sha256sum | cut -c1-64
	exit 0
fi
mesa=$(realpath "$1")
out=$(realpath -m "$2")
fam="$here/userland/a5xelte-air-translation/families"
[ "$(cat "$mesa/VERSION")" = 26.2.4 ] || { echo "need Mesa 26.2.4" >&2; exit 2; }
mkdir -p "$out"
src="$out/mesa"
if [ ! -f "$src/VERSION" ]; then
	mkdir -p "$src"
	(cd "$mesa" && tar --exclude='./build*' -cf - .) | (cd "$src" && tar -xf -)
fi
python3 - "$src" <<'PY'
import sys, pathlib
src = pathlib.Path(sys.argv[1])
root = src / 'meson.build'
t = root.read_text()
mode = ("# A5 host compiler needs full NIR, not the driverless stub.\n"
        "with_gfx_compute = true\n"
        "add_project_arguments('-DHAVE_GFX_COMPUTE', language: ['c', 'cpp'])\n"
        "subdir('src')")
if mode not in t:
    t = t.replace("subdir('src')", mode, 1)
marker = "\n# A5 host compiler executable\nsubdir('src/panfrost')\nsubdir('a5-host')\n"
if marker not in t:
    t += marker
root.write_text(t)
# A local Mesa tree may carry the CI's a5_t720_copy_shader template target,
# which needs the Panfrost gallium packers: drop it from this copy.
pan = src / 'src/panfrost/meson.build'
p = pan.read_text()
i = p.find('a5_t720_copy_shader')
if i >= 0:
    pan.write_text(p[:p.rfind('\n', 0, i)] + '\n')
PY
integ="$src/a5-host"
mkdir -p "$integ"
cp "$fam/misc_backend.c" "$integ/midgard_generic.c"
for h in misc_resource_lowering.h misc_native_rt.h misc_dynamic.h misc_anisotropy.h; do
	cp "$fam/$h" "$integ/$h"
done
cp "$here/userland/a5xelte-air-translation/generic/ios_602_profile.h" "$integ/ios_602_profile.h"
cat > "$integ/meson.build" <<'EOF'
executable('midgard-generic602', files('midgard_generic.c'),
  include_directories: [inc_include, inc_src, inc_panfrost],
  dependencies: [idep_vtn, idep_nir, idep_mesautil],
  link_with: [libpanfrost_compiler, libpanfrost_midgard_disasm],
  c_args: ['-DA5_FAMILY_CONFIG="ios_602_profile.h"'], install: false)
EOF
if [ ! -f "$out/build/build.ninja" ]; then
	CC=clang CXX=clang++ meson setup "$out/build" "$src" \
		-Dbuildtype=debugoptimized -Db_ndebug=false -Ddefault_library=static \
		-Dgallium-drivers= -Dvulkan-drivers= -Dtools= -Dplatforms= -Dllvm=disabled \
		-Degl=disabled -Dgles1=disabled -Dgles2=disabled -Dglx=disabled -Dzstd=disabled \
		-Dshader-cache=disabled -Dlibunwind=disabled -Dvalgrind=disabled \
		-Dxmlconfig=disabled -Dexpat=disabled -Dspirv-tools=disabled -Dbuild-tests=false >/dev/null
fi
ninja -C "$out/build" a5-host/midgard-generic602 | tail -1
cp "$out/build/a5-host/midgard-generic602" "$out/midgard-generic602"
"$here/tools/j5-build-host-midgard.sh" --fingerprint > "$out/source.sha256"
echo "host backend: $out/midgard-generic602"
