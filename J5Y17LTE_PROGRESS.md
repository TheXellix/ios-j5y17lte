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
