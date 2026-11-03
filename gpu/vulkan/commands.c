/*
 * commands.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Recording and submitting commands, rendering and drawing

#include "internal.h"

#define AS_TEXTURE(handle) ((Texture *)(uintptr_t)(handle))
#define AS_RENDER_TARGET(handle) ((RenderTarget *)(uintptr_t)(handle))

// Deferred destruction {{{
typedef enum { GARBAGE_BUFFER, GARBAGE_IMAGE, GARBAGE_PIPELINE, GARBAGE_PIPELINE_OBJECTS } GarbageKind;

struct Garbage {
    GarbageKind kind;
    union {
        struct {
            VkBuffer buffer;
            Allocation alloc;
        } buffer;
        Image image;
        VkPipeline pipeline;
        struct {
            VkPipelineLayout layout;
            VkDescriptorSetLayout set_layout;
            VkShaderModule modules[2];
            size_t num_modules;
        } objects;
    };
    Garbage *next;
};

static void
destroy_garbage(Driver *d, Garbage *g) {
    switch (g->kind) {
        case GARBAGE_BUFFER:
            vkDestroyBuffer(d->device, g->buffer.buffer, NULL);
            free_memory(d, &g->buffer.alloc);
            break;
        case GARBAGE_IMAGE:
            destroy_image_views(d, &g->image);
            vkDestroyImage(d->device, g->image.image, NULL);
            free_memory(d, &g->image.alloc);
            break;
        case GARBAGE_PIPELINE: vkDestroyPipeline(d->device, g->pipeline, NULL); break;
        case GARBAGE_PIPELINE_OBJECTS:
            vkDestroyPipelineLayout(d->device, g->objects.layout, NULL);
            vkDestroyDescriptorSetLayout(d->device, g->objects.set_layout, NULL);
            for (size_t i = 0; i < g->objects.num_modules; i++) vkDestroyShaderModule(d->device, g->objects.modules[i], NULL);
            break;
    }
}

static void
add_garbage(Driver *d, Garbage *g) {
    // Attached to the context being recorded, which completes after every
    // submission that could use the object
    Context *c = current_context(d);
    g->next = c->garbage;
    c->garbage = g;
}

static Garbage *
new_garbage(Driver *d, GarbageKind kind) {
    Garbage *g = calloc(1, sizeof(Garbage));
    if (!g) fatal(d, "Out of memory");
    g->kind = kind;
    return g;
}

void
defer_destroy_buffer(Driver *d, VkBuffer buffer, Allocation *alloc) {
    Garbage *g = new_garbage(d, GARBAGE_BUFFER);
    g->buffer.buffer = buffer;
    g->buffer.alloc = *alloc;
    *alloc = (Allocation){0};
    add_garbage(d, g);
}

void
defer_destroy_image(Driver *d, Image *image) {
    if (d->rendering.image == image) end_rendering(d);
    Garbage *g = new_garbage(d, GARBAGE_IMAGE);
    g->image = *image;
    *image = (Image){0};
    add_garbage(d, g);
}

void
defer_destroy_pipeline(Driver *d, VkPipeline pipeline) {
    if (d->cmd_state.pipeline == pipeline) d->cmd_state.pipeline = VK_NULL_HANDLE;
    Garbage *g = new_garbage(d, GARBAGE_PIPELINE);
    g->pipeline = pipeline;
    add_garbage(d, g);
}

void
defer_destroy_pipeline_objects(Driver *d, VkPipelineLayout layout, VkDescriptorSetLayout set_layout, VkShaderModule *modules, size_t num_modules) {
    Garbage *g = new_garbage(d, GARBAGE_PIPELINE_OBJECTS);
    g->objects.layout = layout;
    g->objects.set_layout = set_layout;
    g->objects.num_modules = MIN(num_modules, arraysz(g->objects.modules));
    memcpy(g->objects.modules, modules, g->objects.num_modules * sizeof(VkShaderModule));
    add_garbage(d, g);
}
// }}}

// Contexts {{{
// Release the resources of a context whose commands have completed
static void
context_completed(Driver *d, Context *c) {
    c->submitted = false;
    if (c->serial > d->completed_serial) d->completed_serial = c->serial;
    release_staging(d, c);
    while (c->garbage) {
        Garbage *g = c->garbage;
        c->garbage = g->next;
        destroy_garbage(d, g);
        free(g);
    }
    for (size_t i = 0; i < c->num_used_semaphores; i++) {
        if (d->num_free_semaphores < arraysz(d->free_semaphores)) d->free_semaphores[d->num_free_semaphores++] = c->used_semaphores[i];
        else vkDestroySemaphore(d->device, c->used_semaphores[i], NULL);
    }
    c->num_used_semaphores = 0;
}

static void
wait_for_context(Driver *d, Context *c) {
    if (!c->submitted) return;
    check_vk(d, vkWaitForFences(d->device, 1, &c->fence, VK_TRUE, UINT64_MAX), "waiting for GPU commands to complete");
    check_vk(d, vkResetFences(d->device, 1, &c->fence), "resetting a fence");
    context_completed(d, c);
}

// Note which submissions have completed, without waiting, so that the
// objects they used can be reused sooner
static void
poll_completed(Driver *d) {
    // Contexts complete in the order they were submitted
    for (size_t i = 1; i <= NUM_CONTEXTS; i++) {
        Context *c = d->contexts + (d->current_context + i) % NUM_CONTEXTS;
        if (!c->submitted) continue;
        if (vkGetFenceStatus(d->device, c->fence) != VK_SUCCESS) break;
        wait_for_context(d, c);
    }
}

Context *
current_context(Driver *d) {
    Context *c = d->contexts + d->current_context;
    if (c->recording) return c;
    poll_completed(d);
    // Waiting on the previous submission of this context throttles the CPU
    wait_for_context(d, c);
    check_vk(d, vkResetCommandPool(d->device, c->pool, 0), "resetting a command pool");
    const VkCommandBufferBeginInfo info = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    check_vk(d, vkBeginCommandBuffer(c->cmd, &info), "beginning a command buffer");
    c->serial = d->next_serial;
    c->recording = true;
    // Command buffer state does not carry over between command buffers
    memset(&d->cmd_state, 0, sizeof(d->cmd_state));
    d->cmd_state.descriptors_dirty = true;
    vkCmdBindIndexBuffer(c->cmd, d->quad_indices, 0, VK_INDEX_TYPE_UINT16);
    return c;
}

VkCommandBuffer
command_buffer(Driver *d) {
    return current_context(d)->cmd;
}

uint64_t
recording_serial(Driver *d) {
    const Context *c = d->contexts + d->current_context;
    return c->recording ? c->serial : d->next_serial;
}

VkSemaphore
get_semaphore(Driver *d) {
    Context *c = current_context(d);
    VkSemaphore ans;
    if (d->num_free_semaphores) ans = d->free_semaphores[--d->num_free_semaphores];
    else {
        const VkSemaphoreCreateInfo info = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
        check_vk(d, vkCreateSemaphore(d->device, &info, NULL, &ans), "creating a semaphore");
    }
    // Reusable once this context completes, as its submission waits on the semaphore
    if (c->num_used_semaphores >= arraysz(c->used_semaphores)) fatal(d, "Too many semaphores used in a single submission");
    c->used_semaphores[c->num_used_semaphores++] = ans;
    return ans;
}

void
add_wait_semaphore(Driver *d, VkSemaphore s) {
    Context *c = current_context(d);
    if (c->num_waits >= arraysz(c->waits)) fatal(d, "Too many semaphores to wait on in a single submission");
    c->waits[c->num_waits++] = s;
}

void
submit_commands(Driver *d, const VkSemaphore *signal, size_t num_signal, bool wait) {
    Context *c = current_context(d);
    end_rendering(d);
    check_vk(d, vkEndCommandBuffer(c->cmd), "ending a command buffer");
    VkSemaphoreSubmitInfo waits[arraysz(c->waits)], signals[4];
    for (size_t i = 0; i < c->num_waits; i++) {
        waits[i] = (VkSemaphoreSubmitInfo){
            .sType = VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, .semaphore = c->waits[i], .stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT};
    }
    num_signal = MIN(num_signal, arraysz(signals));
    for (size_t i = 0; i < num_signal; i++) {
        signals[i] = (VkSemaphoreSubmitInfo){
            .sType = VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, .semaphore = signal[i], .stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT};
    }
    const VkCommandBufferSubmitInfo cmd_info = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO, .commandBuffer = c->cmd};
    const VkSubmitInfo2 info = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO_2,
        .waitSemaphoreInfoCount = (uint32_t)c->num_waits,
        .pWaitSemaphoreInfos = waits,
        .commandBufferInfoCount = 1,
        .pCommandBufferInfos = &cmd_info,
        .signalSemaphoreInfoCount = (uint32_t)num_signal,
        .pSignalSemaphoreInfos = signals,
    };
    check_vk(d, vkQueueSubmit2(d->queue, 1, &info, c->fence), "submitting commands to the GPU");
    c->recording = false;
    c->submitted = true;
    c->num_waits = 0;
    d->next_serial++;
    d->current_context = (d->current_context + 1) % NUM_CONTEXTS;
    if (wait) wait_for_serial(d, c->serial);
}

void
wait_for_serial(Driver *d, uint64_t serial) {
    if (serial <= d->completed_serial) return;
    const Context *rc = d->contexts + d->current_context;
    if (rc->recording && rc->serial <= serial) submit_commands(d, NULL, 0, false);
    // Wait in submission order, oldest first
    for (size_t i = 0; i < NUM_CONTEXTS && serial > d->completed_serial; i++) {
        Context *c = d->contexts + (d->current_context + i) % NUM_CONTEXTS;
        if (c->submitted) wait_for_context(d, c);
    }
}

void
destroy_contexts(Driver *d) {
    for (size_t i = 0; i < NUM_CONTEXTS; i++) {
        Context *c = d->contexts + i;
        if (c->recording) {
            // Commands that were never submitted, discard them
            vkEndCommandBuffer(c->cmd);
            c->recording = false;
        }
        wait_for_context(d, c);
        // Releases unsubmitted resources too. Semaphores to wait on are also
        // in used_semaphores, so they are recycled, and destroyed, with those.
        context_completed(d, c);
        c->num_waits = 0;
        if (c->fence) vkDestroyFence(d->device, c->fence, NULL);
        if (c->pool) vkDestroyCommandPool(d->device, c->pool, NULL);
        *c = (Context){0};
    }
}
// }}}

// Barriers and rendering {{{
static bool
access_writes(VkAccessFlags2 a) {
    return (a & (VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_2_TRANSFER_WRITE_BIT | VK_ACCESS_2_SHADER_WRITE_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT)) != 0;
}

void
transition_image(Driver *d, Image *image, VkImageLayout layout, VkPipelineStageFlags2 stage, VkAccessFlags2 access) {
    image->last_use_serial = recording_serial(d);
    const ImageState s = image->state;
    // Reads after reads in the same layout need no barrier
    if (s.layout == layout && !access_writes(s.access) && !access_writes(access)) {
        image->state.stage |= stage;
        image->state.access |= access;
        return;
    }
    // Barriers cannot be recorded inside a render pass instance, except for self dependencies
    end_rendering(d);
    const VkImageMemoryBarrier2 barrier = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2,
        .srcStageMask = s.stage ? s.stage : VK_PIPELINE_STAGE_2_NONE,
        .srcAccessMask = s.access,
        .dstStageMask = stage,
        .dstAccessMask = access,
        .oldLayout = s.layout,
        .newLayout = layout,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = image->image,
        .subresourceRange = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .levelCount = 1, .layerCount = VK_REMAINING_ARRAY_LAYERS},
    };
    const VkDependencyInfo dep = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier};
    vkCmdPipelineBarrier2(command_buffer(d), &dep);
    image->state = (ImageState){.layout = layout, .stage = stage, .access = access};
}

void
end_rendering(Driver *d) {
    if (!d->rendering.active) return;
    vkCmdEndRendering(d->contexts[d->current_context].cmd);
    d->rendering.active = false;
    d->rendering.image = NULL;
    d->rendering.view = VK_NULL_HANDLE;
}

// The image the current render target renders into, NULL on failure
static Image *
target_image(Driver *d) {
    if (d->render_target) return d->render_target->texture ? &d->render_target->texture->image : NULL;
    return current_surface_image(d);
}

// Begin a render pass instance for the current render target, if not
// already active. Returns false if there is nothing to render to.
static bool
begin_rendering(Driver *d) {
    Image *img = target_image(d);
    if (!img) return false;
    const bool srgb = d->srgb_output && img->srgb_view;
    const VkImageView view = srgb ? img->srgb_view : img->unorm_view;
    if (!view) {
        log_error(d, "Cannot render into a texture of this format");
        return false;
    }
    if (d->rendering.active && d->rendering.view == view) return true;
    end_rendering(d);
    transition_image(
        d,
        img,
        VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT,
        VK_ACCESS_2_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT);
    const VkRenderingAttachmentInfo attachment = {
        .sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,
        .imageView = view,
        .imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        .loadOp = VK_ATTACHMENT_LOAD_OP_LOAD,
        .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
    };
    const VkRenderingInfo info = {
        .sType = VK_STRUCTURE_TYPE_RENDERING_INFO,
        .renderArea = {.extent = {img->width, img->height}},
        .layerCount = 1,
        .colorAttachmentCount = 1,
        .pColorAttachments = &attachment,
    };
    vkCmdBeginRendering(command_buffer(d), &info);
    d->rendering.active = true;
    d->rendering.image = img;
    d->rendering.view = view;
    d->rendering.format = srgb ? img->srgb_format : img->unorm_format;
    d->rendering.extent = (VkExtent2D){img->width, img->height};
    return true;
}

// The scissor rectangle, clipped to the render target, in ans
static void
current_scissor(Driver *d, VkRect2D *ans) {
    const int32_t w = (int32_t)d->rendering.extent.width, h = (int32_t)d->rendering.extent.height;
    int32_t x0 = 0, y0 = 0, x1 = w, y1 = h;
    if (d->scissor.enabled) {
        x0 = MAX(0, d->scissor.rect[0]);
        y0 = MAX(0, d->scissor.rect[1]);
        x1 = MIN(w, d->scissor.rect[0] + d->scissor.rect[2]);
        y1 = MIN(h, d->scissor.rect[1] + d->scissor.rect[3]);
    }
    *ans = (VkRect2D){.offset = {x0, y0}, .extent = {(uint32_t)MAX(0, x1 - x0), (uint32_t)MAX(0, y1 - y0)}};
}

void
clear(void *driver, float r, float g, float b, float a) {
    Driver *d = driver;
    if (!begin_rendering(d)) return;
    VkRect2D rect;
    current_scissor(d, &rect);
    if (!rect.extent.width || !rect.extent.height) return;
    const VkClearAttachment att = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .colorAttachment = 0, .clearValue = {.color = {.float32 = {r, g, b, a}}}};
    const VkClearRect cr = {.rect = rect, .baseArrayLayer = 0, .layerCount = 1};
    vkCmdClearAttachments(command_buffer(d), 1, &att, 1, &cr);
}

void
set_viewport(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    Driver *d = driver;
    d->viewport[0] = x;
    d->viewport[1] = y;
    d->viewport[2] = (int32_t)width;
    d->viewport[3] = (int32_t)height;
}

void
get_viewport(void *driver, int32_t ans[4]) {
    memcpy(ans, ((Driver *)driver)->viewport, sizeof(int32_t) * 4);
}

void
set_scissor(void *driver, bool enabled, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    Driver *d = driver;
    d->scissor.enabled = enabled;
    d->scissor.rect[0] = x;
    d->scissor.rect[1] = y;
    d->scissor.rect[2] = (int32_t)width;
    d->scissor.rect[3] = (int32_t)height;
}

void
set_srgb_output(void *driver, bool enabled) {
    // Takes effect at the next draw, which uses the corresponding view of the render target
    ((Driver *)driver)->srgb_output = enabled;
}
// }}}

// Drawing {{{
// Make the textures used by the current pipeline ready for sampling. Must be
// done before beginning rendering, as layout transitions end it.
static bool
prepare_textures(Driver *d, const Pipeline *p) {
    for (size_t i = 0; i < p->num_bindings; i++) {
        const PipelineBinding *b = p->bindings + i;
        if (b->kind != GPU_BINDING_TEXTURE) continue;
        Texture *t = d->bound_textures[b->slot];
        if (!t) {
            log_error(d, "No texture is bound to the slot: %u used by the texture: %s", b->slot, b->name);
            return false;
        }
        if (d->rendering.active && d->rendering.image == &t->image) end_rendering(d);
        if (target_image(d) == &t->image) {
            log_error(d, "Cannot sample from the texture: %s while rendering into it", b->name);
            return false;
        }
        transition_image(
            d,
            &t->image,
            VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
            VK_PIPELINE_STAGE_2_VERTEX_SHADER_BIT | VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT,
            VK_ACCESS_2_SHADER_SAMPLED_READ_BIT);
    }
    return true;
}

// The uniform buffer bound to a slot, either a parameter block of the pipeline or a buffer bound by kitty
static Buffer *
uniform_buffer_for_slot(Driver *d, const Pipeline *p, uint32_t slot) {
    for (size_t i = 0; i < p->num_param_blocks; i++) {
        if (p->param_blocks[i].slot == (int32_t)slot) return p->param_blocks[i].buffer;
    }
    return d->bound_buffers[slot];
}

static bool
push_descriptors(Driver *d, VkCommandBuffer cmd, const Pipeline *p) {
    if (!p->num_bindings) return true;
    VkWriteDescriptorSet writes[MAX_BINDING_SLOTS];
    VkDescriptorImageInfo images[MAX_BINDING_SLOTS];
    VkDescriptorBufferInfo buffers[MAX_BINDING_SLOTS];
    uint32_t n = 0;
    for (size_t i = 0; i < p->num_bindings && n < MAX_BINDING_SLOTS; i++) {
        const PipelineBinding *b = p->bindings + i;
        VkWriteDescriptorSet *w = writes + n;
        *w = (VkWriteDescriptorSet){.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = b->slot, .descriptorCount = 1};
        if (b->kind == GPU_BINDING_TEXTURE) {
            Texture *t = d->bound_textures[b->slot];
            images[n] =
                (VkDescriptorImageInfo){.sampler = t->sampler, .imageView = t->image.sampled_view, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
            w->descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
            w->pImageInfo = images + n;
        } else {
            Buffer *buf = uniform_buffer_for_slot(d, p, b->slot);
            if (!buf || !buf->storage.buffer) {
                log_error(d, "No uniform buffer is bound to the slot: %u used by the uniform block: %s", b->slot, b->name);
                return false;
            }
            use_buffer(d, buf);
            buffers[n] = (VkDescriptorBufferInfo){.buffer = buf->storage.buffer, .offset = 0, .range = buf->storage.size};
            w->descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
            w->pBufferInfo = buffers + n;
        }
        n++;
    }
    vkCmdPushDescriptorSetKHR(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, p->layout, 0, n, writes);
    return true;
}

static bool
bind_vertex_buffers(Driver *d, VkCommandBuffer cmd, const PipelineVariantKey *key) {
    for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
        if (!key->attribute_formats[loc]) continue;
        const VertexAttribute *a = d->vertex_layout->attributes + loc;
        if (!a->buffer || !a->buffer->storage.buffer) {
            log_error(d, "The vertex buffer for the vertex input at location: %u has no storage", loc);
            return false;
        }
        use_buffer(d, a->buffer);
        const VkDeviceSize offset = a->offset, stride = a->stride;
        vkCmdBindVertexBuffers2(cmd, loc, 1, &a->buffer->storage.buffer, &offset, NULL, &stride);
    }
    return true;
}

void
draw_quad(void *driver, uint32_t instance_count, GPUBlendMode blend) {
    Driver *d = driver;
    Pipeline *p = d->pipeline;
    if (!p) return;
    if (!prepare_textures(d, p) || !begin_rendering(d)) return;
    const VkPipeline vp = pipeline_for_current_state(d, blend == GPU_BLEND_PREMULTIPLIED_ALPHA);
    if (!vp) return;
    VkCommandBuffer cmd = command_buffer(d);
    if (d->cmd_state.pipeline != vp) {
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, vp);
        d->cmd_state.pipeline = vp;
    }
    if (!d->cmd_state.viewport_valid || memcmp(d->cmd_state.viewport, d->viewport, sizeof(d->viewport)) != 0) {
        const VkViewport v = {
            .x = (float)d->viewport[0], .y = (float)d->viewport[1], .width = (float)d->viewport[2], .height = (float)d->viewport[3], .maxDepth = 1.f};
        vkCmdSetViewport(cmd, 0, 1, &v);
        memcpy(d->cmd_state.viewport, d->viewport, sizeof(d->viewport));
        d->cmd_state.viewport_valid = true;
    }
    VkRect2D sc;
    current_scissor(d, &sc);
    if (!sc.extent.width || !sc.extent.height) return;
    const int32_t sc_arr[4] = {sc.offset.x, sc.offset.y, (int32_t)sc.extent.width, (int32_t)sc.extent.height};
    if (!d->cmd_state.scissor_valid || memcmp(d->cmd_state.scissor, sc_arr, sizeof(sc_arr)) != 0) {
        vkCmdSetScissor(cmd, 0, 1, &sc);
        memcpy(d->cmd_state.scissor, sc_arr, sizeof(sc_arr));
        d->cmd_state.scissor_valid = true;
    }
    // The push constant range is the same for all pipeline layouts, so the
    // pushed values survive changes of pipeline, but they are per pipeline in
    // the API
    if (d->cmd_state.push_constants_of != p || d->cmd_state.push_constants_dirty) {
        vkCmdPushConstants(cmd, p->layout, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, PUSH_CONSTANTS_SIZE, p->push_constants);
        d->cmd_state.push_constants_of = p;
        d->cmd_state.push_constants_dirty = false;
    }
    if (!push_descriptors(d, cmd, p)) return;
    const PipelineVariantKey *key = NULL;
    for (size_t i = 0; i < p->num_variants; i++) {
        if (p->variants[i].pipeline == vp) key = &p->variants[i].key;
    }
    if (!key || (d->vertex_layout && !bind_vertex_buffers(d, cmd, key))) return;
    vkCmdDrawIndexed(cmd, 6, instance_count ? instance_count : 1, 0, 0, 0);
}
// }}}

// Render targets and reading back {{{
gpu_render_target_t
render_target_create(void *driver, gpu_texture_t color_texture) {
    Driver *d = driver;
    RenderTarget *rt = calloc(1, sizeof(RenderTarget));
    if (!rt) {
        set_error(d, "Out of memory");
        return GPU_NULL_HANDLE;
    }
    rt->texture = AS_TEXTURE(color_texture);
    return AS_HANDLE(rt);
}

void
render_target_destroy(void *driver, gpu_render_target_t target) {
    Driver *d = driver;
    RenderTarget *rt = AS_RENDER_TARGET(target);
    if (!rt) return;
    if (d->render_target == rt) {
        end_rendering(d);
        d->render_target = NULL;
    }
    free(rt);
}

void
set_render_target(void *driver, gpu_render_target_t target) {
    // Rendering switches to the new target at the next draw
    ((Driver *)driver)->render_target = AS_RENDER_TARGET(target);
}

gpu_render_target_t
get_render_target(void *driver) {
    return AS_HANDLE(((Driver *)driver)->render_target);
}

const char *
render_target_status(void *driver UNUSED, gpu_render_target_t target) {
    const RenderTarget *rt = AS_RENDER_TARGET(target);
    if (!rt || !rt->texture) return "No texture";
    if (!rt->texture->image.unorm_view) return "The texture format cannot be rendered to";
    return NULL;
}

void
read_pixels(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height, void *dst) {
    Driver *d = driver;
    Image *img = target_image(d);
    if (!img || !width || !height) return;
    if (x < 0 || y < 0 || (uint32_t)x + width > img->width || (uint32_t)y + height > img->height) {
        log_error(d, "Reading pixels outside the render target");
        return;
    }
    const size_t bpp = img->format == VK_FORMAT_R16G16B16A16_UNORM ? 8 : 4;
    const VkDeviceSize size = (VkDeviceSize)width * height * bpp;
    VkBuffer buffer;
    Allocation alloc;
    if (!create_buffer_with_memory(d, size, VK_BUFFER_USAGE_TRANSFER_DST_BIT, MEMORY_READBACK, &buffer, &alloc)) {
        log_error(d, "Failed to allocate memory for reading back pixels: %s", d->last_error);
        return;
    }
    transition_image(d, img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
    const VkBufferImageCopy region = {
        .imageSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1},
        .imageOffset = {x, y, 0},
        .imageExtent = {width, height, 1},
    };
    vkCmdCopyImageToBuffer(command_buffer(d), img->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &region);
    submit_commands(d, NULL, 0, true);
    convert_to_rgba8(img->format, alloc.mapped, dst, (size_t)width * height);
    vkDestroyBuffer(d->device, buffer, NULL);
    free_memory(d, &alloc);
}

void
copy_to_texture(void *driver, gpu_texture_t dst, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(dst);
    Image *img = target_image(d);
    if (!img || !t || !width || !height) return;
    transition_image(d, img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
    transition_image(d, &t->image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT);
    // A blit converts between formats, such as from BGRA swapchain images
    const VkImageBlit region = {
        .srcSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1},
        .srcOffsets = {{x, y, 0}, {x + (int32_t)width, y + (int32_t)height, 1}},
        .dstSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1},
        .dstOffsets = {{0, 0, 0}, {(int32_t)width, (int32_t)height, 1}},
    };
    vkCmdBlitImage(
        command_buffer(d),
        img->image,
        VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        t->image.image,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        1,
        &region,
        VK_FILTER_NEAREST);
}
// }}}
