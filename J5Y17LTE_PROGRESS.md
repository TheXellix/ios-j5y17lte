# j5y17lte (SM-J530F, Exynos7870) port log

Base: ios-a5xelte (SM-A510F, Exynos7580). Device: SM-J530F rev07, bootloader
J530FXXS9CUE5, unlocked, TWRP recovery. Full partition backup kept off Git.

## Hardware map (from the phone's own rev07 DTB, BOOT DTBH entry 5)

| Item | J5 (7870) | A5 (7580) |
| --- | --- | --- |
| GIC-400 | GICD 0x104e1000, GICC 0x104e2000 | 0x10c01000 / 0x10c02000 |
| Timer | 26 MHz, CNTFRQ_EL0 reads 0 | same |
| eMMC | dw_mmc 0x13540000, SPI 245 | same |
| Bootloader FB | 0x67000000, 720x1280, 32 bpp, stride 2880 | 0x67000000, 1080x1920 |
| DECON / DSIM | 0x14830000 / 0x14800000 | same |
| PMU (reboot) | 0x10480000; INFORM2 +0x808, INFORM3 +0x80c, SWRESET +0x400 | 0x10460000 |
| Watchdog | 0x10170000 | 0x101b0000 |
| last_kmsg ring | exynos-snapshot log_kernel 0x46800000, 2 MiB | same |
| Touch | Imagis IST3038H, I2C 0x50 | Zinitix |
| PMIC | S2MPU05 | S2MPU03 |
| RAM | 0x40000000-0x7e3fffff, 0x80000000-0xbfffffff | |

0x104e0000 is the GIC on the J5 but a pin bank on the A5: A5 touch/keys/GPU
code must stay disabled (a5touch=0 a5touchprobe=0 a5keys=0, no a5gpu).

## Device results

