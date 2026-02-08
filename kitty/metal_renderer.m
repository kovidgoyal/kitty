/*
 * metal_renderer.m - Optimized Metal rendering backend for kitty
 * Pure Objective-C for maximum performance on Apple Silicon
 */

#ifdef __APPLE__
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#import <AppKit/AppKit.h>
#import <simd/simd.h>

// Undefine MIN/MAX from Foundation before including kitty headers
#undef MIN
#undef MAX

#include "metal_renderer.h"
#include "state.h"
#include "data-types.h"
#include "screen.h"
#include "line.h"
#include "line-buf.h"
#include "colors.h"
#include "fonts.h"
#include "graphics.h"
#include "glfw-wrapper.h"

// Triple buffering for optimal GPU pipelining
#define NUM_INFLIGHT_BUFFERS 3
#define MAX_CELLS_PER_FRAME (512 * 512)
#define MAX_BORDER_RECTS 256
#define MAX_IMAGES 64

// Pipeline indices
typedef NS_ENUM(NSUInteger, MetalPipeline) {
    MetalPipelineCell = 0,
    MetalPipelineCellBG,
    MetalPipelineCellCombined,
    MetalPipelineCursor,
    MetalPipelineSelection,
    MetalPipelineTint,
    MetalPipelineBorder,
    MetalPipelineGraphics,
    MetalPipelineGraphicsPremult,
    MetalPipelineGraphicsAlphaMask,
    MetalPipelineBgImage,
    MetalPipelineBlit,
    MetalPipelineRoundedRect,
    MetalPipelineRoundedRectFilled,
    MetalPipelineTrail,
    MetalPipelineCount
};

// Vertex for cell rendering - packed for cache efficiency
typedef struct __attribute__((packed)) {
    simd_float2 pos;
    simd_float2 uv;
    simd_float4 fg;
    simd_float4 bg;
    float sprite_z;
    float colored;
} CellVertex;

// Simple vertex for rectangles (cursor, selection, borders)
typedef struct {
    simd_float2 pos;
    simd_float4 color;
} RectVertex;

// Image vertex for graphics/background images
typedef struct {
    simd_float2 pos;
    simd_float2 uv;
} ImageVertex;

// Per-frame uniforms
typedef struct {
    simd_float2 viewport_size;
    simd_float2 cell_size;
    simd_float2 sprite_scale;
    float background_opacity;
    float cursor_opacity;
} FrameUniforms;

// Graphics params for image rendering
typedef struct {
    simd_float4 src_rect;
    simd_float4 dest_rect;
    float extra_alpha;
} GraphicsParams;

// Background image params
typedef struct {
    float tiled;
    simd_float4 sizes;
    simd_float4 positions;
    simd_float4 background;
} BgImageParams;

// Rounded rect params
typedef struct {
    simd_float4 rect;
    simd_float2 params;
    simd_float4 color;
    simd_float4 background_color;
} RoundedRectParams;

// Trail params
typedef struct {
    simd_float4 x_coords;
    simd_float4 y_coords;
    simd_float2 cursor_edge_x;
    simd_float2 cursor_edge_y;
    simd_float3 trail_color;
    float trail_opacity;
} TrailParams;

// Alpha mask params
typedef struct {
    simd_float3 fg_color;
    simd_float4 bg_premult;
} AlphaMaskParams;

// Image texture entry (for future graphics protocol support)
typedef struct {
    id<MTLTexture> texture;
    uint32_t id;
    bool in_use;
} ImageEntry;

// Image storage will be used when graphics protocol is implemented
// static ImageEntry g_images[MAX_IMAGES];
// static uint32_t g_next_image_id = 1;

// Per-window Metal state
typedef struct MetalWindow {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLLibrary> library;
    CAMetalLayer *layer;
    
    // Pipelines
    id<MTLRenderPipelineState> pipelines[MetalPipelineCount];
    id<MTLSamplerState> nearestSampler;
    id<MTLSamplerState> linearSampler;
    id<MTLSamplerState> repeatSampler;  // For tiled background images
    
    // Triple-buffered vertex data
    id<MTLBuffer> cellBuffers[NUM_INFLIGHT_BUFFERS];
    id<MTLBuffer> rectBuffers[NUM_INFLIGHT_BUFFERS];  // For cursors, selections, borders
    id<MTLBuffer> imageBuffers[NUM_INFLIGHT_BUFFERS]; // For graphics/images
    id<MTLBuffer> uniformBuffers[NUM_INFLIGHT_BUFFERS];
    NSUInteger currentBuffer;
    dispatch_semaphore_t frameSemaphore;
    
    // Offscreen rendering (for layered compositing)
    id<MTLTexture> offscreenTexture;
    MTLRenderPassDescriptor *offscreenRPD;
    
    // Textures
    id<MTLTexture> spriteTexture;
    id<MTLTexture> decorTexture;
    id<MTLTexture> bgImageTexture;
    
    // State
    NSUInteger cellCount;
    NSUInteger rectCount;
    NSUInteger imageCount;
    unsigned spriteXnum, spriteYnum;
    unsigned cellWidth, cellHeight;
    
    // Background image state
    uint32_t bgImageId;
    bool bgImageNeedsUpdate;
} MetalWindow;

// Global device (shared across windows)
static id<MTLDevice> g_device = nil;
static id<MTLLibrary> g_library = nil;

// Forward declarations
static id<MTLTexture> metal_get_graphics_texture(uint32_t texture_id);

// Metal shader source built using NSMutableString to avoid C99 string length limits
static NSString *kShaderSource = nil;

