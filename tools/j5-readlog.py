#!/usr/bin/env python3
"""Decode a TWRP /proc/last_kmsg capture after a j5y17lte XNU boot.

  adb exec-out cat /proc/last_kmsg > kmsg.bin
  j5-readlog.py kmsg.bin

Prints the J5 loader marker (J5XNU002 page), the XNU entry marker (XNUELTE1)
and the XNU console text from the J5XNULOG ring (patch j5 0001).
"""
import struct
import sys

LOADER_FIELDS = {1: 'CurrentEL', 2: 'SCTLR', 3: 'FDT', 4: 'loader image',
                 10: 'state (5 = jumped to XNU, <0 = payload rejected)',
                 11: 'initrd start', 12: 'initrd end', 13: 'XNU phys base',
                 14: 'XNU mem size', 15: 'entry PA', 16: 'segments',
                 17: 'boot_args PA', 21: 'WTCON before', 22: 'WTCON after',
                 77: 'display (-100 = read-only J5 stage)'}

data = open(sys.argv[1], 'rb').read()
i = data.find(b'J5XNU002')
if i < 0:
    print('loader marker J5XNU002: NOT FOUND')
else:
    print(f'loader marker at {i:#x}')
    words = struct.unpack_from('<80q', data, i) if i + 640 <= len(data) else ()
    for k, name in LOADER_FIELDS.items():
        if k < len(words):
            print(f'  [{k:2}] {name:45} {words[k]:#x}' if words[k] >= 0 else f'  [{k:2}] {name:45} {words[k]}')
j = data.find(b'XNUELTE1')
print('XNU entry marker XNUELTE1:', f'at {j:#x}' if j >= 0 else 'NOT FOUND')
k = data.find(b'J5XNULOG')
if k < 0:
    print('XNU console ring J5XNULOG: NOT FOUND')
    sys.exit(0)
head = data[k:k + 64].split(b'\0', 1)[0]
print(head.decode('utf-8', 'replace').strip())
# 64-byte NUL-padded header, then the console text up to the first NUL run.
text = data[k + 64:].split(b'\0\0\0\0', 1)[0]
print(f'--- XNU console ({len(text)} bytes) ---')
sys.stdout.write(text.decode('utf-8', 'replace'))
print('\n--- end ---')