- 2026-11-14 probe4k (J5XNU001), BOOT p10 only, readback hash matched.
  Phone returned to TWRP by itself. last_kmsg marker: CurrentEL 0x4, SCTLR
  0x30c5183c (MMU off), FDT 0x48000000 (magic ok), image at 0x40080000
  (S-Boot copies the kernel there, unlike the A5's 0x40205000), MPIDR
  0x80000000, MMFR0 0x1122 (4K yes, 16K no), CNTFRQ 0, result 4: 4 KiB MMU
  on, TCR 0x80a03520, SCTLR 0x30c5183d.
- 2026-11-14 first XNU boot attempt with the payload in the ramdisk slot
  (25 MB): S-Boot loops with "could not do normal boot, invalid ramdisk
  length". TWRP's 13.5 MB ramdisk is accepted. Recovered via download mode
  and Heimdall.
- 2026-11-14 payload appended to the loader in the kernel slot (16.7 MB,
  J5EMBED header at +64 KiB), stock 1.1 MB ramdisk, CI kernel run 43588711096
  (patches-j5 0001 + 0002), root rd=emmcroot0 emmcroot=USERDATA on the iOS
  16.7.16 iPhone 8 Plus HFSX root (USERDATA verified in 64 MiB chunks).
  Flashed with Heimdall. User reports XNU verbose console text scrolling
  slowly on the panel: the S-Boot DECON scanout of 0x67000000 shows XNU's
  framebuffer console without any panel re-initialisation.
- 2026-11-14 boot 1 log (TWRP last_kmsg, 673 KB, a few DRAM bit flips after
  the key reset): XNU 22.6.0 boots on 1 CPU, GICv2 mapped from the ADT,
  A5XELTE eMMC finds GPT USERDATA (first LBA 5558272), hfs mounts
  J5IOSROOT, launchd runs all boot tasks, "Early boot complete. Continuing
  system boot", backboardd and SpringBoard exec, backboardd opens the
  AppleCLCD and creates surfaces. 14 eMMC CMD17 errors (RINTSTS 0x424/0x42c:
  HTO data starvation) cause page-in failures -> SIGBUS (code 0xa) in
  SpringBoard x2, callservicesd x2, xpcproxy, chronod, ... AppleCLCD still
  used the A5's fixed 1080x1920 geometry; perf lines every 5 s flood the
  console (use a5fb_perf=0).
- patch j5 0003: CMD17 retry (up to 8, FIFO reset each attempt) and a
  1080x1920 iPhone 8 Plus canvas at 0x68000000 scaled 2/3 into the panel.
- 2026-11-14 boot 3 (kernel run 4, cpus=4, console not muted): 4/4 CPUs
  initialized, SGI1 verified. No eMMC CMD17 errors. backboardd presents 19
  frames of the 1080x1920 surface; SpringBoard creates its own surfaces
  (272x184, 360x246); PosterBoard crashes once (SIGTRAP), driverkitd once.
  Userland reaches maild, bluetoothd, searchd, fairplayd. backboardd turns
  the display off when idle (no touch input) -> use a5fb_keep_on=1. disp0
  canvas changed to 1080x1920 (backboardd also created 720x1280 surfaces).
- boot 4: kernel run 5 (patch j5 0004: RAM log continues while the panel
  console is muted), cpus=4, a5fb_noconsole=1, a5fb_keep_on=1.
- 2026-11-14 boot 5 (kernel run 6, patches j5 0005 + 0006): iOS home screen
  reached (status bar, dock, two "Waiting..." placeholder icons). All four
  GPIO keys work (Home unlocks). Touch: S2MPU05 ID 0x2, LDO34 0x3c -> 0xfc
  (tsp_avdd was off after S-Boot); IST3038H acks 0x50 but reads fail
  (IICSTAT stuck 0xb0 / NACK 0x11) -> patch j5 0007 follows the Linux
  s3c2410 START / repeated START / STOP sequences.
- 2026-11-14 boot 6 (patch j5 0007): I2C reads now succeed; HIB_INTR_MSG
  returns 0x8ead8ead (firmware not scanning). Patch j5 0008 sends the Linux
  ist30xx_start() commands (MODE_SPECIAL 0, FW_START 1) to HIB_CMD
  0xb00b013c and ignores the idle value.
- 2026-11-14 boot 7 (patch j5 0008): start commands acked, firmware stays at
  0x8ead8ead (IST30XX_INITIAL_VALUE, "end initial") with HIB_TOUCH_STATUS 0.
  tools/j5-isttool (raw I2C from TWRP over /dev/i2c-11) shows the working
  Linux state: status 0x....0075 with a running frame counter in [31:20],
  INTR_MSG 0x08000800. Linux resume sends MODE_SPECIAL with
  NOISE_MODE_POWER (bit 8); patch j5 0009 does the same and power-cycles
  LDO34 (ist30xx_reset timing) if the firmware stays idle.
- boot 8 (patch j5 0009): still idle after the POWER mode bit and an LDO34
  power cycle. Patch j5 0010 sets GPA0-6 (touch INT) to input before power-on.
- boot 9 (patch j5 0010; GPA0-6 was already input, con=0): chip id 0x38d;
  ~600 ms after MODE_SPECIAL(POWER) + FW_START the HIB_TOUCH_STATUS frame
  counter runs (0x02200075, 0x04600075), as under Linux. 0x8ead8ead only
  means no message since boot; the 0009 idle reset was wrong. Patch j5 0011
  resets only when the status frame counter stops.
- boot 10 (kernel run 10): user touched corners and swiped, no events: the
  driver required (msg & 0xc00) == 0xc00 like the 30xxc header. Live capture
  under Linux with j5-isttool: touch messages are 0x..001801 (count 1,
  finger 1, bit 11 only, top byte varies), release 0x08000800; coordinates
  0x11xxxyyy (id [31:28], x [23:12], y [11:0]) in 720x1280 panel pixels.
  Patch j5 0012 accepts bit-11 messages.
- 2026-11-15 boot 11 (patch j5 0012): touch works (taps, swipes, slide to
  power off). SpringBoard SIGTRAP after opening/closing the notification
  centre, preceded by a 3.1 s "Completed Runloop Hang"; iOS sees the display
  as 360x640@3x (1080x1920), not a real iPhone geometry.
- patch j5 0013: canvas size from /j5-panel canvas-width/height, each
  presented layer scaled straight into the panel (no uncached canvas pass),
  HID and touch target size from the ADT. tools/mkadt_j5y17lte.py --model
  iphone8 selects iPhone10,4 / D201AP, display-scale 2, 750x1334.
- 2026-11-15 boot 12/13 (iPhone 8 root, 750x1334): first boot stuck on the
  Apple logo; second boot (kernel run 14) reaches the UI in ~9 min.
  Mali-T830: S-Boot leaves pd-g3d on (status 0x3000f) and the G3D clocks
  enabled; GPU_ID 0x08300010 (T830 r0p1), one shader core, one L2, one
  tiler. eMMC: busy ~29.7 s of every 30 s at ~4.5 MB/s single-sector PIO,
  2.2 GB read in ~9 min (re-reads under a 512 MiB RAM window).
- boot 14: RAM window 736 MiB (loader RAM_MIB=736, ADT dram-size,
  ends 0xae000000 below mfc_nfw) and a5emmc_blocks=32.
- boot 14 (736 MiB, a5emmc_blocks=32): UI in ~3 min (was ~9); eMMC 13.7 MB/s
  busy (was 4.5), max request 27 ms (was 407), no errors.
- patch j5 0015: A5XELTEGPU accepts the J5 Mali-T830 (pd-g3d/CMU_G3D gates,
  inherited clock, SC_LS_ALLOW_ATTR_TYPES quirk); ADT gpu nub; tools/j5-boot.sh.
- 2026-11-15 boot 15 (patch j5 0015, a5gpu=3): first Mali-T830 job. L2,
  shader and tiler power on (ready=1 each, T830 shader config 0x10000 read
  back), the private WRITE_VALUE job completes through AS0 in 65 us with
  header DONE, no MMU/GPU fault and both readback words correct.
- patch j5 0016: scanout clear test (a5gpu=5) at the J5 panel centre.
- boot 16 (patch j5 0016, a5gpu=5): the fragment clear fails with JS status
  0x58 DATA_INVALID_FAULT (job IRQ fail bit 16): the A5 fixture builds a T720
  SFBD (Panfrost arch v4); the T830 is arch v5 and needs an MFBD.
- patch j5 0017: T830 MFBD fixture (Mesa genxml v5: local storage, parameters,
  disabled tiler context, RGB render target 0; framebuffer pointer bit 0).
- boot 17 (patch 0017, a5gpu=4): still DATA_INVALID_FAULT 0x58. Mesa pan_props:
  T820/T830 have no_hierarchical_tiling like the T720. Patch j5 0018: disabled
  tiler with USER mask 4095, 516-byte list, body magic 0xa0000000.
- boot 18 (patch 0018, a5gpu=4): the T830 MFBD fragment job completes (JOB_IRQ
  done, header DONE, no MMU/GPU fault), but 0/256 pixels match. Patch j5 0019:
  RT clean pixel write enable (clear-only frame) and a readback log.
- 2026-11-15 boot 19 (patch j5 0019, a5gpu=4): first T830 render. The MFBD
  fragment clear writes 256/256 red pixels (readback ff0000ff), job DONE in
  92 us, no faults.
- boot 20 (a5gpu=5): scanout clear job completes (1.35 ms). boot 21 (a5gpu=6):
  fence 1 256/256, fence 2 0x58: the reuse writes the clear colour at the SFBD
  offset fb[32], which is the MFBD RT format word; fixed in patch j5 0020.
- patch j5 0020: second fence clear colour at the MFBD RT clear words; T830
  texture self-test (a5gpu=7): Mesa-generated v5 fixture (tools/j5-gpu), MFBD
  with the tiler active, GPU model flag from GPU_ID.
