/*
 * internal.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Types and functions shared between the files of the Metal driver.
//
// Overview of how the driver implements the immediate mode API in ../api.h,
// it follows the design of the Vulkan driver, simplified by the things Metal
// does automatically:
//
// * Commands are encoded into the current command buffer, created when first
//   needed. It is committed when a surface is presented, or when the CPU
//   needs the results, such as when reading back pixels. At most
//   NUM_IN_FLIGHT command buffers are in flight, creating a new one waits
//   for the oldest to complete, which throttles the CPU.
// * Every command buffer has a serial number, the completed handler of the
//   command buffer records when it has completed. It runs on a thread owned
//   by Metal, so it only touches atomics and the in flight semaphore.
// * Command buffers retain the resources used by the commands encoded into
//   them, so objects can be released as soon as kitty destroys them. Metal
//   also tracks hazards between passes automatically, so no barriers are
//   needed.
// * Rendering into the current render target is done with a render command
//   encoder, begun lazily by the first draw or clear and ended when the
//   render target changes or a blit is needed, such as for uploading pixels
//   to a texture. Render passes always load and store the contents of the
//   render target, except for clears of the whole render target, which use
//   a clear load action.
// * Buffers live in shared memory and are only ever written by the CPU.
//   Writing to a buffer that encoded commands might still read gives it new
//   storage, so that, as with OpenGL, commands use the contents the buffer
//   had when they were encoded. Textures are private to the GPU and pixels
//   are uploaded with blits from staging memory, so uploads are ordered with
//   respect to draws, as in OpenGL.
// * Textures are bound with set{Vertex,Fragment}Texture() and
//   set{Vertex,Fragment}SamplerState(), uniform buffers with
//   set{Vertex,Fragment}Buffer() and the push constant block of pipelines
//   with set{Vertex,Fragment}Bytes(), at the argument table indices
//   assigned by the shader compiler, which are passed to the driver as native
//   names, see MSL_PUSH_CONSTANTS_NAME in kitty/shaders/slang.py.
// * Vertex inputs each use a buffer of their own, at the highest buffer
//   argument table indices, see VERTEX_BUFFER_INDEX.
//
// The code uses manual reference counting, not ARC, like the rest of the
// Objective-C code in kitty. Objects that are kept are owned by the driver,
// either because they were obtained from methods whose names begin with
// new/alloc/copy, or because they were retained. Every API function that can
// create autoreleased objects drains an autorelease pool, as kitty's render
// loop is not guaranteed to run inside one.

#pragma once

#define _GNU_SOURCE // for strdup() with glibc, has no effect on Darwin
#include "../api.h"
#import <Cocoa/Cocoa.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define UNUSED __attribute__((unused))
#define arraysz(x) (sizeof(x) / sizeof(x[0]))
#ifndef MIN
#define MIN(x, y) ((x) < (y) ? (x) : (y))
#endif
#ifndef MAX
#define MAX(x, y) ((x) > (y) ? (x) : (y))
#endif
#define AS_HANDLE(ptr) ((uint64_t)(uintptr_t)(ptr))

// The maximum number of command buffers submitted to the GPU and not yet completed
#define NUM_IN_FLIGHT 3
// The maximum number of binding slots of textures and uniform buffers, the
// slots used by kitty are much smaller than this
#define MAX_BINDING_SLOTS 32
// The maximum number of vertex inputs
#define MAX_VERTEX_ATTRIBUTES 16
// The maximum size of the push constant block, see GPUParamBlock
#define PUSH_CONSTANTS_SIZE 128
// Metal has 31 entries in the buffer argument table of each stage. Vertex
// buffers use the highest of them, one per vertex input location, the buffers
// used by shaders must have indices below MAX_SHADER_BUFFER_INDEX.
#define NUM_BUFFER_INDICES 31
#define VERTEX_BUFFER_INDEX(location) (NUM_BUFFER_INDICES - 1 - (location))
#define MAX_SHADER_BUFFER_INDEX (NUM_BUFFER_INDICES - MAX_VERTEX_ATTRIBUTES)
// The maximum number of texture and sampler argument table entries used by shaders
#define MAX_SHADER_TEXTURE_INDEX 31
#define MAX_SHADER_SAMPLER_INDEX 16
// The native name of the push constant block, must match MSL_PUSH_CONSTANTS_NAME in kitty/shaders/slang.py
#define MSL_PUSH_CONSTANTS_NAME "push_constants"
// The maximum number of staging buffers kept for reuse
#define MAX_STAGING_CHUNKS 16
// The size of the staging buffers that small uploads are sub-allocated from
#define STAGING_CHUNK_SIZE (4u * 1024u * 1024u)
// The limits of the Mac2 and Apple7 GPU families, see the Metal feature set tables
#define MAX_TEXTURE_SIZE 16384u
#define MAX_TEXTURE_LAYERS 2048u
// The maximum number of render target pixel formats for the utility pipelines, see Driver
#define MAX_UTILITY_FORMATS 8

// Resources {{{
typedef struct BufferStorage {
    id<MTLBuffer> buffer;
    size_t size;
    uint64_t last_use_serial;
} BufferStorage;

typedef struct Buffer {
    GPUBufferKind kind;
    GPUUpdateFrequency frequency;
    BufferStorage storage; // the current storage, size zero if not yet allocated
    // Storage that commands might still use, reusable once the serial completes
    BufferStorage retired[4];
    size_t num_retired;
    // Incremented whenever the contents of the buffer change
    uint64_t generation;
    // A copy of the contents with the elements of a vertex input moved to
    // offsets and strides that are multiples of four bytes, as required by
    // Metal, see repacked_vertex_buffer()
    struct {
        id<MTLBuffer> buffer;
        uint64_t generation;
        size_t offset, size;
        uint32_t stride, element_size;
    } repacked;
    struct Buffer *prev, *next;
} Buffer;

typedef struct Texture {
    GPUTextureDesc desc;
    MTLPixelFormat format;
    id<MTLTexture> texture;
    // Views for rendering without and with encoding to sRGB, see
    // set_srgb_output(). unorm_view is nil if the texture cannot be rendered
    // to and srgb_view is nil if the texture is not sRGB encoded. They can be
    // the texture itself.
    id<MTLTexture> unorm_view, srgb_view;
    id<MTLSamplerState> sampler; // owned by the driver, see Driver.samplers
    struct Texture *prev, *next;
} Texture;

typedef struct VertexAttribute {
    bool enabled;
    Buffer *buffer;
    uint32_t components, stride, divisor;
    GPUAttribType type;
    size_t offset;
} VertexAttribute;

typedef struct VertexLayout {
    VertexAttribute attributes[MAX_VERTEX_ATTRIBUTES];
    struct VertexLayout *prev, *next;
} VertexLayout;

typedef struct VertexInputKey {
    MTLVertexFormat format; // MTLVertexFormatInvalid for unused inputs
    uint32_t stride, step_rate;
    bool per_instance;
} VertexInputKey;

typedef struct PipelineVariantKey {
    MTLPixelFormat color_format;
    bool blend;
    VertexInputKey inputs[MAX_VERTEX_ATTRIBUTES];
} PipelineVariantKey;

typedef struct PipelineVariant {
    PipelineVariantKey key;
    id<MTLRenderPipelineState> state;
} PipelineVariant;

typedef struct PipelineBinding {
    GPUBindingKind kind;
    uint32_t slot;
    char *name;
    // The argument table indices, from the native name of the binding
    int32_t buffer_index, texture_index, sampler_index;
} PipelineBinding;

typedef struct ParamBlock {
    int32_t slot; // -1 for the push constant block
    uint32_t size;
    Buffer *buffer; // the uniform buffer holding the contents of blocks with a slot
} ParamBlock;

typedef struct Pipeline {
    id<MTLFunction> vertex_function, fragment_function;
    PipelineBinding *bindings;
    size_t num_bindings;
    ParamBlock *param_blocks;
    size_t num_param_blocks;
    uint8_t push_constants[PUSH_CONSTANTS_SIZE];
    uint32_t push_constants_size;
    int32_t push_constants_index; // the buffer argument table index of the push constant block, -1 if none
    uint32_t vertex_inputs;       // bit mask of the locations of the inputs used by the vertex function
    uint32_t declared_inputs;     // bit mask of the locations of all inputs declared by the vertex function
    PipelineVariant *variants;
    size_t num_variants, variants_capacity;
    struct Pipeline *prev, *next;
} Pipeline;

typedef struct RenderTarget {
    Texture *texture;
} RenderTarget;

// Something that can be rendered into, a texture or the drawable of a surface
typedef struct RenderImage {
    id<MTLTexture> texture; // the texture itself, for blits and reading back
    id<MTLTexture> unorm_view, srgb_view;
    uint32_t width, height;
} RenderImage;
// }}}

// Surfaces {{{
typedef struct Surface {
    NSView *view;
    CAMetalLayer *layer;
    GPUSurfaceConfig config;
    uint32_t width, height; // the size of the window framebuffer
    int swap_interval;
    // The drawable being rendered into, acquired by the first rendering after
    // the surface was last presented, along with its view for encoding to sRGB
    id<CAMetalDrawable> drawable;
    id<MTLTexture> drawable_srgb_view;
    struct Surface *prev, *next;
} Surface;
// }}}

typedef struct StagingChunk {
    id<MTLBuffer> buffer;
    size_t used;
    uint64_t serial; // the serial of the command buffer using the chunk
} StagingChunk;

typedef struct UtilityPipeline {
    MTLPixelFormat format;
    id<MTLRenderPipelineState> state;
} UtilityPipeline;

typedef struct Driver {
    GPUDriverInitParams params;
    char last_error[8192];
    char version_string[512];

    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    bool initialized;

    // Command buffers
    id<MTLCommandBuffer> cmd;          // the command buffer being encoded, nil if none
    uint64_t cmd_serial;               // the serial of cmd
    uint64_t next_serial;              // the serial of the next command buffer to be created
    _Atomic uint64_t completed_serial; // the serial of the last command buffer that completed
    // Set by the completed handler of the first command buffer that fails, along
    // with a description of the failure, reported by check_gpu_errors()
    _Atomic bool gpu_error_pending;
    char gpu_error[1024];
    dispatch_semaphore_t in_flight;
    id<MTLBlitCommandEncoder> blit; // the active blit encoder, nil if none
    StagingChunk staging[MAX_STAGING_CHUNKS];
    size_t num_staging;

    // Shared objects
    id<MTLBuffer> quad_indices;
    id<MTLSamplerState> samplers[2][4][2]; // [filter][wrap][is_integer]
    // Pipelines used by the driver itself, for clearing rectangles and for
    // copying between textures of different formats, one per render target format
    id<MTLLibrary> utility_library;
    id<MTLFunction> fullscreen_vertex, clear_fragment, copy_fragment;
    UtilityPipeline clear_pipelines[MAX_UTILITY_FORMATS], copy_pipelines[MAX_UTILITY_FORMATS];
    size_t num_clear_pipelines, num_copy_pipelines;

    // Live objects, destroyed with the driver
    Texture *textures;
    Buffer *buffers;
    Pipeline *pipelines;
    VertexLayout *vertex_layouts;
    Surface *surfaces;

    // Current state, see "current" state in ../api.h
    Surface *current_surface;
    RenderTarget *render_target; // NULL for the window
    int32_t viewport[4];
    struct {
        bool enabled;
        int32_t rect[4];
    } scissor;
    bool srgb_output;
    Pipeline *pipeline;
    VertexLayout *vertex_layout;
    Texture *bound_textures[MAX_BINDING_SLOTS];
    Buffer *bound_buffers[MAX_BINDING_SLOTS];

    // The active render command encoder and the state set on it
    struct {
        id<MTLRenderCommandEncoder> encoder; // nil if no render pass is active
        id<MTLTexture> view;                 // the attachment being rendered into
        id<MTLTexture> texture;              // the texture the attachment is a view of
        MTLPixelFormat format;
        uint32_t width, height;
        id<MTLRenderPipelineState> pipeline;
        Pipeline *push_constants_of; // the pipeline whose push constants were last set
        bool push_constants_dirty;
        int32_t viewport[4], scissor[4];
        bool viewport_valid, scissor_valid;
    } rendering;
} Driver;

// driver.m
void set_error(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void log_error(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void debug_print(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void fatal(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3), noreturn));
// The description of an NSError, never NULL
const char *error_description(NSError *err);

// commands.m
// The command buffer to encode into, creating it if needed
id<MTLCommandBuffer> command_buffer(Driver *d);
// The serial of the command buffer being encoded
uint64_t recording_serial(Driver *d);
uint64_t completed_serial(Driver *d);
// Commit the command buffer being encoded, if any. If wait is true, waits for it to complete.
void submit_commands(Driver *d, bool wait);
// Wait until all committed command buffers have completed
void wait_for_idle(Driver *d);
// The active blit encoder, ending any render pass
id<MTLBlitCommandEncoder> blit_encoder(Driver *d);
// End the active render pass and blit encoder, if any
void end_encoding(Driver *d);
// End the active render pass, if any
void end_rendering(Driver *d);
// Report errors from command buffers that failed
void check_gpu_errors(Driver *d);
// Staging memory for uploads in the command buffer being encoded, valid until it completes
bool allocate_staging(Driver *d, size_t size, size_t alignment, id<MTLBuffer> *buffer, size_t *offset, void **mapped);
void release_staging(Driver *d);
bool create_utility_pipelines(Driver *d);
void destroy_utility_pipelines(Driver *d);
void clear(void *driver, float r, float g, float b, float a);
void set_viewport(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height);
void get_viewport(void *driver, int32_t ans[4]);
void set_scissor(void *driver, bool enabled, int32_t x, int32_t y, uint32_t width, uint32_t height);
void set_srgb_output(void *driver, bool enabled);
void read_pixels(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height, void *dst);
void copy_to_texture(void *driver, gpu_texture_t dst, int32_t x, int32_t y, uint32_t width, uint32_t height);
gpu_render_target_t render_target_create(void *driver, gpu_texture_t color_texture);
void render_target_destroy(void *driver, gpu_render_target_t target);
void set_render_target(void *driver, gpu_render_target_t target);
gpu_render_target_t get_render_target(void *driver);
const char *render_target_status(void *driver, gpu_render_target_t target);
void draw_quad(void *driver, uint32_t instance_count, GPUBlendMode blend);

// buffers.m
gpu_buffer_t buffer_create(void *driver, GPUBufferKind kind);
void buffer_destroy(void *driver, gpu_buffer_t buffer);
void buffer_allocate(void *driver, gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency);
void *buffer_map(void *driver, gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size);
void buffer_unmap(void *driver, gpu_buffer_t buffer);
void buffer_copy(void *driver, gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size);
void bind_uniform_buffer(void *driver, uint32_t slot, gpu_buffer_t buffer);
// Mark the current storage of the buffer as used by the commands being encoded
void use_buffer(Driver *d, Buffer *b);
// Write data to the start of the buffer, giving it new storage if commands might still use the current one
bool write_buffer(Driver *d, Buffer *b, const void *data, size_t size);
// The buffer and offset to use for a vertex input, repacking its elements if
// their offset or stride are not multiples of four bytes. Sets stride to the
// stride of the elements in the returned buffer. nil on failure.
id<MTLBuffer> vertex_buffer_for(Driver *d, const VertexAttribute *a, size_t element_size, size_t *offset, uint32_t *stride);
// The stride of the elements of a vertex input in the buffer returned by vertex_buffer_for()
uint32_t vertex_buffer_stride(const VertexAttribute *a, size_t element_size);
void destroy_all_buffers(Driver *d);

// textures.m
bool create_samplers(Driver *d);
void destroy_samplers(Driver *d);
gpu_texture_t texture_create(void *driver, const GPUTextureDesc *desc, const GPUPixelData *initial);
bool texture_reset(void *driver, gpu_texture_t texture, const GPUTextureDesc *desc, const GPUPixelData *initial);
void texture_destroy(void *driver, gpu_texture_t texture);
void texture_upload(void *driver, gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels);
void texture_copy(void *driver, gpu_texture_t src, gpu_texture_t dst);
bool texture_read(void *driver, gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size);
void texture_get_desc(void *driver, gpu_texture_t texture, GPUTextureDesc *ans);
void bind_texture(void *driver, uint32_t slot, gpu_texture_t texture);
void destroy_all_textures(Driver *d);
// The number of bytes per pixel of textures of the format
size_t bytes_per_pixel(MTLPixelFormat f);
// Convert pixels read back from a texture of the specified format to tightly packed RGBA8
void convert_to_rgba8(MTLPixelFormat format, const uint8_t *src, uint8_t *dst, size_t num_pixels);

// pipelines.m
gpu_pipeline_t pipeline_create(
    void *driver,
    const GPUShaderSource *sources,
    size_t num_sources,
    const GPUParamBlock *param_blocks,
    size_t num_param_blocks,
    const GPUBinding *bindings,
    size_t num_bindings,
    const GPUNativeName *native_names,
    size_t num_native_names);
void pipeline_destroy(void *driver, gpu_pipeline_t pipeline);
void use_pipeline(void *driver, gpu_pipeline_t pipeline);
bool pipeline_uniform_block(void *driver, gpu_pipeline_t pipeline, const char *name, GPUUniformBlockInfo *ans);
int32_t pipeline_attribute_location(void *driver, gpu_pipeline_t pipeline, const char *name);
void set_params(void *driver, gpu_pipeline_t pipeline, uint32_t block, const void *data, size_t size);
gpu_vertex_layout_t vertex_layout_create(void *driver);
void vertex_layout_destroy(void *driver, gpu_vertex_layout_t layout);
void bind_vertex_layout(void *driver, gpu_vertex_layout_t layout);
void vertex_layout_set_attribute(
    void *driver,
    gpu_vertex_layout_t layout,
    uint32_t location,
    gpu_buffer_t buffer,
    uint32_t components,
    GPUAttribType type,
    uint32_t stride,
    size_t offset,
    uint32_t instance_divisor);
// The size in bytes of one element of a vertex input
size_t vertex_attribute_size(uint32_t components, GPUAttribType type);
// The pipeline state for drawing with the current state, with its key in
// key, nil on failure. Must be called with a render pass active.
id<MTLRenderPipelineState> pipeline_for_current_state(Driver *d, bool blend, PipelineVariantKey *key);
void destroy_all_pipelines(Driver *d);

// surfaces.m
bool choose_native_visual(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id);
gpu_surface_t surface_create(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height);
void surface_destroy(void *driver, gpu_surface_t surface);
bool make_surface_current(void *driver, gpu_surface_t surface);
gpu_surface_t get_current_surface(void *driver);
void surface_resize(void *driver, gpu_surface_t surface, uint32_t width, uint32_t height);
bool surface_present(void *driver, gpu_surface_t surface);
void surface_set_swap_interval(void *driver, gpu_surface_t surface, int interval);
void surface_native_changed(void *driver, gpu_surface_t surface);
bool surface_recreate(void *driver, gpu_surface_t surface);
void release_native_resources(void *driver);
// The drawable of the current surface to render into, acquiring it if needed. false on failure.
bool current_surface_image(Driver *d, RenderImage *ans);

// Intrusive doubly linked lists of live objects
#define LIST_ADD(head, item)             \
    do {                                 \
        (item)->prev = NULL;             \
        (item)->next = (head);           \
        if (head) (head)->prev = (item); \
        (head) = (item);                 \
    } while (0)
#define LIST_REMOVE(head, item)                              \
    do {                                                     \
        if ((item)->prev) (item)->prev->next = (item)->next; \
        else (head) = (item)->next;                          \
        if ((item)->next) (item)->next->prev = (item)->prev; \
        (item)->prev = (item)->next = NULL;                  \
    } while (0)
