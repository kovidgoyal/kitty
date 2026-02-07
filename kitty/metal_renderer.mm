#ifdef __APPLE__
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#import <AppKit/AppKit.h>
#include "metal_renderer.h"
#include "state.h"
#include "data-types.h"
#include "monotonic.h"
#include "glfw-wrapper.h"
#include <vector>
#include <unordered_map>
#include <atomic>

struct MetalWindow {
    CAMetalLayer *layer;
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLSamplerState> sampler_nearest;
    id<MTLRenderPipelineState> cellPipeline;
    id<MTLRenderPipelineState> clearPipeline;
    id<MTLTexture> spriteTexture;
    id<MTLTexture> decorTexture;
    uint32_t cellWidth, cellHeight;
    uint32_t spriteXnum, spriteYnum, spriteLayers;
    id<MTLBuffer> cellVertexBuffer;
    NSUInteger cellVertexCount;
};

static id<MTLDevice> g_device = nil;
static id<MTLCommandQueue> g_queue = nil;
static id<MTLLibrary> g_library = nil;
static std::unordered_map<uint32_t, id<MTLTexture>> g_image_textures;
static std::atomic<uint32_t> g_image_ids{1000}; // arbitrary non-zero start
static id<MTLSamplerState> g_sampler_nearest = nil;
static id<MTLSamplerState> g_sampler_linear = nil;
static id<MTLRenderPipelineState> g_cell_pipeline = nil;
static id<MTLRenderPipelineState> g_clear_pipeline = nil;
static const NSUInteger kMaxVerticesPerFrame = 1024 * 1024; // cap to prevent runaway

typedef struct {
    simd_float2 pos;            // clip-space
    simd_float2 uv;
    simd_float2 underline_uv;
    simd_float2 strike_uv;
    simd_float2 cursor_uv;
    uint32_t   layer;
    simd_float4 fg_rgba;        // premul fg
    simd_float4 deco_rgba;      // decoration color (premul)
    float       text_alpha;
    float       colored_sprite;
} MetalCellVertex;

static id<MTLRenderPipelineState>
make_pipeline(NSString *vname, NSString *fname, MTLPixelFormat pf) {
    MTLRenderPipelineDescriptor *d = [[MTLRenderPipelineDescriptor alloc] init];
    d.colorAttachments[0].pixelFormat = pf;
    d.vertexFunction = [g_library newFunctionWithName:vname];
    d.fragmentFunction = [g_library newFunctionWithName:fname];
    NSError *err = nil;
    id<MTLRenderPipelineState> p = [g_device newRenderPipelineStateWithDescriptor:d error:&err];
    return p;
}

