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
