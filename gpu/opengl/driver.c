/*
 * driver.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The OpenGL implementation of the kitty GPU driver API, see ../api.h

#include "../api.h"
#include "platform.h"
#include "version.h"
#include "gl-wrapper.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define UNUSED __attribute__((unused))
#define arraysz(x) (sizeof(x) / sizeof(x[0]))
#define MIN(x, y) ((x) < (y) ? (x) : (y))

// All texture management (creation, uploads, copies) is done using this unit,
// so that it never disturbs the textures bound to the units used for drawing.
// Drawing never samples from it. OpenGL 3 guarantees at least 16 units.
#define SCRATCH_TEXTURE_UNIT 15

typedef struct Texture {
    GLuint id;
    GLenum target;
    GPUTextureDesc desc;
} Texture;

typedef struct Buffer {
    GLuint id;
    GLenum target;
    size_t size;
} Buffer;

typedef struct Uniform {
    char name[256];
    GLint location;
} Uniform;

typedef struct Pipeline {
    GLuint id;
    Uniform *uniforms;
    GLint num_uniforms;
} Pipeline;

typedef struct Driver {
    GPUDriverInitParams params;
    const GLPlatform *platform;
    GLSurface *current_surface;
    bool initialized, supports_srgb_output;
    int gl_version;
    GLint max_texture_size, max_array_texture_layers;
    char last_error[8192];
    char version_string[512];
} Driver;

// glad's error callback has no user data pointer and there is only ever one
// driver per process
static Driver *the_driver = NULL;

// Utilities {{{
#define AS_TEXTURE(handle) ((Texture *)(uintptr_t)(handle))
#define AS_BUFFER(handle) ((Buffer *)(uintptr_t)(handle))
#define AS_PIPELINE(handle) ((Pipeline *)(uintptr_t)(handle))
#define AS_SURFACE(handle) ((GLSurface *)(uintptr_t)(handle))
#define AS_HANDLE(ptr) ((uint64_t)(uintptr_t)(ptr))
// Framebuffers and vertex array objects need no extra state, so their handles are the OpenGL names
#define AS_GL_NAME(handle) ((GLuint)(handle))

static void set_error(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void
set_error(Driver *d, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(d->last_error, sizeof(d->last_error), fmt, ap);
    va_end(ap);
}

static void fatal(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3), noreturn));

static void
fatal(Driver *d, const char *fmt, ...) {
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    d->params.fatal(buf);
    abort(); // fatal() must not return
}

static void log_error(Driver *d, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void
log_error(Driver *d, const char *fmt, ...) {
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    d->params.log_error(buf);
}

static void
discard_pending_gl_errors(void) {
    // glad's error checking callback is installed only with --debug-rendering,
    // so in normal runs errors queue up silently. Drain the queue so that a
    // subsequent glGetError() reports only what we are interested in.
    for (unsigned i = 0; i < 16 && glGetError() != GL_NO_ERROR; i++);
}

static void
check_for_gl_error(void UNUSED *ret, const char *name, GLADapiproc UNUSED funcptr, int UNUSED len_args, ...) {
#define f(msg)                                                               \
    fatal(the_driver, "OpenGL error: %s (calling function: %s)", msg, name); \
    break;
    GLenum code = glad_glGetError();
    switch (code) {
        case GL_NO_ERROR: break;
        case GL_INVALID_ENUM: f("An enum value is invalid (GL_INVALID_ENUM)");
        case GL_INVALID_VALUE: f("An numeric value is invalid (GL_INVALID_VALUE)");
        case GL_INVALID_OPERATION: f("This operation is invalid (GL_INVALID_OPERATION)");
        case GL_INVALID_FRAMEBUFFER_OPERATION: f("The framebuffer object is not complete (GL_INVALID_FRAMEBUFFER_OPERATION)");
        case GL_OUT_OF_MEMORY: f("There is not enough memory left to execute the command. (GL_OUT_OF_MEMORY)");
        case GL_STACK_UNDERFLOW: f("An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)");
        case GL_STACK_OVERFLOW: f("An attempt has been made to perform an operation that would cause an internal stack to overflow. (GL_STACK_OVERFLOW)");
        default: fatal(the_driver, "An unknown OpenGL error occurred with code: %d (calling function: %s)", code, name); break;
    }
#undef f
}
// }}}

// Lifecycle {{{
static const char *
last_error(void *driver) {
    return ((Driver *)driver)->last_error;
}

static const char *
version_string(void *driver) {
    Driver *d = driver;
    if (!d->initialized) return "";
    int gl_major = GLAD_VERSION_MAJOR(d->gl_version);
    int gl_minor = GLAD_VERSION_MINOR(d->gl_version);
    const char *gvs = (const char *)glGetString(GL_VERSION);
    snprintf(d->version_string, sizeof(d->version_string), "'%s' Detected version: %d.%d", gvs, gl_major, gl_minor);
    return d->version_string;
}

static bool
initialize(void *driver) {
    Driver *d = driver;
    if (d->initialized) return true;
    if (!d->platform || !d->current_surface) {
        set_error(d, "The OpenGL driver must have a current surface before it can be initialized");
        return false;
    }
    d->gl_version = gladLoadGL((GLADloadfunc)d->platform->get_proc_address);
    if (!d->gl_version) {
        set_error(d, "Loading the OpenGL library failed");
        return false;
    }
    if (!d->params.debug_rendering) gladUninstallGLDebug();
    gladSetGLPostCallback(check_for_gl_error);
    if (!GLAD_GL_ARB_texture_storage) {
        set_error(d, "The OpenGL driver on this system is missing the required extension: ARB_texture_storage");
        return false;
    }
#ifdef __APPLE__
    // See nsgl_context.m srgb is always supported on macOS but its OpenGL
    // drivers dont report the extensions, so hardcode to true.
    d->supports_srgb_output = true;
#else
    d->supports_srgb_output = (GLAD_GL_ARB_framebuffer_sRGB + GLAD_GL_EXT_framebuffer_sRGB) != 0;
#endif
    d->initialized = true;
    int gl_major = GLAD_VERSION_MAJOR(d->gl_version);
    int gl_minor = GLAD_VERSION_MINOR(d->gl_version);
    if (d->params.debug_rendering) {
        char buf[1024];
        snprintf(buf, sizeof(buf), "GL version string: %s", version_string(d));
        d->params.debug_print(buf);
    }
    if (gl_major < OPENGL_REQUIRED_VERSION_MAJOR || (gl_major == OPENGL_REQUIRED_VERSION_MAJOR && gl_minor < OPENGL_REQUIRED_VERSION_MINOR)) {
        set_error(
            d,
            "OpenGL version is %d.%d, version >= %d.%d required for kitty",
            gl_major,
            gl_minor,
            OPENGL_REQUIRED_VERSION_MAJOR,
            OPENGL_REQUIRED_VERSION_MINOR);
        d->initialized = false;
        return false;
    }
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &d->max_texture_size);
    glGetIntegerv(GL_MAX_ARRAY_TEXTURE_LAYERS, &d->max_array_texture_layers);
#ifdef __APPLE__
    // Since on Apple we could have multiple GPUs, with different capabilities,
    // upper bound the values according to the data from https://developer.apple.com/graphicsimaging/opengl/capabilities/
    d->max_texture_size = MIN(8192, d->max_texture_size);
    d->max_array_texture_layers = MIN(512, d->max_array_texture_layers);
#endif
    return true;
}

static void release_native_resources(void *driver);

static void
destroy(void *driver) {
    release_native_resources(driver);
    if (the_driver == driver) the_driver = NULL;
    free(driver);
}

static void
get_capabilities(void *driver, GPUCapabilities *ans) {
    Driver *d = driver;
    ans->max_texture_size = d->max_texture_size > 0 ? (uint32_t)d->max_texture_size : 0;
    ans->max_array_texture_layers = d->max_array_texture_layers > 0 ? (uint32_t)d->max_array_texture_layers : 0;
    ans->supports_srgb_output = d->supports_srgb_output;
}
// }}}

// Textures {{{
static bool
format_is_integer(GPUTextureFormat f) {
    switch (f) {
        case GPU_FORMAT_R8UI:
        case GPU_FORMAT_RG8UI:
        case GPU_FORMAT_R32UI: return true;
        case GPU_FORMAT_R8:
        case GPU_FORMAT_RGBA8:
        case GPU_FORMAT_SRGB8_ALPHA8:
        case GPU_FORMAT_RGBA16: return false;
    }
    return false;
}

// The internal format used for mutable (glTexImage) textures. Unsized formats
// are used where possible to let the driver pick the most efficient storage.
static GLint
unsized_internal_format(GPUTextureFormat f) {
    switch (f) {
        case GPU_FORMAT_R8: return GL_RED;
        case GPU_FORMAT_R8UI: return GL_R8UI;
        case GPU_FORMAT_RG8UI: return GL_RG8UI;
        case GPU_FORMAT_R32UI: return GL_R32UI;
        case GPU_FORMAT_RGBA8: return GL_RGBA;
        case GPU_FORMAT_SRGB8_ALPHA8: return GL_SRGB_ALPHA;
        case GPU_FORMAT_RGBA16: return GL_RGBA16;
    }
    return GL_RGBA;
}

// The internal format used for immutable (glTexStorage) textures
static GLenum
sized_internal_format(GPUTextureFormat f) {
    switch (f) {
        case GPU_FORMAT_R8: return GL_R8;
        case GPU_FORMAT_R8UI: return GL_R8UI;
        case GPU_FORMAT_RG8UI: return GL_RG8UI;
        case GPU_FORMAT_R32UI: return GL_R32UI;
        case GPU_FORMAT_RGBA8: return GL_RGBA8;
        case GPU_FORMAT_SRGB8_ALPHA8: return GL_SRGB8_ALPHA8;
        case GPU_FORMAT_RGBA16: return GL_RGBA16;
    }
    return GL_RGBA8;
}

// The pixel transfer format and type used when no pixel data is supplied
static void
default_transfer_format(GPUTextureFormat f, GLenum *format, GLenum *type) {
    switch (f) {
        case GPU_FORMAT_R8:
            *format = GL_RED;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_FORMAT_R8UI:
            *format = GL_RED_INTEGER;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_FORMAT_RG8UI:
            *format = GL_RG_INTEGER;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_FORMAT_R32UI:
            *format = GL_RED_INTEGER;
            *type = GL_UNSIGNED_INT;
            return;
        case GPU_FORMAT_RGBA8:
        case GPU_FORMAT_SRGB8_ALPHA8:
        case GPU_FORMAT_RGBA16:
            *format = GL_RGBA;
            *type = GL_UNSIGNED_BYTE;
            return;
    }
    *format = GL_RGBA;
    *type = GL_UNSIGNED_BYTE;
}

static void
transfer_format(GPUTextureFormat tf, GPUPixelLayout layout, GLenum *format, GLenum *type) {
    const bool integer = format_is_integer(tf);
    switch (layout) {
        case GPU_PIXELS_R8:
            *format = integer ? GL_RED_INTEGER : GL_RED;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_PIXELS_RG8:
            *format = integer ? GL_RG_INTEGER : GL_RG;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_PIXELS_RGB8:
            *format = GL_RGB;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_PIXELS_RGBA8:
            *format = GL_RGBA;
            *type = GL_UNSIGNED_BYTE;
            return;
        case GPU_PIXELS_RGBA8_PACKED:
            *format = GL_RGBA;
            *type = GL_UNSIGNED_INT_8_8_8_8;
            return;
        case GPU_PIXELS_R32UI:
            *format = GL_RED_INTEGER;
            *type = GL_UNSIGNED_INT;
            return;
    }
    default_transfer_format(tf, format, type);
}

static GLint
gl_wrap(GPUWrap w) {
    switch (w) {
        case GPU_WRAP_CLAMP_TO_EDGE: return GL_CLAMP_TO_EDGE;
        case GPU_WRAP_CLAMP_TO_BORDER: return GL_CLAMP_TO_BORDER;
        case GPU_WRAP_REPEAT: return GL_REPEAT;
        case GPU_WRAP_MIRRORED_REPEAT: return GL_MIRRORED_REPEAT;
    }
    return GL_CLAMP_TO_EDGE;
}

static void
bind_for_management(const Texture *t) {
    glActiveTexture(GL_TEXTURE0 + SCRATCH_TEXTURE_UNIT);
    glBindTexture(t->target, t->id);
}

static void
set_unpack_alignment(const GPUPixelData *p) {
    glPixelStorei(GL_UNPACK_ALIGNMENT, p && p->row_alignment ? (GLint)p->row_alignment : 4);
}

static void
define_texture_storage(Texture *t, const GPUPixelData *initial) {
    const GPUTextureDesc *desc = &t->desc;
    bind_for_management(t);
    const GLint filter = desc->filter == GPU_FILTER_LINEAR ? GL_LINEAR : GL_NEAREST;
    glTexParameteri(t->target, GL_TEXTURE_MIN_FILTER, filter);
    glTexParameteri(t->target, GL_TEXTURE_MAG_FILTER, filter);
    if (desc->wrap == GPU_WRAP_CLAMP_TO_BORDER) {
        static const GLfloat border_color[4] = {0};
        glTexParameterfv(t->target, GL_TEXTURE_BORDER_COLOR, border_color);
    }
    const GLint wrap = gl_wrap(desc->wrap);
    glTexParameteri(t->target, GL_TEXTURE_WRAP_S, wrap);
    glTexParameteri(t->target, GL_TEXTURE_WRAP_T, wrap);
    GLenum format, type;
    if (initial) transfer_format(desc->format, initial->layout, &format, &type);
    else default_transfer_format(desc->format, &format, &type);
    set_unpack_alignment(initial);
    if (t->target == GL_TEXTURE_2D_ARRAY) {
        glTexStorage3D(t->target, 1, sized_internal_format(desc->format), desc->width, desc->height, desc->layers);
        if (initial) glTexSubImage3D(t->target, 0, 0, 0, 0, desc->width, desc->height, desc->layers, format, type, initial->data);
    } else {
        glTexImage2D(t->target, 0, unsized_internal_format(desc->format), desc->width, desc->height, 0, format, type, initial ? initial->data : NULL);
    }
}

static gpu_texture_t
texture_create(void *driver, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    Driver *d = driver;
    Texture *t = calloc(1, sizeof(Texture));
    if (!t) {
        set_error(d, "Out of memory allocating a texture");
        return GPU_NULL_HANDLE;
    }
    t->desc = *desc;
    if (t->desc.kind != GPU_TEXTURE_2D_ARRAY) t->desc.layers = 1;
    t->target = desc->kind == GPU_TEXTURE_2D_ARRAY ? GL_TEXTURE_2D_ARRAY : GL_TEXTURE_2D;
    glGenTextures(1, &t->id);
    define_texture_storage(t, initial);
    return AS_HANDLE(t);
}

static bool
texture_reset(void *driver UNUSED, gpu_texture_t texture, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    Texture *t = AS_TEXTURE(texture);
    const GLenum target = desc->kind == GPU_TEXTURE_2D_ARRAY ? GL_TEXTURE_2D_ARRAY : GL_TEXTURE_2D;
    // Textures with immutable storage, or that change type, need a new name
    if (target == GL_TEXTURE_2D_ARRAY || target != t->target) {
        glDeleteTextures(1, &t->id);
        glGenTextures(1, &t->id);
    }
    t->target = target;
    t->desc = *desc;
    if (t->desc.kind != GPU_TEXTURE_2D_ARRAY) t->desc.layers = 1;
    define_texture_storage(t, initial);
    return true;
}

static void
texture_destroy(void *driver UNUSED, gpu_texture_t texture) {
    Texture *t = AS_TEXTURE(texture);
    if (!t) return;
    glDeleteTextures(1, &t->id);
    free(t);
}

static void
texture_upload(
    void *driver UNUSED, gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels) {
    Texture *t = AS_TEXTURE(texture);
    bind_for_management(t);
    set_unpack_alignment(pixels);
    GLenum format, type;
    transfer_format(t->desc.format, pixels->layout, &format, &type);
    if (t->target == GL_TEXTURE_2D_ARRAY) glTexSubImage3D(t->target, 0, x, y, layer, width, height, 1, format, type, pixels->data);
    else glTexSubImage2D(t->target, 0, x, y, width, height, format, type, pixels->data);
}

static bool
copy_texture_via_framebuffer(const Texture *src, const Texture *dst) {
    const GLint width = src->desc.width, height = src->desc.height, layers = src->desc.layers;
    GLint prev_read_fbo;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &prev_read_fbo);
    discard_pending_gl_errors();
    GLuint fbo;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
    bind_for_management(dst);
    bool ok = true;
    for (GLint z = 0; z < layers && ok; z++) {
        if (src->target == GL_TEXTURE_2D_ARRAY) glFramebufferTextureLayer(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, src->id, 0, z);
        else glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, src->id, 0);
        ok = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
        if (!ok) break;
        if (dst->target == GL_TEXTURE_2D_ARRAY) glCopyTexSubImage3D(dst->target, 0, 0, 0, z, 0, 0, width, height);
        else glCopyTexSubImage2D(dst->target, 0, 0, 0, 0, 0, width, height);
        // A complete framebuffer does not mean the copy itself was accepted,
        // for instance if the two internal formats are not copy compatible.
        // Without this check we would claim success and leave the new texture
        // blank, losing all its contents.
        ok = glGetError() == GL_NO_ERROR;
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, prev_read_fbo);
    glDeleteFramebuffers(1, &fbo);
    return ok;
}

static void
texture_copy(void *driver, gpu_texture_t src_handle, gpu_texture_t dst_handle) {
    // Assumes textures are 32bits per pixel
    Driver *d = driver;
    const Texture *src = AS_TEXTURE(src_handle), *dst = AS_TEXTURE(dst_handle);
    const GLint width = src->desc.width, height = src->desc.height, layers = src->desc.layers;
    if (GLAD_GL_ARB_copy_image) {
        glCopyImageSubData(src->id, src->target, 0, 0, 0, 0, dst->id, dst->target, 0, 0, 0, 0, width, height, layers);
        return;
    }
    if (copy_texture_via_framebuffer(src, dst)) return;

    static bool copy_image_warned = false;
    // Neither ARB_copy_image nor a framebuffer copy is usable, do a slow roundtrip copy
    if (!copy_image_warned) {
        copy_image_warned = true;
        log_error(d, "WARNING: Your system's OpenGL implementation cannot copy between textures on the GPU, falling back to a slower implementation");
    }
    GLenum format, type;
    if (format_is_integer(src->desc.format)) {
        format = GL_RED_INTEGER;
        type = GL_UNSIGNED_INT;
    } else {
        format = GL_RGBA;
        type = GL_UNSIGNED_INT_8_8_8_8;
    }
    uint8_t *pixels = malloc((size_t)width * height * layers * 4u);
    if (!pixels) fatal(d, "Out of memory");
    bind_for_management(src);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glGetTexImage(src->target, 0, format, type, pixels);
    bind_for_management(dst);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    if (dst->target == GL_TEXTURE_2D_ARRAY) glTexSubImage3D(dst->target, 0, 0, 0, 0, width, height, layers, format, type, pixels);
    else glTexSubImage2D(dst->target, 0, 0, 0, width, height, format, type, pixels);
    free(pixels);
}

static bool
texture_read(void *driver, gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size) {
    Driver *d = driver;
    const Texture *t = AS_TEXTURE(texture);
    if (layout != GPU_PIXELS_RGBA8 || t->target != GL_TEXTURE_2D) {
        set_error(d, "Reading back textures is supported only for 2D textures as RGBA8 pixels");
        return false;
    }
    if (dst_size < (size_t)t->desc.width * t->desc.height * 4u) {
        set_error(d, "Buffer too small to read back texture");
        return false;
    }
    bind_for_management(t);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glGetTexImage(t->target, 0, GL_RGBA, GL_UNSIGNED_BYTE, dst);
    return true;
}

static void
texture_get_desc(void *driver UNUSED, gpu_texture_t texture, GPUTextureDesc *ans) {
    *ans = AS_TEXTURE(texture)->desc;
}

static void
bind_texture(void *driver UNUSED, uint32_t unit, gpu_texture_t texture) {
    glActiveTexture(GL_TEXTURE0 + unit);
    const Texture *t = AS_TEXTURE(texture);
    if (t) glBindTexture(t->target, t->id);
    else glBindTexture(GL_TEXTURE_2D, 0);
}
// }}}

// Buffers {{{
static gpu_buffer_t
buffer_create(void *driver, GPUBufferKind kind) {
    Buffer *b = calloc(1, sizeof(Buffer));
    if (!b) {
        set_error(driver, "Out of memory allocating a buffer");
        return GPU_NULL_HANDLE;
    }
    b->target = kind == GPU_BUFFER_UNIFORM ? GL_UNIFORM_BUFFER : GL_ARRAY_BUFFER;
    glGenBuffers(1, &b->id);
    return AS_HANDLE(b);
}

static void
buffer_destroy(void *driver UNUSED, gpu_buffer_t buffer) {
    Buffer *b = AS_BUFFER(buffer);
    if (!b) return;
    glDeleteBuffers(1, &b->id);
    free(b);
}

static GLenum
gl_usage(GPUUpdateFrequency f) {
    switch (f) {
        case GPU_UPDATE_RARELY: return GL_STATIC_DRAW;
        case GPU_UPDATE_OFTEN: return GL_DYNAMIC_DRAW;
        case GPU_UPDATE_EVERY_USE: return GL_STREAM_DRAW;
    }
    return GL_STATIC_DRAW;
}

static void
buffer_allocate(void *driver UNUSED, gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency) {
    Buffer *b = AS_BUFFER(buffer);
    if (b->size == size) return;
    b->size = size;
    glBindBuffer(b->target, b->id);
    glBufferData(b->target, size, NULL, gl_usage(frequency));
    glBindBuffer(b->target, 0);
}

static void *
buffer_map(void *driver UNUSED, gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size) {
    Buffer *b = AS_BUFFER(buffer);
    glBindBuffer(b->target, b->id);
    switch (mode) {
        case GPU_MAP_WRITE: return glMapBuffer(b->target, GL_WRITE_ONLY);
        case GPU_MAP_WRITE_DISCARD_RANGE: return glMapBufferRange(b->target, offset, size, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_RANGE_BIT);
        case GPU_MAP_WRITE_DISCARD_ALL: return glMapBufferRange(b->target, offset, size, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
        case GPU_MAP_READ: return glMapBuffer(b->target, GL_READ_ONLY);
    }
    return NULL;
}

static void
buffer_unmap(void *driver UNUSED, gpu_buffer_t buffer) {
    Buffer *b = AS_BUFFER(buffer);
    glBindBuffer(b->target, b->id);
    glUnmapBuffer(b->target);
    glBindBuffer(b->target, 0);
}

static void
buffer_copy(void *driver UNUSED, gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size) {
    glBindBuffer(GL_COPY_READ_BUFFER, AS_BUFFER(src)->id);
    glBindBuffer(GL_COPY_WRITE_BUFFER, AS_BUFFER(dst)->id);
    glCopyBufferSubData(GL_COPY_READ_BUFFER, GL_COPY_WRITE_BUFFER, src_offset, dst_offset, size);
    glBindBuffer(GL_COPY_READ_BUFFER, 0);
    glBindBuffer(GL_COPY_WRITE_BUFFER, 0);
}

static void
bind_uniform_buffer(void *driver UNUSED, uint32_t binding_point, gpu_buffer_t buffer) {
    glBindBufferBase(GL_UNIFORM_BUFFER, binding_point, AS_BUFFER(buffer)->id);
}
// }}}

// Pipelines {{{
static GLuint
compile_shader(Driver *d, const GPUShaderSource *src) {
    GLenum shader_type = src->stage == GPU_SHADER_VERTEX ? GL_VERTEX_SHADER : GL_FRAGMENT_SHADER;
    const char *shader_type_name = src->stage == GPU_SHADER_VERTEX ? "vertex" : "fragment";
    if (src->language != GPU_SHADER_LANGUAGE_GLSL) {
        set_error(d, "The OpenGL driver supports only GLSL shaders");
        return 0;
    }
    GLuint shader_id = glCreateShader(shader_type);
    const GLchar *code = src->code;
    const GLint len = (GLint)(src->size ? src->size : strlen(src->code));
    glShaderSource(shader_id, 1, &code, &len);
    glCompileShader(shader_id);
    GLint ret = GL_FALSE;
    glGetShaderiv(shader_id, GL_COMPILE_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei loglen;
        static char glbuf[4096];
        glGetShaderInfoLog(shader_id, sizeof(glbuf), &loglen, glbuf);
        glDeleteShader(shader_id);
        set_error(d, "Failed to compile GLSL %s shader:\n%s", shader_type_name, glbuf);
        return 0;
    }
    return shader_id;
}

static void
pipeline_destroy(void *driver UNUSED, gpu_pipeline_t pipeline) {
    Pipeline *p = AS_PIPELINE(pipeline);
    if (!p) return;
    if (p->id) glDeleteProgram(p->id);
    free(p->uniforms);
    free(p);
}

static bool
read_active_uniforms(Driver *d, Pipeline *p) {
    glGetProgramiv(p->id, GL_ACTIVE_UNIFORMS, &p->num_uniforms);
    if (p->num_uniforms <= 0) return true;
    p->uniforms = calloc(p->num_uniforms, sizeof(Uniform));
    if (!p->uniforms) {
        set_error(d, "Out of memory reading the uniforms of a GPU program");
        return false;
    }
    for (GLint i = 0; i < p->num_uniforms; i++) {
        Uniform *u = p->uniforms + i;
        GLint size;
        GLenum type;
        glGetActiveUniform(p->id, (GLuint)i, sizeof(u->name), NULL, &size, &type, u->name);
        char *l = strchr(u->name, '[');
        if (l) *l = 0;
        u->location = glGetUniformLocation(p->id, u->name);
    }
    return true;
}

static gpu_pipeline_t
pipeline_create(void *driver, const GPUShaderSource *sources, size_t num_sources) {
    Driver *d = driver;
    Pipeline *p = calloc(1, sizeof(Pipeline));
    if (!p) {
        set_error(d, "Out of memory allocating a GPU program");
        return GPU_NULL_HANDLE;
    }
    p->id = glCreateProgram();
    for (size_t i = 0; i < num_sources; i++) {
        GLuint shader_id = compile_shader(d, sources + i);
        if (!shader_id) {
            pipeline_destroy(d, AS_HANDLE(p));
            return GPU_NULL_HANDLE;
        }
        glAttachShader(p->id, shader_id);
        glDeleteShader(shader_id);
    }
    glLinkProgram(p->id);
    GLint ret = GL_FALSE;
    glGetProgramiv(p->id, GL_LINK_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        static char glbuf[4096];
        glGetProgramInfoLog(p->id, sizeof(glbuf), &len, glbuf);
        set_error(d, "Failed to link GLSL shaders:\n%s", glbuf);
        pipeline_destroy(d, AS_HANDLE(p));
        return GPU_NULL_HANDLE;
    }
    if (!read_active_uniforms(d, p)) {
        pipeline_destroy(d, AS_HANDLE(p));
        return GPU_NULL_HANDLE;
    }
    return AS_HANDLE(p);
}

static void
use_pipeline(void *driver UNUSED, gpu_pipeline_t pipeline) {
    const Pipeline *p = AS_PIPELINE(pipeline);
    glUseProgram(p ? p->id : 0);
}

static int32_t
pipeline_uniform_slot(void *driver UNUSED, gpu_pipeline_t pipeline, const char *name) {
    const Pipeline *p = AS_PIPELINE(pipeline);
    const size_t n = strlen(name) + 1;
    for (GLint i = 0; i < p->num_uniforms; i++) {
        const Uniform *u = p->uniforms + i;
        if (strncmp(u->name, name, n) == 0) return u->location;
    }
    return -1;
}

static bool
pipeline_uniform_block(void *driver, gpu_pipeline_t pipeline, const char *name, GPUUniformBlockInfo *ans) {
    const Pipeline *p = AS_PIPELINE(pipeline);
    GLuint index = glGetUniformBlockIndex(p->id, name);
    if (index == GL_INVALID_INDEX) {
        set_error(driver, "Could not find block index for %s", name);
        return false;
    }
    GLint size;
    glGetActiveUniformBlockiv(p->id, index, GL_UNIFORM_BLOCK_DATA_SIZE, &size);
    ans->index = index;
    ans->size = size > 0 ? (uint32_t)size : 0;
    return true;
}

static bool
pipeline_uniform_array(void *driver, gpu_pipeline_t pipeline, const char *name, GPUUniformArrayInfo *ans) {
    const Pipeline *p = AS_PIPELINE(pipeline);
    const GLchar *names[1] = {name};
    GLuint t;
    glGetUniformIndices(p->id, 1, names, &t);
    if (t == GL_INVALID_INDEX) {
        set_error(driver, "Could not find the index for uniform array: %s", name);
        return false;
    }
    GLint stride, offset, size;
    glGetActiveUniformsiv(p->id, 1, &t, GL_UNIFORM_ARRAY_STRIDE, &stride);
    glGetActiveUniformsiv(p->id, 1, &t, GL_UNIFORM_OFFSET, &offset);
    glGetActiveUniformsiv(p->id, 1, &t, GL_UNIFORM_SIZE, &size);
    ans->stride = stride > 0 ? (uint32_t)stride : 0;
    ans->offset = offset > 0 ? (uint32_t)offset : 0;
    ans->count = size > 0 ? (uint32_t)size : 0;
    return true;
}

static void
pipeline_bind_uniform_block(void *driver UNUSED, gpu_pipeline_t pipeline, uint32_t block_index, uint32_t binding_point) {
    glUniformBlockBinding(AS_PIPELINE(pipeline)->id, block_index, binding_point);
}

static int32_t
pipeline_attribute_location(void *driver UNUSED, gpu_pipeline_t pipeline, const char *name) {
    return glGetAttribLocation(AS_PIPELINE(pipeline)->id, name);
}

static void
set_uniform_floats(void *driver UNUSED, int32_t slot, uint32_t components, uint32_t count, const float *v) {
    if (slot < 0) return;
    switch (components) {
        case 1: glUniform1fv(slot, count, v); break;
        case 2: glUniform2fv(slot, count, v); break;
        case 3: glUniform3fv(slot, count, v); break;
        case 4: glUniform4fv(slot, count, v); break;
    }
}

static void
set_uniform_ints(void *driver UNUSED, int32_t slot, uint32_t components, uint32_t count, const int32_t *v) {
    if (slot < 0) return;
    switch (components) {
        case 1: glUniform1iv(slot, count, v); break;
        case 2: glUniform2iv(slot, count, v); break;
        case 3: glUniform3iv(slot, count, v); break;
        case 4: glUniform4iv(slot, count, v); break;
    }
}

static void
set_uniform_uints(void *driver UNUSED, int32_t slot, uint32_t components, uint32_t count, const uint32_t *v) {
    if (slot < 0) return;
    switch (components) {
        case 1: glUniform1uiv(slot, count, v); break;
        case 2: glUniform2uiv(slot, count, v); break;
        case 3: glUniform3uiv(slot, count, v); break;
        case 4: glUniform4uiv(slot, count, v); break;
    }
}
// }}}

// Vertex layouts {{{
static gpu_vertex_layout_t
vertex_layout_create(void *driver UNUSED) {
    GLuint vao_id;
    glGenVertexArrays(1, &vao_id);
    return vao_id;
}

static void
vertex_layout_destroy(void *driver UNUSED, gpu_vertex_layout_t layout) {
    GLuint vao_id = AS_GL_NAME(layout);
    if (vao_id) glDeleteVertexArrays(1, &vao_id);
}

static void
bind_vertex_layout(void *driver UNUSED, gpu_vertex_layout_t layout) {
    glBindVertexArray(AS_GL_NAME(layout));
}

static void
vertex_layout_set_attribute(
    void *driver UNUSED,
    gpu_vertex_layout_t layout,
    uint32_t location,
    gpu_buffer_t buffer,
    uint32_t components,
    GPUAttribType type,
    uint32_t stride,
    size_t offset,
    uint32_t instance_divisor) {
    glBindVertexArray(AS_GL_NAME(layout));
    const Buffer *b = AS_BUFFER(buffer);
    glBindBuffer(GL_ARRAY_BUFFER, b->id);
    glEnableVertexAttribArray(location);
    void *ptr = (void *)(uintptr_t)offset;
    switch (type) {
        case GPU_ATTRIB_U8: glVertexAttribIPointer(location, components, GL_UNSIGNED_BYTE, stride, ptr); break;
        case GPU_ATTRIB_U16: glVertexAttribIPointer(location, components, GL_UNSIGNED_SHORT, stride, ptr); break;
        case GPU_ATTRIB_U32: glVertexAttribIPointer(location, components, GL_UNSIGNED_INT, stride, ptr); break;
        case GPU_ATTRIB_F32: glVertexAttribPointer(location, components, GL_FLOAT, GL_FALSE, stride, ptr); break;
    }
    glVertexAttribDivisorARB(location, instance_divisor);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}
// }}}

// Surfaces {{{
bool
gl_extension_in_string(const char *name, const char *extensions) {
    const size_t len = strlen(name);
    for (const char *start = extensions;;) {
        const char *where = strstr(start, name);
        if (!where) return false;
        const char *terminator = where + len;
        if ((where == start || *(where - 1) == ' ') && (*terminator == ' ' || *terminator == '\0')) return true;
        start = terminator;
    }
}

static void host_set_error(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void
host_set_error(const char *fmt, ...) {
    if (!the_driver) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(the_driver->last_error, sizeof(the_driver->last_error), fmt, ap);
    va_end(ap);
}

static void host_log_error(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void
host_log_error(const char *fmt, ...) {
    if (!the_driver) return;
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    the_driver->params.log_error(buf);
}

static void host_debug(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void
host_debug(const char *fmt, ...) {
    if (!the_driver || !the_driver->params.debug_rendering) return;
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    the_driver->params.debug_print(buf);
}

static void
host_x11_push_error_trap(void) {
    if (the_driver && the_driver->params.x11_push_error_trap) the_driver->params.x11_push_error_trap();
}

static int
host_x11_pop_error_trap(void) {
    if (the_driver && the_driver->params.x11_pop_error_trap) return the_driver->params.x11_pop_error_trap();
    return 0;
}

static const GLPlatformHost platform_host = {
    .set_error = host_set_error,
    .log_error = host_log_error,
    .debug = host_debug,
    .x11_push_error_trap = host_x11_push_error_trap,
    .x11_pop_error_trap = host_x11_pop_error_trap,
};

// Select the platform API used to create contexts for windows of the
// specified type. All windows must be of the same type.
static bool
ensure_platform(Driver *d, GPUPlatform type) {
    const GLPlatform *p = NULL;
    switch (type) {
#ifdef __APPLE__
        case GPU_PLATFORM_COCOA: p = nsgl_platform(&platform_host); break;
        case GPU_PLATFORM_X11:
        case GPU_PLATFORM_WAYLAND: break;
#else
        case GPU_PLATFORM_X11: p = glx_platform(&platform_host); break;
        case GPU_PLATFORM_WAYLAND: p = egl_platform(&platform_host); break;
        case GPU_PLATFORM_COCOA: break;
#endif
    }
    if (!p) {
        set_error(d, "The OpenGL driver does not support windows of type: %d on this platform", (int)type);
        return false;
    }
    if (d->platform && d->platform != p) {
        set_error(d, "The OpenGL driver cannot render to windows using both %s and %s", d->platform->name, p->name);
        return false;
    }
    d->platform = p;
    return true;
}

static bool
choose_native_visual(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id) {
    Driver *d = driver;
    *visual_id = 0;
    if (!ensure_platform(d, native->platform)) return false;
    return d->platform->choose_native_visual(native, config, visual_id);
}

static gpu_surface_t
surface_create(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height) {
    Driver *d = driver;
    if (!ensure_platform(d, native->platform)) return GPU_NULL_HANDLE;
    GLSurface *s = d->platform->surface_create(native, config, width, height);
    if (s) host_debug("Created %s OpenGL context for window of size: %ux%u", d->platform->name, width, height);
    return AS_HANDLE(s);
}

static void
surface_destroy(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    GLSurface *s = AS_SURFACE(surface);
    if (!s || !d->platform) return;
    if (d->current_surface == s) {
        d->platform->make_current(NULL);
        d->current_surface = NULL;
    }
    d->platform->surface_destroy(s);
}

static bool
make_surface_current(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    GLSurface *s = AS_SURFACE(surface);
    if (!d->platform) {
        if (!s) return true;
        set_error(d, "Cannot make a surface current before any surface is created");
        return false;
    }
    if (!d->platform->make_current(s)) return false;
    d->current_surface = s;
    return true;
}

static gpu_surface_t
get_current_surface(void *driver) {
    return AS_HANDLE(((Driver *)driver)->current_surface);
}

static void
surface_resize(void *driver, gpu_surface_t surface, uint32_t width, uint32_t height) {
    Driver *d = driver;
    if (surface && d->platform) d->platform->surface_resize(AS_SURFACE(surface), width, height);
}

static bool
surface_present(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    if (!surface || !d->platform) return false;
    return d->platform->present(AS_SURFACE(surface));
}

static void
surface_set_swap_interval(void *driver, gpu_surface_t surface, int interval) {
    Driver *d = driver;
    if (surface && d->platform) d->platform->set_swap_interval(AS_SURFACE(surface), interval);
}

static void
surface_native_changed(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    if (surface && d->platform) d->platform->native_changed(AS_SURFACE(surface));
}

static bool
surface_recreate(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    if (!surface || !d->platform) return false;
    if (!d->platform->recreate(AS_SURFACE(surface))) return false;
    d->current_surface = AS_SURFACE(surface);
    return true;
}

static void
release_native_resources(void *driver) {
    Driver *d = driver;
    if (!d->platform) return;
    d->platform->make_current(NULL);
    d->current_surface = NULL;
    d->platform->terminate();
    d->platform = NULL;
}
// }}}

// Render targets {{{
static const char *
framebuffer_status_string(GLenum status) {
    switch (status) {
        case GL_FRAMEBUFFER_COMPLETE: return NULL;
        case GL_FRAMEBUFFER_UNDEFINED: return "GL_FRAMEBUFFER_UNDEFINED";
        case GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT: return "GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT";
        case GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT: return "GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT";
        case GL_FRAMEBUFFER_INCOMPLETE_DRAW_BUFFER: return "GL_FRAMEBUFFER_INCOMPLETE_DRAW_BUFFER";
        case GL_FRAMEBUFFER_INCOMPLETE_READ_BUFFER: return "GL_FRAMEBUFFER_INCOMPLETE_READ_BUFFER";
        case GL_FRAMEBUFFER_UNSUPPORTED: return "GL_FRAMEBUFFER_UNSUPPORTED";
        case GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE: return "GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE";
        default: return "Unknown error";
    }
}

typedef struct {
    GLint draw, read;
} SavedFramebuffers;

static SavedFramebuffers
save_framebuffers(void) {
    SavedFramebuffers ans;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &ans.draw);
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &ans.read);
    return ans;
}

static void
restore_framebuffers(SavedFramebuffers s) {
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, s.draw);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, s.read);
}

static gpu_render_target_t
render_target_create(void *driver UNUSED, gpu_texture_t color_texture) {
    const Texture *t = AS_TEXTURE(color_texture);
    SavedFramebuffers saved = save_framebuffers();
    GLuint fbo;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->id, 0);
    restore_framebuffers(saved);
    return fbo;
}

static void
render_target_destroy(void *driver UNUSED, gpu_render_target_t target) {
    GLuint fbo = AS_GL_NAME(target);
    if (fbo) glDeleteFramebuffers(1, &fbo);
}

static void
set_render_target(void *driver UNUSED, gpu_render_target_t target) {
    glBindFramebuffer(GL_FRAMEBUFFER, AS_GL_NAME(target));
}

static gpu_render_target_t
get_render_target(void *driver UNUSED) {
    GLint ans;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &ans);
    return ans > 0 ? (gpu_render_target_t)ans : GPU_NULL_HANDLE;
}

static const char *
render_target_status(void *driver UNUSED, gpu_render_target_t target) {
    GLint current;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &current);
    if ((GLuint)current == AS_GL_NAME(target)) return framebuffer_status_string(glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER));
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, AS_GL_NAME(target));
    const char *ans = framebuffer_status_string(glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER));
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, current);
    return ans;
}

static void
clear(void *driver UNUSED, float r, float g, float b, float a) {
    glClearColor(r, g, b, a);
    glClear(GL_COLOR_BUFFER_BIT);
}

static void
set_viewport(void *driver UNUSED, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    glViewport(x, y, width, height);
}

static void
get_viewport(void *driver UNUSED, int32_t ans[4]) {
    glGetIntegerv(GL_VIEWPORT, ans);
}

static void
set_scissor(void *driver UNUSED, bool enabled, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    if (enabled) {
        glEnable(GL_SCISSOR_TEST);
        glScissor(x, y, width, height);
    } else glDisable(GL_SCISSOR_TEST);
}

static void
set_srgb_output(void *driver UNUSED, bool enabled) {
    if (enabled) glEnable(GL_FRAMEBUFFER_SRGB);
    else glDisable(GL_FRAMEBUFFER_SRGB);
}

static void
read_pixels(void *driver UNUSED, int32_t x, int32_t y, uint32_t width, uint32_t height, void *dst) {
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(x, y, width, height, GL_RGBA, GL_UNSIGNED_BYTE, dst);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
}

static void
copy_to_texture(void *driver UNUSED, gpu_texture_t dst, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    const Texture *t = AS_TEXTURE(dst);
    bind_for_management(t);
    glCopyTexSubImage2D(t->target, 0, 0, 0, x, y, width, height);
}
// }}}

// Drawing {{{
static void
draw_quad(void *driver UNUSED, uint32_t instance_count, GPUBlendMode blend) {
    if (blend == GPU_BLEND_PREMULTIPLIED_ALPHA) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    } else {
        glDisable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ZERO);
    }
    if (instance_count) glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, instance_count);
    else glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
}
// }}}

__attribute__((visibility("default"))) bool
kitty_gpu_driver_load(uint32_t api_version, const GPUDriverInitParams *params, GPUDriverAPI *api, void **driver, char *errbuf, size_t errbuf_size) {
    if (api_version != KITTY_GPU_API_VERSION) {
        snprintf(errbuf, errbuf_size, "The OpenGL driver supports GPU API version %u but version %u was requested", KITTY_GPU_API_VERSION, api_version);
        return false;
    }
    if (!params->log_error || !params->fatal || !params->debug_print) {
        snprintf(errbuf, errbuf_size, "The OpenGL driver was not passed all required callbacks");
        return false;
    }
    if (the_driver) {
        snprintf(errbuf, errbuf_size, "The OpenGL driver has already been loaded");
        return false;
    }
    Driver *d = calloc(1, sizeof(Driver));
    if (!d) {
        snprintf(errbuf, errbuf_size, "Out of memory allocating the OpenGL driver");
        return false;
    }
    d->params = *params;
    the_driver = d;
    *api = (GPUDriverAPI){
        .api_version = KITTY_GPU_API_VERSION,
#define F(name) .name = name
        F(initialize),
        F(destroy),
        F(last_error),
        F(version_string),
        F(get_capabilities),

        F(texture_create),
        F(texture_reset),
        F(texture_destroy),
        F(texture_upload),
        F(texture_copy),
        F(texture_read),
        F(texture_get_desc),
        F(bind_texture),

        F(buffer_create),
        F(buffer_destroy),
        F(buffer_allocate),
        F(buffer_map),
        F(buffer_unmap),
        F(buffer_copy),
        F(bind_uniform_buffer),

        F(pipeline_create),
        F(pipeline_destroy),
        F(use_pipeline),
        F(pipeline_uniform_slot),
        F(pipeline_uniform_block),
        F(pipeline_uniform_array),
        F(pipeline_bind_uniform_block),
        F(pipeline_attribute_location),
        F(set_uniform_floats),
        F(set_uniform_ints),
        F(set_uniform_uints),

        F(vertex_layout_create),
        F(vertex_layout_destroy),
        F(bind_vertex_layout),
        F(vertex_layout_set_attribute),

        F(choose_native_visual),
        F(surface_create),
        F(surface_destroy),
        F(make_surface_current),
        F(get_current_surface),
        F(surface_resize),
        F(surface_present),
        F(surface_set_swap_interval),
        F(surface_native_changed),
        F(surface_recreate),
        F(release_native_resources),

        F(render_target_create),
        F(render_target_destroy),
        F(set_render_target),
        F(get_render_target),
        F(render_target_status),
        F(clear),
        F(set_viewport),
        F(get_viewport),
        F(set_scissor),
        F(set_srgb_output),
        F(read_pixels),
        F(copy_to_texture),

        F(draw_quad),
#undef F
    };
    *driver = d;
    return true;
}