bool
metal_build_pipelines(void) {
    if (!g_device || !g_library) return false;
    g_cell_pipeline = make_pipeline(@\"cell_vs\", @\"cell_fs\", MTLPixelFormatBGRA8Unorm_sRGB);
    g_clear_pipeline = make_pipeline(@\"quad_vs\", @\"quad_fs\", MTLPixelFormatBGRA8Unorm_sRGB);
    return g_cell_pipeline != nil && g_clear_pipeline != nil;
}

bool
metal_backend_init(void) {
    if (g_device) return true;
    g_device = MTLCreateSystemDefaultDevice();
    if (!g_device) return false;
    g_queue = [g_device newCommandQueue];
    NSString *source = [NSString stringWithContentsOfFile:@"/Users/nripeshn/Documents/PythonPrograms/kitty/kitty/metal_shaders.metal" encoding:NSUTF8StringEncoding error:nil];
    if (!source) return false;
    NSError *err = nil;
    g_library = [g_device newLibraryWithSource:source options:nil error:&err];
    if (!g_library) return false;
    MTLSamplerDescriptor *sd = [[MTLSamplerDescriptor alloc] init];
    sd.minFilter = MTLSamplerMinMagFilterNearest;
    sd.magFilter = MTLSamplerMinMagFilterNearest;
    sd.sAddressMode = MTLSamplerAddressModeClampToEdge;
    sd.tAddressMode = MTLSamplerAddressModeClampToEdge;
    g_sampler_nearest = [g_device newSamplerStateWithDescriptor:sd];
    sd.minFilter = MTLSamplerMinMagFilterLinear;
    sd.magFilter = MTLSamplerMinMagFilterLinear;
    g_sampler_linear = [g_device newSamplerStateWithDescriptor:sd];
    return g_queue != nil && g_sampler_nearest != nil && g_sampler_linear != nil;
}

static void
update_layer_size(struct MetalWindow *mw, NSView *view) {
    if (!mw || !mw->layer || !view) return;
    CGSize size = view.bounds.size;
    CGFloat scale = view.window.backingScaleFactor ?: 1.0;
    mw->layer.contentsScale = scale;
    mw->layer.drawableSize = CGSizeMake(size.width * scale, size.height * scale);
    mw->layer.frame = view.bounds;
}

bool
metal_window_attach(OSWindow *w) {
    if (!w || !w->handle) return false;
    if (!metal_backend_init()) return false;
    NSWindow *ns_window = (NSWindow*)glfwGetCocoaWindow((GLFWwindow*)w->handle);
    if (!ns_window) return false;
    NSView *content_view = [ns_window contentView];
    if (!content_view) return false;
    [content_view setWantsLayer:YES];

    MetalWindow *mw = (MetalWindow*)calloc(1, sizeof(MetalWindow));
    if (!mw) return false;
    mw->device = g_device;
    mw->queue = g_queue;
    mw->sampler_nearest = g_sampler_nearest;
    mw->sampler_linear = g_sampler_linear;
    mw->cellPipeline = g_cell_pipeline;
    mw->clearPipeline = g_clear_pipeline;

    CAMetalLayer *layer = [CAMetalLayer layer];
    layer.device = g_device;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    layer.framebufferOnly = YES;
    layer.presentsWithTransaction = NO;
    layer.needsDisplayOnBoundsChange = YES;
    layer.autoresizingMask = kCALayerWidthSizable | kCALayerHeightSizable;
    mw->layer = layer;

    content_view.layer = layer;
    content_view.wantsLayer = YES;
    update_layer_size(mw, content_view);

    w->metal = mw;
    return true;
}

void
metal_window_resize(OSWindow *w, int width, int height, float xscale, float yscale) {
    if (!w || !w->metal) return;
    MetalWindow *mw = w->metal;
    if (!mw->layer) return;
    CGFloat scale = xscale > 0 && yscale > 0 ? MAX(xscale, yscale) : mw->layer.contentsScale;
    mw->layer.contentsScale = scale;
    mw->layer.drawableSize = CGSizeMake(width * scale, height * scale);
}

void
metal_present_blank(OSWindow *w, float alpha, color_type background) {
    if (!w || !w->metal) return;
    MetalWindow *mw = w->metal;
    CAMetalLayer *layer = mw->layer;
    if (!layer) return;
    id<CAMetalDrawable> drawable = [layer nextDrawable];
    if (!drawable) return;

    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = drawable.texture;
    rp.colorAttachments[0].loadAction = MTLLoadActionClear;
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    float r = ((background >> 16) & 0xff) / 255.0f;
    float g = ((background >> 8) & 0xff) / 255.0f;
    float b = (background & 0xff) / 255.0f;
    rp.colorAttachments[0].clearColor = MTLClearColorMake(r, g, b, alpha);

    id<MTLCommandBuffer> cb = [mw->queue commandBuffer];
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
    [enc endEncoding];
    [cb presentDrawable:drawable];
    [cb commit];
}

bool
metal_render_os_window(OSWindow *w, monotonic_t now, bool scan_for_animated_images) {
    if (!w || !w->metal) return false;
    MetalWindow *mw = w->metal;
    CAMetalLayer *layer = mw->layer;
    if (!layer) return false;
    id<CAMetalDrawable> drawable = [layer nextDrawable];
    if (!drawable) return false;

    // TODO: build per-frame buffers; for now clear via clear pipeline
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = drawable.texture;
    rp.colorAttachments[0].loadAction = MTLLoadActionClear;
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    float alpha = w->background_opacity.supports_transparency ? OPT(background_opacity) : 1.0f;
    float r = ((OPT(background) >> 16) & 0xff) / 255.0f;
    float g = ((OPT(background) >> 8) & 0xff) / 255.0f;
    float b = (OPT(background) & 0xff) / 255.0f;
    rp.colorAttachments[0].clearColor = MTLClearColorMake(r, g, b, alpha);

    id<MTLCommandBuffer> cb = [mw->queue commandBuffer];
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
    if (g_clear_pipeline) {
        [enc setRenderPipelineState:g_clear_pipeline];
    }
    [enc endEncoding];
    [cb presentDrawable:drawable];
    [cb commit];
    return true;
}

void
metal_window_destroy(OSWindow *w) {
    if (!w || !w->metal) return;
    MetalWindow *mw = w->metal;
    if (mw->spriteTexture) { [(__bridge id<MTLTexture>)mw->spriteTexture release]; }
    if (mw->decorTexture) { [(__bridge id<MTLTexture>)mw->decorTexture release]; }
    free(mw);
    w->metal = NULL;
}

// Sprite atlas helpers --------------------------------------------------

static MTLPixelFormat glyph_format(void) { return MTLPixelFormatBGRA8Unorm_sRGB; }
static MTLPixelFormat decor_format(void) { return MTLPixelFormatR32Uint; }

static bool
ensure_cell_vertex_buffer(MetalWindow *mw, NSUInteger required_vertices) {
    if (!required_vertices) return false;
    if (required_vertices > kMaxVerticesPerFrame) required_vertices = kMaxVerticesPerFrame;
    if (mw->cellVertexBuffer && mw->cellVertexBuffer.length >= required_vertices * sizeof(MetalCellVertex)) {
        mw->cellVertexCount = required_vertices;
        return true;
    }
    if (mw->cellVertexBuffer) mw->cellVertexBuffer = nil;
    mw->cellVertexBuffer = [mw->device newBufferWithLength:required_vertices * sizeof(MetalCellVertex)
                                                   options:MTLResourceStorageModeManaged];
    mw->cellVertexCount = required_vertices;
    return mw->cellVertexBuffer != nil;
}

bool
metal_realloc_sprite_texture(struct SpriteMap *sm, unsigned width, unsigned height, unsigned layers) {
    if (!g_device) return false;
    if (sm->metal_texture) {
        [(__bridge id<MTLTexture>)sm->metal_texture release];
        sm->metal_texture = NULL;
    }
    MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:glyph_format() width:width height:height mipmapped:NO];
    desc.textureType = MTLTextureType2DArray;
    desc.arrayLength = layers;
    desc.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
    id<MTLTexture> tex = [g_device newTextureWithDescriptor:desc];
    sm->metal_texture = (__bridge_retained void*)tex;
    return tex != nil;
}

bool
metal_realloc_decor_texture(struct SpriteMap *sm, unsigned width, unsigned height) {
    if (!g_device) return false;
    if (sm->metal_decorations_texture) {
        [(__bridge id<MTLTexture>)sm->metal_decorations_texture release];
        sm->metal_decorations_texture = NULL;
    }
    MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:decor_format() width:width height:height mipmapped:NO];
    desc.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
    id<MTLTexture> tex = [g_device newTextureWithDescriptor:desc];
    sm->metal_decorations_texture = (__bridge_retained void*)tex;
    return tex != nil;
}

