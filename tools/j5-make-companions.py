#!/usr/bin/env python3
"""Build /usr/libexec/a5shader/companions.json for j5y17lte from the phone's
own QuartzCore default.metallib.

metal2vulkan translates a vertex+fragment pair. For a single-stage request
the compiler used the fixed_vert_lph_spc / fixed_frag_lph_cph scaffold as
the other stage, which fails for most of QuartzCore (boot 31:
downsample_4_frag_lph -> "UnmatchedVarying", and CoreAnimation aborts
backboardd on any failed fragment). This picks, for every vertex and
fragment function, a companion whose interface matches, from the AIR
metadata alone:

  fragment F -> vertex V: V's vertex inputs fit the PACKING0 layout
     (locations 0-3: float4, float2, float2, half4) and V's ungated
     outputs cover F's inputs; prefer V without function constants, then
     the fewest extra outputs, then the longest shared name prefix.
  vertex V -> fragment F: F's inputs are covered by V's ungated outputs;
     prefer F without constants, then fewest inputs, then name prefix.

Companion constants are all zero (types from the metallib); the request's
own named constants override shared names in the compiler. Entries whose
best companion is the fixed_* scaffold are left out (the 603 scaffold with
its documented values is used). Nothing from the metallib is stored in the
repository.

  j5-make-companions.py default.metallib OUT.json
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PACKING0 = {0: 'float4', 1: 'float2', 2: 'float2', 3: 'half4'}
SCAFFOLD = {'fixed_vert_lph_spc', 'fixed_frag_lph_cph'}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyse(bitcode, scaffold):
    with tempfile.TemporaryDirectory() as tmp:
        bc = Path(tmp) / 'f.bc'
        bc.write_bytes(bitcode)
        text = subprocess.run(['llvm-dis', str(bc), '-o', '-'], check=True,
                              capture_output=True, text=True).stdout
    kind = 'vertex' if re.search(r'^!air\.vertex = ', text, re.M) else \
        'fragment' if re.search(r'^!air\.fragment = ', text, re.M) else None
    gated = lambda line: '"air.function_constant"' in line
    outs, ins, inputs, targets = set(), set(), [], set()
    for line in text.splitlines():
        m = re.search(r'"air\.vertex_output", !"([^"]+)"', line)
        if m and not gated(line):
            outs.add(m.group(1))
        m = re.search(r'"air\.render_target", i32 (\d+)', line)
        if m:
            targets.add(int(m.group(1)))
        m = re.search(r'"air\.fragment_input", !"(generated\([^"]+\))"', line)
        if m:
            ins.add(m.group(1))
        m = re.search(r'"air\.vertex_input", !"air\.location_index", i32 (\d+), i32 \d+, '
                      r'!"air\.arg_type_name", !"(\w+)"', line)
        if m:
            inputs.append((int(m.group(1)), m.group(2), gated(line)))
    return {'kind': kind, 'outs': outs, 'ins': ins, 'inputs': inputs, 'targets': targets,
            'constants': scaffold.constants(bitcode) if '!air.function_constants' in text else {}}


def prefix(a, b):
    strip = lambda n: re.sub(r'_(vert|frag)', '', n)
    return len(os.path.commonprefix([strip(a), strip(b)]))


def zeros(consts):
    return [{'name': n, 'type': t, 'bytes': w, 'raw': '00' * w}
            for n, (t, w) in sorted(consts.items())]


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    scaffold = load(HERE / 'j5-make-scaffold603.py', 'scaffold603')
    lib = Path(sys.argv[1]).read_bytes()
    info = {n: analyse(b, scaffold) for n, b in scaffold.functions(lib)}
    vertices = {n: i for n, i in info.items() if i['kind'] == 'vertex' and
                all(g or PACKING0.get(loc) == ty for loc, ty, g in i['inputs'])}
    fragments = {n: i for n, i in info.items() if i['kind'] == 'fragment'}
    out = {'schema': 1, 'fragment': {}, 'vertex': {}}
    for f, fi in sorted(fragments.items()):
        cands = [v for v, vi in vertices.items() if fi['ins'] <= vi['outs']]
        if not cands:
            continue
        v = min(cands, key=lambda v: (bool(vertices[v]['constants']),
                                      len(vertices[v]['outs'] - fi['ins']), -prefix(f, v), v))
        if v not in SCAFFOLD:
            out['fragment'][f] = {'function': v, 'constants': zeros(vertices[v]['constants'])}
    for v, vi in sorted(info.items()):
        if vi['kind'] != 'vertex':
            continue
        cands = [f for f, fi in fragments.items() if fi['ins'] <= vi['outs']]
        if not cands:
            continue
        # The compiler declares colour attachment 0 only (metal2vulkan
        # --color-format 0:BGRA8Unorm): a companion writing RT1+ is invalid.
        f = min(cands, key=lambda f: (bool(fragments[f]['targets'] - {0}),
                                      bool(fragments[f]['constants']),
                                      len(fragments[f]['ins']), -prefix(v, f), f))
        if f not in SCAFFOLD:
            out['vertex'][v] = {'function': f, 'constants': zeros(fragments[f]['constants'])}
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1) + '\n')
    print(f"companions: {len(out['fragment'])}/{len(fragments)} fragments, "
          f"{len(out['vertex'])} vertices")


if __name__ == '__main__':
    main()
