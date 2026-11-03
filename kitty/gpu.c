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

static struct {
    GPUDriverCandidate items[8];
    size_t count, next;
    bool debug_rendering;
} candidates = {0};

bool
set_gpu_driver_candidates(const GPUDriverCandidate *items, size_t count, bool debug_rendering) {
    for (size_t i = 0; i < candidates.count; i++) {
        free((void *)candidates.items[i].name);
        free((void *)candidates.items[i].path);
    }
    zero_at_ptr(&candidates);
    candidates.debug_rendering = debug_rendering;
    for (size_t i = 0; i < count && i < arraysz(candidates.items); i++) {
        GPUDriverCandidate *c = candidates.items + candidates.count++;
        c->name = strdup(items[i].name);
        c->path = strdup(items[i].path);
        if (!c->name || !c->path) return false;
    }
    return true;
}

bool
has_untried_gpu_drivers(void) {
    return candidates.next < candidates.count;
}

const char *
load_next_gpu_driver(const GPUNativeWindow *display) {
    static char errbuf[8192];
    size_t pos = 0;
    errbuf[0] = 0;
#define add_error(...) \
    if (pos < sizeof(errbuf)) pos += snprintf(errbuf + pos, sizeof(errbuf) - pos, __VA_ARGS__);
    if (gpu_driver.driver) {
        if (gpu_driver.initialized) fatal("Cannot switch GPU drivers after the driver has been initialized");
        gpu_release_native_resources();
        unload_gpu_driver();
    }
    if (!candidates.count) {
        add_error("No GPU drivers are available");
        return errbuf;
    }
    while (candidates.next < candidates.count) {
        const GPUDriverCandidate *c = candidates.items + candidates.next++;
        const char *err = load_gpu_driver(c->path, candidates.debug_rendering);
        if (!err) {
            if (gpu_driver.api.connect(gpu_driver.driver, display)) {
                if (candidates.debug_rendering) timed_debug_print("Using the %s GPU driver\n", c->name);
                return NULL;
            }
            err = gpu_last_error();
        }
        if (candidates.debug_rendering) timed_debug_print("The %s GPU driver is not usable: %s\n", c->name, err);
        add_error("%sThe %s GPU driver is not usable: %s", pos ? "\n" : "", c->name, err);
        if (gpu_driver.driver) unload_gpu_driver();
    }
#undef add_error
    return errbuf;
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
save_viewport(int32_t newx, int32_t newy, uint32_t width, uint32_t height) {
    if (saved_viewports.used >= arraysz(saved_viewports.items)) fatal("Too many nested saved viewports");
    int32_t *saved_viewport = saved_viewports.items[saved_viewports.used++];
    gpu_get_viewport(saved_viewport);
    gpu_set_viewport(newx, newy, width, height);
}

void
restore_viewport(void) {
    if (!saved_viewports.used) fatal("Trying to restore a viewport when none is saved");
    const int32_t *saved_viewport = saved_viewports.items[--saved_viewports.used];
    gpu_set_viewport(saved_viewport[0], saved_viewport[1], (uint32_t)saved_viewport[2], (uint32_t)saved_viewport[3]);
}

void
enable_scissor(Viewport vp) {
    gpu_set_scissor(true, vp.left, vp.top, vp.width, vp.height);
}

void
disable_scissor(void) {
    gpu_set_scissor(false, 0, 0, 0, 0);
}

static void flush_params(void);

void
draw_quad(bool blend, unsigned instance_count) {
    flush_params();
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
    const char *png = png_from_32bit_rgba((char *)data, width, height, &sz, false);
    if (!sz) fatal("Failed to save PNG to %s with error: %s", filename, png);
    FILE *file = fopen(filename, "wb");
    if (!file) fatal("Failed to open %s for writing with error: %s", filename, strerror(errno));
    fwrite(png, 1, sz, file);
    fclose(file);
}
// }}}

// Programs {{{
typedef enum { PROGRAM_PARAM, PROGRAM_ATTRIBUTE, PROGRAM_BLOCK, PROGRAM_ARRAY, PROGRAM_TEXTURE } ProgramMetadataKind;
typedef struct ProgramMetadataEntry {
    ProgramMetadataKind kind;
    union {
        int32_t location; // the param ref index for PROGRAM_PARAM, the location for PROGRAM_ATTRIBUTE and the slot for PROGRAM_TEXTURE
        UniformBlock block;
        ArrayInformation array;
    };
} ProgramMetadataEntry;

// Parameter blocks, see GPUParamBlock {{{
typedef struct ParamField {
    char *name;
    uint32_t offset, components, count, stride;
    GPUParamScalar scalar;
    bool type_error_logged;
} ParamField;

typedef struct ParamBlock {
    char *name; // NULL for the push constant block
    int32_t slot;
    uint32_t size;
    uint8_t *data; // the contents, laid out as described by the fields
    bool dirty;    // the contents have changed since they were last passed to the driver
    ParamField *fields;
    size_t num_fields;
} ParamBlock;

// The field with a given name
typedef struct ParamRef {
    uint16_t block, field;
} ParamRef;

typedef struct ProgramParams {
    ParamBlock *blocks;
    size_t num_blocks;
    ParamRef *refs;
    size_t num_refs;
} ProgramParams;
// }}}

static gpu_pipeline_t programs[MAX_GPU_PROGRAMS] = {0};
static ProgramParams program_params[MAX_GPU_PROGRAMS] = {0};
static int current_program = -1;

static void
free_program_params(ProgramParams *pp) {
    for (size_t b = 0; b < pp->num_blocks; b++) {
        ParamBlock *pb = pp->blocks + b;
        for (size_t i = 0; i < pb->num_fields; i++) free(pb->fields[i].name);
        free(pb->fields);
        free(pb->name);
        free(pb->data);
    }
    free(pp->blocks);
    free(pp->refs);
    zero_at_ptr(pp);
}

gpu_pipeline_t
program_pipeline(int program) {
    return programs[program];
}

int32_t
attrib_location(int program, const char *name) {
    return gpu_pipeline_attribute_location(programs[program], name);
}

// Program metadata (parameter, attribute and texture locations and UBO/array info, looked up by name) {{{
#define NAME program_metadata_map
#define KEY_TY const char *
#define VAL_TY ProgramMetadataEntry
#include "kitty-verstable.h"

static program_metadata_map program_layouts[MAX_GPU_PROGRAMS];
static bool program_layouts_initialized[MAX_GPU_PROGRAMS] = {0};

static void
clear_program_layout(int program) {
    free_program_params(program_params + program);
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

void
free_program(int program) {
    if (current_program == program) current_program = -1;
    if (programs[program]) gpu_pipeline_destroy(programs[program]);
    programs[program] = GPU_NULL_HANDLE;
    clear_program_layout(program);
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

static bool
find_program_metadata(int program, const char *name, ProgramMetadataKind expected, ProgramMetadataEntry **ans) {
    if (!program_layouts_initialized[program]) return false;
    program_metadata_map_itr itr = vt_get(program_layouts + program, name);
    if (vt_is_end(itr) || itr.data->val.kind != expected) return false;
    *ans = &itr.data->val;
    return true;
}
// }}}

// Parsing the metadata {{{
// Fetches a required item from a dict in the program metadata, setting a
// Python exception if it is missing or of the wrong type
static PyObject *
metadata_item(PyObject *d, const char *key, PyTypeObject *type) {
    if (!PyDict_Check(d)) {
        PyErr_Format(PyExc_TypeError, "Looking up %s in shader program metadata that is not a dict", key);
        return NULL;
    }
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
metadata_int(PyObject *d, const char *key, int32_t *ans) {
    PyObject *v = metadata_item(d, key, &PyLong_Type);
    if (!v) return false;
    long val = PyLong_AsLong(v);
    if (PyErr_Occurred()) return false;
    *ans = (int32_t)val;
    return true;
}

static bool
metadata_uint(PyObject *d, const char *key, uint32_t *ans) {
    int32_t v;
    if (!metadata_int(d, key, &v)) return false;
    if (v < 0) {
        PyErr_Format(PyExc_ValueError, "The %s entry in the shader program metadata is negative", key);
        return false;
    }
    *ans = (uint32_t)v;
    return true;
}

static const char *
metadata_str(PyObject *d, const char *key) {
    PyObject *v = metadata_item(d, key, &PyUnicode_Type);
    return v ? PyUnicode_AsUTF8(v) : NULL;
}

static bool
parse_scalar(const char *s, GPUParamScalar *ans) {
    if (strcmp(s, "float") == 0) *ans = GPU_PARAM_FLOAT;
    else if (strcmp(s, "int") == 0) *ans = GPU_PARAM_INT;
    else if (strcmp(s, "uint") == 0) *ans = GPU_PARAM_UINT;
    else if (strcmp(s, "bool") == 0) *ans = GPU_PARAM_BOOL;
    else {
        PyErr_Format(PyExc_ValueError, "Unknown shader parameter type: %s", s);
        return false;
    }
    return true;
}

static bool
parse_param_blocks(PyObject *metadata, ProgramParams *pp) {
    PyObject *blocks = metadata_item(metadata, "param_blocks", &PyList_Type);
    if (!blocks) return false;
    const size_t num_blocks = (size_t)PyList_GET_SIZE(blocks);
    if (!num_blocks) return true;
    if (!(pp->blocks = calloc(num_blocks, sizeof(ParamBlock)))) goto oom;
    pp->num_blocks = num_blocks;
    for (size_t b = 0; b < num_blocks; b++) {
        PyObject *src = PyList_GET_ITEM(blocks, b);
        ParamBlock *pb = pp->blocks + b;
        const char *name = metadata_str(src, "name");
        if (!name) return false;
        if (name[0] && !(pb->name = strdup(name))) goto oom;
        if (!metadata_int(src, "slot", &pb->slot) || !metadata_uint(src, "size", &pb->size)) return false;
        if (!(pb->data = calloc(1, MAX(1u, pb->size)))) goto oom;
        PyObject *fields = metadata_item(src, "fields", &PyList_Type);
        if (!fields) return false;
        pb->num_fields = (size_t)PyList_GET_SIZE(fields);
        if (pb->num_fields && !(pb->fields = calloc(pb->num_fields, sizeof(ParamField)))) goto oom;
        for (size_t i = 0; i < pb->num_fields; i++) {
            PyObject *fsrc = PyList_GET_ITEM(fields, i);
            ParamField *f = pb->fields + i;
            const char *fname = metadata_str(fsrc, "name"), *scalar = metadata_str(fsrc, "scalar");
            if (!fname || !scalar || !parse_scalar(scalar, &f->scalar)) return false;
            if (!(f->name = strdup(fname))) goto oom;
            if (!metadata_uint(fsrc, "offset", &f->offset) || !metadata_uint(fsrc, "components", &f->components) || !metadata_uint(fsrc, "count", &f->count) ||
                !metadata_uint(fsrc, "stride", &f->stride))
                return false;
            if (f->components < 1 || f->components > 4 || !f->count ||
                (uint64_t)f->offset + (uint64_t)(f->count - 1) * f->stride + 4u * f->components > pb->size) {
                PyErr_Format(PyExc_ValueError, "The shader parameter %s does not fit in its parameter block", fname);
                return false;
            }
        }
    }
    return true;
oom:
    PyErr_NoMemory();
    return false;
}

// Map parameter names to the fields that have that name
static bool
index_params(int program, ProgramParams *pp) {
    size_t total = 0;
    for (size_t b = 0; b < pp->num_blocks; b++) total += pp->blocks[b].num_fields;
    if (!total) return true;
    if (total > UINT16_MAX || pp->num_blocks > UINT16_MAX) {
        PyErr_SetString(PyExc_ValueError, "Too many shader parameters");
        return false;
    }
    if (!(pp->refs = calloc(total, sizeof(ParamRef)))) {
        PyErr_NoMemory();
        return false;
    }
    for (size_t b = 0; b < pp->num_blocks; b++) {
        for (size_t i = 0; i < pp->blocks[b].num_fields; i++) {
            const char *name = pp->blocks[b].fields[i].name;
            ProgramMetadataEntry *e;
            if (find_program_metadata(program, name, PROGRAM_PARAM, &e)) {
                PyErr_Format(PyExc_ValueError, "The shader parameter %s is present in more than one parameter block", name);
                return false;
            }
            insert_program_metadata(program, name, (ProgramMetadataEntry){.kind = PROGRAM_PARAM, .location = (int32_t)pp->num_refs});
            pp->refs[pp->num_refs++] = (ParamRef){.block = (uint16_t)b, .field = (uint16_t)i};
        }
    }
    return true;
}

static bool
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

    PyObject *textures = metadata_item(metadata, "textures", &PyDict_Type);
    if (!textures) return false;
    pos = 0;
    while (PyDict_Next(textures, &pos, &key, &val)) {
        ProgramMetadataEntry e = {.kind = PROGRAM_TEXTURE, .location = (int32_t)PyLong_AsLong(val)};
        if (PyErr_Occurred()) return false;
        insert_program_metadata(program, PyUnicode_AsUTF8(key), e);
    }

    PyObject *blocks = metadata_item(metadata, "blocks", &PyDict_Type);
    if (!blocks) return false;
    pos = 0;
    while (PyDict_Next(blocks, &pos, &key, &val)) {
        const char *block_name = PyUnicode_AsUTF8(key);
        if (!block_name) return false;
        uint32_t size, slot;
        if (!metadata_uint(val, "size", &size) || !metadata_uint(val, "slot", &slot)) return false;
        GPUUniformBlockInfo info;
        if (!gpu_pipeline_uniform_block(pipeline, block_name, &info)) {
            PyErr_Format(PyExc_ValueError, "The GPU program: %d has no uniform block: %s with error: %s", program, block_name, gpu_last_error());
            return false;
        }
        // The layout of the block is taken from the reflection data, so
        // verify that it matches what the driver actually uses
        if (size != info.size) {
            PyErr_Format(
                PyExc_ValueError,
                "The uniform block: %s in GPU program: %d has size %u according to the GPU driver but %u according to the shader reflection data",
                block_name,
                program,
                info.size,
                size);
            return false;
        }
        ProgramMetadataEntry be = {.kind = PROGRAM_BLOCK, .block = {.index = (int32_t)info.index, .size = (int32_t)size, .slot = slot}};
        insert_program_metadata(program, block_name, be);

        PyObject *arrays = metadata_item(val, "arrays", &PyDict_Type);
        if (!arrays) return false;
        PyObject *akey, *aval;
        Py_ssize_t apos = 0;
        while (PyDict_Next(arrays, &apos, &akey, &aval)) {
            const char *array_name = PyUnicode_AsUTF8(akey);
            if (!array_name) return false;
            int32_t offset, stride, count;
            if (!metadata_int(aval, "offset", &offset) || !metadata_int(aval, "stride", &stride) || !metadata_int(aval, "count", &count)) return false;
            ProgramMetadataEntry ae = {.kind = PROGRAM_ARRAY, .array = {.offset = offset, .stride = stride, .size = count}};
            insert_program_metadata(program, array_name, ae);
        }
    }
    return parse_param_blocks(metadata, program_params + program) && index_params(program, program_params + program);
}
// }}}

bool
compile_gpu_program(int program, const char *vertex, size_t vertex_size, const char *fragment, size_t fragment_size, PyObject *metadata) {
    free_program(program);
    // The shaders must have been compiled for the target of the loaded driver
    const char *target = metadata_str(metadata, "target");
    if (!target) return false;
    if (strcmp(target, gpu_shader_target()) != 0) {
        PyErr_Format(PyExc_ValueError, "The shaders were compiled for the target: %s but the GPU driver needs: %s", target, gpu_shader_target());
        return false;
    }
    GPUShaderLanguage language;
    if (strncmp(target, "glsl-", 5) == 0) language = GPU_SHADER_LANGUAGE_GLSL;
    else if (strncmp(target, "spirv-", 6) == 0) language = GPU_SHADER_LANGUAGE_SPIRV;
    else if (strncmp(target, "msl-", 4) == 0) language = GPU_SHADER_LANGUAGE_MSL;
    else {
        PyErr_Format(PyExc_ValueError, "Unknown shader target: %s", target);
        return false;
    }
    // The strings referenced below remain valid as long as the metadata does
    PyObject *native_names = metadata_item(metadata, "native_names", &PyDict_Type);
    PyObject *textures = metadata_item(metadata, "textures", &PyDict_Type);
    PyObject *blocks = metadata_item(metadata, "blocks", &PyDict_Type);
    if (!native_names || !textures || !blocks) return false;
    RAII_ALLOC(GPUNativeName, names, calloc(MAX(1, PyDict_GET_SIZE(native_names)), sizeof(GPUNativeName)));
    RAII_ALLOC(GPUBinding, bindings, calloc(MAX(1, PyDict_GET_SIZE(textures) + PyDict_GET_SIZE(blocks)), sizeof(GPUBinding)));
    if (!names || !bindings) {
        PyErr_NoMemory();
        return false;
    }
    size_t num_names = 0, num_bindings = 0;
    PyObject *key, *val;
    Py_ssize_t pos = 0;
    while (PyDict_Next(native_names, &pos, &key, &val)) {
        if (!(names[num_names].name = PyUnicode_AsUTF8(key)) || !(names[num_names].native_name = PyUnicode_AsUTF8(val))) return false;
        num_names++;
    }
    pos = 0;
    while (PyDict_Next(textures, &pos, &key, &val)) {
        GPUBinding *b = bindings + num_bindings++;
        b->kind = GPU_BINDING_TEXTURE;
        if (!(b->name = PyUnicode_AsUTF8(key))) return false;
        b->slot = (uint32_t)PyLong_AsUnsignedLong(val);
        if (PyErr_Occurred()) return false;
    }
    pos = 0;
    while (PyDict_Next(blocks, &pos, &key, &val)) {
        GPUBinding *b = bindings + num_bindings++;
        b->kind = GPU_BINDING_UNIFORM_BLOCK;
        if (!(b->name = PyUnicode_AsUTF8(key)) || !metadata_uint(val, "slot", &b->slot)) return false;
    }
    // Parse the parameter blocks first, to pass their layout to the driver
    ProgramParams pp = {0};
    if (!parse_param_blocks(metadata, &pp)) {
        free_program_params(&pp);
        return false;
    }
    size_t total_fields = 0;
    for (size_t b = 0; b < pp.num_blocks; b++) total_fields += pp.blocks[b].num_fields;
    RAII_ALLOC(GPUParamBlock, gpb, calloc(MAX(1u, pp.num_blocks), sizeof(GPUParamBlock)));
    RAII_ALLOC(GPUParamField, gpf, calloc(MAX(1u, total_fields), sizeof(GPUParamField)));
    if (!gpb || !gpf) {
        free_program_params(&pp);
        PyErr_NoMemory();
        return false;
    }
    for (size_t b = 0, fi = 0; b < pp.num_blocks; b++) {
        const ParamBlock *pb = pp.blocks + b;
        gpb[b] = (GPUParamBlock){.name = pb->name, .slot = pb->slot, .size = pb->size, .fields = gpf + fi, .num_fields = pb->num_fields};
        for (size_t i = 0; i < pb->num_fields; i++, fi++) {
            const ParamField *f = pb->fields + i;
            gpf[fi] =
                (GPUParamField){.name = f->name, .offset = f->offset, .scalar = f->scalar, .components = f->components, .count = f->count, .stride = f->stride};
        }
    }
    const GPUShaderSource sources[2] = {
        {.stage = GPU_SHADER_VERTEX, .language = language, .code = vertex, .size = vertex_size},
        {.stage = GPU_SHADER_FRAGMENT, .language = language, .code = fragment, .size = fragment_size},
    };
    programs[program] = gpu_pipeline_create(sources, arraysz(sources), gpb, pp.num_blocks, bindings, num_bindings, names, num_names);
    free_program_params(&pp);
    if (!programs[program]) {
        PyErr_SetString(PyExc_ValueError, gpu_last_error());
        return false;
    }
    if (!set_program_layout(program, metadata)) {
        free_program(program);
        return false;
    }
    return true;
}

// Parameters {{{
int32_t
try_program_param(int program, const char *name) {
    ProgramMetadataEntry *e;
    if (!find_program_metadata(program, name, PROGRAM_PARAM, &e)) return -1;
    return (int32_t)(((uint32_t)program << 16) | (uint32_t)e->location);
}

int32_t
program_param(int program, const char *name) {
    int32_t ans = try_program_param(program, name);
    if (ans < 0) log_error("The GPU program: %d has no parameter named: %s", program, name);
    return ans;
}

static void
write_param(int32_t handle, GPUParamScalar scalar, uint32_t components, uint32_t count, const void *values) {
    if (handle < 0) return;
    const int program = handle >> 16;
    const uint32_t r = handle & 0xffff;
    ProgramParams *pp = program_params + program;
    if (r >= pp->num_refs) return;
    const ParamRef *ref = pp->refs + r;
    const size_t elem = 4u * components;
    ParamBlock *pb = pp->blocks + ref->block;
    ParamField *f = pb->fields + ref->field;
    const bool scalar_ok = f->scalar == scalar || (f->scalar == GPU_PARAM_BOOL && scalar == GPU_PARAM_INT);
    if (!scalar_ok || f->components != components || count > f->count) {
        if (!f->type_error_logged) {
            f->type_error_logged = true;
            log_error("Setting the shader parameter: %s in GPU program: %d with a value of the wrong type", f->name, program);
        }
        return;
    }
    for (uint32_t e = 0; e < count; e++) memcpy(pb->data + f->offset + (size_t)e * f->stride, (const uint8_t *)values + e * elem, elem);
    pb->dirty = true;
}

void
param_floats(int32_t handle, uint32_t components, uint32_t count, const float *values) {
    write_param(handle, GPU_PARAM_FLOAT, components, count, values);
}

void
param_1f(int32_t handle, float a) {
    write_param(handle, GPU_PARAM_FLOAT, 1, 1, &a);
}

void
param_2f(int32_t handle, float a, float b) {
    const float v[2] = {a, b};
    write_param(handle, GPU_PARAM_FLOAT, 2, 1, v);
}

void
param_3f(int32_t handle, float a, float b, float c) {
    const float v[3] = {a, b, c};
    write_param(handle, GPU_PARAM_FLOAT, 3, 1, v);
}

void
param_4f(int32_t handle, float a, float b, float c, float d) {
    const float v[4] = {a, b, c, d};
    write_param(handle, GPU_PARAM_FLOAT, 4, 1, v);
}

void
param_1i(int32_t handle, int32_t a) {
    write_param(handle, GPU_PARAM_INT, 1, 1, &a);
}

void
param_1ui(int32_t handle, uint32_t a) {
    write_param(handle, GPU_PARAM_UINT, 1, 1, &a);
}

// Pass changed parameters of the current program to the driver, done just before drawing
static void
flush_params(void) {
    if (current_program < 0 || !programs[current_program]) return;
    ProgramParams *pp = program_params + current_program;
    for (size_t b = 0; b < pp->num_blocks; b++) {
        ParamBlock *pb = pp->blocks + b;
        if (pb->dirty) {
            gpu_set_params(programs[current_program], (uint32_t)b, pb->data, pb->size);
            pb->dirty = false;
        }
    }
}
// }}}

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

uint32_t
program_texture_slot(int program, const char *name) {
    return (uint32_t)program_metadata_entry(program, name, PROGRAM_TEXTURE)->location;
}

bool
try_program_texture_slot(int program, const char *name, uint32_t *slot) {
    ProgramMetadataEntry *e;
    if (!find_program_metadata(program, name, PROGRAM_TEXTURE, &e)) return false;
    *slot = (uint32_t)e->location;
    return true;
}

void
bind_program(int program) {
    current_program = program;
    gpu_use_pipeline(programs[program]);
}

void
unbind_program(void) {
    current_program = -1;
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
