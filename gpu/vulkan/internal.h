/*
 * internal.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Types and functions shared between the files of the Vulkan driver.
//
// Overview of how the driver implements the immediate mode API in ../api.h:
//
// * Commands are recorded into the command buffer of the current Context, one
//   of a small ring of them. A Context is submitted when a surface is
//   presented, or when the CPU needs the results, such as when reading back
//   pixels. Before a Context is reused, its fence is waited on, which also
//   throttles the CPU to at most a few submissions ahead of the GPU.
// * Every submission has a serial number. Objects that recorded commands
//   might still use are destroyed, or reused, only once the serial of the
//   last submission that could use them has completed.
// * Rendering uses dynamic rendering. A render pass instance is begun lazily,
//   by the first draw or clear, and ended when the render target changes or
//   commands that cannot be recorded inside render pass instances, such as
//   copies, are recorded. Image layouts are tracked per image and transitions
//   are recorded as needed.
// * Buffers live in memory the CPU can write to and are only ever written by
//   the CPU. Writing to a buffer that recorded commands might still read
//   gives it new storage, so that, as with OpenGL, commands use the contents
//   the buffer had when they were recorded.
// * Textures and uniform buffers are bound with push descriptors and the
//   uniform parameters of pipelines are push constants.

#pragma once

#define _GNU_SOURCE // for strdup() and strnlen()
#include "../api.h"
#include "functions.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define UNUSED __attribute__((unused))
#define arraysz(x) (sizeof(x) / sizeof(x[0]))
#define MIN(x, y) ((x) < (y) ? (x) : (y))
#define MAX(x, y) ((x) > (y) ? (x) : (y))
#define AS_HANDLE(ptr) ((uint64_t)(uintptr_t)(ptr))

// The number of Contexts, see above
#define NUM_CONTEXTS 3
// The maximum number of binding slots of textures and uniform buffers, the
// slots used by kitty are much smaller than this
#define MAX_BINDING_SLOTS 32
// The maximum number of vertex inputs
#define MAX_VERTEX_ATTRIBUTES 16
// The size of the push constant block guaranteed by Vulkan, see GPUParamBlock
#define PUSH_CONSTANTS_SIZE 128

// Memory {{{
typedef enum {
    MEMORY_DEVICE,   // device local memory for images
    MEMORY_UPLOAD,   // host visible memory, preferably also device local, for buffers read by the GPU
    MEMORY_READBACK, // host visible memory, preferably cached, for reading back from the GPU
} MemoryUsage;

typedef struct MemoryBlock MemoryBlock;

typedef struct Allocation {
    VkDeviceMemory memory;
    VkDeviceSize offset, size;
    void *mapped;       // NULL if not host visible
    MemoryBlock *block; // NULL for dedicated allocations
} Allocation;
// }}}

// Command recording {{{
typedef struct Garbage Garbage;

typedef struct Context {
    VkCommandPool pool;
    VkCommandBuffer cmd;
    VkFence fence;
    uint64_t serial;  // the serial of the submission of this context
    bool recording;   // commands are being recorded into cmd
    bool submitted;   // submitted and the fence has not yet been waited on
    Garbage *garbage; // objects to destroy once this context completes
    // Staging memory for uploads and reads, released once the context completes
    struct {
        VkBuffer buffer;
        Allocation alloc;
        VkDeviceSize used;
    } staging[64];
    size_t num_staging;
    // Semaphores the submission must wait on, from acquiring swapchain images
    VkSemaphore waits[8];
    size_t num_waits;
    // Semaphores used for acquiring swapchain images, recycled once the context completes
    VkSemaphore used_semaphores[8];
    size_t num_used_semaphores;
} Context;

// The way an image was last accessed, for recording barriers
typedef struct ImageState {
    VkImageLayout layout;
    VkPipelineStageFlags2 stage;
    VkAccessFlags2 access;
} ImageState;

// A Vulkan image together with its views, used by textures and swapchains
typedef struct Image {
    VkImage image;
    Allocation alloc;                   // not used for swapchain images
    VkFormat format;                    // the format of the image, for sampling
    VkFormat unorm_format, srgb_format; // for render target views, srgb_format is zero if not supported
    VkImageView sampled_view;
    VkImageView unorm_view, srgb_view; // views for rendering, NULL if the image cannot be rendered to
    uint32_t width, height, layers;
    ImageState state;
    uint64_t last_use_serial;
} Image;
// }}}

// Resources {{{
typedef struct Texture {
    GPUTextureDesc desc;
    Image image;
    VkSampler sampler;
    struct Texture *prev, *next;
} Texture;

typedef struct BufferStorage {
    VkBuffer buffer;
    Allocation alloc;
    VkDeviceSize size;
    uint64_t last_use_serial;
} BufferStorage;

typedef struct Buffer {
    GPUBufferKind kind;
    GPUUpdateFrequency frequency;
    BufferStorage storage; // the current storage, size zero if not yet allocated
    // Storage that commands might still use, reusable once the serial completes
    BufferStorage retired[4];
    size_t num_retired;
    struct Buffer *prev, *next;
} Buffer;

typedef struct VertexAttribute {
    bool enabled;
    Buffer *buffer;
    uint32_t components, stride, divisor;
    GPUAttribType type;
    VkDeviceSize offset;
} VertexAttribute;

typedef struct VertexLayout {
    VertexAttribute attributes[MAX_VERTEX_ATTRIBUTES];
    struct VertexLayout *prev, *next;
} VertexLayout;

typedef struct PipelineVariantKey {
    VkFormat color_format;
    bool blend;
    // The format and input rate of each vertex attribute, format is zero for unused attributes
    VkFormat attribute_formats[MAX_VERTEX_ATTRIBUTES];
    bool attribute_per_instance[MAX_VERTEX_ATTRIBUTES];
} PipelineVariantKey;

typedef struct PipelineVariant {
    PipelineVariantKey key;
    VkPipeline pipeline;
} PipelineVariant;

typedef struct PipelineBinding {
    GPUBindingKind kind;
    uint32_t slot;
    char *name;
} PipelineBinding;

typedef struct ParamBlock {
    int32_t slot; // -1 for the push constant block
    uint32_t size;
    Buffer *buffer; // the uniform buffer holding the contents of blocks with a slot
} ParamBlock;

typedef struct Pipeline {
    VkShaderModule modules[2];
    size_t num_modules;
    VkPipelineShaderStageCreateInfo stages[2];
    char *entry_points[2];
    VkDescriptorSetLayout set_layout;
    VkPipelineLayout layout;
    PipelineBinding *bindings;
    size_t num_bindings;
    ParamBlock *param_blocks;
    size_t num_param_blocks;
    uint8_t push_constants[PUSH_CONSTANTS_SIZE];
    uint32_t push_constants_size;
    uint32_t vertex_inputs; // bit mask of the locations of the inputs of the vertex shader
    PipelineVariant *variants;
    size_t num_variants, variants_capacity;
    struct Pipeline *prev, *next;
} Pipeline;

typedef struct RenderTarget {
    Texture *texture;
} RenderTarget;
// }}}

// Surfaces {{{
typedef struct Swapchain {
    VkSwapchainKHR swapchain;
    Image *images;
    VkSemaphore *present_semaphores; // one per image, signalled when rendering to the image is done
    uint32_t num_images;
    VkExtent2D extent;
    VkFormat format;
    VkPresentModeKHR present_mode;
} Swapchain;

typedef struct Surface {
    GPUPlatform platform;
    VkSurfaceKHR surface;
    GPUSurfaceConfig config;
    Swapchain swapchain;
    uint32_t width, height; // the size of the window framebuffer
    int swap_interval;
    bool needs_recreate; // the swapchain must be recreated before it is next used
    bool image_acquired; // an image has been acquired and not yet presented
    uint32_t image_index;
    struct Surface *prev, *next;
} Surface;
// }}}

typedef struct Driver {
    GPUDriverInitParams params;
    char last_error[8192];
    char version_string[512];
    void *libvulkan;

    VkInstance instance;
    VkDebugUtilsMessengerEXT messenger;
    VkPhysicalDevice physical_device;
    VkPhysicalDeviceProperties properties;
    VkPhysicalDeviceMemoryProperties memory_properties;
    VkDevice device;
    uint32_t queue_family;
    VkQueue queue;
    GPUPlatform platform;
    void *native_display;
    bool has_debug_utils, has_swapchain_mutable_format;
    bool initialized;

    // Command recording
    Context contexts[NUM_CONTEXTS];
    size_t current_context; // index into contexts of the context being recorded or next to be recorded
    uint64_t next_serial, completed_serial;
    VkSemaphore free_semaphores[64];
    size_t num_free_semaphores;
    MemoryBlock *memory_blocks;

    // Shared objects
    VkBuffer quad_indices;
    Allocation quad_indices_alloc;
    VkSampler samplers[2][4][2]; // [filter][wrap][is_integer]

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

    // State of the command buffer being recorded
    struct {
        bool active;  // a render pass instance is active
        Image *image; // the image being rendered to
        VkImageView view;
        VkFormat format;
        VkExtent2D extent;
    } rendering;
    struct {
        VkPipeline pipeline;         // the bound pipeline
        Pipeline *push_constants_of; // the pipeline whose push constants were last pushed
        bool push_constants_dirty;
        bool descriptors_dirty;
        int32_t viewport[4];
        int32_t scissor[4];
        bool viewport_valid, scissor_valid;
    } cmd_state;
} Driver;

// driver.c
void set_error(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void log_error(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void debug_print(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void fatal(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3), noreturn));
const char *vk_result_string(VkResult r);
// Calls fatal() if r is not VK_SUCCESS
void check_vk(Driver *d, VkResult r, const char *what);

// memory.c
bool allocate_memory(Driver *d, const VkMemoryRequirements *req, MemoryUsage usage, Allocation *ans);
void free_memory(Driver *d, Allocation *a);
void free_all_memory(Driver *d);
bool create_buffer_with_memory(Driver *d, VkDeviceSize size, VkBufferUsageFlags usage, MemoryUsage mem_usage, VkBuffer *buffer, Allocation *alloc);
// Staging memory for uploads in the current context, valid until the context completes
bool allocate_staging(Driver *d, VkDeviceSize size, VkDeviceSize alignment, VkBuffer *buffer, VkDeviceSize *offset, void **mapped);
void release_staging(Driver *d, Context *c);
gpu_buffer_t buffer_create(void *driver, GPUBufferKind kind);
void buffer_destroy(void *driver, gpu_buffer_t buffer);
void buffer_allocate(void *driver, gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency);
void *buffer_map(void *driver, gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size);
void buffer_unmap(void *driver, gpu_buffer_t buffer);
void buffer_copy(void *driver, gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size);
void bind_uniform_buffer(void *driver, uint32_t slot, gpu_buffer_t buffer);
// Mark the current storage of the buffer as used by the commands being recorded
void use_buffer(Driver *d, Buffer *b);
// Write data to the start of the buffer, giving it new storage if commands might still use the current one
bool write_buffer(Driver *d, Buffer *b, const void *data, size_t size);
void destroy_all_buffers(Driver *d);

// commands.c
// The context being recorded, beginning recording if needed
Context *current_context(Driver *d);
// The command buffer to record into, beginning recording if needed
VkCommandBuffer command_buffer(Driver *d);
// Submit the commands recorded so far. If wait is true, waits for them to complete.
void submit_commands(Driver *d, const VkSemaphore *signal, size_t num_signal, bool wait);
// Wait for submissions until serial has completed
void wait_for_serial(Driver *d, uint64_t serial);
// The serial of the commands being recorded
uint64_t recording_serial(Driver *d);
// Destroy objects once the commands being recorded have completed, see Garbage
void defer_destroy_buffer(Driver *d, VkBuffer buffer, Allocation *alloc);
void defer_destroy_image(Driver *d, Image *image);
void defer_destroy_pipeline(Driver *d, VkPipeline pipeline);
void defer_destroy_pipeline_objects(Driver *d, VkPipelineLayout layout, VkDescriptorSetLayout set_layout, VkShaderModule *modules, size_t num_modules);
void destroy_contexts(Driver *d);
VkSemaphore get_semaphore(Driver *d);
void add_wait_semaphore(Driver *d, VkSemaphore s);
void transition_image(Driver *d, Image *image, VkImageLayout layout, VkPipelineStageFlags2 stage, VkAccessFlags2 access);
void end_rendering(Driver *d);
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

// textures.c
bool create_samplers(Driver *d);
void destroy_samplers(Driver *d);
VkFormat vk_format_for(GPUTextureFormat f);
bool create_image_views(Driver *d, Image *img, VkImageViewType sampled_type);
void destroy_image_views(Driver *d, Image *img);
gpu_texture_t texture_create(void *driver, const GPUTextureDesc *desc, const GPUPixelData *initial);
bool texture_reset(void *driver, gpu_texture_t texture, const GPUTextureDesc *desc, const GPUPixelData *initial);
void texture_destroy(void *driver, gpu_texture_t texture);
void texture_upload(void *driver, gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels);
void texture_copy(void *driver, gpu_texture_t src, gpu_texture_t dst);
bool texture_read(void *driver, gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size);
void texture_get_desc(void *driver, gpu_texture_t texture, GPUTextureDesc *ans);
void bind_texture(void *driver, uint32_t slot, gpu_texture_t texture);
void destroy_all_textures(Driver *d);
// Convert pixels read back from an image of the specified format to tightly packed RGBA8
void convert_to_rgba8(VkFormat format, const uint8_t *src, uint8_t *dst, size_t num_pixels);

// pipelines.c
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
// The VkPipeline for drawing with the current state, NULL on failure
VkPipeline pipeline_for_current_state(Driver *d, bool blend);
VkFormat vertex_attribute_format(uint32_t components, GPUAttribType type);
void destroy_all_pipelines(Driver *d);

// surfaces.c
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
// The image of the current surface to render into, acquiring it if needed. NULL on failure.
Image *current_surface_image(Driver *d);
// Whether the physical device can present to windows on the display
bool presentation_supported(Driver *d, VkPhysicalDevice device, uint32_t queue_family);

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
