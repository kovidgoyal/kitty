/*
 * api.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The backend neutral GPU driver API used by kitty. A driver is a shared
// library, loaded at runtime with dlopen(), that exports a single function
// named KITTY_GPU_DRIVER_ENTRY_POINT of type gpu_driver_load_func. That
// function fills in a GPUDriverAPI table of function pointers and returns an
// opaque driver object. Every function in the table takes that object as its
// first argument.
//
// This header must use only standard C so that it can be shared between
// kitty and drivers written for any graphics API (OpenGL, Vulkan, Metal).
//
// Conventions:
//
// * All resources are referred to by opaque 64 bit handles. The value zero
//   (GPU_NULL_HANDLE) is never a valid handle and means "no resource".
// * Functions that create resources return GPU_NULL_HANDLE on failure, and
//   functions that can fail return false. In both cases a description of the
//   failure is available from last_error(). Errors from which the driver
//   cannot recover are reported via the fatal() callback in GPUDriverInitParams.
// * Pixel coordinates for viewports, scissor rectangles and reading back pixels
//   have their origin at the bottom left corner of the current render target,
//   with y increasing upwards. Rows of pixel data read back from the GPU are
//   ordered bottom to top. Pixel data uploaded to textures is ordered with the
//   first row at texture coordinate t=0.
// * The driver tracks a small amount of "current" state: the pipeline,
//   vertex layout, render target, viewport, scissor rectangle, sRGB output
//   mode and textures bound to texture units. Draw calls use this state. This
//   is cheap to implement on top of OpenGL and straightforward to record into
//   command buffers for Vulkan and Metal.
// * Rendering happens into surfaces, created from native windows supplied by
//   the windowing system (see GPUNativeWindow). The driver owns everything
//   needed to render to and present a surface, such as OpenGL contexts or
//   Vulkan swapchains. The windowing system owns only the window itself.
// * On APIs where some objects are bound to a context or device queue, such
//   as framebuffers and vertex array objects in OpenGL, vertex layouts and
//   render targets are only valid with the surface that was current when they
//   were created. Textures, buffers and pipelines are shared between all
//   surfaces.

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define KITTY_GPU_API_VERSION 4u
#define KITTY_GPU_DRIVER_ENTRY_POINT "kitty_gpu_driver_load"
#define GPU_NULL_HANDLE ((uint64_t)0)

typedef uint64_t gpu_texture_t;
typedef uint64_t gpu_buffer_t;
typedef uint64_t gpu_pipeline_t;
typedef uint64_t gpu_vertex_layout_t;
typedef uint64_t gpu_render_target_t;
typedef uint64_t gpu_surface_t;

// Initialization {{{

typedef void (*gpu_message_func)(const char *message);

typedef struct GPUDriverInitParams {
    // Enable extra error checking and debug output
    bool debug_rendering;
    // Report a non-fatal error to the user
    gpu_message_func log_error;
    // Print debug output, only called when debug_rendering is true
    gpu_message_func debug_print;
    // Report an unrecoverable error, must not return
    gpu_message_func fatal;
    // X11: The windowing system installs a process wide X error handler, so
    // drivers must not install their own. Instead, to detect errors caused by
    // their requests, they call x11_push_error_trap() before making the
    // requests and x11_pop_error_trap() after. Errors caused by requests made
    // on the display connection while a trap is open are captured by it
    // rather than being reported. x11_pop_error_trap() waits for the X server
    // to process the requests, if needed, and returns the code of the first
    // error caused by them, or zero (Success) if there were none. Traps nest
    // and every push must be matched by a pop. Both may only be called on the
    // main thread, with surfaces on X11 displays.
    void (*x11_push_error_trap)(void);
    int (*x11_pop_error_trap)(void);
} GPUDriverInitParams;

typedef struct GPUCapabilities {
    uint32_t max_texture_size;         // max width and height of a texture
    uint32_t max_array_texture_layers; // max number of layers in an array texture
    // Whether render targets can encode linear colors to sRGB on output, see set_srgb_output()
    bool supports_srgb_output;
} GPUCapabilities;
// }}}

// Surfaces {{{

typedef enum {
    GPU_PLATFORM_X11 = 1,
    GPU_PLATFORM_WAYLAND,
    GPU_PLATFORM_COCOA,
} GPUPlatform;

// A native window, or just the native display connection when used with
// choose_native_visual()
typedef struct GPUNativeWindow {
    GPUPlatform platform;
    void *display;       // X11: Display*, Wayland: struct wl_display*, Cocoa: unused
    int screen;          // X11: the screen number, negative for the default screen, unused on other platforms
    uint64_t x11_window; // X11: the Window, unused on other platforms
    void *handle;        // Wayland: struct wl_surface*, Cocoa: the NSView* to render into, unused on X11
} GPUNativeWindow;

typedef struct GPUSurfaceConfig {
    // The window is semi-transparent and composited using the alpha channel of its contents
    bool transparent;
    // Request a framebuffer that supports encoding to sRGB on output
    bool srgb;
    // macOS: allow rendering on, and automatically switching to, offline or low power GPUs
    bool allow_offline_renderers;
    // macOS: render at the full resolution of high DPI (retina) displays
    bool high_resolution;
} GPUSurfaceConfig;
// }}}

// Textures {{{

typedef enum {
    GPU_TEXTURE_2D = 1,
    GPU_TEXTURE_2D_ARRAY,
} GPUTextureKind;

typedef enum {
    GPU_FORMAT_R8 = 1,       // one normalized 8 bit channel
    GPU_FORMAT_R8UI,         // one unsigned 8 bit integer channel
    GPU_FORMAT_RG8UI,        // two unsigned 8 bit integer channels
    GPU_FORMAT_R32UI,        // one unsigned 32 bit integer channel
    GPU_FORMAT_RGBA8,        // four normalized 8 bit channels
    GPU_FORMAT_SRGB8_ALPHA8, // sRGB encoded colors with linear alpha, decoded to linear when sampled
    GPU_FORMAT_RGBA16,       // four normalized 16 bit channels
} GPUTextureFormat;

typedef enum {
    GPU_FILTER_NEAREST = 1,
    GPU_FILTER_LINEAR,
} GPUFilter;

typedef enum {
    GPU_WRAP_CLAMP_TO_EDGE = 1,
    GPU_WRAP_CLAMP_TO_BORDER, // sampling outside the texture returns transparent black
    GPU_WRAP_REPEAT,
    GPU_WRAP_MIRRORED_REPEAT,
} GPUWrap;

typedef struct GPUTextureDesc {
    GPUTextureKind kind;
    GPUTextureFormat format;
    uint32_t width, height;
    uint32_t layers; // number of layers, used only for GPU_TEXTURE_2D_ARRAY
    GPUFilter filter;
    GPUWrap wrap;
} GPUTextureDesc;

// The layout of pixel data in CPU memory
typedef enum {
    GPU_PIXELS_R8 = 1,       // one byte per pixel
    GPU_PIXELS_RG8,          // two bytes per pixel
    GPU_PIXELS_RGB8,         // three bytes per pixel, in the order R, G, B
    GPU_PIXELS_RGBA8,        // four bytes per pixel, in the order R, G, B, A
    GPU_PIXELS_RGBA8_PACKED, // one native endian uint32_t per pixel with R in the most significant byte
    GPU_PIXELS_R32UI,        // one native endian uint32_t per pixel
} GPUPixelLayout;

typedef struct GPUPixelData {
    GPUPixelLayout layout;
    // Rows start at addresses that are a multiple of this many bytes, one of 1, 2, 4 or 8
    uint32_t row_alignment;
    const void *data;
} GPUPixelData;
// }}}

// Buffers {{{

typedef enum {
    GPU_BUFFER_VERTEX = 1, // per vertex or per instance data for vertex layouts
    GPU_BUFFER_UNIFORM,    // data for uniform blocks
} GPUBufferKind;

typedef enum {
    GPU_UPDATE_RARELY = 1, // written once, used many times
    GPU_UPDATE_OFTEN,      // written repeatedly, used many times
    GPU_UPDATE_EVERY_USE,  // written before every use
} GPUUpdateFrequency;

typedef enum {
    GPU_MAP_WRITE = 1,           // write to the buffer, preserving existing contents
    GPU_MAP_WRITE_DISCARD_RANGE, // write to a range of the buffer, the previous contents of the range are discarded
    GPU_MAP_WRITE_DISCARD_ALL,   // write the whole buffer, its previous contents are discarded
    GPU_MAP_READ,                // read the contents of the buffer
} GPUMapMode;
// }}}

// Pipelines {{{

typedef enum {
    GPU_SHADER_VERTEX = 1,
    GPU_SHADER_FRAGMENT,
} GPUShaderStage;

typedef enum {
    GPU_SHADER_LANGUAGE_GLSL = 1,
    GPU_SHADER_LANGUAGE_SPIRV,
    GPU_SHADER_LANGUAGE_MSL,
} GPUShaderLanguage;

typedef struct GPUShaderSource {
    GPUShaderStage stage;
    GPUShaderLanguage language;
    const char *code;
    size_t size; // size of code in bytes, may be zero for null terminated text
} GPUShaderSource;

typedef struct GPUUniformBlockInfo {
    uint32_t index; // identifies the block within the pipeline
    uint32_t size;  // size in bytes of the data in the block
} GPUUniformBlockInfo;

// Shaders are written in Slang and compiled ahead of time, or for user
// supplied shaders at runtime, to the shader target of the driver, see
// shader_target(). Everything about the parameters of a pipeline, such as the
// layout of uniform blocks, comes from the reflection data produced by the
// Slang compiler and is identified by the names used in the Slang source.
// Some targets, such as GLSL for OpenGL, look up parameters by the identifier
// used in the compiled code, which can differ from the Slang name. For those
// the mapping is supplied when creating the pipeline.
// The binding slot of a texture or uniform block of a pipeline, from the
// reflection data. Textures and uniform buffers are bound to these slots with
// bind_texture() and bind_uniform_buffer(). Targets where the slots are not
// part of the compiled code, such as GLSL for OpenGL 3, apply them when the
// pipeline is created.
typedef enum {
    GPU_BINDING_TEXTURE = 1,
    GPU_BINDING_UNIFORM_BLOCK,
} GPUBindingKind;

typedef struct GPUBinding {
    GPUBindingKind kind;
    const char *name; // name of the texture, or of the type of the uniform block, in the Slang source
    uint32_t slot;
} GPUBinding;

// Parameter blocks hold the small, frequently changing, parameters of a
// pipeline: the push constant block, holding the uniform parameters shared
// by all stages of the pipeline, and uniform blocks whose contents are
// constant for the lifetime of the pipeline. Their layout
// comes from the reflection data. kitty writes their contents into memory it
// owns, laid out as described here, and passes it to set_params() before
// drawing. Values persist with the pipeline until set again. Drivers are free
// to implement them as they see fit, for example as loose uniforms in OpenGL,
// push constants in Vulkan or set*Bytes() in Metal.
typedef enum {
    GPU_PARAM_FLOAT = 1, // 32 bit float
    GPU_PARAM_INT,       // 32 bit signed integer
    GPU_PARAM_UINT,      // 32 bit unsigned integer
    GPU_PARAM_BOOL,      // 32 bit, zero is false
} GPUParamScalar;

typedef struct GPUParamField {
    const char *name; // name in the Slang source
    uint32_t offset;  // byte offset from the start of the block
    GPUParamScalar scalar;
    uint32_t components; // number of components in each element, 1 to 4
    uint32_t count;      // number of elements, greater than one for arrays
    uint32_t stride;     // bytes between consecutive elements
} GPUParamField;

typedef struct GPUParamBlock {
    // For the push constant block name is NULL and slot is -1. Its contents
    // are used by every stage of the pipeline and are at most 128 bytes. For
    // uniform blocks name is the name of the type of the block in the Slang
    // source and slot is the binding slot of the block, which drivers that
    // implement it as a uniform buffer must use.
    const char *name;
    int32_t slot;
    uint32_t size; // size in bytes of the block
    const GPUParamField *fields;
    size_t num_fields;
} GPUParamBlock;

typedef struct GPUNativeName {
    const char *name;        // the name of a parameter, vertex input or uniform block type in the Slang source
    const char *native_name; // the corresponding identifier in the compiled code
} GPUNativeName;
// }}}

// Drawing {{{

typedef enum {
    GPU_ATTRIB_U8 = 1, // these integer types are passed to shaders as integers
    GPU_ATTRIB_U16,
    GPU_ATTRIB_U32,
    GPU_ATTRIB_F32,
} GPUAttribType;

typedef enum {
    GPU_BLEND_NONE = 1,           // output replaces the existing contents
    GPU_BLEND_PREMULTIPLIED_ALPHA // output, with pre-multiplied alpha, is composited over the existing contents
} GPUBlendMode;
// }}}

typedef struct GPUDriverAPI {
    uint32_t api_version;
    // A human readable name for the driver, such as "OpenGL"
    const char *name;
    // The identifier of the shader target this driver consumes, for example
    // glsl-140. This is a fixed property of the driver, available as soon as
    // it is loaded. kitty compiles its built-in shaders for the targets of the
    // drivers it builds at build time, and user supplied shaders for the target
    // of the loaded driver at runtime.
    const char *(*shader_target)(void *driver);

    // Lifecycle {{{
    // Called once, after the driver is loaded and before any surfaces are
    // created, with the connection to the windowing system: only the
    // platform, display and screen fields of display are used. The driver
    // must check, as far as is possible without a window, that it can render
    // to windows on this display, for example, that the needed system
    // libraries are present and that there is a GPU that can present to the
    // display. If it returns false, last_error() describes the problem and
    // kitty unloads the driver and tries the next one.
    bool (*connect)(void *driver, const GPUNativeWindow *display);
    // Called once, when the first surface has been created and made current.
    // Must be called before any other function except connect(), destroy(),
    // last_error() and the surface functions.
    bool (*initialize)(void *driver);
    void (*destroy)(void *driver);
    // A description of the last error, never NULL
    const char *(*last_error)(void *driver);
    // A human readable description of the GPU driver and API version
    const char *(*version_string)(void *driver);
    void (*get_capabilities)(void *driver, GPUCapabilities *ans);
    // }}}

    // Textures {{{
    // Create a texture. If initial is not NULL it must contain the pixels of
    // the whole texture, otherwise the contents of the texture are undefined.
    gpu_texture_t (*texture_create)(void *driver, const GPUTextureDesc *desc, const GPUPixelData *initial);
    // Replace the storage of an existing texture, keeping its handle
    bool (*texture_reset)(void *driver, gpu_texture_t texture, const GPUTextureDesc *desc, const GPUPixelData *initial);
    void (*texture_destroy)(void *driver, gpu_texture_t texture);
    // Upload pixels to a rectangle within a single layer of a texture
    void (*texture_upload)(
        void *driver, gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels);
    // Copy the entire contents of src into dst, starting at the origin of dst.
    // Both textures must have the same kind and format and dst must be at
    // least as large as src in every dimension.
    void (*texture_copy)(void *driver, gpu_texture_t src, gpu_texture_t dst);
    // Read back the first layer of a texture. dst must be large enough to hold
    // width * height pixels of the specified layout with rows aligned to 4 bytes.
    bool (*texture_read)(void *driver, gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size);
    void (*texture_get_desc)(void *driver, gpu_texture_t texture, GPUTextureDesc *ans);
    // Bind a texture to a slot, for sampling by pipelines, see GPUBinding
    void (*bind_texture)(void *driver, uint32_t slot, gpu_texture_t texture);
    // }}}

    // Buffers {{{
    gpu_buffer_t (*buffer_create)(void *driver, GPUBufferKind kind);
    void (*buffer_destroy)(void *driver, gpu_buffer_t buffer);
    // Allocate storage for the buffer, discarding its contents, unless it
    // already has exactly that much storage
    void (*buffer_allocate)(void *driver, gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency);
    // Map the buffer for access from the CPU. offset and size are used only
    // by GPU_MAP_WRITE_DISCARD_RANGE and GPU_MAP_WRITE_DISCARD_ALL, the other
    // modes map the whole buffer.
    void *(*buffer_map)(void *driver, gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size);
    void (*buffer_unmap)(void *driver, gpu_buffer_t buffer);
    void (*buffer_copy)(void *driver, gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size);
    // Bind a uniform buffer to a slot, for use by pipelines, see GPUBinding
    void (*bind_uniform_buffer)(void *driver, uint32_t slot, gpu_buffer_t buffer);
    // }}}

    // Pipelines {{{
    // Create a pipeline from shader sources compiled for the shader target of
    // the driver. param_blocks describe its parameter blocks, see
    // GPUParamBlock, and are identified by their index in this array.
    // bindings are the binding slots of its textures and uniform blocks, see
    // GPUBinding. native_names maps Slang names to identifiers in the compiled
    // code, see GPUNativeName, and may be empty for targets that do not need
    // it. On failure last_error() contains the compiler output.
    gpu_pipeline_t (*pipeline_create)(
        void *driver,
        const GPUShaderSource *sources,
        size_t num_sources,
        const GPUParamBlock *param_blocks,
        size_t num_param_blocks,
        const GPUBinding *bindings,
        size_t num_bindings,
        const GPUNativeName *native_names,
        size_t num_native_names);
    void (*pipeline_destroy)(void *driver, gpu_pipeline_t pipeline);
    // Make a pipeline current, GPU_NULL_HANDLE for none
    void (*use_pipeline)(void *driver, gpu_pipeline_t pipeline);
    // All names below are names in the Slang source.
    // name is the name of the type of the uniform block. The size reported
    // by the driver is used to verify the layout from the reflection data.
    bool (*pipeline_uniform_block)(void *driver, gpu_pipeline_t pipeline, const char *name, GPUUniformBlockInfo *ans);
    // The location of the named vertex input, -1 if it is not used
    int32_t (*pipeline_attribute_location)(void *driver, gpu_pipeline_t pipeline, const char *name);
    // Set the contents of a parameter block of the pipeline, which must be
    // the current pipeline. block is the index of the block in the array
    // passed to pipeline_create() and data is laid out as described there.
    void (*set_params)(void *driver, gpu_pipeline_t pipeline, uint32_t block, const void *data, size_t size);
    // }}}

    // Vertex layouts {{{
    gpu_vertex_layout_t (*vertex_layout_create)(void *driver);
    void (*vertex_layout_destroy)(void *driver, gpu_vertex_layout_t layout);
    // Make a vertex layout current, GPU_NULL_HANDLE for none
    void (*bind_vertex_layout)(void *driver, gpu_vertex_layout_t layout);
    // Configure the vertex input at location to read components values of
    // type from buffer, starting at offset bytes and advancing by stride bytes
    // per vertex, or per instance_divisor instances if instance_divisor is
    // not zero. Also makes the layout current.
    void (*vertex_layout_set_attribute)(
        void *driver,
        gpu_vertex_layout_t layout,
        uint32_t location,
        gpu_buffer_t buffer,
        uint32_t components,
        GPUAttribType type,
        uint32_t stride,
        size_t offset,
        uint32_t instance_divisor);
    // }}}

    // Surfaces {{{
    // Some platforms, such as X11, require the visual of a window to be
    // chosen before the window is created. native must describe only the
    // display. Sets visual_id to the id of the visual the window must use,
    // or zero if the driver has no preference.
    bool (*choose_native_visual)(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id);
    // Create a surface to render into the native window. width and height
    // are the size of the window framebuffer in pixels. Does not change the
    // current surface.
    gpu_surface_t (*surface_create)(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height);
    // Destroy a surface, must be called before its native window is destroyed
    void (*surface_destroy)(void *driver, gpu_surface_t surface);
    // Make a surface current, all subsequent rendering goes to it.
    // GPU_NULL_HANDLE for no surface.
    bool (*make_surface_current)(void *driver, gpu_surface_t surface);
    gpu_surface_t (*get_current_surface)(void *driver);
    // Inform the driver that the framebuffer of the native window was resized
    void (*surface_resize)(void *driver, gpu_surface_t surface, uint32_t width, uint32_t height);
    // Present the rendered contents of the surface on screen
    bool (*surface_present)(void *driver, gpu_surface_t surface);
    // Set the number of display refreshes to wait for when presenting the
    // surface, zero to present immediately. The surface must be current.
    void (*surface_set_swap_interval)(void *driver, gpu_surface_t surface, int interval);
    // Inform the driver that the geometry or screen of the native window
    // changed, needed on platforms such as Cocoa where the driver must update
    // the drawable it renders into
    void (*surface_native_changed)(void *driver, gpu_surface_t surface);
    // Recreate the drawable of the surface, used to recover when the platform
    // invalidates it. Makes the surface current. Per surface state, such as
    // vertex layouts and render targets must be recreated.
    bool (*surface_recreate)(void *driver, gpu_surface_t surface);
    // Destroy all surfaces and release all connections to the windowing
    // system. Must be called before the windowing system is shut down.
    // After this only destroy() may be called.
    void (*release_native_resources)(void *driver);
    // }}}

    // Render targets {{{
    // Create a render target that draws into the specified texture. Does not
    // change the current render target. Use render_target_status() to check
    // that the render target is usable.
    gpu_render_target_t (*render_target_create)(void *driver, gpu_texture_t color_texture);
    void (*render_target_destroy)(void *driver, gpu_render_target_t target);
    // Make a render target current, GPU_NULL_HANDLE for the window surface
    void (*set_render_target)(void *driver, gpu_render_target_t target);
    gpu_render_target_t (*get_render_target)(void *driver);
    // NULL if the render target can be rendered to, otherwise a description of the problem
    const char *(*render_target_status)(void *driver, gpu_render_target_t target);
    // Fill the current render target, within the scissor rectangle if enabled, with the specified color
    void (*clear)(void *driver, float r, float g, float b, float a);
    void (*set_viewport)(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height);
    void (*get_viewport)(void *driver, int32_t ans[4]);
    void (*set_scissor)(void *driver, bool enabled, int32_t x, int32_t y, uint32_t width, uint32_t height);
    // When enabled linear colors output by shaders are encoded to sRGB, if the render target supports it
    void (*set_srgb_output)(void *driver, bool enabled);
    // Read back a rectangle of the current render target as tightly packed GPU_PIXELS_RGBA8
    void (*read_pixels)(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height, void *dst);
    // Copy a rectangle of the current render target to the origin of a GPU_FORMAT_RGBA8 texture
    void (*copy_to_texture)(void *driver, gpu_texture_t dst, int32_t x, int32_t y, uint32_t width, uint32_t height);
    // }}}

    // Drawing {{{
    // Draw a quad using the current pipeline, vertex layout and render
    // target. The vertex shader is invoked with vertex indices 0 to 3 and
    // must map them to the corners of the quad going around its perimeter,
    // so that 0, 1, 2 and 0, 2, 3 are the two triangles covering it. If
    // instance_count is zero the draw is not instanced.
    void (*draw_quad)(void *driver, uint32_t instance_count, GPUBlendMode blend);
    // }}}
} GPUDriverAPI;

// The type of the function exported by drivers as KITTY_GPU_DRIVER_ENTRY_POINT.
// api_version is the KITTY_GPU_API_VERSION the caller was compiled with. On
// success, fills in api and driver and returns true. On failure writes a null
// terminated error message to errbuf and returns false.
typedef bool (*gpu_driver_load_func)(
    uint32_t api_version, const GPUDriverInitParams *params, GPUDriverAPI *api, void **driver, char *errbuf, size_t errbuf_size);
