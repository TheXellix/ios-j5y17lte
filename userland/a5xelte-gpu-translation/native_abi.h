/* SPDX-License-Identifier: MIT
 * Privileged experimental T720 native queue. Addresses are selected by the
 * kernel and name only this client's AS1 mappings, never physical memory.
 */
#ifndef A5_MALI_NATIVE_ABI_H
#define A5_MALI_NATIVE_ABI_H
#include <stdint.h>
enum { A5NativeQuerySelector=17, A5NativeSubmitSelector=18,
       A5NativeCapability=32, A5NativeBatchCapability=64, A5NativeBatchSelector=20, A5NativeBatchMax=8, A5NativeSlots=4, A5NativeJobBytes=0x40000,
       A5NativeJobVA=0x18000000, A5NativePreloadOffset=0x1800,
       A5NativeBulkWriteSelector=19,
       A5NativeBulkWriteMax=0x100000, A5NativeBufferMax=0x800000,
       /* j5y17lte: the kernel accepts a coverage hint in SubmitRequest.reserved */
       A5NativeBoundsCapability=128,
       /* j5y17lte: Batch20 items may carry a compact job (see below) */
       A5NativeCompactCapability=256, A5NativeCompactMaxRanges=64 };
typedef struct { uint32_t version,size,reserved0,reserved1; } A5NativeHeader;
typedef struct {
    A5NativeHeader header;
    uint64_t surfaces[A5NativeSlots], buffers[A5NativeSlots];
} A5NativeQueryRequest;
typedef struct {
    uint64_t token, gpuVA;
    uint32_t bytes,width,height,rowBytes,pixelFormat,usage;
} A5NativeSpan;
typedef struct {
    A5NativeHeader header;
    uint64_t jobVA;
    uint32_t jobBytes, flags; /* flags is the nonzero AS1 mapping epoch */
    A5NativeSpan surfaces[A5NativeSlots], buffers[A5NativeSlots];
} A5NativeQueryResult;
typedef struct {
    A5NativeHeader header;
    uint32_t jobBytes,vertexOffset,tilerOffset,fragmentOffset;
    uint32_t readSurfaces,writeSurfaces,readBuffers,reserved;
    uint32_t profileID,mappingEpoch;
    uint64_t surfaces[A5NativeSlots], buffers[A5NativeSlots];
    /* Exactly jobBytes encoded bytes follow this fixed structure. */
} A5NativeSubmitRequest;
typedef struct {
    A5NativeHeader header; /* size is fixed header + actual chunk length */
    uint64_t handle;
    uint32_t offset,length;
} A5NativeBulkWriteRequest;
typedef struct {
    A5NativeHeader header;
    uint32_t status,reserved;
    uint64_t tilerFence,fragmentFence;
} A5NativeSubmitResult;
/* At most eight complete snapshots, same mapping epoch. Each item validates its own tokens. Results contain
 * only real terminal fences; completedCount excludes the failed item. */
typedef struct { A5NativeHeader header;uint32_t count,reserved; } A5NativeBatchRequest;
typedef struct {
    A5NativeHeader header;uint32_t count,completedCount,status,reserved;
    A5NativeSubmitResult items[A5NativeBatchMax];
} A5NativeBatchResult;
/* An epoch is changed by every map/unmap/release mutation. Stable epochs
 * permit different subsets/orderings of already mapped resources. The kernel
 * must still validate every item's live tokens and collect physical-use masks. */
static inline int A5NativeSameEpoch(const A5NativeSubmitRequest *a,const A5NativeSubmitRequest *b){
 return a->mappingEpoch && a->mappingEpoch==b->mappingEpoch;
}
static inline int A5NativeSameMapping(const A5NativeSubmitRequest *a,const A5NativeSubmitRequest *b){
 if(a->mappingEpoch!=b->mappingEpoch)return 0;
 for(unsigned i=0;i<A5NativeSlots;i++)if(a->surfaces[i]!=b->surfaces[i]||a->buffers[i]!=b->buffers[i])return 0;
 return 1;
}
/* j5y17lte coverage hint (SubmitRequest.reserved, only with
 * A5NativeBoundsCapability): bit31 set, bits 12..22 the vertex count (1..2047),
 * bits 0..11 the 64-byte-aligned offset/64 of the vertex job's screen-space
 * float4 position plane inside the job. After the vertex/tiler chain the
 * kernel shrinks the fragment job's tile bounds to the positions' rectangle
 * (never grows them). Zero means no hint. */