bool
metal_upload_sprite(struct SpriteMap *sm, unsigned x, unsigned y, unsigned layer, unsigned w, unsigned h, const void *rgba) {
    id<MTLTexture> tex = (__bridge id<MTLTexture>)sm->metal_texture;
    if (!tex) return false;
    MTLRegion region = { { (NSUInteger)x, (NSUInteger)y, 0 }, { (NSUInteger)w, (NSUInteger)h, 1 } };
    NSUInteger bpr = w * 4;
    [tex replaceRegion:region mipmapLevel:0 slice:layer withBytes:rgba bytesPerRow:bpr bytesPerImage:bpr * h];
    return true;
}

bool
metal_upload_decor(struct SpriteMap *sm, unsigned x, unsigned y, uint32_t decoration_idx) {
    id<MTLTexture> tex = (__bridge id<MTLTexture>)sm->metal_decorations_texture;
    if (!tex) return false;
    MTLRegion region = { { (NSUInteger)x, (NSUInteger)y, 0 }, { 1, 1, 1 } };
    uint32_t val = decoration_idx;
    [tex replaceRegion:region mipmapLevel:0 withBytes:&val bytesPerRow:sizeof(uint32_t)];
    return true;
}

// Generic 2D textures ----------------------------------------------------

uint32_t
metal_image_alloc(void) {
    return g_image_ids.fetch_add(1, std::memory_order_relaxed);
}

void
metal_image_upload(uint32_t tex_id, const void *data, int width, int height, bool srgb, bool is_opaque, bool linear_filter, int repeat_mode) {
    if (!g_device) return;
    MTLPixelFormat pf = srgb ? MTLPixelFormatBGRA8Unorm_sRGB : MTLPixelFormatBGRA8Unorm;
    id<MTLTexture> tex = nil;
    auto it = g_image_textures.find(tex_id);
    if (it == g_image_textures.end()) {
        MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pf width:width height:height mipmapped:NO];
        desc.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
        tex = [g_device newTextureWithDescriptor:desc];
        g_image_textures[tex_id] = tex;
    } else {
        tex = it->second;
        if ((int)tex.width != width || (int)tex.height != height || tex.pixelFormat != pf) {
            [tex release];
            MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pf width:width height:height mipmapped:NO];
            desc.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
            tex = [g_device newTextureWithDescriptor:desc];
            it->second = tex;
        }
    }
    MTLRegion region = { {0,0,0}, { (NSUInteger)width, (NSUInteger)height, 1 } };
    NSUInteger bpr = (NSUInteger)width * 4;
    [tex replaceRegion:region mipmapLevel:0 withBytes:data bytesPerRow:bpr];
    (void)is_opaque; (void)linear_filter; (void)repeat_mode; // TODO: sampler configuration
}

void
metal_image_free(uint32_t tex_id) {
    auto it = g_image_textures.find(tex_id);
    if (it != g_image_textures.end()) {
        [it->second release];
        g_image_textures.erase(it);
    }
}

#endif // __APPLE__
