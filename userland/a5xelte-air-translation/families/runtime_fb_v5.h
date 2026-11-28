/* SPDX-License-Identifier: MIT
 * j5y17lte Mali-T830 (Panfrost arch v5): multi-target framebuffer helpers
 * that replace the T720 (v4) single framebuffer descriptor.
 *
 * v4 SFBD: one FRAMEBUFFER with LOCAL_STORAGE, PARAMETERS (bounds, colour
 *          format, writeback base/stride, clear colour) and TILER sections.
 * v5 MFBD: FRAMEBUFFER = LOCAL_STORAGE, PARAMETERS (size/bounds/tile size),
 *          TILER, TILER_WEIGHTS; followed by one RENDER_TARGET per colour
 *          attachment (format, writeback base/stride, clear colour). Every
 *          pointer to it carries the MFBD tag (bit 0) as in Mesa pan_jm.c.
 * Blending moves from the renderer state to one BLEND descriptor per render
 * target placed directly after the RSD (Mesa panfrost_emit_blend).
 *
 * The layout and values reproduce the kernel fixture that passed on the
 * phone (A5XELTEGPU.cpp T830 MFBD, patch j5 0020: 256/256 texels).
 */
#ifndef A5_RUNTIME_FB_V5_H
#define A5_RUNTIME_FB_V5_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
/* Mesa's __gen_unpack_uint builds a 64-bit-field mask in a branch that is
 * dead for width 64; clang still warns (v5 RSD shader / legacy blend). */
#pragma clang diagnostic ignored "-Wshift-count-overflow"
#include "genxml/v5_pack.h"

#define A5_FBD_TAG_MFBD 1u
/* MFBD size: framebuffer sections plus one render target. */
#define A5_FB_V5_RT_OFFSET MALI_FRAMEBUFFER_LENGTH
#define A5_FB_V5_BYTES (MALI_FRAMEBUFFER_LENGTH + MALI_RENDER_TARGET_LENGTH)

/* v4 colour-format names used by the A5 encoders -> v5 values
 * (v4 1_32B_CHANNEL=3 / 1_16B_CHANNEL=7 / 2_32B_CHANNELS=2 become
 * v5 RAW32=3 / RAW16=1 / RAW64=5). */
#define A5_CF_1x32 MALI_COLOR_FORMAT_RAW32
#define A5_CF_1x16 MALI_COLOR_FORMAT_RAW16
#define A5_CF_2x32 MALI_COLOR_FORMAT_RAW64

typedef struct {
   unsigned width, height;            /* pixels */
   unsigned bound_max_x, bound_max_y; /* pixels, inclusive */
   enum mali_color_buffer_internal_format internal_format;
   enum mali_color_format writeback_format;
   unsigned swizzle;
   uint64_t base;                     /* colour writeback GPU VA */
   uint32_t row_stride, surface_stride;
   uint32_t clear[4];
   bool clean_pixel_write, preload, dither;
   unsigned tls_size;                 /* LOCAL_STORAGE: log2 bytes code */
   uint64_t tls_base;
   uint64_t preload_base;             /* when preload: source GPU VA */
   /* Tiler context (Midgard, T830 has no hierarchical tiling). */
   unsigned hierarchy_mask, polygon_list_size;
   uint64_t polygon_list, polygon_list_body, heap_start, heap_end;
} A5FbV5;

/* Midgard v5 (Mesa pan_jm.c): jobs reference the MFBD, also as their
 * thread storage, through a FRAMEBUFFER_POINTER: pointer | MFBD | 1 RT. */
static inline uint64_t
a5_fbd_ptr_v5(uint64_t fb)
{
   return fb | A5_FBD_TAG_MFBD;
}