static inline uint32_t A5NativeBoundsHint(uint32_t positionOffset,uint32_t count)
{ return (positionOffset&63u)||positionOffset>>18||!count||count>2047u?0u:
    0x80000000u|(count<<12)|(positionOffset>>6); }
static inline int A5NativeBoundsHintValid(uint32_t hint,uint32_t jobBytes,int clear)
{
    if(!hint)return 1;
    uint32_t count=(hint>>12)&2047u,offset=(hint&4095u)<<6;
    return !clear&&(hint&0x7f800000u)==0u&&(hint>>31)&&count&&
        offset>=0x2000u&&offset<jobBytes&&count*16u<=jobBytes-offset;
}
/* Bounded descriptor topology shared by the transport and kernel. Preload is
 * an optional real v4 textured TILER job, not a framebuffer address alias.
 * Return -1 for invalid, 0 for the original chain/clear, 1 for preload.
 * This validates topology only; the lab interface still requires trusted code. */
static inline uint32_t A5NativeJobWord(const uint8_t *p,uint32_t o)
{ return (uint32_t)p[o]|((uint32_t)p[o+1]<<8)|((uint32_t)p[o+2]<<16)|((uint32_t)p[o+3]<<24); }
static inline uint64_t A5NativeJobPointer(const uint8_t *p,uint32_t o)
{ return (uint64_t)A5NativeJobWord(p,o)|((uint64_t)A5NativeJobWord(p,o+4)<<32); }
static inline int A5NativeJobHeader(const uint8_t *p,uint32_t o,uint32_t type,uint64_t next)
{ return !A5NativeJobWord(p,o)&&!A5NativeJobWord(p,o+4)&&!A5NativeJobPointer(p,o+8)&&
    (A5NativeJobWord(p,o+16)&1u)&&((A5NativeJobWord(p,o+16)>>1)&127u)==type&&
    A5NativeJobPointer(p,o+24)==next; }
static inline int A5NativeJobOffset(uint32_t o,uint32_t bytes)
{ return !(o&15u)&&o<bytes-256u; }
static inline int A5NativeJobSeparate(uint32_t a,uint32_t b)
{ return a>b?a-b>=256u:b-a>=256u; }
static inline int A5NativeCheckJobChain(const uint8_t *p,uint32_t bytes,uint64_t base,
    uint32_t vertex,uint32_t tiler,uint32_t fragment,int clear)
{
    if(!p||bytes!=A5NativeJobBytes||!base||base>UINT64_MAX-bytes||
        !A5NativeJobOffset(fragment,bytes)||!A5NativeJobHeader(p,fragment,9,0))return -1;
    if(clear)return vertex==UINT32_MAX&&tiler==UINT32_MAX?0:-1;
    if(!A5NativeJobOffset(vertex,bytes)||!A5NativeJobOffset(tiler,bytes)||
        !A5NativeJobSeparate(vertex,tiler)||!A5NativeJobSeparate(vertex,fragment)||
        !A5NativeJobSeparate(tiler,fragment)||!A5NativeJobHeader(p,tiler,7,0))return -1;
    if(A5NativeJobHeader(p,vertex,5,base+tiler))return 0;
    uint32_t preload=A5NativePreloadOffset;
    if(!A5NativeJobSeparate(preload,vertex)||!A5NativeJobSeparate(preload,tiler)||
        !A5NativeJobSeparate(preload,fragment)||
        !A5NativeJobHeader(p,vertex,5,base+preload)||
        !A5NativeJobHeader(p,preload,7,base+tiler)||
        (A5NativeJobWord(p,vertex+16)>>16)!=1u||
        (A5NativeJobWord(p,preload+16)>>16)!=2u||
        (A5NativeJobWord(p,tiler+16)>>16)!=3u||
        A5NativeJobWord(p,vertex+20)!=0u||
        A5NativeJobWord(p,preload+20)!=1u||
        A5NativeJobWord(p,tiler+20)!=(1u|(2u<<16)))return -1;
    return 1;
}
/* j5y17lte compact job (A5NativeCompactCapability, Batch20 only). A job blob
 * is 256 KiB but a draw writes a few KiB of it. An item whose jobBytes is
 * below A5NativeJobBytes carries instead a sequence of records
 *   { uint32 offset, uint32 length, uint64 zero } + length bytes
 * with offset/length 16-byte multiples, length > 0, records ascending and
 * disjoint inside the job, exactly filling jobBytes. Bytes outside every
 * record are zero. The kernel expands it into the full snapshot before the
 * unchanged validation, so the job topology contract is identical. */
