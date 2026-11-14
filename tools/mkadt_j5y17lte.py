#!/usr/bin/env python3
"""Build an entry-only j5y17lte (SM-J530F, Exynos7870) ADT.

Derived from mkadt_a5xelte.py. Values come from the phone's own revision-7
DTB (BOOT DTBH entry 5) and the live fb0 geometry read in TWRP.
"""
import argparse
import os
from pathlib import Path

import adt
import mkadt
import a5xelte_identity


def set_prop(node, name, value):
    for i, (key, flags, _) in enumerate(node.props):
        if key == name:
            node.props[i] = (key, flags, value)
            return
    node.props.append((name, 0, value))


def child(node, name):
    for candidate in node.children:
        if candidate.prop('name') == mkadt.cstr(name):
            return candidate
    raise ValueError(f'missing donor ADT node {name}')


def build():
    # The donor's optional /product is D22AP-specific Apple metadata.
    root = mkadt.build(seed=os.urandom(64), qemu=True, donor_product=False)
    set_prop(root, 'compatible', mkadt.cstr('samsung,j5y17lte') +
             mkadt.cstr('samsung,exynos7870') + mkadt.cstr('AppleARM'))
    chosen = child(root, 'chosen')
    buttons = child(root, 'buttons')
    # J5 DT gpio_keys: KEY_HOMEPAGE on its own GPIO bank, pin 7.
    set_prop(buttons, 'home-button-type', mkadt.u32(0))
    set_prop(buttons, 'button-names', b''.join(mkadt.cstr(name) for name in
                                       ('volup', 'voldown', 'hold', 'home')))
    set_prop(chosen, 'dram-base', mkadt.u64(0x80000000))
    set_prop(chosen, 'dram-size', mkadt.u64(0x20000000))
    set_prop(chosen, 'firmware-version', mkadt.cstr('j5y17lte-entry'))
    set_prop(chosen, 'system-firmware-version', mkadt.cstr('j5y17lte-entry'))
    cpus = child(root, 'cpus')
    cpu0 = child(cpus, 'cpu0')
    set_prop(cpu0, 'compatible', mkadt.cstr('arm,cortex-a53') + mkadt.cstr('ARM,v8'))
    set_prop(cpu0, 'reg', mkadt.u32(0))
    set_prop(cpu0, 'timebase-frequency', mkadt.u32(26000000))
    # The J5 DT also has two A53 clusters of four cores:
    # MPIDR 0..3 in cluster 0 and 0x100..0x103 in cluster 1. The cpus=N
    # boot argument still selects a prefix, so cpus=1 and cpus=2 remain valid.
    for logical in range(1, 8):
        cluster, core = divmod(logical, 4)
        mpidr = (cluster << 8) | core
        cpus.children.append(mkadt.node(f'cpu{logical}', [
            ('device_type', mkadt.cstr('cpu')),
            ('compatible', mkadt.cstr('arm,cortex-a53') + mkadt.cstr('ARM,v8')),
            ('reg', mkadt.u32(mpidr)),
            ('cpu-id', mkadt.u32(logical)),
            ('cluster-id', mkadt.u32(cluster)),
            ('cluster-type', mkadt.u32(0)),
            ('die-cluster-id', mkadt.u32(cluster)),
            ('cluster-core-id', mkadt.u32(core)),
            ('l2-cache-id', mkadt.u32(cluster)),
            ('l3-cache-id', mkadt.u32(0)),
            ('state', mkadt.cstr('stopped')),
            ('timebase-frequency', mkadt.u32(26000000)),
            ('clock-frequency', mkadt.u32(1600000000)),
            ('bus-frequency', mkadt.u32(100000000)),
            ('memory-frequency', mkadt.u32(1866000000)),
            ('peripheral-frequency', mkadt.u32(26000000)),
            ('fixed-frequency', mkadt.u32(26000000)),
        ]))
    arm_io = child(root, 'arm-io')
    set_prop(arm_io, 'device_type', mkadt.cstr('a5xelte-io'))
    set_prop(arm_io, 'compatible', mkadt.cstr('samsung,exynos7870-io') +
             mkadt.cstr('arm-io'))
    set_prop(arm_io, 'ranges', mkadt.u64(0, 0x10000000, 0xf0000000))
    arm_io.children = [n for n in arm_io.children if n.prop('name') == mkadt.cstr('wdt')]
    arm_io.children.append(mkadt.node('gic', [
        ('compatible', mkadt.cstr('arm,cortex-a15-gic')),
        ('interrupt-controller', mkadt.cstr('master')),
        ('virtual-timer-intid', mkadt.u32(27)),
        # J5 DT interrupt-controller@104E0000: GICD 0x104e1000, GICC 0x104e2000.
        ('reg', mkadt.u64(0x04e1000, 0x1000, 0x04e2000, 0x1000)),
    ]))
    # The Linux DECON handoff and Samsung loader already scan out this buffer.
    # Publish its iOS display service without importing the SWEET panel size.
    arm_io.children.append(mkadt.node('disp0', [
        ('device_type', mkadt.cstr('display-subsystem')),
        ('compatible', mkadt.cstr('samsung,a5xelte-display')),
        # iOS sees the iPhone 8 Plus 1080x1920 canvas (j5-panel scales it).
        ('canvas-width', mkadt.u32(1080)),
        ('canvas-height', mkadt.u32(1920)),
    ]))
    # No GPU nub: the A5 Mali-T720 stage is not ported to the J5 Mali-T830.
    root.children = [n for n in root.children if n.prop('name') not in
                     (mkadt.cstr('sweet-fbcon'), mkadt.cstr('sweet-ufs'))]
    root.children.append(mkadt.node('a5xelte-fbcon', [
        # s3cfb.bootloaderfb=0x67000000; fb0 720x1280, 32 bpp, stride 2880.
        ('reg', mkadt.u64(0x67000000, 720 * 1280 * 4)),
        ('width', mkadt.u32(720)),
        ('height', mkadt.u32(1280)),
        ('stride', mkadt.u32(2880)),
    ]))
    # Samsung exynos-snapshot log_kernel ring (TWRP /proc/last_kmsg). The
    # last 4 KiB page stays with the loader markers and SEC_LKMSG_MAGICKEY.
    root.children.append(mkadt.node('j5-ramlog', [
        ('reg', mkadt.u64(0x46800000, 0x200000 - 0x1000)),
    ]))
    # PMU window for the restart/panic -> TWRP path (J5 exynos,reboot node).
    root.children.append(mkadt.node('j5-reset', [
        ('reg', mkadt.u64(0x10480000, 0x1000)),
    ]))
    # Real 720x1280 DECON scanout; iOS draws a 1080x1920 iPhone 8 Plus canvas
    # in Linux-only RAM at virtual-base (outside XNU's 0x80000000 window),
    # scaled 2/3 into the panel by the A5XELTE AppleCLCD (patch j5 0003).
    root.children.append(mkadt.node('j5-panel', [
        ('reg', mkadt.u64(0x67000000, 720 * 1280 * 4)),
        ('width', mkadt.u32(720)),
        ('height', mkadt.u32(1280)),
        ('stride', mkadt.u32(2880)),
        ('virtual-base', mkadt.u64(0x68000000)),
    ]))
    # gpio_keys from the J5 DT: ALIVE pinctrl 0x139f0000, DAT = bank + 4,
    # active low. Order = sweet_hid_key: power, volume up, volume down, home.
    root.children.append(mkadt.node('j5-keys', [
        ('reg', mkadt.u64(0x139f0000, 0x1000)),
        ('keys', b''.join(mkadt.u32(v) for v in (0x44, 0, 0x84, 0, 0x84, 1, 0x64, 7))),
    ]))
    # Imagis IST3038H on I2C2 (s3c2440) 0x50, powered by S2MPU05 LDO34 over
    # the MIF HSI2C; attention on GPA0-6 (patch j5 0006). flags: 1 swap,
    # 2 invert x, 4 invert y (touch panel pixels, before scaling).
    root.children.append(mkadt.node('j5-touch', [
        ('i2c', mkadt.u64(0x13890000, 0x1000)),
        ('pmic-hsi2c', mkadt.u64(0x10510000, 0x2000)),
        ('alive-pins', mkadt.u64(0x139f0000, 0x1000)),
        ('peri-cmu', mkadt.u64(0x101f0000, 0x1000)),
        ('mif-cmu', mkadt.u64(0x10460000, 0x1000)),
        ('i2c-pins', mkadt.u64(0x139c0000, 0x1000)),
        ('pmic-pins', mkadt.u64(0x10530000, 0x1000)),
        ('max-x', mkadt.u32(720)),
        ('max-y', mkadt.u32(1280)),
        ('flags', mkadt.u32(0)),
    ]))
    root.children.append(mkadt.node('a5xelte-emmc', [
        ('reg', mkadt.u64(0x13540000, 0x2000)),
    ]))
    return a5xelte_identity.apply(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    blob = adt.serialize(build())
    args.output.write_bytes(blob)
    print(f'{args.output}: {len(blob)} bytes')
