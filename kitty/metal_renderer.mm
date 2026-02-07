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

struct MetalWindow {
    CAMetalLayer *layer;
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLRenderPipelineState> cellPipeline;
    id<MTLRenderPipelineState> clearPipeline;
    id<MTLTexture> spriteTexture;
    id<MTLTexture> decorTexture;
    uint32_t cellWidth, cellHeight;
    uint32_t spriteXnum, spriteYnum, spriteLayers;
};

static id<MTLDevice> g_device = nil;
static id<MTLCommandQueue> g_queue = nil;
static id<MTLLibrary> g_library = nil;

bool
metal_backend_init(void) {
    if (g_device) return true;
    g_device = MTLCreateSystemDefaultDevice();
    if (!g_device) return false;
    g_queue = [g_device newCommandQueue];
    // Minimal inline library for future pipelines; safe to create even if unused for clear-only path.
    NSString *source = @"using namespace metal;\\n"
                       "struct VSOut { float4 pos [[position]]; };\\n"
                       "vertex VSOut vtx(uint vid [[vertex_id]]) {\\n"
                       "  float2 pts[3] = { {-1.0, -1.0}, {3.0, -1.0}, {-1.0, 3.0} };\\n"
                       "  VSOut o; o.pos = float4(pts[vid], 0, 1); return o; }\\n"
                       "fragment float4 frag() { return float4(0,0,0,1); }\\n";
    NSError *err = nil;
    g_library = [g_device newLibraryWithSource:source options:nil error:&err];
    if (!g_library) {
        g_library = nil; // but still allow clear-only path
    }
    return g_queue != nil;
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
    // Placeholder: currently just clears to background color.
    (void)now; (void)scan_for_animated_images;
    float alpha = w->background_opacity.supports_transparency ? OPT(background_opacity) : 1.0f;
    metal_present_blank(w, alpha, OPT(background));
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

#endif // __APPLE__
