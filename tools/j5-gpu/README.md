# Mali-T830 (j5y17lte) texture fixture

Ports of `tools/a5xelte-gpu/gen-t720-*.c` to the J5's Mali-T830, which is
Panfrost arch v5 (MFBD), not v4 (SFBD) like the A5's T720.

- `gen-t830-copy-shader.c`: the same NIR copy shader compiled for
  `gpu_id 0x08300010`. Output `t830-copy-16x16.bin` (112 bytes, SHA-256
  `cd7a802ba84c4dae007edc13ed9f2455c738a59429b55c148637a6aaccab0a14`).
- `gen-t830-texture-fixture.c`: `PAN_ARCH 5` packers. Differences from v4:
  the draw's FBD pointer carries the FRAMEBUFFER_POINTER tag (`| 1`, MFBD, one
  RT, as Mesa pan_jm.c); the renderer state has no blend fields and is
  followed by one BLEND descriptor (fixed-function replace, round to
  framebuffer precision, equation in word 2), as panfrost_emit_blend.
  Output `t830-texture-fixture.bin` (SHA-256
  `a74e35b7740a187fe4e61a0487f049dc61751c5b93755b3e3d5b9b37f09e6e7a`).

Build: Mesa 26.2.4, `meson setup build -Dgallium-drivers= -Dvulkan-drivers=
-Dplatforms= -Dglx=disabled -Degl=disabled -Dgles1=disabled -Dgles2=disabled
-Dopengl=false -Dllvm=disabled -Dgbm=disabled -Dtools=panfrost`, with
`with_nir_headers_only` forced to false in `src/compiler/nir/meson.build`
(tools-only builds otherwise link the NIR stub), and both files added as
executables in `src/panfrost/tools/meson.build` (dependencies `idep_nir`,
`idep_mesautil`, `libpanfrost_dep`, link `libpanfrost_compiler`).
The kernel table `A5XELTEGPUTextureFixtureT830.inc` (patch j5 0020) lists the
nonzero words of the page from 0x300 to 0x9ff.