// Try to load shader source from external file, fall back to embedded source
static NSString* get_shader_source(void) {
    if (kShaderSource) return kShaderSource;
    
    // Try to load from external .metal file first (for development)
    NSBundle *bundle = [NSBundle mainBundle];
    NSString *metalPath = [bundle pathForResource:@"metal_shaders" ofType:@"metal"];
    if (metalPath) {
        NSError *error = nil;
        NSString *source = [NSString stringWithContentsOfFile:metalPath encoding:NSUTF8StringEncoding error:&error];
        if (source && !error) {
            kShaderSource = source;
            return kShaderSource;
        }
    }
    
    // Fall back to embedded shader source
    NSMutableString *s = [NSMutableString stringWithCapacity:20000];
    [s appendString:@"#include <metal_stdlib>\n"
"using namespace metal;\n"
"\n"
"// Color space conversion\n"
"inline float srgb2linear(float x) {\n"
"    return mix(x / 12.92, pow((x + 0.055f) / 1.055f, 2.4f), step(0.04045f, x));\n"
"}\n"
"inline float linear2srgb(float x) {\n"
"    return mix(12.92 * x, 1.055 * pow(x, 1.0f / 2.4f) - 0.055f, step(0.0031308f, x));\n"
"}\n"
"inline float3 linear2srgb(float3 x) {\n"
"    float3 lower = 12.92 * x;\n"
"    float3 upper = 1.055 * pow(x, float3(1.0f / 2.4f)) - 0.055f;\n"
"    return mix(lower, upper, step(0.0031308f, x));\n"
"}\n"
"\n"
"// Alpha blending\n"
"inline float4 alpha_blend(float4 over, float4 under) {\n"
"    float alpha = mix(under.a, 1.0f, over.a);\n"
"    float3 combined = mix(under.rgb * under.a, over.rgb, over.a);\n"
"    return float4(combined, alpha);\n"
"}\n"
"inline float4 alpha_blend_premul(float4 over, float4 under) {\n"
"    float inv = 1.0f - over.a;\n"
"    return float4(over.rgb + under.rgb * inv, over.a + under.a * inv);\n"
"}\n"
"inline float4 vec4_premul(float3 rgb, float a) { return float4(rgb * a, a); }\n"
"inline float4 vec4_premul(float4 c) { return float4(c.rgb * c.a, c.a); }\n"
"\n"
"constant float3 Y = float3(0.2126, 0.7152, 0.0722);\n"
"\n"
"// Foreground override for contrast (simplified version without full HSLUV)\n"
"inline float3 override_fg_simple(float3 over, float3 under, float threshold) {\n"
"    float under_lum = dot(under, Y);\n"
"    float over_lum = dot(over, Y);\n"
"    float diff = abs(under_lum - over_lum);\n"
"    float override_level = step(diff, threshold);\n"
"    return mix(over, float3(step(under_lum, 0.5)), override_level);\n"
"}\n"
"\n"
"// Cell structures\n"
"struct CellVertex {\n"
"    float2 pos [[attribute(0)]];\n"
"    float2 uv [[attribute(1)]];\n"
"    float4 fg [[attribute(2)]];\n"
"    float4 bg [[attribute(3)]];\n"
"    float sprite_z [[attribute(4)]];\n"
"    float colored [[attribute(5)]];\n"
"};\n"
"struct CellOut {\n"
"    float4 pos [[position]];\n"
"    float2 uv;\n"
"    float4 fg;\n"
"    float4 bg;\n"
"    float sprite_z;\n"
"    float colored;\n"
"};\n"
"\n"
"// Rectangle structures\n"
"struct RectVertex {\n"
"    float2 pos [[attribute(0)]];\n"
"    float4 color [[attribute(1)]];\n"
"};\n"
"struct RectOut {\n"
"    float4 pos [[position]];\n"
"    float4 color;\n"
"};\n"
"\n"
"// Image structures\n"
"struct ImageOut {\n"
"    float4 pos [[position]];\n"
"    float2 uv;\n"
"};\n"
"\n"
"// Cell shaders\n"
"vertex CellOut cell_vertex(CellVertex in [[stage_in]]) {\n"
"    CellOut out;\n"
"    out.pos = float4(in.pos, 0.0, 1.0);\n"
"    out.uv = in.uv;\n"
"    out.fg = in.fg;\n"
"    out.bg = in.bg;\n"
"    out.sprite_z = in.sprite_z;\n"
"    out.colored = in.colored;\n"
"    return out;\n"
"}\n"
"\n"
"fragment float4 cell_bg_fragment(CellOut in [[stage_in]]) {\n"
"    return in.bg;\n"
"}\n"
"\n"
"fragment float4 cell_fg_fragment(CellOut in [[stage_in]],\n"
"                                  texture2d_array<float> sprites [[texture(0)]],\n"
"                                  sampler samp [[sampler(0)]]) {\n"
"    if (in.uv.x == 0.0 && in.uv.y == 0.0 && in.sprite_z == 0.0) discard_fragment();\n"
"    float4 tex = sprites.sample(samp, in.uv, uint(in.sprite_z));\n"
"    float alpha = tex.r;\n"
"    if (in.colored > 0.5) return float4(tex.a * alpha, tex.b * alpha, tex.g * alpha, alpha);\n"
"    float final_alpha = in.fg.a * alpha;\n"
"    return float4(in.fg.rgb * final_alpha, final_alpha);\n"
"}\n"
"\n"
"fragment float4 cell_combined_fragment(CellOut in [[stage_in]],\n"
"                                       texture2d_array<float> sprites [[texture(0)]],\n"
"                                       sampler samp [[sampler(0)]],\n"
"                                       constant float2 &contrast [[buffer(0)]]) {\n"
"    float4 bg = in.bg;\n"
"    if (in.uv.x == 0.0 && in.uv.y == 0.0 && in.sprite_z == 0.0) return bg;\n"
"    float4 tex = sprites.sample(samp, in.uv, uint(in.sprite_z));\n"
"    float alpha = tex.r;\n"
"    float4 fg;\n"
"    if (in.colored > 0.5) {\n"
"        fg = float4(tex.a, tex.b, tex.g, alpha);\n"
"    } else {\n"
"        float under_lum = dot(bg.rgb / max(bg.a, 0.001), Y);\n"
"        float over_lum = dot(in.fg.rgb, Y);\n"
"        float adj = clamp(mix(alpha, pow(alpha, contrast.y), (1.0 - over_lum + under_lum) * 0.5) * contrast.x, 0.0, 1.0);\n"
"        fg = float4(in.fg.rgb, adj * in.fg.a);\n"
"    }\n"
"    return alpha_blend_premul(vec4_premul(fg), bg);\n"
"}\n"];
    [s appendString:@"\n"
"// Rectangle shaders\n"
"vertex RectOut rect_vertex(RectVertex in [[stage_in]]) {\n"
"    RectOut out;\n"
"    out.pos = float4(in.pos, 0.0, 1.0);\n"
"    out.color = in.color;\n"
"    return out;\n"
"}\n"
"fragment float4 rect_fragment(RectOut in [[stage_in]]) { return in.color; }\n"
"\n"
"// Tint shaders\n"
"vertex float4 tint_vertex(uint vid [[vertex_id]], constant float4 &edges [[buffer(0)]]) {\n"
"    float2 pos[4] = {float2(edges[0],edges[1]), float2(edges[0],edges[3]),\n"
"                     float2(edges[2],edges[3]), float2(edges[2],edges[1])};\n"
"    return float4(pos[vid], 0.0, 1.0);\n"
"}\n"
"vertex float4 fullscreen_tint_vertex(uint vid [[vertex_id]]) {\n"
"    float2 pos[4] = {float2(-1,-1), float2(1,-1), float2(-1,1), float2(1,1)};\n"
"    return float4(pos[vid], 0.0, 1.0);\n"
"}\n"
"fragment float4 tint_fragment(constant float4 &color [[buffer(0)]]) { return color; }\n"
"\n"
"// Trail shaders\n"
"struct TrailOut { float4 pos [[position]]; float2 frag_pos; };\n"
"struct TrailParams { float4 x_coords; float4 y_coords; float2 cursor_x; float2 cursor_y; float3 color; float opacity; };\n"
"vertex TrailOut trail_vertex(uint vid [[vertex_id]], constant TrailParams &p [[buffer(0)]]) {\n"
"    TrailOut out;\n"
"    float2 pos = float2(p.x_coords[vid], p.y_coords[vid]);\n"
"    out.pos = float4(pos, 1.0, 1.0);\n"
"    out.frag_pos = pos;\n"
"    return out;\n"
"}\n"
"fragment float4 trail_fragment(TrailOut in [[stage_in]], constant TrailParams &p [[buffer(0)]]) {\n"
"    float op = p.opacity;\n"
"    float in_x = step(p.cursor_x[0], in.frag_pos.x) * step(in.frag_pos.x, p.cursor_x[1]);\n"
"    float in_y = step(p.cursor_y[1], in.frag_pos.y) * step(in.frag_pos.y, p.cursor_y[0]);\n"
"    op *= 1.0f - in_x * in_y;\n"
"    return float4(p.color * op, op);\n"
"}\n"
"\n"
"// Image/graphics shaders\n"
"struct GraphicsParams { float4 src_rect; float4 dest_rect; float extra_alpha; };\n"
"vertex ImageOut image_vertex(uint vid [[vertex_id]], constant GraphicsParams &p [[buffer(0)]]) {\n"
"    int2 pm[4] = {int2(2,1), int2(2,3), int2(0,3), int2(0,1)};\n"
"    int2 pos = pm[vid];\n"
"    ImageOut out;\n"
"    out.uv = float2(p.src_rect[pos.x], p.src_rect[pos.y]);\n"
"    out.pos = float4(p.dest_rect[pos.x], p.dest_rect[pos.y], 0, 1);\n"
"    return out;\n"
"}\n"
"fragment float4 image_fragment(ImageOut in [[stage_in]], texture2d<float> tex [[texture(0)]],\n"
"                               sampler samp [[sampler(0)]], constant float &alpha [[buffer(0)]]) {\n"
"    float4 c = tex.sample(samp, in.uv);\n"
"    c.a *= alpha;\n"
"    return vec4_premul(c);\n"
"}\n"
"fragment float4 image_premult_fragment(ImageOut in [[stage_in]], texture2d<float> tex [[texture(0)]],\n"
"                                       sampler samp [[sampler(0)]], constant float &alpha [[buffer(0)]]) {\n"
"    return tex.sample(samp, in.uv) * alpha;\n"
"}\n"
"struct AlphaMaskParams { float3 fg; float4 bg_premult; };\n"
"fragment float4 image_alpha_mask_fragment(ImageOut in [[stage_in]], texture2d<float> tex [[texture(0)]],\n"
"                                          sampler samp [[sampler(0)]], constant AlphaMaskParams &p [[buffer(0)]]) {\n"
"    float4 c = tex.sample(samp, in.uv);\n"
"    float4 fg = vec4_premul(float4(p.fg, c.r));\n"
"    return alpha_blend_premul(fg, p.bg_premult);\n"
"}\n"];
    [s appendString:@"\n"
"// Background image shaders\n"
"struct BgImageParams { float tiled; float4 sizes; float4 positions; float4 background; };\n"
"struct BgImageOut { float4 pos [[position]]; float2 uv; };\n"
"vertex BgImageOut bgimage_vertex(uint vid [[vertex_id]], constant BgImageParams &p [[buffer(0)]]) {\n"
"    float2 tm[4] = {float2(0,0), float2(0,1), float2(1,1), float2(1,0)};\n"
"    float2 pm[4] = {float2(p.positions[0],p.positions[1]), float2(p.positions[0],p.positions[3]),\n"
"                    float2(p.positions[2],p.positions[3]), float2(p.positions[2],p.positions[1])};\n"
"    float sx = p.tiled * (p.sizes[0] / p.sizes[2]) + (1.0 - p.tiled);\n"
"    float sy = p.tiled * (p.sizes[1] / p.sizes[3]) + (1.0 - p.tiled);\n"
"    BgImageOut out;\n"
"    out.uv = float2(tm[vid].x * sx, tm[vid].y * sy);\n"
"    out.pos = float4(pm[vid], 0, 1);\n"
"    return out;\n"
"}\n"
"fragment float4 bgimage_fragment(BgImageOut in [[stage_in]], texture2d<float> img [[texture(0)]],\n"
"                                 sampler samp [[sampler(0)]], constant BgImageParams &p [[buffer(0)]]) {\n"
"    return alpha_blend(img.sample(samp, in.uv), p.background);\n"
"}\n"
"\n"
"// Blit shader (final compositing with sRGB conversion)\n"
"vertex ImageOut blit_vertex(uint vid [[vertex_id]], constant float4 &src [[buffer(0)]], constant float4 &dst [[buffer(1)]]) {\n"
"    int2 pm[4] = {int2(2,1), int2(2,3), int2(0,3), int2(0,1)};\n"
"    int2 pos = pm[vid];\n"
"    ImageOut out;\n"
"    out.uv = float2(src[pos.x], src[pos.y]);\n"
"    out.pos = float4(dst[pos.x], dst[pos.y], 0, 1);\n"
"    return out;\n"
"}\n"
"fragment float4 blit_fragment(ImageOut in [[stage_in]], texture2d<float> img [[texture(0)]], sampler samp [[sampler(0)]]) {\n"
"    float4 c = img.sample(samp, in.uv);\n"
"    return vec4_premul(linear2srgb(c.rgb / max(c.a, 0.001)), c.a);\n"
"}\n"
"\n"
"// Rounded rectangle shader\n"
"struct RoundedRectParams { float4 rect; float2 params; float4 color; float4 bg_color; };\n"
"vertex float4 rounded_rect_vertex(uint vid [[vertex_id]]) {\n"
"    float2 pos[4] = {float2(1,1), float2(1,-1), float2(-1,-1), float2(-1,1)};\n"
"    return float4(pos[vid], 0, 1);\n"
"}\n"
"float rounded_rect_sdf(float2 p, float2 b, float r) {\n"
"    float2 q = abs(p) - b;\n"
"    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;\n"
"}\n"
"fragment float4 rounded_rect_fragment(float4 pos [[position]], constant RoundedRectParams &p [[buffer(0)]]) {\n"
"    float2 size = p.rect.ba, origin = p.rect.xy;\n"
"    float thickness = p.params[0], radius = p.params[1];\n"
"    float2 position = pos.xy - size / 2.0 - origin;\n"
"    float dist = rounded_rect_sdf(position, size * 0.5 - radius, radius);\n"
"    float outer = -dist, inner = outer - thickness;\n"
"    float alpha = smoothstep(-1.0, 1.0, outer) - smoothstep(-1.0, 1.0, inner);\n"
"    float4 ans = p.color; ans.a *= alpha;\n"
"    return alpha_blend(ans, p.bg_color);\n"
"}\n"
"fragment float4 rounded_rect_filled_fragment(float4 pos [[position]], constant RoundedRectParams &p [[buffer(0)]]) {\n"
"    float2 size = p.rect.ba, origin = p.rect.xy;\n"
"    float radius = p.params[1];\n"
"    float2 position = pos.xy - size / 2.0 - origin;\n"
"    float dist = rounded_rect_sdf(position, size * 0.5 - radius, radius);\n"
"    float alpha = 1.0 - smoothstep(0.0, 1.0, dist);\n"
"    float4 ans = p.color; ans.a *= alpha;\n"
"    return alpha_blend(ans, p.bg_color);\n"
"}\n"];
    kShaderSource = [s copy];
    return kShaderSource;
}

