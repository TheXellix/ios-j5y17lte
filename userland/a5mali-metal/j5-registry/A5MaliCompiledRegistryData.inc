/* SPDX-License-Identifier: MIT
 * j5y17lte: empty compiled-family registry.
 *
 * The A5 registry holds private T720 programs translated from captured
 * QuartzCore pipelines. The Mali-T830 has none; every pipeline is linked at
 * runtime from stages that /usr/libexec/a5shader-compile builds on the phone
 * (A5MaliComposeDynamicPipeline). Including a registry is what enables the
 * native render backend (A5_MALI_NATIVE_RENDER) in this build. */
static const A5MaliCompiledProfile kA5MaliCompiledProfiles[] = {};
