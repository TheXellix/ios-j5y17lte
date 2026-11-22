#!/usr/bin/env python3
"""Build /usr/libexec/a5shader/generic603.json for j5y17lte from the phone's
own QuartzCore default.metallib.

The A5 package derives its 602-606 recipes from private device captures and
pins T720 native hashes. The compiler's dynamic stage path only needs 603 as
a scaffold: the companion stage (fixed_vert_lph_spc / fixed_frag_lph_cph),
its specialization constants and the vertex descriptor. This tool reads the
function-constant declarations (name, type) from the metallib's AIR bitcode
with llvm-dis, sets the values the public 0189 contract documents (NONZERO,
vertex constants all zero) and uses the public PACKING0 layout. The recipe is
marked j5_scaffold_only, so the patched runner never treats it as a pinned
pipeline profile. Nothing from the metallib is stored in the repository.

  j5-make-scaffold603.py default.metallib OUT.json
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
GENERIC = HERE.parent / 'userland/a5xelte-air-translation/generic'
VERTEX = 'fixed_vert_lph_spc'
FRAGMENT = 'fixed_frag_lph_cph'
# Metal data types (MTLDataType) by scalar name: (first value, unit bytes).
TYPES = {'float': (3, 4), 'half': (16, 2), 'int': (29, 4), 'uint': (33, 4),
         'short': (37, 2), 'ushort': (41, 2), 'char': (45, 1), 'uchar': (49, 1),
         'bool': (53, 1), 'long': (81, 8), 'ulong': (85, 8)}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def functions(lib):
    flo, _, _, _, _, _, bco, _ = struct.unpack_from('<8Q', lib, 0x18)
    count = struct.unpack_from('<I', lib, flo)[0]
    p = flo + 4
    for _ in range(count):
        length = struct.unpack_from('<I', lib, p)[0]
        q, tags = p + 4, {}
        while lib[q:q + 4] != b'ENDT':
            tag = lib[q:q + 4]
            size = struct.unpack_from('<H', lib, q + 4)[0]
            tags[tag] = lib[q + 6:q + 6 + size]
            q += 6 + size
        p += length
        name = tags[b'NAME'].rstrip(b'\0').decode()
        offset = struct.unpack_from('<3Q', tags[b'OFFT'])[2]
        size = struct.unpack_from('<Q', tags[b'MDSZ'])[0]
        yield name, lib[bco + offset:bco + offset + size]


def constants(bitcode):
    with tempfile.TemporaryDirectory() as tmp:
        bc = Path(tmp) / 'f.bc'
        bc.write_bytes(bitcode)
        text = subprocess.run(['llvm-dis', str(bc), '-o', '-'], check=True,
                              capture_output=True, text=True).stdout
    listed = re.search(r'^!air\.function_constants = !\{([^}]*)\}', text, re.M)
    ids = re.findall(r'!(\d+)', listed.group(1)) if listed else []
    result = {}
    for node in ids:
        m = re.search(r'^!%s = !\{ptr addrspace\(2\) @\S+, !"(\w+)", !"(\w+)", i32 \d+, i1 (?:true|false)\}'
                      % node, text, re.M)
        if not m:
            raise ValueError(f'unexpected function constant metadata !{node}')
        ty, name = m.groups()
        scalar = ty.rstrip('234')
        components = int(ty[len(scalar):] or 1)
        first, unit = TYPES[scalar]
        result[name] = (first + components - 1, unit * components)
    return result


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    lib = Path(sys.argv[1]).read_bytes()
    if lib[:4] != b'MTLB':
        raise SystemExit('not a metallib')
    found = dict(functions(lib))
    old = load(GENERIC / 'compile_0189.py', 'compile_0189')

    def listed(name, values):
        out = []
        for cname, (ty, width) in sorted(constants(found[name]).items()):
            raw = bytes([values.get(cname, 0)]) + bytes(width - 1)
            out.append({'name': cname, 'type': ty, 'bytes': width, 'raw': raw.hex()})
        return out

    # 0189: the candidate vertex constants are the fragment capture's values.
    vertex = listed(VERTEX, old.NONZERO)
    fragment = listed(FRAGMENT, old.NONZERO)
    if [c['name'] for c in vertex] != sorted(old.VERTEX_NAMES) or len(fragment) != 58:
        raise SystemExit('QuartzCore companion constants differ from the 0189 contract')
    recipe = {
        'schema': 1, 'profile_id': 603, 'j5_scaffold_only': True,
        'metallib_sha256': hashlib.sha256(lib).hexdigest(),
        'vertex_function': VERTEX, 'fragment_function': FRAGMENT,
        'vertex_constants': vertex, 'fragment_constants': fragment,
        'configured_vertex_packing0': old.PACKING0,
    }
    Path(sys.argv[2]).write_text(json.dumps(recipe, indent=2) + '\n')
    print(f'generic603 scaffold: {len(vertex)} vertex + {len(fragment)} fragment constants')


if __name__ == '__main__':
    main()