#pragma mark - Initialization

static bool create_pipelines(MetalWindow *mw) {
    NSError *error = nil;
    
    // Compile shaders
    MTLCompileOptions *opts = [[MTLCompileOptions alloc] init];
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    opts.fastMathEnabled = YES;
#pragma clang diagnostic pop
    opts.languageVersion = MTLLanguageVersion2_4;
    
    mw->library = [mw->device newLibraryWithSource:get_shader_source() options:opts error:&error];
    if (!mw->library) {
        NSLog(@"Metal shader compile error: %@", error);
        return false;
    }
    
    // Vertex descriptor for cells
    MTLVertexDescriptor *vd = [[MTLVertexDescriptor alloc] init];
    vd.attributes[0].format = MTLVertexFormatFloat2;
    vd.attributes[0].offset = offsetof(CellVertex, pos);
    vd.attributes[0].bufferIndex = 0;
    vd.attributes[1].format = MTLVertexFormatFloat2;
    vd.attributes[1].offset = offsetof(CellVertex, uv);
    vd.attributes[1].bufferIndex = 0;
    vd.attributes[2].format = MTLVertexFormatFloat4;
    vd.attributes[2].offset = offsetof(CellVertex, fg);
    vd.attributes[2].bufferIndex = 0;
    vd.attributes[3].format = MTLVertexFormatFloat4;
    vd.attributes[3].offset = offsetof(CellVertex, bg);
    vd.attributes[3].bufferIndex = 0;
    vd.attributes[4].format = MTLVertexFormatFloat;
    vd.attributes[4].offset = offsetof(CellVertex, sprite_z);
    vd.attributes[4].bufferIndex = 0;
    vd.attributes[5].format = MTLVertexFormatFloat;
    vd.attributes[5].offset = offsetof(CellVertex, colored);
    vd.attributes[5].bufferIndex = 0;
    vd.layouts[0].stride = sizeof(CellVertex);
    vd.layouts[0].stepFunction = MTLVertexStepFunctionPerVertex;
    
    // Cell BG pipeline
    MTLRenderPipelineDescriptor *pd = [[MTLRenderPipelineDescriptor alloc] init];
    pd.vertexFunction = [mw->library newFunctionWithName:@"cell_vertex"];
    pd.fragmentFunction = [mw->library newFunctionWithName:@"cell_bg_fragment"];
    pd.vertexDescriptor = vd;
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    pd.colorAttachments[0].blendingEnabled = YES;
    pd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
    pd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    pd.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
    pd.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    
    mw->pipelines[MetalPipelineCellBG] = [mw->device newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!mw->pipelines[MetalPipelineCellBG]) {
        NSLog(@"BG pipeline error: %@", error);
        return false;
    }
    
    // Cell FG pipeline (alpha blended text)
    pd.fragmentFunction = [mw->library newFunctionWithName:@"cell_fg_fragment"];
    pd.colorAttachments[0].blendingEnabled = YES;
    pd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    pd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    
    mw->pipelines[MetalPipelineCell] = [mw->device newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!mw->pipelines[MetalPipelineCell]) {
        NSLog(@"Cell pipeline error: %@", error);
        return false;
    }
    
    // Rectangle vertex descriptor (for cursors, selections, borders)
    MTLVertexDescriptor *rectVd = [[MTLVertexDescriptor alloc] init];
    rectVd.attributes[0].format = MTLVertexFormatFloat2;
    rectVd.attributes[0].offset = offsetof(RectVertex, pos);
    rectVd.attributes[0].bufferIndex = 0;
    rectVd.attributes[1].format = MTLVertexFormatFloat4;
    rectVd.attributes[1].offset = offsetof(RectVertex, color);
    rectVd.attributes[1].bufferIndex = 0;
    rectVd.layouts[0].stride = sizeof(RectVertex);
    rectVd.layouts[0].stepFunction = MTLVertexStepFunctionPerVertex;
    
    // Cursor/Selection/Border pipeline (solid rectangles)
    MTLRenderPipelineDescriptor *rectPd = [[MTLRenderPipelineDescriptor alloc] init];
    rectPd.vertexFunction = [mw->library newFunctionWithName:@"rect_vertex"];
    rectPd.fragmentFunction = [mw->library newFunctionWithName:@"rect_fragment"];
    rectPd.vertexDescriptor = rectVd;
    rectPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    rectPd.colorAttachments[0].blendingEnabled = YES;
    rectPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
    rectPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    rectPd.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
    rectPd.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    
    mw->pipelines[MetalPipelineCursor] = [mw->device newRenderPipelineStateWithDescriptor:rectPd error:&error];
    if (!mw->pipelines[MetalPipelineCursor]) {
        NSLog(@"Cursor pipeline error: %@", error);
        return false;
    }
    
    // Selection pipeline (same as cursor)
    mw->pipelines[MetalPipelineSelection] = mw->pipelines[MetalPipelineCursor];
    
    // Border pipeline (same as cursor)
    mw->pipelines[MetalPipelineBorder] = mw->pipelines[MetalPipelineCursor];
    
    // Tint pipeline
    MTLRenderPipelineDescriptor *tintPd = [[MTLRenderPipelineDescriptor alloc] init];
    tintPd.vertexFunction = [mw->library newFunctionWithName:@"tint_vertex"];
    tintPd.fragmentFunction = [mw->library newFunctionWithName:@"tint_fragment"];
    tintPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    tintPd.colorAttachments[0].blendingEnabled = YES;
    tintPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
    tintPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    
    mw->pipelines[MetalPipelineTint] = [mw->device newRenderPipelineStateWithDescriptor:tintPd error:&error];
    
    // Cell combined pipeline (BG + FG in one pass with contrast adjustment)
    pd.fragmentFunction = [mw->library newFunctionWithName:@"cell_combined_fragment"];
    mw->pipelines[MetalPipelineCellCombined] = [mw->device newRenderPipelineStateWithDescriptor:pd error:&error];
    
    // Graphics/Image pipeline
    MTLRenderPipelineDescriptor *imgPd = [[MTLRenderPipelineDescriptor alloc] init];
    imgPd.vertexFunction = [mw->library newFunctionWithName:@"image_vertex"];
    imgPd.fragmentFunction = [mw->library newFunctionWithName:@"image_fragment"];
    imgPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    imgPd.colorAttachments[0].blendingEnabled = YES;
    imgPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    imgPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    imgPd.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
    imgPd.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    mw->pipelines[MetalPipelineGraphics] = [mw->device newRenderPipelineStateWithDescriptor:imgPd error:&error];
    
    // Graphics premultiplied pipeline
    imgPd.fragmentFunction = [mw->library newFunctionWithName:@"image_premult_fragment"];
    mw->pipelines[MetalPipelineGraphicsPremult] = [mw->device newRenderPipelineStateWithDescriptor:imgPd error:&error];
    
    // Graphics alpha mask pipeline
    imgPd.fragmentFunction = [mw->library newFunctionWithName:@"image_alpha_mask_fragment"];
    mw->pipelines[MetalPipelineGraphicsAlphaMask] = [mw->device newRenderPipelineStateWithDescriptor:imgPd error:&error];
    
    // Background image pipeline
    MTLRenderPipelineDescriptor *bgPd = [[MTLRenderPipelineDescriptor alloc] init];
    bgPd.vertexFunction = [mw->library newFunctionWithName:@"bgimage_vertex"];
    bgPd.fragmentFunction = [mw->library newFunctionWithName:@"bgimage_fragment"];
    bgPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    bgPd.colorAttachments[0].blendingEnabled = YES;
    bgPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    bgPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    mw->pipelines[MetalPipelineBgImage] = [mw->device newRenderPipelineStateWithDescriptor:bgPd error:&error];
    
    // Blit pipeline (for final compositing)
    MTLRenderPipelineDescriptor *blitPd = [[MTLRenderPipelineDescriptor alloc] init];
    blitPd.vertexFunction = [mw->library newFunctionWithName:@"blit_vertex"];
    blitPd.fragmentFunction = [mw->library newFunctionWithName:@"blit_fragment"];
    blitPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    blitPd.colorAttachments[0].blendingEnabled = YES;
    blitPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    blitPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    mw->pipelines[MetalPipelineBlit] = [mw->device newRenderPipelineStateWithDescriptor:blitPd error:&error];
    
    // Rounded rectangle pipeline
    MTLRenderPipelineDescriptor *rrPd = [[MTLRenderPipelineDescriptor alloc] init];
    rrPd.vertexFunction = [mw->library newFunctionWithName:@"rounded_rect_vertex"];
    rrPd.fragmentFunction = [mw->library newFunctionWithName:@"rounded_rect_fragment"];
    rrPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    rrPd.colorAttachments[0].blendingEnabled = YES;
    rrPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    rrPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    mw->pipelines[MetalPipelineRoundedRect] = [mw->device newRenderPipelineStateWithDescriptor:rrPd error:&error];
    
    // Rounded rectangle filled pipeline
    rrPd.fragmentFunction = [mw->library newFunctionWithName:@"rounded_rect_filled_fragment"];
    mw->pipelines[MetalPipelineRoundedRectFilled] = [mw->device newRenderPipelineStateWithDescriptor:rrPd error:&error];
    
    // Trail pipeline
    MTLRenderPipelineDescriptor *trailPd = [[MTLRenderPipelineDescriptor alloc] init];
    trailPd.vertexFunction = [mw->library newFunctionWithName:@"trail_vertex"];
    trailPd.fragmentFunction = [mw->library newFunctionWithName:@"trail_fragment"];
    trailPd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    trailPd.colorAttachments[0].blendingEnabled = YES;
    trailPd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    trailPd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    mw->pipelines[MetalPipelineTrail] = [mw->device newRenderPipelineStateWithDescriptor:trailPd error:&error];
    
    // Samplers
    MTLSamplerDescriptor *sd = [[MTLSamplerDescriptor alloc] init];
    sd.minFilter = MTLSamplerMinMagFilterNearest;
    sd.magFilter = MTLSamplerMinMagFilterNearest;
    sd.sAddressMode = MTLSamplerAddressModeClampToEdge;
    sd.tAddressMode = MTLSamplerAddressModeClampToEdge;
    mw->nearestSampler = [mw->device newSamplerStateWithDescriptor:sd];
    
    sd.minFilter = MTLSamplerMinMagFilterLinear;
    sd.magFilter = MTLSamplerMinMagFilterLinear;
    mw->linearSampler = [mw->device newSamplerStateWithDescriptor:sd];
    
    // Repeat sampler for tiled background images
    sd.sAddressMode = MTLSamplerAddressModeRepeat;
    sd.tAddressMode = MTLSamplerAddressModeRepeat;
    mw->repeatSampler = [mw->device newSamplerStateWithDescriptor:sd];
    
    return true;
}

