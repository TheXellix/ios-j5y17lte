#!/usr/bin/env python3
"""Precompile QuartzCore dynamic Metal stages for the j5y17lte on the PC.

A line-for-line port of the phone's /usr/libexec/a5shader-compile dynamic
path (userland/a5xelte-air-translation/ios/a5shader_requests.inc.m:
a5DynamicScaffold, a5CompileDynamic, a5DynamicABI,
a5DynamicConstantArguments, a5DynamicIdentity, a5PublishDynamic). For every
"function" request it writes the same publication the phone would
(stage.midgard, reflection.json, receipt.json) using metal2vulkan and the
Mesa midgard-generic602 backend built for this PC
(tools/j5-build-host-midgard.sh). Requests needing anything not ported
(immutable samplers, floats in canonical JSON, ...) are skipped and left
to the phone. Publications go to OUT/<request_id>/.

  j5-precompile.py --metallib default.metallib --a5shader DIR \\
      --m2v metal2vulkan --backend midgard-generic602 REQUESTS... OUT

--a5shader is the installed /usr/libexec/a5shader content (profile.json,
generic603.json, companions.json) as staged by j5-install-metal.sh.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class Skip(Exception):
    pass


def canonical(value):
    """NSJSONSerialization(NSJSONWritingSortedKeys) bytes."""
    def walk(v):
        if isinstance(v, float):
            raise Skip('float in canonical JSON')
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return text.replace('/', '\\/').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unsigned(v, limit):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= limit


def variable_blur(request):
    return ((request['stage'] == 'vertex' and request['function'] == 'variable_blur_vert_lph') or
            (request['stage'] == 'fragment' and request['function'] == 'variable_blur_downsample_frag_lph'))


def scaffold_for(request, fallback, companions):
    if variable_blur(request):
        pair = dict(fallback)
        pair['vertex_function'] = 'variable_blur_vert_lph'
        pair['fragment_function'] = 'variable_blur_downsample_frag_lph'
        pair['vertex_constants'] = []
        pair['fragment_constants'] = []
        return pair
    entry = (companions or {}).get(request['stage'], {}).get(request['function'])
    if not isinstance(entry, dict) or not isinstance(entry.get('constants'), list):
        return fallback
    pair = dict(fallback)
    vertex = request['stage'] == 'vertex'
    pair['fragment_function' if vertex else 'vertex_function'] = entry['function']
    pair['fragment_constants' if vertex else 'vertex_constants'] = entry['constants']
    return pair


def constant_arguments(named, indexed):
    out = []
    for item in list(named) + list(indexed):
        t = item['type']
        kind = None
        components, unit = 1, 1
        if 3 <= t <= 6:
            kind, components, unit = 'float', t - 2, 4
        elif 16 <= t <= 19:
            kind, components, unit = 'half', t - 15, 2
        elif 29 <= t <= 36:
            kind, components, unit = ('int' if t < 33 else 'uint'), 1 + (t - 29) % 4, 4
        elif 37 <= t <= 44:
            kind, components, unit = ('short' if t < 41 else 'ushort'), 1 + (t - 37) % 4, 2
        elif 45 <= t <= 56:
            kind = 'char' if t < 49 else 'uchar' if t < 53 else 'bool'
            components = 1 + (t - 45) % 4
        elif 81 <= t <= 88:
            kind, components, unit = ('long' if t < 85 else 'ulong'), 1 + (t - 81) % 4, 8
        if not kind:
            raise Skip('unsupported constant type')
        raw = item['raw']
        values = []
        for c in range(components):
            bits = 0
            for j in range(unit):
                bits |= int(raw[(c * unit + j) * 2:(c * unit + j) * 2 + 2], 16) << (j * 8)
            if kind == 'bool':
                values.append('true' if bits else 'false')
            elif kind in ('float', 'half'):
                values.append('0x%x' % bits)
            elif kind in ('char', 'short', 'int', 'long'):
                if unit < 8 and bits & (1 << (unit * 8 - 1)):
                    bits -= 1 << (unit * 8)
                values.append('%d' % bits)
            else:
                values.append('%d' % bits)
        type_name = kind if components == 1 else '%s%d' % (kind, components)
        key = item['name'] if 'name' in item else str(item['index'])
        out += ['--constant', '%s:%s:%s' % (key, type_name, ','.join(values))]
    return out


def buffer_size(reflection, title, slot):
    if slot.get('stage') != title or slot.get('class') != 'Buffer' or not unsigned(slot.get('index'), 30):
        raise Skip('invalid buffer slot')
    for entry in reflection['interface']['slots']:
        if len(entry) != 2:
            raise Skip('invalid interface slot')
        if entry[0] != slot:
            continue
        buffer = entry[1].get('Buffer') or {}
        window = (buffer.get('window') or {}).get('Bounded') if isinstance(buffer.get('window'), dict) else None
        if (buffer.get('access') != {'read': True, 'write': False} or
                buffer.get('form') != {'Descriptor': 'UniformWords'} or not window or
                window.get('start') != 0 or not unsigned(window.get('len'), 4096) or not window['len']):
            raise Skip('unsupported buffer window')
        return window['len']
    raise Skip('buffer has no reflected slot')


def dynamic_abi(reflection, stage):
    title = 'Vertex' if stage == 'vertex' else 'Fragment'
    short = 'vert' if stage == 'vertex' else 'frag'
    mask = 1 if stage == 'vertex' else 16
    iface = reflection.get('interface')
    if (reflection.get('kind') != 'render' or not isinstance(reflection.get('layout'), dict) or
            not isinstance(iface, dict) or iface.get('needs_pointer_translation') or
            iface.get('needs_handle_translation')):
        raise Skip('unbounded resources')
    m = 'A5MIDGARD1\nstage %s\n' % stage
    push = 0
    for r in reflection['layout'].get('push_constants', []):
        if not (unsigned(r.get('stages'), 31) and unsigned(r.get('offset'), 80) and unsigned(r.get('size'), 80)):
            raise Skip('push range')
        if r['stages'] & mask:
            end = r['offset'] + r['size']
            if end > 80 or end % 4:
                raise Skip('push > 80')
            push = max(push, end)
    m += 'push_bytes %d\n' % push
    sets = reflection['layout'].get('sets', [])
    if len(sets) != 1:
        raise Skip('sets')
    resources = textures = fetches = 0
    for s in sets:
        if s.get('set') != 0 or s.get('flags'):
            raise Skip('set0')
        for b in s.get('bindings', []):
            if not unsigned(b.get('stages'), 31):
                raise Skip('binding stage')
            if not b['stages'] & mask:
                continue
            resources += 1
            if not unsigned(b.get('binding'), 30) or b.get('count') != 1 or b.get('flags') or resources > 32:
                raise Skip('binding abi')
            index, ty = b['binding'], b.get('ty')
            if ty == 6:
                if index >= 7:
                    raise Skip('ubo table')
                m += 'binding %d uniform %d\n' % (index, buffer_size(reflection, title, b['source']['Buffer']))
            elif ty == 7 and b.get('source') == {'Synthetic': {'stage': title, 'binding': 'ConstantBlob'}}:
                m += 'binding %d storage 0\n' % index
            elif ty == 1:
                src = b['source']['CombinedTextureSampler']
                texture, sampler = src['texture'], src['sampler']
                selection = sampler.get('sampler')
                if isinstance(selection, dict) and 'Constexpr' in selection:
                    raise Skip('immutable sampler (not ported)')
                if not isinstance(selection, dict) or set(selection) != {'Slot'} or b.get('immutable_sampler') is not None:
                    raise Skip('sampler source')
                info = None
                for slot in iface['slots']:
                    if len(slot) == 2 and slot[0] == texture:
                        info = slot[1].get('Texture')
                if (textures >= 4 or texture.get('stage') != title or not info or
                        info.get('texture_type') != 'Type2D' or info.get('sampled_type') != 'Float' or
                        info.get('depth_compare') or
                        info.get('access') != {'sample': True, 'read': False, 'write': False} or
                        sampler.get('compare') or sampler.get('integer') or
                        sampler.get('cube_gradient') or sampler.get('raw')):
                    raise Skip('texture abi')
                m += 'texture %d %d\n' % (index, textures)
                textures += 1
            elif ty == 10 and stage == 'fragment' and b.get('source') == {'InputAttachment': 0}:
                g = reflection.get('graphics') or {}
                fetches += 1
                if (fetches > 1 or g.get('rasterization_order_attachment_access') is not True or
                        g.get('rasterization_samples') != 1 or
                        g.get('input_attachments') != [{'color_index': 0, 'input_attachment_index': 0,
                                                        'format_class': 'Float'}]):
                    raise Skip('framebuffer fetch')
                m += 'framebuffer_fetch %d 0\n' % index
            else:
                raise Skip('descriptor kind needs a new lowering')
    selected = [e for e in reflection.get('stages', []) if e.get('stage') == short]
    if (len(selected) != 1 or selected[0].get('entry_point') != 'main' or
            selected[0].get('stage_flags') or selected[0].get('required_subgroup_size') is not None):
        raise Skip('stage execution model')
    specs = 0
    for c in (selected[0].get('specialization') or {}).get('constants', []):
        specs += 1
        if not unsigned(c.get('id'), 65535) or c.get('size') != 4 or specs > 16:
            raise Skip('spec shape')
        key, value = c.get('key') or {}, None
        if 'RangeAtBindOffset' in key:
            value = buffer_size(reflection, title, key['RangeAtBindOffset'])
        elif 'SamplerState' in key:
            st = key['SamplerState']
            if (st['slot'].get('stage') != title or not unsigned(st['slot'].get('index'), 15) or
                    st['slot'].get('class') != 'Sampler' or st.get('fields') != 2147483655 or
                    c.get('unread_bits') != 4294967288):
                raise Skip('sampler spec')
            value = 0
        if value is None:
            raise Skip('spec key needs a new lowering')
        m += 'spec %d %d\n' % (c['id'], value)
    return m


def compile_request(request, a, scaffold603, companions, profile_json, out):
    key = request['request_id']
    stage = request['stage']
    scaffold = scaffold_for(request, scaffold603, companions)
    vertex = stage == 'vertex'
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        prefix = tmp / 'shader'
        meta = tmp / 'reflection.json'
        packing = tmp / 'packing0.json'
        packing.write_bytes(canonical(scaffold['configured_vertex_packing0']))
        profile = json.loads(profile_json)
        caps, profiles = profile['capabilities'], profile['profiles']
        if not isinstance(caps, dict) or not isinstance(profiles, dict) or len(profiles) != 1:
            raise Skip('profile')
        caps['a5_ordered_tilebuffer_color0'] = {
            'extensions': {'VK_EXT_rasterization_order_attachment_access': 1},
            'features': {'VkPhysicalDeviceRasterizationOrderAttachmentAccessFeaturesEXT': {
                'rasterizationOrderColorAttachmentAccess': True,
                'rasterizationOrderDepthAttachmentAccess': False,
                'rasterizationOrderStencilAttachmentAccess': False}}}
        next(iter(profiles.values()))['capabilities'].append('a5_ordered_tilebuffer_color0')
        device_profile = tmp / 'ordered-color0-profile.json'
        device_profile.write_bytes(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode())
        constants = {}
        for item in scaffold['fragment_constants' if vertex else 'vertex_constants']:
            constants[item['name']] = item
        for item in request['named_constants']:
            constants[item['name']] = item
        named = [constants[k] for k in sorted(constants)]
        cmd = [a.m2v, a.metallib, str(prefix) + '.spv', '--profile', str(device_profile),
               '--function', request['function'] if vertex else scaffold['vertex_function'],
               '--fragment', scaffold['fragment_function'] if vertex else request['function'],
               '--color-format', '0:BGRA8Unorm', '--vertex-descriptor', str(packing),
               '--emit-meta', str(meta), '--no-timeout']
        cmd += constant_arguments(named, request['indexed_constants'])
        env = dict(os.environ, METAL2VULKAN_SPIRV_VAL=a.spirv_val)
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if r.returncode or 'spirv-val vulkan1.2: PASS' not in r.stdout + r.stderr:
            raise Skip('metal2vulkan: ' + (r.stdout + r.stderr).strip().splitlines()[-1][:160]
                       if (r.stdout + r.stderr).strip() else 'metal2vulkan failed')
        reflection = json.loads(meta.read_text())
        manifest = dynamic_abi(reflection, stage)
        if 'blend_state' in request:
            b = request['blend_state']
            manifest += 'blend %d %d %d %d %d %d %d %d\n' % (
                b['format'], b['write_mask'], b['rgb_operation'], b['alpha_operation'],
                b['source_rgb'], b['destination_rgb'], b['source_alpha'], b['destination_alpha'])
        abi = tmp / 'ABI.txt'
        abi.write_text(manifest)
        short = 'vert' if vertex else 'frag'
        native_path, info_path = tmp / 'stage.midgard', tmp / 'info.json'
        r = subprocess.run([a.backend, '--dynamic-stage', stage, '%s.%s.spv' % (prefix, short),
                            str(native_path), str(abi), str(info_path)], capture_output=True, text=True)
        if r.returncode:
            raise Skip('midgard: ' + ((r.stdout + r.stderr).strip().splitlines() or ['failed'])[-1][:160])
        native = native_path.read_bytes()
        info = json.loads(info_path.read_text())
        stats = info.get('native_info') or {}
        if (info.get('schema') != 1 or info.get('stage') != stage or stats.get('bytes') != len(native) or
                not unsigned(stats.get('first_tag'), 15) or not stats['first_tag'] or
                stats['first_tag'] != native[0] & 15 or not unsigned(stats.get('work_regs'), 32) or
                not unsigned(stats.get('tls'), 1 << 20) or not unsigned(stats.get('wls'), 1 << 20)):
            raise Skip('native metadata')
        semantic = dict(reflection)
        semantic['stages'] = [dict(e, spirv='shader.%s.spv' % e['stage']) for e in reflection['stages']]
        semantic['compilation_context'] = {
            'kind': 'render-pair-scaffold', 'requested_stage': stage,
            'requested_function': request['function'],
            'companion_function': scaffold['fragment_function'] if vertex else scaffold['vertex_function'],
            'selected_native_stage_only': True, 'native_manifest': manifest,
            'translation_named_constants': named,
            'translation_indexed_constants': request['indexed_constants'],
            'vertex_descriptor': scaffold['configured_vertex_packing0']}
        reflection_data = canonical(semantic)
        receipt = {
            'schema': 2, 'kind': 'dynamic-stage', 'request_id': key,
            'source_library': 'quartzcore', 'metallib_sha256': request['metallib_sha256'],
            'gpu_id': '08300010', 'compiler_abi': request['compiler_abi'], 'stage': stage,
            'function': request['function'], 'stage_compiled': True, 'pipeline_compatible': False,
            'named_constants_sha256': digest(canonical(request['named_constants'])),
            'indexed_constants_sha256': digest(canonical(request['indexed_constants'])),
            'support_generation': 3 if variable_blur(request) else 2}
        if 'blend_state' in request:
            receipt['blend_state'] = request['blend_state']
        receipt['native'] = {'file': 'stage.midgard', 'bytes': len(native), 'sha256': digest(native),
                             'first_tag': stats['first_tag'], 'work_registers': stats['work_regs'],
                             'tls_bytes': stats['tls'], 'wls_bytes': stats['wls']}
        receipt['reflection'] = {'file': 'reflection.json', 'bytes': len(reflection_data),
                                 'sha256': digest(reflection_data)}
        if request['compiler_abi'] == 2 and info.get('shader_anisotropy') != 1:
            raise Skip('generation2 without shader anisotropy')
        receipt['native_abi'] = info
        work = out / ('.precompile-' + key)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        (work / 'stage.midgard').write_bytes(native)
        (work / 'reflection.json').write_bytes(reflection_data)
        (work / 'receipt.json').write_bytes(canonical(receipt))
        for f in work.iterdir():
            f.chmod(0o444)
        work.chmod(0o755)
        work.rename(out / key)
        return len(native)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--metallib', required=True)
    ap.add_argument('--a5shader', required=True, type=Path)
    ap.add_argument('--m2v', required=True)
    ap.add_argument('--backend', required=True)
    ap.add_argument('--spirv-val', default=shutil.which('spirv-val') or 'spirv-val')
    ap.add_argument('requests', nargs='+', type=Path)
    a = ap.parse_args()
    out = a.requests.pop()
    out.mkdir(parents=True, exist_ok=True)
    scaffold603 = json.loads((a.a5shader / 'generic603.json').read_text())
    comp_path = a.a5shader / 'companions.json'
    companions = json.loads(comp_path.read_text()) if comp_path.exists() else None
    profile_json = (a.a5shader / 'profile.json').read_text()
    files = []
    for p in a.requests:
        files += sorted(p.rglob('*.request.json')) if p.is_dir() else [p]
    done = skipped = present = 0
    for f in files:
        request = json.loads(f.read_text())
        if request.get('kind') != 'function' or request.get('stage') not in ('vertex', 'fragment'):
            continue
        if (out / request['request_id']).exists():
            present += 1
            continue
        try:
            n = compile_request(request, a, scaffold603, companions, profile_json, out)
            done += 1
            print('compiled %s %s %s %d bytes' % (request['request_id'][:12], request['stage'],
                                                  request['function'], n))
        except Skip as e:
            skipped += 1
            print('skipped  %s %s %s: %s' % (request['request_id'][:12], request['stage'],
                                             request['function'], e))
    print('precompile: %d compiled, %d skipped, %d already present' % (done, skipped, present))


if __name__ == '__main__':
    main()
