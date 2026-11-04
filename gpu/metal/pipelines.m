/*
 * pipelines.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Pipelines and vertex layouts.
//
// A GPU API pipeline corresponds to several Metal render pipeline states, its
// variants, as Metal pipeline states also depend on the pixel format of the
// render target, the blend mode and the formats, strides and step rates of
// the vertex inputs. Variants are created when they are first drawn with.

#include "internal.h"
#include "version.h"

// The language version passed to the MSL compiler, see compile_library()
_Static_assert(MSL_VERSION == 24, "Update the MTLLanguageVersion used for compiling shaders");

#define AS_PIPELINE(handle) ((Pipeline *)(uintptr_t)(handle))
#define AS_LAYOUT(handle) ((VertexLayout *)(uintptr_t)(handle))
#define AS_BUFFER(handle) ((Buffer *)(uintptr_t)(handle))

// Native names {{{
// The native name of a Slang name, see MSL_PUSH_CONSTANTS_NAME, NULL if there is none
static const char *
native_name(const GPUNativeName *names, size_t num_names, const char *name) {
    for (size_t i = 0; i < num_names; i++) {
        if (names[i].name && names[i].native_name && strcmp(names[i].name, name) == 0) return names[i].native_name;
    }
    return NULL;
}

static bool
buffer_index_for(Driver *d, const GPUNativeName *names, size_t num_names, const char *name, int32_t *ans) {
    const char *n = native_name(names, num_names, name);
    int idx = -1;
    if (!n || sscanf(n, "buffer(%d)", &idx) != 1) {
        set_error(d, "The uniform block %s has no buffer index in the native names of the shader", name);
        return false;
    }
    if (idx < 0 || idx >= MAX_SHADER_BUFFER_INDEX) {
        set_error(d, "The buffer index %d of the uniform block %s is not below %d", idx, name, MAX_SHADER_BUFFER_INDEX);
        return false;
    }
    *ans = idx;
    return true;
}

static bool
texture_indices_for(Driver *d, const GPUNativeName *names, size_t num_names, const char *name, int32_t *texture, int32_t *sampler) {
    const char *n = native_name(names, num_names, name);
    int t = -1, s = -1;
    if (!n || sscanf(n, "texture(%d) sampler(%d)", &t, &s) != 2) {
        set_error(d, "The texture %s has no texture and sampler indices in the native names of the shader", name);
        return false;
    }
    if (t < 0 || t >= MAX_SHADER_TEXTURE_INDEX || s < 0 || s >= MAX_SHADER_SAMPLER_INDEX) {
        set_error(d, "The texture and sampler indices %d and %d of the texture %s are out of range", t, s, name);
        return false;
    }
    *texture = t;
    *sampler = s;
    return true;
}
// }}}

// Pipelines {{{
static void
free_pipeline(Driver *d, Pipeline *p) {
    for (size_t i = 0; i < p->num_variants; i++) {
        if (d->rendering.pipeline == p->variants[i].state) d->rendering.pipeline = nil;
        // Command buffers retain the pipeline states they use
        [p->variants[i].state release];
    }
    free(p->variants);
    [p->vertex_function release];
    [p->fragment_function release];
    if (p->param_blocks) {
        for (size_t i = 0; i < p->num_param_blocks; i++) {
            if (p->param_blocks[i].buffer) buffer_destroy(d, AS_HANDLE(p->param_blocks[i].buffer));
        }
    }
    free(p->param_blocks);
    if (p->bindings) {
        for (size_t i = 0; i < p->num_bindings; i++) free(p->bindings[i].name);
    }
    free(p->bindings);
    free(p);
}

static bool
add_binding(Driver *d, Pipeline *p, GPUBindingKind kind, uint32_t slot, const char *name, const GPUNativeName *names, size_t num_names) {
    if (!name) name = "";
    if (slot >= MAX_BINDING_SLOTS) {
        set_error(d, "The binding slot %u of %s is too large", slot, name);
        return false;
    }
    for (size_t i = 0; i < p->num_bindings; i++) {
        if (p->bindings[i].slot == slot) {
            set_error(d, "The binding slot %u is used by both %s and %s", slot, p->bindings[i].name, name);
            return false;
        }
    }
    PipelineBinding *b = p->bindings + p->num_bindings;
    *b = (PipelineBinding){.kind = kind, .slot = slot, .buffer_index = -1, .texture_index = -1, .sampler_index = -1};
    if (kind == GPU_BINDING_TEXTURE) {
        if (!texture_indices_for(d, names, num_names, name, &b->texture_index, &b->sampler_index)) return false;
    } else if (!buffer_index_for(d, names, num_names, name, &b->buffer_index)) return false;
    if (!(b->name = strdup(name))) {
        set_error(d, "Out of memory");
        return false;
    }
    p->num_bindings++;
    return true;
}

static id<MTLLibrary>
compile_library(Driver *d, const GPUShaderSource *s) {
    const size_t size = s->size ? s->size : strlen(s->code);
    id<MTLLibrary> ans = nil;
    @autoreleasepool {
        NSString *src = [[[NSString alloc] initWithBytes:s->code length:size encoding:NSUTF8StringEncoding] autorelease];
        if (src == nil) {
            set_error(d, "The MSL shader is not valid UTF-8");
            return nil;
        }
        MTLCompileOptions *opts = [[[MTLCompileOptions alloc] init] autorelease];
        [opts setLanguageVersion:MTLLanguageVersion2_4];
        // OpenGL on Apple GPUs is implemented on top of Metal and uses fast
        // math, so that is needed for rendering to match it exactly, for
        // example in the pow() of the gamma adjustments of text. Relaxed math
        // does the same optimizations but keeps NaN and infinity working, which
        // custom shaders might rely on. Before macOS 15, fast math, the default,
        // is the only choice.
#if defined(__MAC_15_0) && __MAC_OS_X_VERSION_MAX_ALLOWED >= __MAC_15_0
        if (@available(macOS 15.0, *)) [opts setMathMode:MTLMathModeRelaxed];
        else
#endif
        {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
            [opts setFastMathEnabled:YES];
#pragma clang diagnostic pop
        }
        NSError *err = nil;
        ans = [d->device newLibraryWithSource:src options:opts error:&err];
        if (ans == nil) set_error(d, "Failed to compile the MSL shader with error: %s", error_description(err));
        else if (err != nil) debug_print(d, "Metal: Compiling an MSL shader produced warnings: %s", error_description(err));
    }
    return ans;
}

static bool
same_source(const GPUShaderSource *a, const GPUShaderSource *b) {
    if (a->code == b->code && a->size == b->size) return true;
    const size_t asz = a->size ? a->size : strlen(a->code), bsz = b->size ? b->size : strlen(b->code);
    return asz == bsz && memcmp(a->code, b->code, asz) == 0;
}

static id<MTLFunction>
get_function(Driver *d, id<MTLLibrary> library, const char *name) {
    id<MTLFunction> ans = nil;
    @autoreleasepool {
        ans = [library newFunctionWithName:[NSString stringWithUTF8String:name]];
    }
    if (ans == nil) set_error(d, "The MSL shader has no function named: %s", name);
    return ans;
}

static bool
create_functions(Driver *d, Pipeline *p, const GPUShaderSource *sources, size_t num_sources) {
    if (num_sources != 2) {
        set_error(d, "A pipeline needs a vertex and a fragment shader");
        return false;
    }
    id<MTLLibrary> libraries[2] = {nil, nil};
    bool ok = true;
    for (size_t i = 0; i < num_sources && ok; i++) {
        const GPUShaderSource *s = sources + i;
        if (s->language != GPU_SHADER_LANGUAGE_MSL) {
            set_error(d, "The Metal driver supports only MSL shaders");
            ok = false;
            break;
        }
        if (!s->code || !s->entry_point) {
            set_error(d, "Invalid MSL shader");
            ok = false;
            break;
        }
        // Modules containing the entry points of several stages are passed for
        // each stage, as separate copies, compiling them is slow, so do it once
        if (i > 0 && same_source(sources, s)) libraries[i] = [libraries[0] retain];
        else if (!(libraries[i] = compile_library(d, s))) {
            ok = false;
            break;
        }
        id<MTLFunction> f = get_function(d, libraries[i], s->entry_point);
        if (f == nil) {
            ok = false;
            break;
        }
        const MTLFunctionType expected = s->stage == GPU_SHADER_VERTEX ? MTLFunctionTypeVertex : MTLFunctionTypeFragment;
        if ([f functionType] != expected) {
            set_error(d, "The MSL function %s is not a %s function", s->entry_point, s->stage == GPU_SHADER_VERTEX ? "vertex" : "fragment");
            [f release];
            ok = false;
            break;
        }
        if (s->stage == GPU_SHADER_VERTEX) {
            [p->vertex_function release];
            p->vertex_function = f;
        } else {
            [p->fragment_function release];
            p->fragment_function = f;
        }
    }
    // The functions retain their libraries
    [libraries[0] release];
    [libraries[1] release];
    if (!ok) return false;
    if (p->vertex_function == nil || p->fragment_function == nil) {
        set_error(d, "A pipeline needs a vertex and a fragment shader");
        return false;
    }
    // Only the inputs actually used by the vertex function need to be
    // supplied by vertex layouts. Declared but unused inputs are passed if the
    // vertex layout has them.
    for (MTLVertexAttribute *a in [p->vertex_function vertexAttributes]) {
        const NSUInteger loc = [a attributeIndex];
        if (loc >= MAX_VERTEX_ATTRIBUTES) {
            set_error(d, "The vertex input %s has the location %lu, which is too large", [[a name] UTF8String], (unsigned long)loc);
            return false;
        }
        p->declared_inputs |= 1u << loc;
        if ([a isActive]) p->vertex_inputs |= 1u << loc;
    }
    return true;
}

gpu_pipeline_t
pipeline_create(
    void *driver,
    const GPUShaderSource *sources,
    size_t num_sources,
    const GPUParamBlock *param_blocks,
    size_t num_param_blocks,
    const GPUBinding *bindings,
    size_t num_bindings,
    const GPUNativeName *native_names,
    size_t num_native_names) {
    Driver *d = driver;
    Pipeline *p = calloc(1, sizeof(Pipeline));
    if (!p) goto oom;
    p->push_constants_index = -1;
    if (!(p->bindings = calloc(MAX(1u, num_bindings + num_param_blocks), sizeof(PipelineBinding)))) goto oom;
    if (!(p->param_blocks = calloc(MAX(1u, num_param_blocks), sizeof(ParamBlock)))) goto oom;
    if (!create_functions(d, p, sources, num_sources)) goto fail;
    for (size_t i = 0; i < num_bindings; i++) {
        if (!add_binding(d, p, bindings[i].kind, bindings[i].slot, bindings[i].name, native_names, num_native_names)) goto fail;
    }
    for (size_t i = 0; i < num_param_blocks; i++) {
        const GPUParamBlock *src = param_blocks + i;
        ParamBlock *pb = p->param_blocks + p->num_param_blocks++;
        pb->slot = src->slot;
        pb->size = src->size;
        if (src->slot < 0) {
            if (src->size > PUSH_CONSTANTS_SIZE) {
                set_error(d, "The push constant block of size %u is larger than the maximum of %d", src->size, PUSH_CONSTANTS_SIZE);
                goto fail;
            }
            p->push_constants_size = src->size;
            if (!buffer_index_for(d, native_names, num_native_names, MSL_PUSH_CONSTANTS_NAME, &p->push_constants_index)) goto fail;
        } else {
            // Uniform blocks whose contents are constant for the lifetime of
            // the pipeline are kept in a uniform buffer owned by the pipeline
            if (!add_binding(d, p, GPU_BINDING_UNIFORM_BLOCK, (uint32_t)src->slot, src->name, native_names, num_native_names)) goto fail;
            pb->buffer = AS_BUFFER(buffer_create(d, GPU_BUFFER_UNIFORM));
            if (!pb->buffer) goto fail;
            buffer_allocate(d, AS_HANDLE(pb->buffer), src->size, GPU_UPDATE_RARELY);
            memset([pb->buffer->storage.buffer contents], 0, src->size);
        }
    }
    LIST_ADD(d->pipelines, p);
    return AS_HANDLE(p);
oom:
    set_error(d, "Out of memory");
fail:
    if (p) free_pipeline(d, p);
    return GPU_NULL_HANDLE;
}

void
pipeline_destroy(void *driver, gpu_pipeline_t pipeline) {
    Driver *d = driver;
    Pipeline *p = AS_PIPELINE(pipeline);
    if (!p) return;
    if (d->pipeline == p) d->pipeline = NULL;
    if (d->rendering.push_constants_of == p) d->rendering.push_constants_of = NULL;
    LIST_REMOVE(d->pipelines, p);
    free_pipeline(d, p);
}

void
destroy_all_pipelines(Driver *d) {
    while (d->pipelines) pipeline_destroy(d, AS_HANDLE(d->pipelines));
}

void
use_pipeline(void *driver, gpu_pipeline_t pipeline) {
    ((Driver *)driver)->pipeline = AS_PIPELINE(pipeline);
}

bool
pipeline_uniform_block(void *driver, gpu_pipeline_t pipeline, const char *name, GPUUniformBlockInfo *ans) {
    Driver *d = driver;
    const Pipeline *p = AS_PIPELINE(pipeline);
    for (size_t i = 0; i < p->num_bindings; i++) {
        if (p->bindings[i].kind == GPU_BINDING_UNIFORM_BLOCK && strcmp(p->bindings[i].name, name) == 0) {
            ans->index = p->bindings[i].slot;
            // The size is not known without pipeline reflection
            ans->size = 0;
            return true;
        }
    }
    set_error(d, "The pipeline has no uniform block named: %s", name);
    return false;
}

int32_t
pipeline_attribute_location(void *driver UNUSED, gpu_pipeline_t pipeline UNUSED, const char *name UNUSED) {
    // The names of inputs in the MSL code are mangled by the shader compiler,
    // the locations come from the reflection data in the program metadata
    return -1;
}

void
set_params(void *driver, gpu_pipeline_t pipeline, uint32_t block, const void *data, size_t size) {
    Driver *d = driver;
    Pipeline *p = AS_PIPELINE(pipeline);
    if (block >= p->num_param_blocks) {
        log_error(d, "Invalid parameter block index: %u", block);
        return;
    }
    ParamBlock *pb = p->param_blocks + block;
    if (size != pb->size) {
        log_error(d, "The data for parameter block %u is %zu bytes instead of %u", block, size, pb->size);
        return;
    }
    if (pb->slot < 0) {
        memcpy(p->push_constants, data, size);
        if (d->rendering.push_constants_of == p) d->rendering.push_constants_dirty = true;
    } else if (!write_buffer(d, pb->buffer, data, size)) log_error(d, "Failed to write the parameter block %u", block);
}
// }}}

// Variants {{{
size_t
vertex_attribute_size(uint32_t components, GPUAttribType type) {
    switch (type) {
        case GPU_ATTRIB_U8: return components;
        case GPU_ATTRIB_U16: return 2u * components;
        case GPU_ATTRIB_U32:
        case GPU_ATTRIB_F32: return 4u * components;
    }
    return 4u * components;
}

static MTLVertexFormat
vertex_format(uint32_t components, GPUAttribType type) {
    static const MTLVertexFormat formats[4][4] = {
        {MTLVertexFormatUChar, MTLVertexFormatUChar2, MTLVertexFormatUChar3, MTLVertexFormatUChar4},
        {MTLVertexFormatUShort, MTLVertexFormatUShort2, MTLVertexFormatUShort3, MTLVertexFormatUShort4},
        {MTLVertexFormatUInt, MTLVertexFormatUInt2, MTLVertexFormatUInt3, MTLVertexFormatUInt4},
        {MTLVertexFormatFloat, MTLVertexFormatFloat2, MTLVertexFormatFloat3, MTLVertexFormatFloat4},
    };
    if (components < 1 || components > 4) return MTLVertexFormatInvalid;
    switch (type) {
        case GPU_ATTRIB_U8: return formats[0][components - 1];
        case GPU_ATTRIB_U16: return formats[1][components - 1];
        case GPU_ATTRIB_U32: return formats[2][components - 1];
        case GPU_ATTRIB_F32: return formats[3][components - 1];
    }
    return MTLVertexFormatInvalid;
}

static id<MTLRenderPipelineState>
create_variant(Driver *d, Pipeline *p, const PipelineVariantKey *key) {
    id<MTLRenderPipelineState> ans = nil;
    @autoreleasepool {
        MTLRenderPipelineDescriptor *desc = [[[MTLRenderPipelineDescriptor alloc] init] autorelease];
        [desc setVertexFunction:p->vertex_function];
        [desc setFragmentFunction:p->fragment_function];
        MTLVertexDescriptor *vd = [MTLVertexDescriptor vertexDescriptor];
        bool has_inputs = false;
        for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
            const VertexInputKey *k = key->inputs + loc;
            if (k->format == MTLVertexFormatInvalid) continue;
            has_inputs = true;
            // Each input has a buffer of its own, its offset is applied when binding the buffer
            MTLVertexAttributeDescriptor *a = [[vd attributes] objectAtIndexedSubscript:loc];
            [a setFormat:k->format];
            [a setOffset:0];
            [a setBufferIndex:VERTEX_BUFFER_INDEX(loc)];
            MTLVertexBufferLayoutDescriptor *l = [[vd layouts] objectAtIndexedSubscript:VERTEX_BUFFER_INDEX(loc)];
            [l setStride:k->stride];
            [l setStepFunction:k->per_instance ? MTLVertexStepFunctionPerInstance : MTLVertexStepFunctionPerVertex];
            [l setStepRate:k->step_rate];
        }
        if (has_inputs) [desc setVertexDescriptor:vd];
        MTLRenderPipelineColorAttachmentDescriptor *ca = [[desc colorAttachments] objectAtIndexedSubscript:0];
        [ca setPixelFormat:key->color_format];
        [ca setBlendingEnabled:key->blend ? YES : NO];
        // Pre-multiplied alpha, see GPU_BLEND_PREMULTIPLIED_ALPHA
        [ca setRgbBlendOperation:MTLBlendOperationAdd];
        [ca setAlphaBlendOperation:MTLBlendOperationAdd];
        [ca setSourceRGBBlendFactor:MTLBlendFactorOne];
        [ca setSourceAlphaBlendFactor:MTLBlendFactorOne];
        [ca setDestinationRGBBlendFactor:MTLBlendFactorOneMinusSourceAlpha];
        [ca setDestinationAlphaBlendFactor:MTLBlendFactorOneMinusSourceAlpha];
        NSError *err = nil;
        ans = [d->device newRenderPipelineStateWithDescriptor:desc error:&err];
        if (ans == nil) log_error(d, "Failed to create a Metal pipeline with error: %s", error_description(err));
    }
    return ans;
}

id<MTLRenderPipelineState>
pipeline_for_current_state(Driver *d, bool blend, PipelineVariantKey *key) {
    Pipeline *p = d->pipeline;
    memset(key, 0, sizeof(*key)); // the key is compared with memcmp()
    key->color_format = d->rendering.format;
    key->blend = blend;
    for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
        if (!(p->declared_inputs & (1u << loc))) continue;
        const VertexAttribute *a = d->vertex_layout ? d->vertex_layout->attributes + loc : NULL;
        if (!a || !a->enabled) {
            if (!(p->vertex_inputs & (1u << loc))) continue;
            log_error(d, "The vertex layout has no input at location: %u used by the shader", loc);
            return nil;
        }
        VertexInputKey *k = key->inputs + loc;
        k->format = vertex_format(a->components, a->type);
        if (k->format == MTLVertexFormatInvalid) {
            log_error(d, "The vertex input at location: %u has an unsupported format", loc);
            return nil;
        }
        if ((a->offset % VERTEX_INPUT_ALIGNMENT) != 0 || (a->stride % VERTEX_INPUT_ALIGNMENT) != 0) {
            log_error(
                d,
                "The vertex input at location: %u has offset: %zu and stride: %u which are not multiples of: %u bytes",
                loc,
                a->offset,
                a->stride,
                VERTEX_INPUT_ALIGNMENT);
            return nil;
        }
        k->stride = a->stride;
        k->per_instance = a->divisor > 0;
        k->step_rate = a->divisor > 0 ? a->divisor : 1;
    }
    for (size_t i = 0; i < p->num_variants; i++) {
        if (memcmp(&p->variants[i].key, key, sizeof(*key)) == 0) return p->variants[i].state;
    }
    if (p->num_variants >= p->variants_capacity) {
        const size_t cap = MAX((size_t)4u, p->variants_capacity * 2);
        PipelineVariant *v = realloc(p->variants, cap * sizeof(PipelineVariant));
        if (!v) fatal(d, "Out of memory");
        p->variants = v;
        p->variants_capacity = cap;
    }
    id<MTLRenderPipelineState> state = create_variant(d, p, key);
    if (state == nil) return nil;
    p->variants[p->num_variants++] = (PipelineVariant){.key = *key, .state = state};
    return state;
}
// }}}

// Vertex layouts {{{
gpu_vertex_layout_t
vertex_layout_create(void *driver) {
    Driver *d = driver;
    VertexLayout *l = calloc(1, sizeof(VertexLayout));
    if (!l) {
        set_error(d, "Out of memory");
        return GPU_NULL_HANDLE;
    }
    LIST_ADD(d->vertex_layouts, l);
    return AS_HANDLE(l);
}

void
vertex_layout_destroy(void *driver, gpu_vertex_layout_t layout) {
    Driver *d = driver;
    VertexLayout *l = AS_LAYOUT(layout);
    if (!l) return;
    if (d->vertex_layout == l) d->vertex_layout = NULL;
    LIST_REMOVE(d->vertex_layouts, l);
    free(l);
}

void
bind_vertex_layout(void *driver, gpu_vertex_layout_t layout) {
    ((Driver *)driver)->vertex_layout = AS_LAYOUT(layout);
}

void
vertex_layout_set_attribute(
    void *driver,
    gpu_vertex_layout_t layout,
    uint32_t location,
    gpu_buffer_t buffer,
    uint32_t components,
    GPUAttribType type,
    uint32_t stride,
    size_t offset,
    uint32_t instance_divisor) {
    Driver *d = driver;
    VertexLayout *l = AS_LAYOUT(layout);
    if (location >= MAX_VERTEX_ATTRIBUTES) {
        log_error(d, "Invalid vertex input location: %u", location);
        return;
    }
    l->attributes[location] = (VertexAttribute){
        .enabled = true,
        .buffer = AS_BUFFER(buffer),
        .components = components,
        .type = type,
        // A stride of zero means tightly packed, as in OpenGL
        .stride = stride ? stride : (uint32_t)vertex_attribute_size(components, type),
        .offset = offset,
        .divisor = instance_divisor,
    };
    d->vertex_layout = l;
}
// }}}