static bool create_buffers(MetalWindow *mw) {
    NSUInteger cellBufSize = MAX_CELLS_PER_FRAME * 6 * sizeof(CellVertex);
    NSUInteger rectBufSize = (MAX_BORDER_RECTS + 10) * 6 * sizeof(RectVertex);  // borders + cursors + selections
    NSUInteger imageBufSize = MAX_IMAGES * 6 * sizeof(ImageVertex);  // for graphics protocol images
    NSUInteger uniformSize = sizeof(FrameUniforms);
    
    for (int i = 0; i < NUM_INFLIGHT_BUFFERS; i++) {
        mw->cellBuffers[i] = [mw->device newBufferWithLength:cellBufSize
                                                    options:MTLResourceStorageModeShared];
        mw->rectBuffers[i] = [mw->device newBufferWithLength:rectBufSize
                                                    options:MTLResourceStorageModeShared];
        mw->imageBuffers[i] = [mw->device newBufferWithLength:imageBufSize
                                                     options:MTLResourceStorageModeShared];
        mw->uniformBuffers[i] = [mw->device newBufferWithLength:uniformSize
                                                       options:MTLResourceStorageModeShared];
        if (!mw->cellBuffers[i] || !mw->rectBuffers[i] || !mw->imageBuffers[i] || !mw->uniformBuffers[i]) return false;
    }
    
    mw->frameSemaphore = dispatch_semaphore_create(NUM_INFLIGHT_BUFFERS);
    return true;
}

#pragma mark - Public API

bool metal_backend_init(void) {
    if (g_device) return true;
    g_device = MTLCreateSystemDefaultDevice();
    return g_device != nil;
}

bool metal_build_pipelines(void) {
    // Pipelines are built per-window in metal_window_attach
    // This function exists for API compatibility
    return g_device != nil;
}

bool metal_init(void) {
    return metal_backend_init();
}

void metal_shutdown(void) {
    g_device = nil;
    g_library = nil;
}

bool metal_window_attach(OSWindow *w) {
    if (!w || !g_device) return false;
    if (w->metal) return true;
    
    MetalWindow *mw = calloc(1, sizeof(MetalWindow));
    if (!mw) return false;
    
    mw->device = g_device;
    mw->queue = [g_device newCommandQueue];
    if (!mw->queue) { free(mw); return false; }
    
    if (!create_pipelines(mw)) { free(mw); return false; }
    if (!create_buffers(mw)) { free(mw); return false; }
    
    // Setup CAMetalLayer
    NSWindow *nswin = glfwGetCocoaWindow(w->handle);
    NSView *view = nswin.contentView;
    
    CAMetalLayer *layer = [CAMetalLayer layer];
    layer.device = mw->device;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    layer.framebufferOnly = YES;
    layer.displaySyncEnabled = YES;
    
    CGFloat scale = nswin.backingScaleFactor;
    layer.contentsScale = scale;
    layer.drawableSize = CGSizeMake(view.bounds.size.width * scale, 
                                     view.bounds.size.height * scale);
    
    view.layer = layer;
    view.wantsLayer = YES;
    mw->layer = layer;
    
    w->metal = mw;
    return true;
}

void metal_window_resize(OSWindow *w, int width, int height, float xscale, float yscale) {
    if (!w || !w->metal) return;
    MetalWindow *mw = w->metal;
    CGFloat scale = MAX(xscale, yscale);
    if (scale < 1.0) scale = mw->layer.contentsScale;
    mw->layer.contentsScale = scale;
    mw->layer.drawableSize = CGSizeMake(width * scale, height * scale);
}

void metal_window_destroy(OSWindow *w) {
    if (!w || !w->metal) return;
    MetalWindow *mw = w->metal;
    
    // Wait for all in-flight frames
    for (int i = 0; i < NUM_INFLIGHT_BUFFERS; i++) {
        dispatch_semaphore_wait(mw->frameSemaphore, DISPATCH_TIME_FOREVER);
    }
    for (int i = 0; i < NUM_INFLIGHT_BUFFERS; i++) {
        dispatch_semaphore_signal(mw->frameSemaphore);
    }
    
    free(mw);
    w->metal = NULL;
}

#pragma mark - Sprite Textures

bool metal_realloc_sprite_texture(SpriteMap *sm, unsigned w, unsigned h, unsigned layers) {
    if (!g_device) return false;
    
    MTLTextureDescriptor *desc = [MTLTextureDescriptor new];
    desc.textureType = MTLTextureType2DArray;
    // Use RGBA format without sRGB conversion to preserve alpha values
    desc.pixelFormat = MTLPixelFormatRGBA8Unorm;
    desc.width = w;
    desc.height = h;
    desc.arrayLength = layers;
    desc.usage = MTLTextureUsageShaderRead;
    desc.storageMode = MTLStorageModeShared;
    
    id<MTLTexture> tex = [g_device newTextureWithDescriptor:desc];
    if (sm->metal_texture) {
        CFRelease(sm->metal_texture);
    }
    sm->metal_texture = (void*)CFBridgingRetain(tex);
    return tex != nil;
}

bool metal_realloc_decor_texture(SpriteMap *sm, unsigned w, unsigned h) {
    if (!g_device) return false;
    
    MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR32Uint
                                                                                    width:w height:h mipmapped:NO];
    desc.usage = MTLTextureUsageShaderRead;
    desc.storageMode = MTLStorageModeShared;
    
    id<MTLTexture> tex = [g_device newTextureWithDescriptor:desc];
    if (sm->metal_decorations_texture) {
        CFRelease(sm->metal_decorations_texture);
    }
    sm->metal_decorations_texture = (void*)CFBridgingRetain(tex);
    return tex != nil;
}

void metal_reload_textures(SpriteMap *sm UNUSED) {}

bool metal_upload_sprite(SpriteMap *sm, unsigned x, unsigned y, unsigned z, unsigned w, unsigned h, const void *data) {
    id<MTLTexture> tex = (__bridge id<MTLTexture>)sm->metal_texture;
    if (!tex) return false;
    
    MTLRegion region = MTLRegionMake3D(x, y, 0, w, h, 1);
    [tex replaceRegion:region mipmapLevel:0 slice:z withBytes:data bytesPerRow:w*4 bytesPerImage:w*h*4];
    return true;
}

bool metal_upload_decor(SpriteMap *sm, unsigned x, unsigned y, uint32_t idx) {
    id<MTLTexture> tex = (__bridge id<MTLTexture>)sm->metal_decorations_texture;
    if (!tex) return false;
    
    MTLRegion region = MTLRegionMake2D(x, y, 1, 1);
    [tex replaceRegion:region mipmapLevel:0 withBytes:&idx bytesPerRow:4];
    return true;
}

#pragma mark - Rendering

static inline simd_float4 color_to_vec4(color_type c, float a) {
    return simd_make_float4(((c >> 16) & 0xFF) / 255.0f,
                            ((c >> 8) & 0xFF) / 255.0f,
                            (c & 0xFF) / 255.0f, a);
}

// Helper to add a rectangle to the rect buffer
static inline void add_rect(RectVertex *verts, NSUInteger *count, 
                           float x0, float y0, float x1, float y1, 
                           simd_float4 color) {
    RectVertex v[6] = {
        {{x0, y1}, color},
        {{x1, y1}, color},
        {{x0, y0}, color},
        {{x0, y0}, color},
        {{x1, y1}, color},
        {{x1, y0}, color},
    };
    memcpy(verts + *count, v, sizeof(v));
    *count += 6;
}

// Convert pixel coordinates to clip space
static inline void pixel_to_clip(float px, float py, float vw, float vh, float *cx, float *cy) {
    *cx = (px / vw) * 2.0f - 1.0f;
    *cy = 1.0f - (py / vh) * 2.0f;
}

