#!/usr/bin/env python3
"""Read files from the iOS HFS+ root without copying the partition.

Parses the volume header and the catalog B-tree and reads only the needed
blocks, either from a local image or straight from the SM-J530F USERDATA
partition in TWRP (adb exec-out dd, J5 serial only).

  j5-hfs.py SOURCE ls PATH            list a directory (size, mtime, name)
  j5-hfs.py SOURCE get PATH OUT       copy one file
  j5-hfs.py SOURCE pull PATH OUTDIR   copy a directory tree
SOURCE is an image path or "phone".

Limits: plain data forks with at most 8 extents (no extents-overflow or
decmpfs-compressed files, which are reported); the journal is not
replayed, so after a forced reboot the very latest metadata may be missing.
"""
import os
import struct
import subprocess
import sys
import time

SERIAL = os.environ.get('ANDROID_SERIAL', '5200479dc6a79451')
PART = '/dev/block/by-name/USERDATA'
HFS_EPOCH = 2082844800


class Phone:
    def read(self, offset, size):
        # 4 KiB aligned dd; callers ask for block-aligned ranges.
        bs = 4096
        first, last = offset // bs, (offset + size + bs - 1) // bs
        cmd = ['adb', '-s', SERIAL, 'exec-out',
               f'dd if={PART} bs={bs} skip={first} count={last - first} 2>/dev/null']
        data = subprocess.run(cmd, check=True, capture_output=True).stdout
        data = data[offset - first * bs:][:size]
        if len(data) != size:
            raise IOError(f'short read at {offset}: {len(data)}/{size}')
        return data


class Image:
    def __init__(self, path):
        self.f = open(path, 'rb')

    def read(self, offset, size):
        self.f.seek(offset)
        return self.f.read(size)


def fork(raw):
    size = struct.unpack_from('>Q', raw, 0)[0]
    extents = [struct.unpack_from('>II', raw, 16 + 8 * i) for i in range(8)]
    return size, [e for e in extents if e[1]]


class Volume:
    def __init__(self, dev):
        self.dev = dev
        vh = dev.read(1024, 512)
        if vh[:2] not in (b'H+', b'HX'):
            raise SystemExit('not an HFS+ volume')
        self.bs = struct.unpack_from('>I', vh, 0x28)[0]
        self.catalog = fork(vh[0x110:0x160])
        self.nodes = self.read_fork(*self.catalog)
        self.records = list(self.leaves())

    def read_fork(self, size, extents):
        out = bytearray()
        for start, count in extents:
            out += self.dev.read(start * self.bs, count * self.bs)
        if len(out) < size:
            raise IOError('fork needs the extents overflow file')
        return bytes(out[:size])

    def leaves(self):
        node_size = struct.unpack_from('>H', self.nodes, 14 + 18)[0]
        node = struct.unpack_from('>I', self.nodes, 14 + 10)[0]
        while node:
            n = self.nodes[node * node_size:(node + 1) * node_size]
            flink, _, kind, _, count = struct.unpack_from('>IIbBH', n, 0)
            if kind != -1:
                raise IOError('catalog leaf chain broken')
            for i in range(count):
                off = struct.unpack_from('>H', n, node_size - 2 * (i + 1))[0]
                klen, parent, nlen = struct.unpack_from('>HIH', n, off)
                name = n[off + 8:off + 8 + 2 * nlen].decode('utf-16-be')
                rec = n[off + 2 + klen:]
                yield parent, name, rec
            node = flink

    def children(self, folder):
        for parent, name, rec in self.records:
            kind = struct.unpack_from('>h', rec, 0)[0]
            if parent == folder and kind in (1, 2):
                yield name, rec

    def lookup(self, path):
        folder, rec = 2, None   # root folder ID is 2
        for part in [p for p in path.split('/') if p]:
            found = dict(self.children(folder)).get(part)
            if found is None:
                raise SystemExit(f'not found: {path}')
            rec = found
            if struct.unpack_from('>h', rec, 0)[0] == 1:
                folder = struct.unpack_from('>I', rec, 8)[0]
        return folder, rec

    def data(self, rec):
        flags = struct.unpack_from('>H', rec, 2)[0]
        bsd_flags = rec[32 + 9]   # ownerFlags; UF_COMPRESSED is 0x20
        if bsd_flags & 0x20:
            raise IOError('decmpfs-compressed file')
        _ = flags
        return self.read_fork(*fork(rec[88:168]))


def mtime(rec):
    t = struct.unpack_from('>I', rec, 16)[0] - HFS_EPOCH
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(max(t, 0)))


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    src, cmd, path = sys.argv[1:4]
    vol = Volume(Phone() if src == 'phone' else Image(src))
    folder, rec = vol.lookup(path)
    if cmd == 'ls':
        for name, r in sorted(vol.children(folder)):
            kind = struct.unpack_from('>h', r, 0)[0]
            size = fork(r[88:168])[0] if kind == 2 else 0
            print(f'{size:>10} {mtime(r)} {name}{"/" if kind == 1 else ""}')
    elif cmd == 'get':
        open(sys.argv[4], 'wb').write(vol.data(rec))
    elif cmd == 'pull':
        def walk(fid, out):
            os.makedirs(out, exist_ok=True)
            for name, r in vol.children(fid):
                dst = os.path.join(out, name.replace('/', ':'))
                if struct.unpack_from('>h', r, 0)[0] == 1:
                    walk(struct.unpack_from('>I', r, 8)[0], dst)
                else:
                    try:
                        open(dst, 'wb').write(vol.data(r))
                    except IOError as e:
                        print(f'skip {dst}: {e}', file=sys.stderr)
        walk(folder, sys.argv[4])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