typedef struct { uint32_t offset,length; } A5NativeRange;
static inline uint32_t A5NativeCompactRecordWord(const uint8_t *p,uint32_t o)
{ return (uint32_t)p[o]|((uint32_t)p[o+1]<<8)|((uint32_t)p[o+2]<<16)|((uint32_t)p[o+3]<<24); }
/* Validate and expand into job (A5NativeJobBytes, all zero). Records the
 * written ranges (at most A5NativeCompactMaxRanges) so the next expansion
 * re-zeroes only them. Returns 0 on success. */
static inline int A5NativeCompactExpand(const uint8_t *in,uint32_t bytes,uint8_t *job,
    A5NativeRange *ranges,uint32_t *rangeCount)
{
    uint32_t at=0,end=0,n=0;
    if(!in||!job||!bytes||(bytes&15u)||bytes>=A5NativeJobBytes)return -1;
    while(at<bytes){
        if(bytes-at<16u)return -1;
        uint32_t offset=A5NativeCompactRecordWord(in,at),length=A5NativeCompactRecordWord(in,at+4);
        if(A5NativeCompactRecordWord(in,at+8)||A5NativeCompactRecordWord(in,at+12)||
           (offset&15u)||!length||(length&15u)||offset<end||offset>A5NativeJobBytes||
           length>A5NativeJobBytes-offset||length>bytes-at-16u||n==A5NativeCompactMaxRanges)return -1;
        for(uint32_t i=0;i<length;i++)job[offset+i]=in[at+16u+i];
        if(ranges)ranges[n]=(A5NativeRange){offset,length};
        ++n;end=offset+length;at+=16u+length;
    }
    if(rangeCount)*rangeCount=n;
    return 0;
}
/* Encode the nonzero 64-byte blocks of a full job; gaps up to two blocks
 * are merged. Returns the compact size, or 0 when it would not be smaller
 * than cap or needs more than A5NativeCompactMaxRanges records. */
static inline uint32_t A5NativeCompactEncode(const uint8_t *job,uint8_t *out,uint32_t cap)
{
    uint32_t used=0,records=0;
    for(uint32_t b=0;b<A5NativeJobBytes;){
        const uint64_t *w=(const uint64_t *)(const void *)(job+b);
        if(!(w[0]|w[1]|w[2]|w[3]|w[4]|w[5]|w[6]|w[7])){b+=64u;continue;}
        uint32_t start=b,last=b;
        for(b+=64u;b<A5NativeJobBytes;b+=64u){
            w=(const uint64_t *)(const void *)(job+b);
            if(w[0]|w[1]|w[2]|w[3]|w[4]|w[5]|w[6]|w[7])last=b;
            else if(b-last>128u)break;
        }
        uint32_t length=last+64u-start;
        if(records==A5NativeCompactMaxRanges||length+16u>cap-used)return 0;
        uint32_t h[4]={start,length,0,0};
        for(unsigned i=0;i<16;i++)out[used+i]=((const uint8_t *)h)[i];
        for(uint32_t i=0;i<length;i++)out[used+16u+i]=job[start+i];
        used+=16u+length;++records;b=last+64u;
    }
    return used&&used<A5NativeJobBytes?used:0;
}

#endif