// Render a single window's cells
static NSUInteger render_window_cells(CellVertex *verts, NSUInteger vcount,
                                      Screen *screen, FONTS_DATA_HANDLE fd,
                                      float offset_x, float offset_y,
                                      float vw, float vh,
                                      color_type default_fg, color_type default_bg,
                                      float bg_alpha, bool is_active) {
    unsigned xnum, ynum, zmax;
    sprite_tracker_current_layout(fd, &xnum, &ynum, &zmax);
    
    const float cw = (float)fd->fcm.cell_width;
    const float ch = (float)fd->fcm.cell_height;
    
    // UV calculation: sprites are arranged in a grid of xnum x ynum
    // Each sprite cell is 1/xnum wide and 1/ynum tall in UV space
    // But the texture has (cell_height + 1) pixels per row to skip decoration row
    const float sprite_u_size = 1.0f / (float)xnum;
    const float sprite_v_size = 1.0f / (float)ynum;
    // The actual texture height includes the +1 padding per row
    const float texture_height_px = (float)((ch + 1) * ynum);
    const float row_height_uv = 1.0f / texture_height_px;
    
    LineBuf *lb = screen->linebuf;
    unsigned cols = screen->columns;
    unsigned lines = screen->lines;
    
    float inactive_alpha = is_active ? 1.0f : OPT(inactive_text_alpha);
    
    for (unsigned row = 0; row < lines && vcount < MAX_CELLS_PER_FRAME * 6; row++) {
        linebuf_init_line(lb, row);
        Line *line = lb->line;
        
        for (unsigned col = 0; col < cols; col++) {
            GPUCell *gc = line->gpu_cells + col;
            
            // Position in clip space
            float px = offset_x + col * cw;
            float py = offset_y + row * ch;
            float x0, y0, x1, y1;
            pixel_to_clip(px, py, vw, vh, &x0, &y0);
            pixel_to_clip(px + cw, py + ch, vw, vh, &x1, &y1);
            
            // Colors - always render background
            color_type fg = gc->fg ? gc->fg : default_fg;
            color_type bg = gc->bg ? gc->bg : default_bg;
            simd_float4 fgv = color_to_vec4(fg, inactive_alpha);
            simd_float4 bgv = color_to_vec4(bg, bg_alpha);
            
            // Sprite UV - only if we have a sprite
            float u0 = 0, v0 = 0, u1 = 0, v1 = 0;
            float sz = 0;
            float colored = 0;
            
            if (gc->sprite_idx) {
                sprite_index sidx = gc->sprite_idx & 0x7FFFFFFF;  // Remove colored flag
                // Match sprite_index_to_pos: div(idx, ynum * xnum), then div(rem, xnum)
                unsigned sprites_per_page = xnum * ynum;
                unsigned page_idx = sidx / sprites_per_page;
                unsigned idx_on_page = sidx - sprites_per_page * page_idx;
                unsigned sy = idx_on_page / xnum;
                unsigned sx = idx_on_page - xnum * sy;
                sz = (float)page_idx;
                
                // UV coordinates matching OpenGL shader logic
                u0 = (float)sx * sprite_u_size;
                u1 = (float)(sx + 1) * sprite_u_size;
                v0 = (float)sy * sprite_v_size;
                v1 = (float)(sy + 1) * sprite_v_size - row_height_uv;  // Skip decoration row
                colored = (gc->sprite_idx & 0x80000000) ? 1.0f : 0.0f;
            }
            
            // Two triangles per cell
            CellVertex v[6] = {
                {{x0, y1}, {u0, v1}, fgv, bgv, sz, colored},
                {{x1, y1}, {u1, v1}, fgv, bgv, sz, colored},
                {{x0, y0}, {u0, v0}, fgv, bgv, sz, colored},
                {{x0, y0}, {u0, v0}, fgv, bgv, sz, colored},
                {{x1, y1}, {u1, v1}, fgv, bgv, sz, colored},
                {{x1, y0}, {u1, v0}, fgv, bgv, sz, colored},
            };
            memcpy(verts + vcount, v, sizeof(v));
            vcount += 6;
        }
    }
    
    return vcount;
}

// Render cursor
static NSUInteger render_cursor(RectVertex *rects, NSUInteger rcount,
                               Screen *screen, FONTS_DATA_HANDLE fd,
                               float offset_x, float offset_y,
                               float vw, float vh,
                               color_type cursor_color, float cursor_opacity,
                               CursorShape shape, bool is_focused UNUSED) {
    if (shape == NO_CURSOR_SHAPE) return rcount;
    
    const float cw = (float)fd->fcm.cell_width;
    const float ch = (float)fd->fcm.cell_height;
    
    CursorRenderInfo *cursor = &screen->cursor_render_info;
    if (!cursor->is_visible) return rcount;
    
    float px = offset_x + cursor->x * cw;
    float py = offset_y + cursor->y * ch;
    float x0, y0, x1, y1;
    
    simd_float4 color = color_to_vec4(cursor_color, cursor_opacity);
    
    switch (shape) {
        case CURSOR_BLOCK:
            pixel_to_clip(px, py, vw, vh, &x0, &y0);
            pixel_to_clip(px + cw, py + ch, vw, vh, &x1, &y1);
            add_rect(rects, &rcount, x0, y0, x1, y1, color);
            break;
            
        case CURSOR_BEAM: {
            float beam_width = MAX(1.0f, cw / 8.0f);
            pixel_to_clip(px, py, vw, vh, &x0, &y0);
            pixel_to_clip(px + beam_width, py + ch, vw, vh, &x1, &y1);
            add_rect(rects, &rcount, x0, y0, x1, y1, color);
            break;
        }
            
        case CURSOR_UNDERLINE: {
            float underline_height = MAX(1.0f, ch / 8.0f);
            pixel_to_clip(px, py + ch - underline_height, vw, vh, &x0, &y0);
            pixel_to_clip(px + cw, py + ch, vw, vh, &x1, &y1);
            add_rect(rects, &rcount, x0, y0, x1, y1, color);
            break;
        }
            
        case CURSOR_HOLLOW: {
            // Draw 4 lines for hollow cursor
            float line_width = MAX(1.0f, cw / 16.0f);
            pixel_to_clip(px, py, vw, vh, &x0, &y0);
            pixel_to_clip(px + cw, py + ch, vw, vh, &x1, &y1);
            
            float lw_x = (line_width / vw) * 2.0f;
            float lw_y = (line_width / vh) * 2.0f;
            
            // Top
            add_rect(rects, &rcount, x0, y0, x1, y0 + lw_y, color);
            // Bottom
            add_rect(rects, &rcount, x0, y1 - lw_y, x1, y1, color);
            // Left
            add_rect(rects, &rcount, x0, y0, x0 + lw_x, y1, color);
            // Right
            add_rect(rects, &rcount, x1 - lw_x, y0, x1, y1, color);
            break;
        }
            
        default:
            break;
    }
    
    return rcount;
}

// Render selection highlighting
static NSUInteger render_selection(RectVertex *rects, NSUInteger rcount,
                                   Screen *screen, FONTS_DATA_HANDLE fd,
                                   float offset_x, float offset_y,
                                   float vw, float vh,
                                   color_type highlight_bg, float alpha) {
    if (!screen->selections.count) return rcount;
    
    const float cw = (float)fd->fcm.cell_width;
    const float ch = (float)fd->fcm.cell_height;
    
    simd_float4 color = color_to_vec4(highlight_bg, alpha * 0.5f);
    
    for (size_t i = 0; i < screen->selections.count; i++) {
        Selection *sel = screen->selections.items + i;
        // Skip empty selections
        if (sel->start.x == sel->end.x && sel->start.y == sel->end.y && 
            sel->start.in_left_half_of_cell == sel->end.in_left_half_of_cell) {
            continue;
        }
        
        // Simplified: draw selection as rectangles per line
        index_type start_y = sel->start.y < sel->end.y ? sel->start.y : sel->end.y;
        index_type end_y = sel->start.y > sel->end.y ? sel->start.y : sel->end.y;
        
        for (index_type row = start_y; row <= end_y && row < screen->lines; row++) {
            index_type start_x = 0, end_x = screen->columns;
            
            if (row == sel->start.y && row == sel->end.y) {
                start_x = sel->start.x < sel->end.x ? sel->start.x : sel->end.x;
                end_x = sel->start.x > sel->end.x ? sel->start.x : sel->end.x;
            } else if (row == start_y) {
                start_x = (sel->start.y < sel->end.y) ? sel->start.x : sel->end.x;
            } else if (row == end_y) {
                end_x = (sel->start.y < sel->end.y) ? sel->end.x : sel->start.x;
            }
            
            float px0 = offset_x + start_x * cw;
            float py0 = offset_y + row * ch;
            float px1 = offset_x + (end_x + 1) * cw;
            float py1 = py0 + ch;
            
            float x0, y0, x1, y1;
            pixel_to_clip(px0, py0, vw, vh, &x0, &y0);
            pixel_to_clip(px1, py1, vw, vh, &x1, &y1);
            add_rect(rects, &rcount, x0, y0, x1, y1, color);
        }
    }
    
    return rcount;
}

// Render URL underlines
static NSUInteger render_url_underlines(RectVertex *rects, NSUInteger rcount,
                                        Screen *screen, FONTS_DATA_HANDLE fd,
                                        float offset_x, float offset_y,
                                        float vw, float vh,
                                        color_type url_color) {
    if (!screen->url_ranges.count) return rcount;
    
    const float cw = (float)fd->fcm.cell_width;
    const float ch = (float)fd->fcm.cell_height;
    const float underline_height = MAX(1.0f, ch / 16.0f);
    
    simd_float4 color = color_to_vec4(url_color, 1.0f);
    
    for (size_t i = 0; i < screen->url_ranges.count; i++) {
        Selection *sel = screen->url_ranges.items + i;
        
        // Draw underline for each line in the URL range
        index_type start_y = sel->start.y < sel->end.y ? sel->start.y : sel->end.y;
        index_type end_y = sel->start.y > sel->end.y ? sel->start.y : sel->end.y;
        
        for (index_type row = start_y; row <= end_y && row < screen->lines; row++) {
            index_type start_x = 0, end_x = screen->columns;
            
            if (row == sel->start.y && row == sel->end.y) {
                start_x = sel->start.x < sel->end.x ? sel->start.x : sel->end.x;
                end_x = sel->start.x > sel->end.x ? sel->start.x : sel->end.x;
            } else if (row == start_y) {
                start_x = (sel->start.y < sel->end.y) ? sel->start.x : sel->end.x;
            } else if (row == end_y) {
                end_x = (sel->start.y < sel->end.y) ? sel->end.x : sel->start.x;
            }
            
            // Draw underline at bottom of cell
            float px0 = offset_x + start_x * cw;
            float py0 = offset_y + (row + 1) * ch - underline_height;
            float px1 = offset_x + (end_x + 1) * cw;
            float py1 = offset_y + (row + 1) * ch;
            
            float x0, y0, x1, y1;
            pixel_to_clip(px0, py0, vw, vh, &x0, &y0);
            pixel_to_clip(px1, py1, vw, vh, &x1, &y1);
            add_rect(rects, &rcount, x0, y0, x1, y1, color);
        }
    }
    
    return rcount;
}

// Check if window should show scrollbar
static bool has_scrollbar(Window *window, Screen *screen) {
    if (!screen || !screen->historybuf || screen->historybuf->count == 0) return false;
    
    switch (OPT(scrollbar)) {
        case SCROLLBAR_NEVER: return false;
        case SCROLLBAR_ALWAYS: return true;
        case SCROLLBAR_ON_SCROLLED: return screen->scrolled_by > 0;
        case SCROLLBAR_ON_HOVERED: return window->scrollbar.is_hovering;
        case SCROLLBAR_ON_SCROLL_AND_HOVER: 
            return screen->scrolled_by > 0 || window->scrollbar.is_hovering;
        default: return false;
    }
}

