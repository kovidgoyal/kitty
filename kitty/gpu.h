/*
 * gpu.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Loading of the GPU driver and thin, type safe wrappers around the driver
// API defined in gpu/api.h, plus the higher level helpers used by the rendering
// code in shaders.c.

#pragma once

#include "data-types.h"
#include "../gpu/api.h"

typedef struct GPUDriver {
    GPUDriverAPI api;
    void *driver;
    void *dl_handle;
    bool initialized;
} GPUDriver;

extern GPUDriver gpu_driver;

// Load the GPU driver shared library at path. Returns NULL on success or an error message.
const char *load_gpu_driver(const char *path, bool debug_rendering);

// Choosing between GPU drivers {{{
// The drivers to try, in order of preference, see the gpu_driver option
typedef struct GPUDriverCandidate {
    const char *name, *path;
} GPUDriverCandidate;

// Remember the drivers to try. Copies the strings.
bool set_gpu_driver_candidates(const GPUDriverCandidate *candidates, size_t count, bool debug_rendering);
// Unload the current driver, if any, and load the next candidate that can
// render to windows on the specified display, see connect() in gpu/api.h.
// Returns NULL on success or a description of why every remaining
// candidate failed. Must be called before any GPU resources are created.
const char *load_next_gpu_driver(const GPUNativeWindow *display);
// Whether there are candidates that have not yet been tried
bool has_untried_gpu_drivers(void);
// }}}
// Must be called once a surface has been created and made current, before any
// other GPU functions, except the surface functions, are used
void initialize_gpu_driver(void);
void unload_gpu_driver(void);

// Driver API wrappers {{{
#define D gpu_driver.driver
#define A gpu_driver.api

static inline const char *
gpu_driver_name(void) {
    return gpu_driver.driver ? A.name : "";
}

static inline const char *
gpu_shader_target(void) {
    return gpu_driver.driver ? A.shader_target(D) : "";
}

static inline const char *
gpu_last_error(void) {
    return A.last_error(D);
}

static inline const char *
gpu_version_string(void) {
    return gpu_driver.initialized ? A.version_string(D) : "";
}

static inline void
gpu_get_capabilities(GPUCapabilities *ans) {
    A.get_capabilities(D, ans);
}

static inline bool
gpu_choose_native_visual(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id) {
    return A.choose_native_visual(D, native, config, visual_id);
}

static inline gpu_surface_t
gpu_surface_create(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height) {
    return A.surface_create(D, native, config, width, height);
}

static inline void
gpu_surface_destroy(gpu_surface_t surface) {
    A.surface_destroy(D, surface);
}

static inline bool
gpu_make_surface_current(gpu_surface_t surface) {
    return A.make_surface_current(D, surface);
}

static inline gpu_surface_t
gpu_get_current_surface(void) {
    return A.get_current_surface(D);
}

static inline void
gpu_surface_resize(gpu_surface_t surface, uint32_t width, uint32_t height) {
    A.surface_resize(D, surface, width, height);
}

static inline bool
gpu_surface_present(gpu_surface_t surface) {
    return A.surface_present(D, surface);
}

static inline void
gpu_surface_set_swap_interval(gpu_surface_t surface, int interval) {
    A.surface_set_swap_interval(D, surface, interval);
}

static inline void
gpu_surface_native_changed(gpu_surface_t surface) {
    A.surface_native_changed(D, surface);
}

static inline bool
gpu_surface_recreate(gpu_surface_t surface) {
    return A.surface_recreate(D, surface);
}

static inline void
gpu_release_native_resources(void) {
    A.release_native_resources(D);
}

static inline gpu_texture_t
gpu_texture_create(const GPUTextureDesc *desc, const GPUPixelData *initial) {
    return A.texture_create(D, desc, initial);
}

static inline bool
gpu_texture_reset(gpu_texture_t texture, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    return A.texture_reset(D, texture, desc, initial);
}

static inline void
gpu_texture_destroy(gpu_texture_t texture) {
    A.texture_destroy(D, texture);
}

static inline void
gpu_texture_upload(gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels) {
    A.texture_upload(D, texture, x, y, layer, width, height, pixels);
}

static inline void
gpu_texture_copy(gpu_texture_t src, gpu_texture_t dst) {
    A.texture_copy(D, src, dst);
}

static inline bool
gpu_texture_read(gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size) {
    return A.texture_read(D, texture, layout, dst, dst_size);
}

static inline void
gpu_texture_get_desc(gpu_texture_t texture, GPUTextureDesc *ans) {
    A.texture_get_desc(D, texture, ans);
}

static inline void
gpu_bind_texture(uint32_t unit, gpu_texture_t texture) {
    A.bind_texture(D, unit, texture);
}

static inline gpu_buffer_t
gpu_buffer_create(GPUBufferKind kind) {
    return A.buffer_create(D, kind);
}

static inline void
gpu_buffer_destroy(gpu_buffer_t buffer) {
    A.buffer_destroy(D, buffer);
}

static inline void
gpu_buffer_allocate(gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency) {
    A.buffer_allocate(D, buffer, size, frequency);
}

static inline void *
gpu_buffer_map(gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size) {
    return A.buffer_map(D, buffer, mode, offset, size);
}

static inline void
gpu_buffer_unmap(gpu_buffer_t buffer) {
    A.buffer_unmap(D, buffer);
}

static inline void
gpu_buffer_copy(gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size) {
    A.buffer_copy(D, src, src_offset, dst, dst_offset, size);
}

static inline void
gpu_bind_uniform_buffer(uint32_t binding_point, gpu_buffer_t buffer) {
    A.bind_uniform_buffer(D, binding_point, buffer);
}

static inline gpu_pipeline_t
gpu_pipeline_create(
    const GPUShaderSource *sources,
    size_t num_sources,
    const GPUParamBlock *param_blocks,
    size_t num_param_blocks,
    const GPUBinding *bindings,
    size_t num_bindings,
    const GPUNativeName *native_names,
    size_t num_native_names) {
    return A.pipeline_create(D, sources, num_sources, param_blocks, num_param_blocks, bindings, num_bindings, native_names, num_native_names);
}

static inline void
gpu_set_params(gpu_pipeline_t pipeline, uint32_t block, const void *data, size_t size) {
    A.set_params(D, pipeline, block, data, size);
}

static inline void
gpu_pipeline_destroy(gpu_pipeline_t pipeline) {
    A.pipeline_destroy(D, pipeline);
}

static inline void
gpu_use_pipeline(gpu_pipeline_t pipeline) {
    A.use_pipeline(D, pipeline);
}

static inline bool
gpu_pipeline_uniform_block(gpu_pipeline_t pipeline, const char *name, GPUUniformBlockInfo *ans) {
    return A.pipeline_uniform_block(D, pipeline, name, ans);
}

static inline int32_t
gpu_pipeline_attribute_location(gpu_pipeline_t pipeline, const char *name) {
    return A.pipeline_attribute_location(D, pipeline, name);
}

static inline gpu_vertex_layout_t
gpu_vertex_layout_create(void) {
    return A.vertex_layout_create(D);
}

static inline void
gpu_vertex_layout_destroy(gpu_vertex_layout_t layout) {
    A.vertex_layout_destroy(D, layout);
}

static inline void
gpu_bind_vertex_layout(gpu_vertex_layout_t layout) {
    A.bind_vertex_layout(D, layout);
}

static inline void
gpu_vertex_layout_set_attribute(
    gpu_vertex_layout_t layout,
    uint32_t location,
    gpu_buffer_t buffer,
    uint32_t components,
    GPUAttribType type,
    uint32_t stride,
    size_t offset,
    uint32_t instance_divisor) {
    A.vertex_layout_set_attribute(D, layout, location, buffer, components, type, stride, offset, instance_divisor);
}

static inline gpu_render_target_t
gpu_render_target_create(gpu_texture_t color_texture) {
    return A.render_target_create(D, color_texture);
}

static inline void
gpu_render_target_destroy(gpu_render_target_t target) {
    A.render_target_destroy(D, target);
}

static inline void
gpu_set_render_target(gpu_render_target_t target) {
    A.set_render_target(D, target);
}

static inline gpu_render_target_t
gpu_get_render_target(void) {
    return A.get_render_target(D);
}

static inline const char *
gpu_render_target_status(gpu_render_target_t target) {
    return A.render_target_status(D, target);
}

static inline void
gpu_clear(float r, float g, float b, float a) {
    A.clear(D, r, g, b, a);
}

static inline void
gpu_set_viewport(int32_t x, int32_t y, uint32_t width, uint32_t height) {
    A.set_viewport(D, x, y, width, height);
}

static inline void
gpu_get_viewport(int32_t ans[4]) {
    A.get_viewport(D, ans);
}

static inline void
gpu_set_scissor(bool enabled, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    A.set_scissor(D, enabled, x, y, width, height);
}

static inline void
gpu_set_srgb_output(bool enabled) {
    A.set_srgb_output(D, enabled);
}

static inline void
gpu_read_pixels(int32_t x, int32_t y, uint32_t width, uint32_t height, void *dst) {
    A.read_pixels(D, x, y, width, height, dst);
}

static inline void
gpu_copy_to_texture(gpu_texture_t dst, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    A.copy_to_texture(D, dst, x, y, width, height);
}

static inline void
gpu_draw_quad(uint32_t instance_count, GPUBlendMode blend) {
    A.draw_quad(D, instance_count, blend);
}
#undef D
#undef A
// }}}

// Higher level helpers {{{
typedef struct Viewport {
    unsigned left, top, width, height;
} Viewport;

void set_gpu_viewport(unsigned w, unsigned h);
// Co-ordinates are relative to the top left corner of the render target, see gpu/api.h
// Set the viewport, saving the current one, which is restored by restore_viewport()
void save_viewport(int32_t x, int32_t y, uint32_t width, uint32_t height);
void restore_viewport(void);
void enable_scissor(Viewport);
void disable_scissor(void);
// Draw a quad, blending pre-multiplied colors if blend is true
void draw_quad(bool blend, unsigned instance_count);
void free_texture(gpu_texture_t *tex);
void free_framebuffer(gpu_render_target_t *fb);
// The render target used for output, render target zero is redirected to
// the target set with set_framebuffer_to_use_for_output()
void bind_framebuffer_for_output(gpu_render_target_t fb);
void set_framebuffer_to_use_for_output(gpu_render_target_t fb);
const char *check_framebuffer_status(void);
void save_texture_as_png(gpu_texture_t texture, const char *filename);
// }}}

// Programs {{{
typedef struct UniformBlock {
    int32_t size, index;
    uint32_t slot; // the binding slot, see bind_uniform_buffer()
} UniformBlock;

typedef struct ArrayInformation {
    int32_t offset; // byte offset from start of UBO
    int32_t stride; // element stride in bytes
    int32_t size;   // number of elements
} ArrayInformation;

#define MAX_GPU_PROGRAMS 64

gpu_pipeline_t program_pipeline(int program);
// Free the pipeline of the program, if any
void free_program(int program);
// Create the pipeline for program from shader sources compiled for the shader
// target of the driver and their metadata, see program_metadata() in
// shaders/slang.py. Returns false with a Python exception set on failure.
bool compile_gpu_program(int program, const char *vertex, size_t vertex_size, const char *fragment, size_t fragment_size, PyObject *metadata);
int32_t attrib_location(int program, const char *name);
void free_program_layouts(void);
// Parameters, the push constant block holding the uniform parameters and the
// pipeline constant blocks of a program. Values are written into memory owned by
// kitty and passed to the driver before the next draw call using the
// program. A handle identifies a parameter of a program, negative handles
// are ignored by the setters.
int32_t program_param(int program, const char *name);
// As above, but returns -1 without logging an error if the program has no such parameter
int32_t try_program_param(int program, const char *name);
void param_floats(int32_t handle, uint32_t components, uint32_t count, const float *values);
void param_1f(int32_t handle, float a);
void param_2f(int32_t handle, float a, float b);
void param_3f(int32_t handle, float a, float b, float c);
void param_4f(int32_t handle, float a, float b, float c, float d);
void param_1i(int32_t handle, int32_t a);
void param_1ui(int32_t handle, uint32_t a);
int32_t program_attribute_location(int program, const char *name);
UniformBlock program_uniform_block(int program, const char *name);
ArrayInformation program_uniform_array(int program, const char *name);
// The binding slot of the named texture of the program, see bind_texture()
uint32_t program_texture_slot(int program, const char *name);
// As above, returns false if the program has no such texture
bool try_program_texture_slot(int program, const char *name, uint32_t *slot);
void bind_program(int program);
void unbind_program(void);
// }}}

// Vertex array objects: a vertex layout together with the buffers it uses {{{
ssize_t create_vao(void);
size_t add_buffer_to_vao(ssize_t vao_idx, GPUBufferKind kind);
// Add an attribute reading from the most recently added buffer
void add_attribute_to_vao(ssize_t vao_idx, int location, uint32_t components, GPUAttribType type, uint32_t stride, size_t offset, uint32_t divisor);
void
set_vao_attribute(ssize_t vao_idx, size_t buffer_idx, int location, uint32_t components, GPUAttribType type, uint32_t stride, size_t offset, uint32_t divisor);
void remove_vao(ssize_t vao_idx);
void bind_vertex_array(ssize_t vao_idx);
void unbind_vertex_array(void);
void alloc_vao_buffer(ssize_t vao_idx, size_t size, size_t bufnum, GPUUpdateFrequency frequency);
void *alloc_and_map_vao_buffer(ssize_t vao_idx, size_t size, size_t bufnum);
// Discards the old contents, the caller must write every byte of the buffer
void *alloc_and_map_vao_buffer_for_full_rewrite(ssize_t vao_idx, size_t size, size_t bufnum);
void *map_vao_buffer_for_write_only(ssize_t vao_idx, size_t bufnum, size_t offset, size_t size);
const void *map_vao_buffer_for_reading(ssize_t vao_idx, size_t bufnum);
void unmap_vao_buffer(ssize_t vao_idx, size_t bufnum);
void bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, uint32_t binding_point);
void copy_vao_buffer_region(ssize_t vao_idx, size_t src_bufnum, size_t src_off, size_t dst_bufnum, size_t dst_off, size_t size);
// }}}