/* Pack the MFBD and its render target at fb (A5_FB_V5_BYTES). */
static inline void
a5_pack_fb_v5(uint8_t *fb, const A5FbV5 *f)
{
   memset(fb, 0, A5_FB_V5_BYTES);
   pan_section_pack(fb, FRAMEBUFFER, LOCAL_STORAGE, c) {
      c.tls_size = f->tls_size;
      c.tls_base_pointer = f->tls_base;
      c.wls_instances = MALI_LOCAL_STORAGE_NO_WORKGROUP_MEM;
   }
   pan_section_pack(fb, FRAMEBUFFER, PARAMETERS, c) {
      c.width = f->width;
      c.height = f->height;
      c.bound_max_x = f->bound_max_x;
      c.bound_max_y = f->bound_max_y;
      c.sample_count = 1;
      c.sample_pattern = MALI_SAMPLE_PATTERN_SINGLE_SAMPLED;
      c.tie_break_rule = MALI_TIE_BREAK_RULE_MINUS_180_IN_0_OUT;
      c.effective_tile_size = 256;    /* 16x16 */
      c.render_target_count = 1;
      /* Mesa pan_select_tile_size: ALIGN_POT(tib bytes/pixel x 256, 1K).
       * RAW64 (RGBA16Float/RG32Float) needs 8 bytes/pixel: 2048. With 1024
       * the T830 faults the fragment job (js_status 0x58 DATA_INVALID). */
      c.color_buffer_allocation =
         f->writeback_format == A5_CF_2x32 ? 2048 : 1024;
      c.z_internal_format = MALI_Z_INTERNAL_FORMAT_D24;
   }
   pan_section_pack(fb, FRAMEBUFFER, TILER, c) {
      c.polygon_list_size = f->polygon_list_size;
      c.hierarchy_mask = f->hierarchy_mask;
      c.polygon_list = f->polygon_list;
      c.polygon_list_body = f->polygon_list_body;
      c.heap_start = f->heap_start;
      c.heap_end = f->heap_end;
   }
   pan_section_pack(fb, FRAMEBUFFER, TILER_WEIGHTS, c) { (void)c; }
   pan_cast_and_pack(fb + A5_FB_V5_RT_OFFSET, RGB_RENDER_TARGET, c) {
      /* Mesa get_rt_formats (v5 MFBD): a raw target's tile buffer format is
       * RAW8..RAW128 by size. "Raw Value" is the v4 SFBD convention; with a
       * RAW64 writeback (RGBA16Float, RG32Float) the T830 faults clear-only
       * fragment jobs (js_status 0x58). 32-bit and smaller raw targets keep
       * the value that already works on the phone. */
      c.internal_format = f->internal_format;
      if (f->internal_format == MALI_COLOR_BUFFER_INTERNAL_FORMAT_RAW_VALUE &&
          f->writeback_format == MALI_COLOR_FORMAT_RAW64)
         c.internal_format = MALI_COLOR_BUFFER_INTERNAL_FORMAT_RAW64;
      if (f->internal_format == MALI_COLOR_BUFFER_INTERNAL_FORMAT_RAW_VALUE &&
          f->writeback_format == MALI_COLOR_FORMAT_RAW128)
         c.internal_format = MALI_COLOR_BUFFER_INTERNAL_FORMAT_RAW128;
      c.write_enable = true;
      c.writeback_format = f->writeback_format;
      c.writeback_block_format = MALI_BLOCK_FORMAT_LINEAR;
      c.dithering_enable = f->dither;
      c.swizzle = f->swizzle;
      c.clean_pixel_write_enable = f->clean_pixel_write;
      if (f->preload) {
         c.preload_enable = true;
         c.preload_format = f->writeback_format;
         c.preload_block_format = MALI_BLOCK_FORMAT_LINEAR;
      }
      c.writeback_buffer.base = f->base;
      c.writeback_buffer.row_stride = f->row_stride;
      c.writeback_buffer.surface_stride = f->surface_stride;
      if (f->preload) {
         c.preload_buffer.base = f->preload_base ? f->preload_base : f->base;
         c.preload_buffer.row_stride = f->row_stride;
         c.preload_buffer.surface_stride = f->surface_stride;
      }
      c.clear.color_0 = f->clear[0];
      c.clear.color_1 = f->clear[1];
      c.clear.color_2 = f->clear[2];
      c.clear.color_3 = f->clear[3];
   }
}

/* Disabled flat tiler (fragment-only jobs): Mesa pan_emit_midgard_tiler
 * with disable=true and no hierarchy: user mask, minimum header + 4. */
static inline void
a5_fb_v5_tiler_disabled(A5FbV5 *f, uint64_t polygon, uint64_t body)
{
   f->hierarchy_mask = MALI_MIDGARD_TILER_USER;
   f->polygon_list_size = MALI_MIDGARD_TILER_MINIMUM_HEADER_SIZE + 4;
   f->polygon_list = polygon;
   f->polygon_list_body = body;
   f->heap_start = polygon;
   f->heap_end = polygon;
}

/* One fixed-function BLEND descriptor after the RSD (rsd + RSD length). */
static inline void
a5_pack_blend_v5(uint8_t *blend, bool enable, bool load_destination,
                 const struct MALI_BLEND_EQUATION *equation)
{
   pan_cast_and_pack(blend, BLEND, c) {
      c.enable = enable;
      c.load_destination = load_destination;
      c.round_to_fb_precision = true;
      c.equation = *equation;
   }
}
#endif
