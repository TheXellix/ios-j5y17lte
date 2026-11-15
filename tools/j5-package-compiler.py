#!/usr/bin/env python3
"""Package the on-device shader compiler service for j5y17lte (Mali-T830).

Like userland/a5xelte-air-translation/ios/prepare_package.py, but without the
A5's private captured 602-606 recipes and T720 reference hashes: the worker's
dynamic typed-stage path compiles requests on the phone, and pairs.json has no
expected_output (those hashes are T720 machine code). No Apple shader bytes
are packaged.

Output layout (installed under /usr/libexec):
  OUT/a5shader-compile                     runner (signed)
  OUT/a5shader/{metal2vulkan,midgard-compile,midgard-generic602,spirv-val}
  OUT/a5shader/{pairs.json,profile.json}
  OUT/compiler-launchdaemon.plist
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
IOS = HERE.parent / 'userland/a5xelte-air-translation/ios'
AIR = IOS.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sign(path, ident, entitlements):
    subprocess.run(['codesign', '--force', '--sign', '-', '--pagesize', '4096',
                    '--identifier', ident, '--entitlements', str(entitlements),
                    str(path)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(path)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('air', type=Path, help='metal2vulkan iOS executable')
    ap.add_argument('midgard', type=Path, help='midgard-compile iOS executable')
    ap.add_argument('generic602', type=Path, help='midgard-generic602 iOS executable')
    ap.add_argument('validator', type=Path, help='spirv-val iOS executable')
    ap.add_argument('profile', type=Path, help='metal2vulkan validation profile JSON')
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    out = args.output.resolve()
    res = out / 'a5shader'
    res.mkdir(parents=True, exist_ok=True)
    ent = IOS / 'compiler-entitlements.plist'
    for name, src in (('metal2vulkan', args.air), ('midgard-compile', args.midgard),
                      ('midgard-generic602', args.generic602), ('spirv-val', args.validator)):
        dst = res / name
        shutil.copyfile(src, dst)
        dst.chmod(0o755)
        sign(dst, 'com.orhunnx.a5shader.' + name, ent)
    runner = out / 'a5shader-compile'
    subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios16.0',
                    '-mcpu=cortex-a53', '-march=armv8-a+crypto', '-fobjc-arc', '-fblocks',
                    '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                    str(IOS / 'a5shader_compile.m'), '-framework', 'Foundation',
                    '-framework', 'IOKit', '-o', str(runner)], check=True)
    runner.chmod(0o755)
    sign(runner, 'com.orhunnx.a5shader.a5shader-compile', ent)
    verifier = HERE.parent / 'userland/a5mali-metal/StockMetalPlugin/verify_signature_pages.py'
    subprocess.run(['python3', str(verifier), str(runner),
                    *(str(res / n) for n in ('metal2vulkan', 'midgard-compile',
                                             'midgard-generic602', 'spirv-val'))], check=True)
    translation = load(AIR / 'translate_stock_quartzcore.py', 'translation')
    pairs = {p: translation.PAIRS[p] for p in ('read_surf', 'downsample_4')}
    (res / 'pairs.json').write_text(json.dumps(pairs, indent=2) + '\n')
    shutil.copyfile(args.profile, res / 'profile.json')
    shutil.copyfile(IOS / 'compiler-launchdaemon.plist', out / 'compiler-launchdaemon.plist')
    for f in sorted(out.rglob('*')):
        if f.is_file():
            print(f.relative_to(out), f.stat().st_size)


if __name__ == '__main__':
    main()
