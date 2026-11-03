/*
 * pipelines.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Pipelines and vertex layouts.
//
// A GPU API pipeline corresponds to several Vulkan pipelines, its variants,
// as Vulkan pipelines also depend on the format of the render target, the
// blend mode and the formats of the vertex inputs. Variants are created when
// they are first drawn with. The strides of vertex inputs are dynamic state.

#include "internal.h"

#define AS_PIPELINE(handle) ((Pipeline *)(uintptr_t)(handle))
#define AS_LAYOUT(handle) ((VertexLayout *)(uintptr_t)(handle))
#define AS_BUFFER(handle) ((Buffer *)(uintptr_t)(handle))

// SPIR-V {{{
// The locations of the inputs of the vertex entry point named entry in the
// SPIR-V module, as a bit mask. Only the inputs actually used by the shader
// need to be supplied by vertex layouts.
static bool
vertex_input_locations(Driver *d, const uint32_t *words, size_t num_words, const char *entry, uint32_t *ans) {
    enum { OP_ENTRY_POINT = 15, OP_DECORATE = 71, OP_VARIABLE = 59, DECORATION_LOCATION = 30, STORAGE_INPUT = 1, MODEL_VERTEX = 0 };
    *ans = 0;
    if (num_words < 5 || words[0] != 0x07230203) {
        set_error(d, "Not a valid SPIR-V module");
        return false;
    }
    const uint32_t bound = words[3];
    int32_t *locations = malloc(sizeof(int32_t) * bound);
    uint8_t *is_input = calloc(bound, 1);
    if (!locations || !is_input) {
        free(locations);
        free(is_input);
        set_error(d, "Out of memory");
        return false;
    }
    for (uint32_t i = 0; i < bound; i++) locations[i] = -1;
    const uint32_t *interface = NULL;
    size_t num_interface = 0;
    for (size_t i = 5; i < num_words;) {
        const uint32_t count = words[i] >> 16, opcode = words[i] & 0xffff;
        if (!count || i + count > num_words) break;
        const uint32_t *op = words + i;
        switch (opcode) {
            case OP_ENTRY_POINT:
                if (count > 3 && op[1] == MODEL_VERTEX) {
                    const char *name = (const char *)(op + 3);
                    const size_t max_len = (count - 3) * 4, len = strnlen(name, max_len);
                    if (len < max_len && strcmp(name, entry) == 0) {
                        const size_t name_words = len / 4 + 1;
                        interface = op + 3 + name_words;
                        num_interface = count - 3 - name_words;
                    }
                }
                break;
            case OP_DECORATE:
                if (count >= 4 && op[2] == DECORATION_LOCATION && op[1] < bound) locations[op[1]] = (int32_t)op[3];
                break;
            case OP_VARIABLE:
                if (count >= 4 && op[2] < bound && op[3] == STORAGE_INPUT) is_input[op[2]] = 1;
                break;
        }
        i += count;
    }
    for (size_t i = 0; interface && i < num_interface; i++) {
        const uint32_t id = interface[i];
        if (id < bound && is_input[id] && locations[id] >= 0 && locations[id] < MAX_VERTEX_ATTRIBUTES) *ans |= 1u << locations[id];
    }
    free(locations);
    free(is_input);
    if (!interface) {
        set_error(d, "The SPIR-V module has no vertex entry point named: %s", entry);
        return false;
    }
    return true;
}
// }}}

// Pipelines {{{
static void
free_pipeline(Driver *d, Pipeline *p, bool deferred) {
    for (size_t i = 0; i < p->num_variants; i++) {
        if (deferred) defer_destroy_pipeline(d, p->variants[i].pipeline);
        else vkDestroyPipeline(d->device, p->variants[i].pipeline, NULL);
    }
    free(p->variants);
    if (deferred) defer_destroy_pipeline_objects(d, p->layout, p->set_layout, p->modules, p->num_modules);
    else {
        if (p->layout) vkDestroyPipelineLayout(d->device, p->layout, NULL);
        if (p->set_layout) vkDestroyDescriptorSetLayout(d->device, p->set_layout, NULL);
        for (size_t i = 0; i < p->num_modules; i++) vkDestroyShaderModule(d->device, p->modules[i], NULL);
    }
    for (size_t i = 0; i < p->num_param_blocks; i++) {
        if (p->param_blocks[i].buffer) buffer_destroy(d, AS_HANDLE(p->param_blocks[i].buffer));
    }
    free(p->param_blocks);
    for (size_t i = 0; i < p->num_bindings; i++) free(p->bindings[i].name);
    free(p->bindings);
    for (size_t i = 0; i < arraysz(p->entry_points); i++) free(p->entry_points[i]);
    free(p);
}

static bool
add_binding(Driver *d, Pipeline *p, GPUBindingKind kind, uint32_t slot, const char *name) {
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
    if (!(b->name = strdup(name ? name : ""))) {
        set_error(d, "Out of memory");
        return false;
    }
    b->kind = kind;
    b->slot = slot;
    p->num_bindings++;
    return true;
}

static bool
create_layouts(Driver *d, Pipeline *p) {
    VkDescriptorSetLayoutBinding bindings[MAX_BINDING_SLOTS];
    for (size_t i = 0; i < p->num_bindings; i++) {
        bindings[i] = (VkDescriptorSetLayoutBinding){
            .binding = p->bindings[i].slot,
            .descriptorType = p->bindings[i].kind == GPU_BINDING_TEXTURE ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,
            .descriptorCount = 1,
            .stageFlags = VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT,
        };
    }
    const VkDescriptorSetLayoutCreateInfo set_info = {
        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
        .bindingCount = (uint32_t)p->num_bindings,
        .pBindings = bindings,
    };
    VkResult r = vkCreateDescriptorSetLayout(d->device, &set_info, NULL, &p->set_layout);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create a descriptor set layout with error: %s", vk_result_string(r));
        return false;
    }
    // Every pipeline layout has the same push constant range, see draw_quad()
    const VkPushConstantRange range = {.stageFlags = VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, .size = PUSH_CONSTANTS_SIZE};
    const VkPipelineLayoutCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount = 1,
        .pSetLayouts = &p->set_layout,
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &range,
    };
    if ((r = vkCreatePipelineLayout(d->device, &info, NULL, &p->layout)) != VK_SUCCESS) {
        set_error(d, "Failed to create a pipeline layout with error: %s", vk_result_string(r));
        return false;
    }
    return true;
}

static bool
create_modules(Driver *d, Pipeline *p, const GPUShaderSource *sources, size_t num_sources) {
    if (num_sources != 2) {
        set_error(d, "A pipeline needs a vertex and a fragment shader");
        return false;
    }
    for (size_t i = 0; i < num_sources; i++) {
        const GPUShaderSource *s = sources + i;
        if (s->language != GPU_SHADER_LANGUAGE_SPIRV) {
            set_error(d, "The Vulkan driver supports only SPIR-V shaders");
            return false;
        }
        if (!s->size || s->size % 4 || !s->entry_point) {
            set_error(d, "Invalid SPIR-V shader");
            return false;
        }
        // Modules containing the entry points of several stages are passed for each stage
        VkShaderModule module = VK_NULL_HANDLE;
        if (i > 0 && sources[0].code == s->code && sources[0].size == s->size) module = p->modules[0];
        else {
            const VkShaderModuleCreateInfo info = {
                .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = s->size, .pCode = (const uint32_t *)s->code};
            VkResult r = vkCreateShaderModule(d->device, &info, NULL, &module);
            if (r != VK_SUCCESS) {
                set_error(d, "Failed to create a shader module with error: %s", vk_result_string(r));
                return false;
            }
            p->modules[p->num_modules++] = module;
        }
        if (!(p->entry_points[i] = strdup(s->entry_point))) {
            set_error(d, "Out of memory");
            return false;
        }
        p->stages[i] = (VkPipelineShaderStageCreateInfo){
            .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
            .stage = s->stage == GPU_SHADER_VERTEX ? VK_SHADER_STAGE_VERTEX_BIT : VK_SHADER_STAGE_FRAGMENT_BIT,
            .module = module,
            .pName = p->entry_points[i],
        };
        if (s->stage == GPU_SHADER_VERTEX && !vertex_input_locations(d, (const uint32_t *)s->code, s->size / 4, s->entry_point, &p->vertex_inputs))
            return false;
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
    const GPUNativeName *native_names UNUSED,
    size_t num_native_names UNUSED) {
    Driver *d = driver;
    Pipeline *p = calloc(1, sizeof(Pipeline));
    if (!p) goto oom;
    if (!(p->bindings = calloc(MAX(1u, num_bindings + num_param_blocks), sizeof(PipelineBinding)))) goto oom;
    if (!(p->param_blocks = calloc(MAX(1u, num_param_blocks), sizeof(ParamBlock)))) goto oom;
    if (!create_modules(d, p, sources, num_sources)) goto fail;
    for (size_t i = 0; i < num_bindings; i++) {
        if (!add_binding(d, p, bindings[i].kind, bindings[i].slot, bindings[i].name)) goto fail;
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
        } else {
            // Uniform blocks whose contents are constant for the lifetime of
            // the pipeline are kept in a uniform buffer owned by the pipeline
            if (!add_binding(d, p, GPU_BINDING_UNIFORM_BLOCK, (uint32_t)src->slot, src->name)) goto fail;
            pb->buffer = AS_BUFFER(buffer_create(d, GPU_BUFFER_UNIFORM));
            if (!pb->buffer) goto fail;
            buffer_allocate(d, AS_HANDLE(pb->buffer), src->size, GPU_UPDATE_RARELY);
            memset(pb->buffer->storage.alloc.mapped, 0, src->size);
        }
    }
    if (!create_layouts(d, p)) goto fail;
    LIST_ADD(d->pipelines, p);
    return AS_HANDLE(p);
oom:
    set_error(d, "Out of memory");
fail:
    if (p) free_pipeline(d, p, false);
    return GPU_NULL_HANDLE;
}

void
pipeline_destroy(void *driver, gpu_pipeline_t pipeline) {
    Driver *d = driver;
    Pipeline *p = AS_PIPELINE(pipeline);
    if (!p) return;
    if (d->pipeline == p) d->pipeline = NULL;
    if (d->cmd_state.push_constants_of == p) d->cmd_state.push_constants_of = NULL;
    LIST_REMOVE(d->pipelines, p);
    free_pipeline(d, p, true);
}

void
destroy_all_pipelines(Driver *d) {
    while (d->pipelines) {
        Pipeline *p = d->pipelines;
        LIST_REMOVE(d->pipelines, p);
        free_pipeline(d, p, false);
    }
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
            // The size is not known without reflecting the SPIR-V
            ans->size = 0;
            return true;
        }
    }
    set_error(d, "The pipeline has no uniform block named: %s", name);
    return false;
}

int32_t
pipeline_attribute_location(void *driver UNUSED, gpu_pipeline_t pipeline UNUSED, const char *name UNUSED) {
    // SPIR-V does not reliably preserve the names of inputs, the locations
    // come from the reflection data in the program metadata
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
        if (d->cmd_state.push_constants_of == p) d->cmd_state.push_constants_dirty = true;
    } else if (!write_buffer(d, pb->buffer, data, size)) log_error(d, "Failed to write the parameter block %u", block);
}

VkFormat
vertex_attribute_format(uint32_t components, GPUAttribType type) {
    static const VkFormat formats[4][4] = {
        {VK_FORMAT_R8_UINT, VK_FORMAT_R8G8_UINT, VK_FORMAT_R8G8B8_UINT, VK_FORMAT_R8G8B8A8_UINT},
        {VK_FORMAT_R16_UINT, VK_FORMAT_R16G16_UINT, VK_FORMAT_R16G16B16_UINT, VK_FORMAT_R16G16B16A16_UINT},
        {VK_FORMAT_R32_UINT, VK_FORMAT_R32G32_UINT, VK_FORMAT_R32G32B32_UINT, VK_FORMAT_R32G32B32A32_UINT},
        {VK_FORMAT_R32_SFLOAT, VK_FORMAT_R32G32_SFLOAT, VK_FORMAT_R32G32B32_SFLOAT, VK_FORMAT_R32G32B32A32_SFLOAT},
    };
    if (components < 1 || components > 4) return VK_FORMAT_UNDEFINED;
    switch (type) {
        case GPU_ATTRIB_U8: return formats[0][components - 1];
        case GPU_ATTRIB_U16: return formats[1][components - 1];
        case GPU_ATTRIB_U32: return formats[2][components - 1];
        case GPU_ATTRIB_F32: return formats[3][components - 1];
    }
    return VK_FORMAT_UNDEFINED;
}

static VkPipeline
create_variant(Driver *d, Pipeline *p, const PipelineVariantKey *key) {
    VkVertexInputBindingDescription vbindings[MAX_VERTEX_ATTRIBUTES];
    VkVertexInputAttributeDescription vattrs[MAX_VERTEX_ATTRIBUTES];
    uint32_t n = 0;
    for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
        if (!key->attribute_formats[loc]) continue;
        // Each input has a binding of its own, its offset is applied when binding the buffer
        vbindings[n] = (VkVertexInputBindingDescription){
            .binding = loc, .inputRate = key->attribute_per_instance[loc] ? VK_VERTEX_INPUT_RATE_INSTANCE : VK_VERTEX_INPUT_RATE_VERTEX};
        vattrs[n] = (VkVertexInputAttributeDescription){.location = loc, .binding = loc, .format = key->attribute_formats[loc]};
        n++;
    }
    const VkPipelineVertexInputStateCreateInfo vertex_input = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
        .vertexBindingDescriptionCount = n,
        .pVertexBindingDescriptions = vbindings,
        .vertexAttributeDescriptionCount = n,
        .pVertexAttributeDescriptions = vattrs,
    };
    const VkPipelineInputAssemblyStateCreateInfo input_assembly = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    const VkPipelineViewportStateCreateInfo viewport = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .scissorCount = 1};
    const VkPipelineRasterizationStateCreateInfo raster = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode = VK_POLYGON_MODE_FILL,
        .cullMode = VK_CULL_MODE_NONE,
        .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE,
        .lineWidth = 1.f,
    };
    const VkPipelineMultisampleStateCreateInfo multisample = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    const VkPipelineColorBlendAttachmentState blend = {
        .blendEnable = key->blend,
        // Pre-multiplied alpha, see GPU_BLEND_PREMULTIPLIED_ALPHA
        .srcColorBlendFactor = VK_BLEND_FACTOR_ONE,
        .dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .colorBlendOp = VK_BLEND_OP_ADD,
        .srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE,
        .dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .alphaBlendOp = VK_BLEND_OP_ADD,
        .colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT,
    };
    const VkPipelineColorBlendStateCreateInfo color_blend = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &blend};
    const VkDynamicState dynamic_states[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR, VK_DYNAMIC_STATE_VERTEX_INPUT_BINDING_STRIDE};
    const VkPipelineDynamicStateCreateInfo dynamic = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = n ? 3 : 2,
        .pDynamicStates = dynamic_states,
    };
    const VkPipelineRenderingCreateInfo rendering = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO, .colorAttachmentCount = 1, .pColorAttachmentFormats = &key->color_format};
    const VkGraphicsPipelineCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,
        .pNext = &rendering,
        .stageCount = 2,
        .pStages = p->stages,
        .pVertexInputState = &vertex_input,
        .pInputAssemblyState = &input_assembly,
        .pViewportState = &viewport,
        .pRasterizationState = &raster,
        .pMultisampleState = &multisample,
        .pColorBlendState = &color_blend,
        .pDynamicState = &dynamic,
        .layout = p->layout,
    };
    VkPipeline ans = VK_NULL_HANDLE;
    VkResult r = vkCreateGraphicsPipelines(d->device, VK_NULL_HANDLE, 1, &info, NULL, &ans);
    if (r != VK_SUCCESS) {
        log_error(d, "Failed to create a Vulkan pipeline with error: %s", vk_result_string(r));
        return VK_NULL_HANDLE;
    }
    return ans;
}

VkPipeline
pipeline_for_current_state(Driver *d, bool blend) {
    Pipeline *p = d->pipeline;
    PipelineVariantKey key;
    memset(&key, 0, sizeof(key)); // the key is compared with memcmp()
    key.color_format = d->rendering.format;
    key.blend = blend;
    for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
        if (!(p->vertex_inputs & (1u << loc))) continue;
        const VertexAttribute *a = d->vertex_layout ? d->vertex_layout->attributes + loc : NULL;
        if (!a || !a->enabled) {
            log_error(d, "The vertex layout has no input at location: %u used by the shader", loc);
            return VK_NULL_HANDLE;
        }
        if (a->divisor > 1) {
            log_error(d, "Instance divisors greater than one are not supported");
            return VK_NULL_HANDLE;
        }
        key.attribute_formats[loc] = vertex_attribute_format(a->components, a->type);
        key.attribute_per_instance[loc] = a->divisor > 0;
    }
    for (size_t i = 0; i < p->num_variants; i++) {
        if (memcmp(&p->variants[i].key, &key, sizeof(key)) == 0) return p->variants[i].pipeline;
    }
    for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
        if (!key.attribute_formats[loc]) continue;
        VkFormatProperties fp;
        vkGetPhysicalDeviceFormatProperties(d->physical_device, key.attribute_formats[loc], &fp);
        if (!(fp.bufferFeatures & VK_FORMAT_FEATURE_VERTEX_BUFFER_BIT)) {
            log_error(d, "The GPU does not support the vertex input format: %d", (int)key.attribute_formats[loc]);
            return VK_NULL_HANDLE;
        }
    }
    if (p->num_variants >= p->variants_capacity) {
        const size_t cap = MAX(4u, p->variants_capacity * 2);
        PipelineVariant *v = realloc(p->variants, cap * sizeof(PipelineVariant));
        if (!v) fatal(d, "Out of memory");
        p->variants = v;
        p->variants_capacity = cap;
    }
    const VkPipeline vp = create_variant(d, p, &key);
    if (!vp) return VK_NULL_HANDLE;
    p->variants[p->num_variants++] = (PipelineVariant){.key = key, .pipeline = vp};
    return vp;
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
        .stride = stride ? stride
                         : components * (type == GPU_ATTRIB_U8    ? 1
                                         : type == GPU_ATTRIB_U16 ? 2
                                                                  : 4),
        .offset = offset,
        .divisor = instance_divisor,
    };
    d->vertex_layout = l;
}
// }}}
