/* SPDX-License-Identifier: MIT
 * Released Mesa26.2.4 pan_clear.c pan_pack_color/pan_pack_raw semantics and
 * pan_desc.c pan_emit_fbd + disabled flat tiler context. j5y17lte: Mali-T830,
 * Panfrost v5 MFBD + render target (runtime_fb_v5.h).
 */
#define PAN_ARCH 5
#include "runtime_clear.h"
#include <math.h>
#include <string.h>
#include "runtime_fb_v5.h"
enum { FB=0x300,POLY=0x1000,BODY=0x1200 };
static unsigned pixel_bytes(unsigned format){return format==80||format==55?4:format==10?1:format==30||format==43||format==23||format==25?2:format==115||format==105?8:0;}
static uint32_t unorm_bits(double x,unsigned bits){
 float v=(float)(x<0?0:x>1?1:x)*(float)((1u<<bits)-1);uint32_t n=(uint32_t)v;float rem=v-(float)n;
 return n+(rem>.5f||(rem==.5f&&(n&1)));
}
static uint32_t unorm(double x){return unorm_bits(x,8);}
static uint32_t float_bits(float f){uint32_t v;memcpy(&v,&f,4);return v;}
static uint16_t half_bits(double x){_Float16 h=(_Float16)(float)x;uint16_t bits;memcpy(&bits,&h,2);return bits;}
static int encode(const A5RuntimeClear*r,uint8_t*d){
 const A5RuntimeImage*i=&r->destination;unsigned bytes=pixel_bytes(i->metalPixelFormat);
 uint64_t limit=UINT64_C(1)<<40;
 if(!bytes)return A5RuntimeUnsupported;
 if(!r->descriptorGPUVA||(r->descriptorGPUVA&4095)||r->descriptorGPUVA>limit-A5RuntimeJobBytes||
    !i->gpuVA||(i->gpuVA&63)||!i->bytes||i->gpuVA>=limit||i->bytes>limit-i->gpuVA||
    !i->width||i->width>4096||!i->height||i->height>4096||
    i->rowBytes<i->width*bytes||(i->rowBytes&15)||(uint64_t)i->rowBytes*i->height>i->bytes||
    (i->gpuVA<r->descriptorGPUVA+A5RuntimeJobBytes&&r->descriptorGPUVA<i->gpuVA+i->bytes))return A5RuntimeBounds;
 for(unsigned c=0;c<4;++c)if(!isfinite(r->color[c]))return A5RuntimeUnsupported;
 uint32_t words[4];unsigned raw=i->metalPixelFormat==55||i->metalPixelFormat==115||i->metalPixelFormat==23||i->metalPixelFormat==25||i->metalPixelFormat==105;
 if(i->metalPixelFormat==55){uint32_t w=float_bits((float)r->color[0]);for(unsigned c=0;c<4;++c)words[c]=w;}
 else if(i->metalPixelFormat==23||i->metalPixelFormat==25){
  /* For integer clears admit only unambiguous exact integral values, including
   * default zero; do not silently invent fractional/overflow conversion. */
  if(i->metalPixelFormat==23&&(r->color[0]<0||r->color[0]>65535||floor(r->color[0])!=r->color[0]))return A5RuntimeUnsupported;
  uint32_t h=i->metalPixelFormat==25?half_bits(r->color[0]):(uint32_t)r->color[0];
  for(unsigned c=0;c<4;++c)words[c]=h|(h<<16);
 }else if(i->metalPixelFormat==105){
  words[0]=float_bits((float)r->color[0]);words[1]=float_bits((float)r->color[1]);words[2]=words[0];words[3]=words[1];
 }else if(i->metalPixelFormat==43){
  /* pan_clear.c R5G5B5A1 internal layout: five integer+five fractional
   * bits/channel, one integer+one fractional alpha bit, no dithering. */
  uint32_t w=(unorm_bits(r->color[0],5)<<5)|(unorm_bits(r->color[1],5)<<15)|
             (unorm_bits(r->color[2],5)<<25)|(unorm_bits(r->color[3],1)<<31);
  for(unsigned c=0;c<4;++c)words[c]=w;
 }else if(i->metalPixelFormat==115){
  words[0]=(uint32_t)half_bits(r->color[0])|((uint32_t)half_bits(r->color[1])<<16);
  words[1]=(uint32_t)half_bits(r->color[2])|((uint32_t)half_bits(r->color[3])<<16);
  words[2]=words[0];words[3]=words[1];
 }else{
  unsigned a=i->metalPixelFormat==80?unorm(r->color[3]):255;
  uint32_t w=unorm(r->color[0])|(unorm(r->color[1])<<8)|(unorm(r->color[2])<<16)|(a<<24);
  for(unsigned c=0;c<4;++c)words[c]=w;
 }
 A5FbV5 f={.width=i->width,.height=i->height,.bound_max_x=i->width-1,.bound_max_y=i->height-1,
  .internal_format=raw?MALI_COLOR_BUFFER_INTERNAL_FORMAT_RAW_VALUE:i->metalPixelFormat==43?MALI_COLOR_BUFFER_INTERNAL_FORMAT_R5G5B5A1:MALI_COLOR_BUFFER_INTERNAL_FORMAT_R8G8B8A8,
  .writeback_format=i->metalPixelFormat==55?A5_CF_1x32:
    i->metalPixelFormat==23||i->metalPixelFormat==25?A5_CF_1x16:
    i->metalPixelFormat==43?MALI_COLOR_FORMAT_R5G5B5A1:
    i->metalPixelFormat==115||i->metalPixelFormat==105?A5_CF_2x32:
    i->metalPixelFormat==10?MALI_COLOR_FORMAT_R8:i->metalPixelFormat==30?MALI_COLOR_FORMAT_R8G8:MALI_COLOR_FORMAT_R8G8B8A8,
  .swizzle=i->metalPixelFormat==80||i->metalPixelFormat==43?0x60a:0x688,
  .base=i->gpuVA,.row_stride=i->rowBytes,.surface_stride=i->rowBytes*i->height,
  .clear={words[0],words[1],words[2],words[3]},.clean_pixel_write=true,.dither=false};
 /* No vertex/tiler jobs: released pan_emit_midgard_tiler(disable=true),
  * flat(nohierarchy) minimum header+4 and the empty-list marker. */
 a5_fb_v5_tiler_disabled(&f,r->descriptorGPUVA+POLY,r->descriptorGPUVA+BODY);
 a5_pack_fb_v5(d+FB,&f);
 uint32_t marker=0xa0000000;memcpy(d+BODY,&marker,4);
 pan_pack((struct mali_job_header_packed*)d,JOB_HEADER,c){c.type=MALI_JOB_TYPE_FRAGMENT;c.index=1;c.enable_texture_mapper=true;}
 pan_pack((struct mali_fragment_job_payload_packed*)(d+32),FRAGMENT_JOB_PAYLOAD,c){c.bound_max_x=(i->width-1)/16;c.bound_max_y=(i->height-1)/16;c.framebuffer=(r->descriptorGPUVA+FB)|A5_FBD_TAG_MFBD;}
 return A5RuntimeOK;
}
int A5MaliEncodeRuntimeClear(const A5RuntimeClear*r,void*out,size_t n){
 if(!out||n!=A5RuntimeJobBytes)return A5RuntimeInvalid;memset(out,0,n);
 int rc=r?encode(r,out):A5RuntimeInvalid;if(rc)memset(out,0,n);return rc;
}