// Render scrollbar for a window
static NSUInteger render_scrollbar(RectVertex *rects, NSUInteger rcount,
                                   Window *window, Screen *screen,
                                   FONTS_DATA_HANDLE fd,
                                   float offset_x, float offset_y,
                                   float win_width, float win_height,
                                   float vw, float vh) {
    if (!has_scrollbar(window, screen)) return rcount;
    
    const float cw = (float)fd->fcm.cell_width;
    const float ch = (float)fd->fcm.cell_height;
    
    // Scrollbar dimensions
    float scrollbar_width = OPT(scrollbar_width) * cw;
    if (window->scrollbar.is_hovering) {
        scrollbar_width = OPT(scrollbar_hover_width) * cw;
    }
    float scrollbar_gap = OPT(scrollbar_gap) * cw;
    
    // Calculate scrollbar position
    float scrollbar_left = offset_x + win_width - scrollbar_width - scrollbar_gap;
    float scrollbar_top = offset_y + scrollbar_gap;
    float scrollbar_height = win_height - 2 * scrollbar_gap;
    
    // Calculate thumb size and position
    float visible_fraction = (float)screen->lines / (float)(screen->lines + screen->historybuf->count);
    float min_thumb_height = OPT(scrollbar_min_handle_height) * ch;
    float thumb_height = MAX(min_thumb_height, visible_fraction * scrollbar_height);
    
    float bar_frac = (float)screen->scrolled_by / MAX(1u, (float)screen->historybuf->count);
    float available_space = scrollbar_height - thumb_height;
    float thumb_top = scrollbar_top + available_space * bar_frac;
    
    // Store thumb position for mouse interaction
    window->scrollbar.thumb_top = thumb_top / vh;
    window->scrollbar.thumb_bottom = (thumb_top + thumb_height) / vh;
    
    // Draw track (background)
    float track_opacity = window->scrollbar.is_hovering ? 
                          OPT(scrollbar_track_hover_opacity) : OPT(scrollbar_track_opacity);
    if (track_opacity > 0) {
        color_type track_color = OPT(scrollbar_track_color) >> 8;
        simd_float4 track_col = color_to_vec4(track_color, track_opacity);
        
        float x0, y0, x1, y1;
        pixel_to_clip(scrollbar_left, scrollbar_top, vw, vh, &x0, &y0);
        pixel_to_clip(scrollbar_left + scrollbar_width, scrollbar_top + scrollbar_height, vw, vh, &x1, &y1);
        add_rect(rects, &rcount, x0, y0, x1, y1, track_col);
    }
    
    // Draw thumb (handle)
    float handle_opacity = OPT(scrollbar_handle_opacity);
    color_type handle_color = OPT(scrollbar_handle_color) >> 8;
    simd_float4 handle_col = color_to_vec4(handle_color, handle_opacity);
    
    float x0, y0, x1, y1;
    pixel_to_clip(scrollbar_left, thumb_top, vw, vh, &x0, &y0);
    pixel_to_clip(scrollbar_left + scrollbar_width, thumb_top + thumb_height, vw, vh, &x1, &y1);
    add_rect(rects, &rcount, x0, y0, x1, y1, handle_col);
    
    return rcount;
}

// Render cursor trail effect
static NSUInteger render_cursor_trail(RectVertex *rects, NSUInteger rcount,
                                      Tab *tab, Screen *screen,
                                      float vw UNUSED, float vh UNUSED) {
    CursorTrail *ct = &tab->cursor_trail;
    
    if (!ct->needs_render || ct->opacity <= 0.0f) return rcount;
    if (!OPT(cursor_trail)) return rcount;
    
    // Get cursor trail color
    color_type trail_color = OPT(cursor_trail_color);
    if (!trail_color) {
        // Use last rendered cursor color
        trail_color = screen->last_rendered.cursor_bg;
    }
    
    simd_float4 color = color_to_vec4(trail_color, ct->opacity);
    
    // The cursor trail is a quad defined by corner_x[4] and corner_y[4]
    // These are already in NDC coordinates (-1 to 1)
    // Draw as two triangles
    RectVertex v[6] = {
        {{ct->corner_x[0], ct->corner_y[0]}, color},
        {{ct->corner_x[1], ct->corner_y[1]}, color},
        {{ct->corner_x[2], ct->corner_y[2]}, color},
        {{ct->corner_x[2], ct->corner_y[2]}, color},
        {{ct->corner_x[3], ct->corner_y[3]}, color},
        {{ct->corner_x[0], ct->corner_y[0]}, color},
    };
    memcpy(rects + rcount, v, sizeof(v));
    rcount += 6;
    
    return rcount;
}

void metal_present_blank(OSWindow *w, float alpha, color_type bg) {
    if (!w || !w->metal) return;
    MetalWindow *mw = w->metal;
    
    id<CAMetalDrawable> drawable = [mw->layer nextDrawable];
    if (!drawable) return;
    
    MTLRenderPassDescriptor *rpd = [MTLRenderPassDescriptor new];
    rpd.colorAttachments[0].texture = drawable.texture;
    rpd.colorAttachments[0].loadAction = MTLLoadActionClear;
    rpd.colorAttachments[0].storeAction = MTLStoreActionStore;
    rpd.colorAttachments[0].clearColor = MTLClearColorMake(
        ((bg >> 16) & 0xFF) / 255.0, ((bg >> 8) & 0xFF) / 255.0,
        (bg & 0xFF) / 255.0, alpha);
    
    id<MTLCommandBuffer> cb = [mw->queue commandBuffer];
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rpd];
    [enc endEncoding];
    [cb presentDrawable:drawable];
    [cb commit];
}

// Render borders for a tab
static NSUInteger render_borders(RectVertex *rects, NSUInteger rcount,
                                BorderRects *br, float vw, float vh,
                                color_type active_bg) {
    if (!br || br->num_border_rects == 0) return rcount;
    
    for (unsigned i = 0; i < br->num_border_rects && rcount < (MAX_BORDER_RECTS * 6); i++) {
        BorderRect *rect = br->rect_buf + i;
        
        float x0, y0, x1, y1;
        pixel_to_clip(rect->left, rect->top, vw, vh, &x0, &y0);
        pixel_to_clip(rect->right, rect->bottom, vw, vh, &x1, &y1);
        
        simd_float4 color = color_to_vec4(rect->color ? rect->color : active_bg, 1.0f);
        add_rect(rects, &rcount, x0, y0, x1, y1, color);
    }
    
    return rcount;
}

