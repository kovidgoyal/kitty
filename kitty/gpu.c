/*
 * gpu.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "gpu.h"
#include "state.h"
#include "png-reader.h"
#include <dlfcn.h>
#include <math.h>
#include <string.h>

GPUDriver gpu_driver = {0};

// Driver loading {{{
static void
driver_log_error(const char *msg) {
    log_error("%s", msg);
}

static void
driver_debug_print(const char *msg) {
    timed_debug_print("%s\n", msg);
}

static void
driver_fatal(const char *msg) {
    fatal("%s", msg);
}

static void
driver_x11_push_error_trap(void) {
    if (glfwX11PushErrorTrap_impl) glfwX11PushErrorTrap();
}

static int
driver_x11_pop_error_trap(void) {
    return glfwX11PopErrorTrap_impl ? glfwX11PopErrorTrap() : 0;
}

const char *
load_gpu_driver(const char *path, bool debug_rendering) {
    static char errbuf[2048];
    if (gpu_driver.driver) return NULL;
    void *handle = dlopen(path, RTLD_LAZY | RTLD_LOCAL);
    if (!handle) {
        snprintf(errbuf, sizeof(errbuf), "Failed to load the GPU driver from %s with error: %s", path, dlerror());
        return errbuf;
    }
    dlerror();
    gpu_driver_load_func load = NULL;
    *(void **)(&load) = dlsym(handle, KITTY_GPU_DRIVER_ENTRY_POINT);
    if (!load) {
        snprintf(errbuf, sizeof(errbuf), "The GPU driver at %s does not export %s, with error: %s", path, KITTY_GPU_DRIVER_ENTRY_POINT, dlerror());
        dlclose(handle);
        return errbuf;
    }
    const GPUDriverInitParams params = {
        .debug_rendering = debug_rendering,
        .log_error = driver_log_error,
        .debug_print = driver_debug_print,
        .fatal = driver_fatal,
        .x11_push_error_trap = driver_x11_push_error_trap,
        .x11_pop_error_trap = driver_x11_pop_error_trap,
    };
    GPUDriverAPI api = {0};
    void *driver = NULL;
    char lerr[1024] = {0};
    if (!load(KITTY_GPU_API_VERSION, &params, &api, &driver, lerr, sizeof(lerr))) {
        snprintf(errbuf, sizeof(errbuf), "Failed to load the GPU driver from %s with error: %s", path, lerr);
        dlclose(handle);
        return errbuf;
    }
    if (api.api_version != KITTY_GPU_API_VERSION) {
        snprintf(errbuf, sizeof(errbuf), "The GPU driver at %s implements API version %u instead of %u", path, api.api_version, KITTY_GPU_API_VERSION);
        if (api.destroy) api.destroy(driver);
        dlclose(handle);
        return errbuf;
    }
    gpu_driver.api = api;
    gpu_driver.driver = driver;
    gpu_driver.dl_handle = handle;
    gpu_driver.initialized = false;
    return NULL;
}

void
initialize_gpu_driver(void) {
    if (gpu_driver.initialized) return;
    if (!gpu_driver.driver) fatal("Cannot initialize the GPU as no GPU driver has been loaded");
    if (!gpu_driver.api.initialize(gpu_driver.driver))
        fatal("Failed to initialize the GPU driver with error: %s", gpu_driver.api.last_error(gpu_driver.driver));
    gpu_driver.initialized = true;
}

void
unload_gpu_driver(void) {
    // The shared library is not unloaded since code registered with
    // atexit() or TLS destructors could still reference it
    if (gpu_driver.driver) gpu_driver.api.destroy(gpu_driver.driver);
    gpu_driver.driver = NULL;
    gpu_driver.initialized = false;
}
// }}}

// Viewports, framebuffers and textures {{{
void
set_gpu_viewport(unsigned w, unsigned h) {
    gpu_set_viewport(0, 0, w, h);
}

static struct {
    int32_t items[16][4];
    size_t used;
} saved_viewports;

void
save_viewport_using_bottom_left_origin(int32_t newx, int32_t newy, uint32_t width, uint32_t height) {
    if (saved_viewports.used >= arraysz(saved_viewports.items)) fatal("Too many nested saved viewports");
    int32_t *saved_viewport = saved_viewports.items[saved_viewports.used++];
    gpu_get_viewport(saved_viewport);
    gpu_set_viewport(newx, newy, width, height);
}

void
save_viewport_using_top_left_origin(int32_t newx, int32_t newy, uint32_t width, uint32_t height, int32_t full_framebuffer_height) {
    // Converts the viewport defined by the specified arguments which are
    // assumed to be in the usual co-ord system with origin at top left to the
    // GPU viewport co-ord system with origin at bottom left.
    // Use restore_viewport() to restore the viewport to what it was before.
    newy = full_framebuffer_height - (newy + (int32_t)height);
    save_viewport_using_bottom_left_origin(newx, newy, width, height);
}

void
restore_viewport(void) {
    if (!saved_viewports.used) fatal("Trying to restore a viewport when none is saved");
    const int32_t *saved_viewport = saved_viewports.items[--saved_viewports.used];
    gpu_set_viewport(saved_viewport[0], saved_viewport[1], (uint32_t)saved_viewport[2], (uint32_t)saved_viewport[3]);
}

void
enable_scissor_using_top_left_origin(Viewport vp, unsigned full_framebuffer_height) {
    int32_t newy = (int32_t)full_framebuffer_height - (int32_t)(vp.top + vp.height);
    gpu_set_scissor(true, vp.left, newy, vp.width, vp.height);
}

void
disable_scissor(void) {
    gpu_set_scissor(false, 0, 0, 0, 0);
}

void
draw_quad(bool blend, unsigned instance_count) {
    gpu_draw_quad(instance_count, blend ? GPU_BLEND_PREMULTIPLIED_ALPHA : GPU_BLEND_NONE);
}

// Resources can be freed by Python object destructors during interpreter
// shutdown, after the driver has been unloaded, in which case they are simply
// dropped, as the process is exiting.
void
free_texture(gpu_texture_t *tex) {
    if (gpu_driver.driver) gpu_texture_destroy(*tex);
    *tex = GPU_NULL_HANDLE;
}

void
free_framebuffer(gpu_render_target_t *fb) {
    if (gpu_driver.driver) gpu_render_target_destroy(*fb);
    *fb = GPU_NULL_HANDLE;
}

static gpu_render_target_t output_framebuffer = GPU_NULL_HANDLE;

void
bind_framebuffer_for_output(gpu_render_target_t fb) {
    gpu_set_render_target(fb ? fb : output_framebuffer);
}

void
set_framebuffer_to_use_for_output(gpu_render_target_t fb) {
    output_framebuffer = fb;
}

const char *
check_framebuffer_status(void) {
    return gpu_render_target_status(gpu_get_render_target());
}

static float
linear_to_srgb(float c) {
    return (c <= 0.0031308f) ? 12.92f * c : 1.055f * powf(c, 1.0f / 2.4f) - 0.055f;
}

void
save_texture_as_png(gpu_texture_t texture, const char *filename) {
    GPUTextureDesc desc;
    gpu_texture_get_desc(texture, &desc);
    const size_t width = desc.width, height = desc.height;
    size_t sz = sizeof(uint32_t) * width * height;
    RAII_ALLOC(uint32_t, data, malloc(sz));
    if (!data) fatal("Out of memory");
    if (!gpu_texture_read(texture, GPU_PIXELS_RGBA8, data, sz)) fatal("Failed to read texture with error: %s", gpu_last_error());
    // assume data is linear and pre-multiplied
    for (size_t i = 0; i < width * height; i++) {
        uint32_t px = data[i];
        uint8_t r = (px >> 0) & 0xFF;
        uint8_t g = (px >> 8) & 0xFF;
        uint8_t b = (px >> 16) & 0xFF;
        uint8_t a = (px >> 24) & 0xFF;
        float alpha = a / 255.0f;
        float rf = 0, gf = 0, bf = 0;
        if (alpha > 0.0f) {
            rf = (r / 255.0f) / alpha;
            gf = (g / 255.0f) / alpha;
            bf = (b / 255.0f) / alpha;
        }
        r = (uint8_t)(linear_to_srgb(rf) * 255);
        g = (uint8_t)(linear_to_srgb(gf) * 255);
        b = (uint8_t)(linear_to_srgb(bf) * 255);
        data[i] = (r << 0) | (g << 8) | (b << 16) | ((uint32_t)a << 24);
    }
    const char *png = png_from_32bit_rgba((char *)data, width, height, &sz, true);
    if (!sz) fatal("Failed to save PNG to %s with error: %s", filename, png);
    FILE *file = fopen(filename, "wb");
    if (!file) fatal("Failed to open %s for writing with error: %s", filename, strerror(errno));
    fwrite(png, 1, sz, file);
    fclose(file);
}
// }}}

// Programs {{{
typedef enum { PROGRAM_UNIFORM, PROGRAM_ATTRIBUTE, PROGRAM_BLOCK, PROGRAM_ARRAY } ProgramMetadataKind;
typedef struct ProgramMetadataEntry {
    ProgramMetadataKind kind;
    bool missing_location_logged;
    union {
        int32_t location;
        UniformBlock block;
        ArrayInformation array;
    };
} ProgramMetadataEntry;

static gpu_pipeline_t programs[MAX_GPU_PROGRAMS] = {0};

gpu_pipeline_t
program_pipeline(int program) {
    return programs[program];
}

void
set_program_pipeline(int program, gpu_pipeline_t pipeline) {
    if (programs[program]) gpu_pipeline_destroy(programs[program]);
    programs[program] = pipeline;
}

int32_t
attrib_location(int program, const char *name) {
    return gpu_pipeline_attribute_location(programs[program], name);
}

// Program metadata (uniform/attribute locations and UBO/array info, looked up by name) {{{
#define NAME program_metadata_map
#define KEY_TY const char *
#define VAL_TY ProgramMetadataEntry
#include "kitty-verstable.h"

static program_metadata_map program_layouts[MAX_GPU_PROGRAMS];
static bool program_layouts_initialized[MAX_GPU_PROGRAMS] = {0};

static void
clear_program_layout(int program) {
    if (!program_layouts_initialized[program]) return;
    program_metadata_map *m = program_layouts + program;
    vt_create_for_loop(program_metadata_map_itr, itr, m) free((void *)itr.data->key);
    vt_cleanup(m);
    program_layouts_initialized[program] = false;
}

void
free_program_layouts(void) {
    for (size_t i = 0; i < arraysz(program_layouts); i++) clear_program_layout((int)i);
}

static void
insert_program_metadata(int program, const char *name, ProgramMetadataEntry entry) {
    program_metadata_map_itr itr = vt_insert(program_layouts + program, strdup(name), entry);
    if (vt_is_end(itr)) fatal("Out of memory adding program metadata entry: %s", name);
}

static ProgramMetadataEntry *
program_metadata_entry(int program, const char *name, ProgramMetadataKind expected) {
    program_metadata_map_itr itr = vt_get(program_layouts + program, name);
    if (vt_is_end(itr)) fatal("No metadata entry named: %s for program: %d", name, program);
    if (itr.data->val.kind != expected) fatal("The metadata entry named: %s for program: %d is not of the expected kind", name, program);
    return &itr.data->val;
}

// Fetches a required item from a dict in the program metadata, setting a
// Python exception if it is missing or of the wrong type
static PyObject *
metadata_item(PyObject *d, const char *key, PyTypeObject *type) {
    PyObject *ans = PyDict_GetItemString(d, key);
    if (!ans) {
        PyErr_Format(PyExc_KeyError, "The shader program metadata has no %s entry", key);
        return NULL;
    }
    if (!PyObject_TypeCheck(ans, type)) {
        PyErr_Format(PyExc_TypeError, "The %s entry in the shader program metadata is not a %s", key, type->tp_name);
        return NULL;
    }
    return ans;
}

static bool
metadata_uint(PyObject *d, const char *key, int32_t *ans) {
    PyObject *v = metadata_item(d, key, &PyLong_Type);
    if (!v) return false;
    long val = PyLong_AsLong(v);
    if (PyErr_Occurred()) return false;
    *ans = (int32_t)val;
    return true;
}

// The metadata is generated from the reflection data produced by the Slang
// compiler, see program_metadata() in shaders/slang.py. It is backend neutral,
// all names are names from the Slang source.
bool
set_program_layout(int program, PyObject *metadata) {
    clear_program_layout(program);
    vt_init(program_layouts + program);
    program_layouts_initialized[program] = true;
    const gpu_pipeline_t pipeline = programs[program];

    PyObject *key, *val;
    Py_ssize_t pos;

    PyObject *inputs = metadata_item(metadata, "inputs", &PyDict_Type);
    if (!inputs) return false;
    pos = 0;
    while (PyDict_Next(inputs, &pos, &key, &val)) {
        ProgramMetadataEntry e = {.kind = PROGRAM_ATTRIBUTE, .location = (int32_t)PyLong_AsLong(val)};
        if (PyErr_Occurred()) return false;
        insert_program_metadata(program, PyUnicode_AsUTF8(key), e);
    }

    PyObject *uniforms = metadata_item(metadata, "uniforms", &PyList_Type);
    if (!uniforms) return false;
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(uniforms); i++) {
        const char *name = PyUnicode_AsUTF8(PyList_GET_ITEM(uniforms, i));
        if (!name) return false;
        ProgramMetadataEntry e = {.kind = PROGRAM_UNIFORM, .location = gpu_pipeline_uniform_slot(pipeline, name)};
        insert_program_metadata(program, name, e);
    }

    PyObject *blocks = metadata_item(metadata, "blocks", &PyDict_Type);
    if (!blocks) return false;
    pos = 0;
    while (PyDict_Next(blocks, &pos, &key, &val)) {
        const char *block_name = PyUnicode_AsUTF8(key);
        if (!block_name) return false;
        int32_t size;
        if (!metadata_uint(val, "size", &size)) return false;
        GPUUniformBlockInfo info;
        if (!gpu_pipeline_uniform_block(pipeline, block_name, &info)) {
            PyErr_Format(PyExc_ValueError, "The GPU program: %d has no uniform block: %s with error: %s", program, block_name, gpu_last_error());
            return false;
        }
        // The layout of the block is taken from the reflection data, so
        // verify that it matches what the driver actually uses
        if ((uint32_t)size != info.size) {
            PyErr_Format(
                PyExc_ValueError,
                "The uniform block: %s in GPU program: %d has size %u according to the GPU driver but %d according to the shader reflection data",
                block_name,
                program,
                info.size,
                size);
            return false;
        }
        ProgramMetadataEntry be = {.kind = PROGRAM_BLOCK, .block = {.index = (int32_t)info.index, .size = size}};
        insert_program_metadata(program, block_name, be);

        PyObject *arrays = metadata_item(val, "arrays", &PyDict_Type);
        if (!arrays) return false;
        PyObject *akey, *aval;
        Py_ssize_t apos = 0;
        while (PyDict_Next(arrays, &apos, &akey, &aval)) {
            const char *array_name = PyUnicode_AsUTF8(akey);
            if (!array_name) return false;
            ArrayInformation ai;
            if (!metadata_uint(aval, "offset", &ai.offset) || !metadata_uint(aval, "stride", &ai.stride) || !metadata_uint(aval, "count", &ai.size))
                return false;
            ProgramMetadataEntry ae = {.kind = PROGRAM_ARRAY, .array = ai};
            insert_program_metadata(program, array_name, ae);
        }
    }
    return true;
}

int32_t
program_uniform_location(int program, const char *name) {
    ProgramMetadataEntry *e = program_metadata_entry(program, name, PROGRAM_UNIFORM);
    // Setting a uniform at location -1 is a silent no-op, so a uniform the driver
    // does not report as active leaves whatever value it was last set to,
    // rendering incorrectly with no other indication that anything is wrong.
    if (e->location < 0 && !e->missing_location_logged) {
        e->missing_location_logged = true;
        log_error("The uniform: %s is not active in the linked GPU program: %d. Setting it will have no effect and rendering may be incorrect.", name, program);
    }
    return e->location;
}

int32_t
try_program_uniform_location(int program, const char *name) {
    program_metadata_map_itr itr = vt_get(program_layouts + program, name);
    if (vt_is_end(itr) || itr.data->val.kind != PROGRAM_UNIFORM) return -1;
    return itr.data->val.location;
}

int32_t
program_attribute_location(int program, const char *name) {
    return program_metadata_entry(program, name, PROGRAM_ATTRIBUTE)->location;
}

UniformBlock
program_uniform_block(int program, const char *name) {
    return program_metadata_entry(program, name, PROGRAM_BLOCK)->block;
}

ArrayInformation
program_uniform_array(int program, const char *name) {
    return program_metadata_entry(program, name, PROGRAM_ARRAY)->array;
}
// }}}

void
bind_program_uniform_block(int program, const char *name, uint32_t binding_point) {
    UniformBlock b = program_uniform_block(program, name);
    gpu_pipeline_bind_uniform_block(programs[program], (uint32_t)b.index, binding_point);
}

void
bind_program(int program) {
    gpu_use_pipeline(programs[program]);
}

void
unbind_program(void) {
    gpu_use_pipeline(GPU_NULL_HANDLE);
}
// }}}

// Vertex Array Objects (VAO) {{{
typedef struct {
    gpu_vertex_layout_t layout;
    size_t num_buffers;
    gpu_buffer_t buffers[10];
} VAO;

static VAO vaos[4 * MAX_CHILDREN + 10] = {{0}};

ssize_t
create_vao(void) {
    for (size_t i = 0; i < arraysz(vaos); i++) {
        if (!vaos[i].layout) {
            gpu_vertex_layout_t layout = gpu_vertex_layout_create();
            if (!layout) fatal("Failed to create a vertex layout with error: %s", gpu_last_error());
            vaos[i].layout = layout;
            vaos[i].num_buffers = 0;
            gpu_bind_vertex_layout(layout);
            return i;
        }
    }
    fatal("Too many VAOs");
    return -1;
}

size_t
add_buffer_to_vao(ssize_t vao_idx, GPUBufferKind kind) {
    VAO *vao = vaos + vao_idx;
    if (vao->num_buffers >= arraysz(vao->buffers)) fatal("Too many buffers in a single VAO");
    gpu_buffer_t buf = gpu_buffer_create(kind);
    if (!buf) fatal("Failed to create a GPU buffer with error: %s", gpu_last_error());
    vao->buffers[vao->num_buffers++] = buf;
    return vao->num_buffers - 1;
}

void
add_attribute_to_vao(ssize_t vao_idx, int location, uint32_t components, GPUAttribType type, uint32_t stride, size_t offset, uint32_t divisor) {
    VAO *vao = vaos + vao_idx;
    if (!vao->num_buffers) fatal("You must create a buffer for this attribute first");
    set_vao_attribute(vao_idx, vao->num_buffers - 1, location, components, type, stride, offset, divisor);
}

void
set_vao_attribute(ssize_t vao_idx, size_t buffer_idx, int location, uint32_t components, GPUAttribType type, uint32_t stride, size_t offset, uint32_t divisor) {
    VAO *vao = vaos + vao_idx;
    gpu_vertex_layout_set_attribute(vao->layout, (uint32_t)location, vao->buffers[buffer_idx], components, type, stride, offset, divisor);
}

void
remove_vao(ssize_t vao_idx) {
    VAO *vao = vaos + vao_idx;
    const bool loaded = gpu_driver.driver != NULL; // see free_texture()
    while (vao->num_buffers) {
        vao->num_buffers--;
        if (loaded) gpu_buffer_destroy(vao->buffers[vao->num_buffers]);
        vao->buffers[vao->num_buffers] = GPU_NULL_HANDLE;
    }
    if (loaded) gpu_vertex_layout_destroy(vao->layout);
    vao->layout = GPU_NULL_HANDLE;
}

void
bind_vertex_array(ssize_t vao_idx) {
    gpu_bind_vertex_layout(vaos[vao_idx].layout);
}

void
unbind_vertex_array(void) {
    gpu_bind_vertex_layout(GPU_NULL_HANDLE);
}

void
alloc_vao_buffer(ssize_t vao_idx, size_t size, size_t bufnum, GPUUpdateFrequency frequency) {
    gpu_buffer_allocate(vaos[vao_idx].buffers[bufnum], size, frequency);
}

void *
map_vao_buffer_for_write_only(ssize_t vao_idx, size_t bufnum, size_t offset, size_t size) {
    return gpu_buffer_map(vaos[vao_idx].buffers[bufnum], GPU_MAP_WRITE_DISCARD_RANGE, offset, size);
}

void *
alloc_and_map_vao_buffer(ssize_t vao_idx, size_t size, size_t bufnum) {
    alloc_vao_buffer(vao_idx, size, bufnum, GPU_UPDATE_RARELY);
    return gpu_buffer_map(vaos[vao_idx].buffers[bufnum], GPU_MAP_WRITE, 0, size);
}

void *
alloc_and_map_vao_buffer_for_full_rewrite(ssize_t vao_idx, size_t size, size_t bufnum) {
    // The previous contents are discarded so the driver can hand out fresh
    // storage instead of waiting for the GPU to finish reading the old data.
    // The caller MUST write every byte of the mapped range, any byte not
    // written is undefined.
    alloc_vao_buffer(vao_idx, size, bufnum, GPU_UPDATE_EVERY_USE);
    return gpu_buffer_map(vaos[vao_idx].buffers[bufnum], GPU_MAP_WRITE_DISCARD_ALL, 0, size);
}

const void *
map_vao_buffer_for_reading(ssize_t vao_idx, size_t bufnum) {
    return gpu_buffer_map(vaos[vao_idx].buffers[bufnum], GPU_MAP_READ, 0, 0);
}

void
unmap_vao_buffer(ssize_t vao_idx, size_t bufnum) {
    gpu_buffer_unmap(vaos[vao_idx].buffers[bufnum]);
}

void
bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, uint32_t binding_point) {
    gpu_bind_uniform_buffer(binding_point, vaos[vao_idx].buffers[bufnum]);
}

void
copy_vao_buffer_region(ssize_t vao_idx, size_t src_bufnum, size_t src_off, size_t dst_bufnum, size_t dst_off, size_t size) {
    gpu_buffer_copy(vaos[vao_idx].buffers[src_bufnum], src_off, vaos[vao_idx].buffers[dst_bufnum], dst_off, size);
}
// }}}