// Draw background image
static void draw_background_image(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                                  OSWindow *w, float bg_alpha, color_type bg_color) {
    if (!w->bgimage || !w->bgimage->texture_id) return;
    
    id<MTLTexture> bgTex = metal_get_graphics_texture(w->bgimage->texture_id);
    if (!bgTex) return;
    
    BgImageParams params;
    params.tiled = (OPT(background_image_layout) == 1) ? 1.0f : 0.0f;  // TILED layout
    params.sizes = simd_make_float4(w->viewport_width, w->viewport_height, 
                                    bgTex.width, bgTex.height);
    params.positions = simd_make_float4(-1.0f, 1.0f, 1.0f, -1.0f);  // Full screen
    params.background = simd_make_float4(
        ((bg_color >> 16) & 0xFF) / 255.0f * bg_alpha,
        ((bg_color >> 8) & 0xFF) / 255.0f * bg_alpha,
        (bg_color & 0xFF) / 255.0f * bg_alpha,
        bg_alpha);
    
    id<MTLBuffer> paramBuf = [mw->device newBufferWithBytes:&params 
                                                    length:sizeof(params)
                                                   options:MTLResourceStorageModeShared];
    
    [enc setRenderPipelineState:mw->pipelines[MetalPipelineBgImage]];
    [enc setVertexBuffer:paramBuf offset:0 atIndex:0];
    [enc setFragmentBuffer:paramBuf offset:0 atIndex:0];
    [enc setFragmentTexture:bgTex atIndex:0];
    [enc setFragmentSamplerState:params.tiled > 0.5f ? mw->repeatSampler : mw->linearSampler atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
}

// Draw graphics protocol images for a window
static void draw_graphics_images(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                                 Window *win, float vw, float vh, float alpha) {
    if (!win || !win->render_data.screen) return;
    Screen *screen = win->render_data.screen;
    if (!screen->grman) return;
    
    GraphicsRenderData grd = grman_render_data(screen->grman);
    if (grd.count == 0) return;
    
    WindowGeometry *geom = &win->render_data.geometry;
    float offset_x = (float)geom->left;
    float offset_y = (float)geom->top;
    
    for (size_t i = 0; i < grd.count; i++) {
        ImageRenderData *img = &grd.images[i];
        
        // Get the Metal texture for this image
        id<MTLTexture> tex = metal_get_graphics_texture(img->texture_id);
        if (!tex) continue;
        
        // Calculate source rect (texture coordinates)
        GraphicsParams params;
        params.src_rect = simd_make_float4(
            img->src_rect.left,
            img->src_rect.top,
            img->src_rect.right,
            img->src_rect.bottom
        );
        
        // Calculate destination rect (clip space coordinates)
        // The dest_rect from ImageRenderData is already in clip space (-1 to 1)
        params.dest_rect = simd_make_float4(
            img->dest_rect.left,
            img->dest_rect.top,
            img->dest_rect.right,
            img->dest_rect.bottom
        );
        
        params.extra_alpha = alpha;
        
        id<MTLBuffer> paramBuf = [mw->device newBufferWithBytes:&params 
                                                        length:sizeof(params)
                                                       options:MTLResourceStorageModeShared];
        
        // Choose pipeline based on whether image is premultiplied
        // Most images from the graphics protocol are premultiplied
        [enc setRenderPipelineState:mw->pipelines[MetalPipelineGraphicsPremult]];
        [enc setVertexBuffer:paramBuf offset:0 atIndex:0];
        [enc setFragmentBytes:&params.extra_alpha length:sizeof(float) atIndex:0];
        [enc setFragmentTexture:tex atIndex:0];
        [enc setFragmentSamplerState:mw->linearSampler atIndex:0];
        [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
    }
    
    (void)vw; (void)vh; (void)offset_x; (void)offset_y;
}

// Draw a single graphics image with specified parameters
__attribute__((unused))
static void draw_single_image(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                              id<MTLTexture> tex,
                              float src_left, float src_top, float src_right, float src_bottom,
                              float dst_left, float dst_top, float dst_right, float dst_bottom,
                              float extra_alpha, bool is_premultiplied) {
    GraphicsParams params;
    params.src_rect = simd_make_float4(src_left, src_top, src_right, src_bottom);
    params.dest_rect = simd_make_float4(dst_left, dst_top, dst_right, dst_bottom);
    params.extra_alpha = extra_alpha;
    
    id<MTLBuffer> paramBuf = [mw->device newBufferWithBytes:&params 
                                                    length:sizeof(params)
                                                   options:MTLResourceStorageModeShared];
    
    MetalPipeline pipeline = is_premultiplied ? MetalPipelineGraphicsPremult : MetalPipelineGraphics;
    [enc setRenderPipelineState:mw->pipelines[pipeline]];
    [enc setVertexBuffer:paramBuf offset:0 atIndex:0];
    [enc setFragmentBytes:&extra_alpha length:sizeof(float) atIndex:0];
    [enc setFragmentTexture:tex atIndex:0];
    [enc setFragmentSamplerState:mw->linearSampler atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
}

// Draw a rounded rectangle border
__attribute__((unused))
static void draw_rounded_rect(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                              float x, float y, float width, float height,
                              float thickness, float radius,
                              color_type color, float alpha,
                              color_type bg_color, float bg_alpha) {
    RoundedRectParams params;
    params.rect = simd_make_float4(x, y, width, height);
    params.params = simd_make_float2(thickness, radius);
    params.color = simd_make_float4(
        ((color >> 16) & 0xFF) / 255.0f,
        ((color >> 8) & 0xFF) / 255.0f,
        (color & 0xFF) / 255.0f,
        alpha);
    params.background_color = simd_make_float4(
        ((bg_color >> 16) & 0xFF) / 255.0f * bg_alpha,
        ((bg_color >> 8) & 0xFF) / 255.0f * bg_alpha,
        (bg_color & 0xFF) / 255.0f * bg_alpha,
        bg_alpha);
    
    id<MTLBuffer> paramBuf = [mw->device newBufferWithBytes:&params 
                                                    length:sizeof(params)
                                                   options:MTLResourceStorageModeShared];
    
    [enc setRenderPipelineState:mw->pipelines[MetalPipelineRoundedRect]];
    [enc setFragmentBuffer:paramBuf offset:0 atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
}

// Draw visual bell flash
static void draw_visual_bell(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                             Screen *screen, float intensity, color_type flash_color) {
    if (intensity <= 0) return;
    
    // Calculate attenuated color
    float attenuation = 0.4f;
    float r = ((flash_color >> 16) & 0xFF) / 255.0f;
    float g = ((flash_color >> 8) & 0xFF) / 255.0f;
    float b = (flash_color & 0xFF) / 255.0f;
    float max_channel = fmax(r, fmax(g, b));
    if (max_channel > 0) {
        float scale = attenuation / max_channel;
        r *= scale; g *= scale; b *= scale;
    }
    
    simd_float4 tint = simd_make_float4(r * intensity, g * intensity, b * intensity, intensity);
    
    id<MTLBuffer> colorBuf = [mw->device newBufferWithBytes:&tint 
                                                    length:sizeof(tint)
                                                   options:MTLResourceStorageModeShared];
    simd_float4 edges = simd_make_float4(-1, 1, 1, -1);
    id<MTLBuffer> edgesBuf = [mw->device newBufferWithBytes:&edges 
                                                    length:sizeof(edges)
                                                   options:MTLResourceStorageModeShared];
    
    [enc setRenderPipelineState:mw->pipelines[MetalPipelineTint]];
    [enc setVertexBuffer:edgesBuf offset:0 atIndex:0];
    [enc setFragmentBuffer:colorBuf offset:0 atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
    
    (void)screen;  // May be used for window-specific bell in future
}

// Draw tint overlay (for background tint)
static void draw_tint_overlay(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                              float tint_amount, color_type tint_color) {
    if (tint_amount <= 0) return;
    
    simd_float4 tint = simd_make_float4(
        ((tint_color >> 16) & 0xFF) / 255.0f * tint_amount,
        ((tint_color >> 8) & 0xFF) / 255.0f * tint_amount,
        (tint_color & 0xFF) / 255.0f * tint_amount,
        tint_amount);
    
    id<MTLBuffer> colorBuf = [mw->device newBufferWithBytes:&tint 
                                                    length:sizeof(tint)
                                                   options:MTLResourceStorageModeShared];
    simd_float4 edges = simd_make_float4(-1, 1, 1, -1);
    id<MTLBuffer> edgesBuf = [mw->device newBufferWithBytes:&edges 
                                                    length:sizeof(edges)
                                                   options:MTLResourceStorageModeShared];
    
    [enc setRenderPipelineState:mw->pipelines[MetalPipelineTint]];
    [enc setVertexBuffer:edgesBuf offset:0 atIndex:0];
    [enc setFragmentBuffer:colorBuf offset:0 atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
}

// Draw an alpha-masked image (for text overlays like resize text)
__attribute__((unused))
static void draw_alpha_mask_image(id<MTLRenderCommandEncoder> enc, MetalWindow *mw,
                                  id<MTLTexture> tex, float x, float y, float w, float h,
                                  float vw, float vh,
                                  color_type fg_color, color_type bg_color, float bg_alpha) {
    GraphicsParams gparams;
    gparams.src_rect = simd_make_float4(0, 0, 1, 1);
    
    float x0, y0, x1, y1;
    pixel_to_clip(x, y, vw, vh, &x0, &y0);
    pixel_to_clip(x + w, y + h, vw, vh, &x1, &y1);
    gparams.dest_rect = simd_make_float4(x0, y0, x1, y1);
    gparams.extra_alpha = 1.0f;
    
    AlphaMaskParams amparams;
    amparams.fg_color = simd_make_float3(
        ((fg_color >> 16) & 0xFF) / 255.0f,
        ((fg_color >> 8) & 0xFF) / 255.0f,
        (fg_color & 0xFF) / 255.0f);
    amparams.bg_premult = simd_make_float4(
        ((bg_color >> 16) & 0xFF) / 255.0f * bg_alpha,
        ((bg_color >> 8) & 0xFF) / 255.0f * bg_alpha,
        (bg_color & 0xFF) / 255.0f * bg_alpha,
        bg_alpha);
    
    id<MTLBuffer> gparamBuf = [mw->device newBufferWithBytes:&gparams 
                                                     length:sizeof(gparams)
                                                    options:MTLResourceStorageModeShared];
    id<MTLBuffer> amparamBuf = [mw->device newBufferWithBytes:&amparams 
                                                      length:sizeof(amparams)
                                                     options:MTLResourceStorageModeShared];
    
    [enc setRenderPipelineState:mw->pipelines[MetalPipelineGraphicsAlphaMask]];
    [enc setVertexBuffer:gparamBuf offset:0 atIndex:0];
    [enc setFragmentBuffer:amparamBuf offset:0 atIndex:0];
    [enc setFragmentTexture:tex atIndex:0];
    [enc setFragmentSamplerState:mw->linearSampler atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
}

bool metal_render_os_window(OSWindow *w, monotonic_t now UNUSED, bool scan UNUSED) {
    if (!w || !w->metal || !w->num_tabs) return false;
    MetalWindow *mw = w->metal;
    
    Tab *tab = w->tabs + w->active_tab;
    if (!tab) return false;
    
    FONTS_DATA_HANDLE fd = w->fonts_data;
    if (!fd) return false;
    
    // Wait for buffer availability (triple buffering)
    dispatch_semaphore_wait(mw->frameSemaphore, DISPATCH_TIME_FOREVER);
    
    id<CAMetalDrawable> drawable = [mw->layer nextDrawable];
    if (!drawable) {
        dispatch_semaphore_signal(mw->frameSemaphore);
        return false;
    }
    
    NSUInteger bufIdx = mw->currentBuffer;
    mw->currentBuffer = (mw->currentBuffer + 1) % NUM_INFLIGHT_BUFFERS;
    
    // Update sprite texture reference
    SpriteMap *sm = (SpriteMap*)fd->sprite_map;
    if (sm && sm->metal_texture) {
        mw->spriteTexture = (__bridge id<MTLTexture>)sm->metal_texture;
    }
    
    const float vw = (float)w->viewport_width;
    const float vh = (float)w->viewport_height;
    
    // Get default colors from first window's screen
    color_type default_bg = 0x000000;
    float bg_alpha = OPT(background_opacity);
    
    if (tab->num_windows > 0) {
        Window *first_win = tab->windows;
        if (first_win && first_win->render_data.screen) {
            ColorProfile *cp = first_win->render_data.screen->color_profile;
            default_bg = colorprofile_to_color(cp, cp->overridden.default_bg, cp->configured.default_bg).rgb;
        }
    }
    
    // Build cell vertices
    CellVertex *cellVerts = mw->cellBuffers[bufIdx].contents;
    NSUInteger cellCount = 0;
    
    // Build rect vertices (cursors, selections, borders)
    RectVertex *rectVerts = mw->rectBuffers[bufIdx].contents;
    NSUInteger rectCount = 0;
    
    // Render borders first
    rectCount = render_borders(rectVerts, rectCount, &tab->border_rects, vw, vh, default_bg);
    
    // Render each visible window
    for (unsigned i = 0; i < tab->num_windows; i++) {
        Window *win = tab->windows + i;
        if (!win->visible) continue;
        
        Screen *screen = win->render_data.screen;
        if (!screen) continue;
        
        // Trigger font rendering for dirty lines (sets sprite_idx in GPUCells)
        // Pass NULL address to skip the memcpy to GPU buffer (Metal reads directly from linebuf)
        if (screen->is_dirty || screen->reload_all_gpu_data) {
            screen_update_cell_data(screen, NULL, fd, false);
        }
        
        WindowGeometry *geom = &win->render_data.geometry;
        float offset_x = (float)geom->left;
        float offset_y = (float)geom->top;
        
        bool is_active = (i == tab->active_window);
        
        // Get window-specific colors
        ColorProfile *cp = screen->color_profile;
        color_type win_fg = colorprofile_to_color(cp, cp->overridden.default_fg, cp->configured.default_fg).rgb;
        color_type win_bg = colorprofile_to_color(cp, cp->overridden.default_bg, cp->configured.default_bg).rgb;
        color_type win_cursor = colorprofile_to_color(cp, cp->overridden.cursor_color, cp->configured.cursor_color).rgb;
        color_type win_highlight = colorprofile_to_color(cp, cp->overridden.highlight_bg, cp->configured.highlight_bg).rgb;
        
        // Render cells
        cellCount = render_window_cells(cellVerts, cellCount, screen, fd,
                                        offset_x, offset_y, vw, vh,
                                        win_fg, win_bg, bg_alpha, is_active);
        
        // Render selection
        rectCount = render_selection(rectVerts, rectCount, screen, fd,
                                    offset_x, offset_y, vw, vh,
                                    win_highlight, bg_alpha);
        
        // Render URL underlines
        rectCount = render_url_underlines(rectVerts, rectCount, screen, fd,
                                         offset_x, offset_y, vw, vh,
                                         OPT(url_color));
        
        // Render cursor
        if (is_active || screen->cursor_render_info.render_even_when_unfocused) {
            CursorShape shape = screen->cursor_render_info.shape;
            if (!screen->cursor_render_info.is_focused && OPT(cursor_shape_unfocused) != NO_CURSOR_SHAPE) {
                shape = OPT(cursor_shape_unfocused);
            }
            float cursor_opacity = screen->cursor_render_info.cursor_opacity;
            rectCount = render_cursor(rectVerts, rectCount, screen, fd,
                                     offset_x, offset_y, vw, vh,
                                     win_cursor, cursor_opacity, shape,
                                     screen->cursor_render_info.is_focused);
        }
        
        // Render scrollbar
        float win_width = (float)(geom->right - geom->left);
        float win_height = (float)(geom->bottom - geom->top);
        rectCount = render_scrollbar(rectVerts, rectCount, win, screen, fd,
                                    offset_x, offset_y, win_width, win_height,
                                    vw, vh);
        
        // Render cursor trail (only for active window)
        if (is_active) {
            rectCount = render_cursor_trail(rectVerts, rectCount, tab, screen, vw, vh);
        }
    }
    
    // Render tab bar if present
    if (w->tab_bar_render_data.screen && w->num_tabs > 1) {
        Screen *tb_screen = w->tab_bar_render_data.screen;
        WindowGeometry *tb_geom = &w->tab_bar_render_data.geometry;
        
        ColorProfile *cp = tb_screen->color_profile;
        color_type tb_fg = colorprofile_to_color(cp, cp->overridden.default_fg, cp->configured.default_fg).rgb;
        color_type tb_bg = colorprofile_to_color(cp, cp->overridden.default_bg, cp->configured.default_bg).rgb;
        
        cellCount = render_window_cells(cellVerts, cellCount, tb_screen, fd,
                                        (float)tb_geom->left, (float)tb_geom->top,
                                        vw, vh, tb_fg, tb_bg, 1.0f, true);
    }
    
    mw->cellCount = cellCount;
    mw->rectCount = rectCount;
    
    // Create render pass
    MTLRenderPassDescriptor *rpd = [MTLRenderPassDescriptor new];
    rpd.colorAttachments[0].texture = drawable.texture;
    rpd.colorAttachments[0].loadAction = MTLLoadActionClear;
    rpd.colorAttachments[0].storeAction = MTLStoreActionStore;
    rpd.colorAttachments[0].clearColor = MTLClearColorMake(
        ((default_bg >> 16) & 0xFF) / 255.0 * bg_alpha,
        ((default_bg >> 8) & 0xFF) / 255.0 * bg_alpha,
        (default_bg & 0xFF) / 255.0 * bg_alpha, bg_alpha);
    
    id<MTLCommandBuffer> cb = [mw->queue commandBuffer];
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rpd];
    
    // Draw background image if present
    if (w->bgimage && w->bgimage->texture_id) {
        draw_background_image(enc, mw, w, bg_alpha, default_bg);
    }
    
    // Draw background tint if enabled
    if (w->bgimage && OPT(background_tint) > 0) {
        draw_tint_overlay(enc, mw, OPT(background_tint), default_bg);
    }
    
    // Draw cell backgrounds
    if (cellCount > 0) {
        [enc setRenderPipelineState:mw->pipelines[MetalPipelineCellBG]];
        [enc setVertexBuffer:mw->cellBuffers[bufIdx] offset:0 atIndex:0];
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:cellCount];
    }
    
    // Draw graphics protocol images (below text, z_index < 0)
    for (unsigned i = 0; i < tab->num_windows; i++) {
        Window *win = tab->windows + i;
        if (!win->visible) continue;
        draw_graphics_images(enc, mw, win, vw, vh, 1.0f);
    }
    
    // Draw selections (behind text)
    if (rectCount > 0) {
        [enc setRenderPipelineState:mw->pipelines[MetalPipelineSelection]];
        [enc setVertexBuffer:mw->rectBuffers[bufIdx] offset:0 atIndex:0];
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:rectCount];
    }
    
    // Draw cell foreground (text) with contrast adjustment
    if (cellCount > 0 && mw->spriteTexture) {
        [enc setRenderPipelineState:mw->pipelines[MetalPipelineCell]];
        [enc setVertexBuffer:mw->cellBuffers[bufIdx] offset:0 atIndex:0];
        [enc setFragmentTexture:mw->spriteTexture atIndex:0];
        [enc setFragmentSamplerState:mw->nearestSampler atIndex:0];
        
        // Set text contrast parameters
        simd_float2 contrast_params = simd_make_float2(OPT(text_contrast), OPT(text_gamma_adjustment));
        id<MTLBuffer> contrastBuf = [mw->device newBufferWithBytes:&contrast_params 
                                                           length:sizeof(contrast_params)
                                                          options:MTLResourceStorageModeShared];
        [enc setFragmentBuffer:contrastBuf offset:0 atIndex:0];
        
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:cellCount];
    }
    
    // Visual bell for each window
    for (unsigned i = 0; i < tab->num_windows; i++) {
        Window *win = tab->windows + i;
        if (!win->visible || !win->render_data.screen) continue;
        Screen *screen = win->render_data.screen;
        
        if (screen->start_visual_bell_at) {
            monotonic_t bell_time = monotonic() - screen->start_visual_bell_at;
            if (bell_time < OPT(visual_bell_duration)) {
                float intensity = 1.0f - (float)bell_time / (float)OPT(visual_bell_duration);
                
                // Get visual bell color
                ColorProfile *cp = screen->color_profile;
                color_type flash_color = colorprofile_to_color(cp, 
                    cp->overridden.visual_bell_color, cp->configured.visual_bell_color).rgb;
                if (!flash_color) {
                    flash_color = colorprofile_to_color(cp, 
                        cp->overridden.highlight_bg, cp->configured.highlight_bg).rgb;
                }
                if (!flash_color) {
                    flash_color = colorprofile_to_color(cp, 
                        cp->overridden.default_fg, cp->configured.default_fg).rgb;
                }
                
                draw_visual_bell(enc, mw, screen, intensity, flash_color);
            } else {
                screen->start_visual_bell_at = 0;
            }
        }
    }
    
    [enc endEncoding];
    
    // Signal semaphore when GPU is done
    __block dispatch_semaphore_t sem = mw->frameSemaphore;
    [cb addCompletedHandler:^(id<MTLCommandBuffer> _Nonnull buffer UNUSED) {
        dispatch_semaphore_signal(sem);
    }];
    
    [cb presentDrawable:drawable];
    [cb commit];
    
    return true;
}

#pragma mark - Image/Graphics Protocol Support

// Simple texture storage for graphics protocol
#define MAX_GRAPHICS_TEXTURES 1024

typedef struct {
    id<MTLTexture> texture;
    uint32_t width, height;
    bool in_use;
} GraphicsTexture;

static GraphicsTexture g_graphics_textures[MAX_GRAPHICS_TEXTURES];
static uint32_t g_next_texture_slot = 1;  // 0 is reserved for "no texture"

uint32_t metal_image_alloc(void) {
    if (!g_device) return 0;
    
    // Find a free slot
    for (uint32_t i = 1; i < MAX_GRAPHICS_TEXTURES; i++) {
        uint32_t slot = (g_next_texture_slot + i - 1) % MAX_GRAPHICS_TEXTURES;
        if (slot == 0) slot = 1;  // Skip slot 0
        if (!g_graphics_textures[slot].in_use) {
            g_graphics_textures[slot].in_use = true;
            g_graphics_textures[slot].texture = nil;
            g_next_texture_slot = slot + 1;
            return slot;
        }
    }
    return 0;  // No free slots
}

void metal_image_upload(uint32_t texture_id, const void *data, int width, int height,
                        bool is_opaque UNUSED, bool is_4byte_aligned UNUSED, 
                        bool linear UNUSED, int repeat_strategy UNUSED) {
    if (!g_device || texture_id == 0 || texture_id >= MAX_GRAPHICS_TEXTURES) return;
    if (!g_graphics_textures[texture_id].in_use) return;
    
    GraphicsTexture *gt = &g_graphics_textures[texture_id];
    
    // Create or recreate texture if size changed
    if (!gt->texture || gt->width != (uint32_t)width || gt->height != (uint32_t)height) {
        MTLTextureDescriptor *desc = [MTLTextureDescriptor 
            texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
            width:width height:height mipmapped:NO];
        desc.usage = MTLTextureUsageShaderRead;
        desc.storageMode = MTLStorageModeShared;
        
        gt->texture = [g_device newTextureWithDescriptor:desc];
        gt->width = width;
        gt->height = height;
    }
    
    if (gt->texture && data) {
        MTLRegion region = MTLRegionMake2D(0, 0, width, height);
        [gt->texture replaceRegion:region mipmapLevel:0 withBytes:data bytesPerRow:width * 4];
    }
}

void metal_image_free(uint32_t texture_id) {
    if (texture_id == 0 || texture_id >= MAX_GRAPHICS_TEXTURES) return;
    
    GraphicsTexture *gt = &g_graphics_textures[texture_id];
    gt->texture = nil;
    gt->width = 0;
    gt->height = 0;
    gt->in_use = false;
}

// Get Metal texture for a graphics texture ID
id<MTLTexture> metal_get_graphics_texture(uint32_t texture_id) {
    if (texture_id == 0 || texture_id >= MAX_GRAPHICS_TEXTURES) return nil;
    if (!g_graphics_textures[texture_id].in_use) return nil;
    return g_graphics_textures[texture_id].texture;
}

#endif // __APPLE__
