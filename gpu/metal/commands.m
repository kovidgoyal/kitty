/*
 * commands.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Command buffers, encoders, rendering and drawing

#include "internal.h"

#define AS_TEXTURE(handle) ((Texture *)(uintptr_t)(handle))
#define AS_RENDER_TARGET(handle) ((RenderTarget *)(uintptr_t)(handle))

// Command buffers {{{
uint64_t
completed_serial(Driver *d) {
    return atomic_load_explicit(&d->completed_serial, memory_order_acquire);
}

uint64_t
recording_serial(Driver *d) {
    return d->cmd != nil ? d->cmd_serial : d->next_serial;
}

static void
mark_completed(Driver *d, uint64_t serial) {
    uint64_t cur = atomic_load_explicit(&d->completed_serial, memory_order_acquire);
    while (cur < serial && !atomic_compare_exchange_weak_explicit(&d->completed_serial, &cur, serial, memory_order_acq_rel, memory_order_acquire));
}

void
check_gpu_errors(Driver *d) {
    if (!atomic_load_explicit(&d->gpu_error_pending, memory_order_acquire)) return;
    log_error(d, "Metal: Executing GPU commands failed with error: %s", d->gpu_error);
    // Allows the next failure to be recorded
    atomic_store_explicit(&d->gpu_error_pending, false, memory_order_release);
}

id<MTLCommandBuffer>
command_buffer(Driver *d) {
    if (d->cmd != nil) return d->cmd;
    check_gpu_errors(d);
    // Waiting for a slot throttles the CPU to at most NUM_IN_FLIGHT command
    // buffers ahead of the GPU. The slot is released by the completed handler.
    dispatch_semaphore_wait(d->in_flight, DISPATCH_TIME_FOREVER);
    @autoreleasepool {
        if (d->params.debug_rendering) {
            // Detailed errors for the encoders of command buffers that fail
            MTLCommandBufferDescriptor *desc = [[MTLCommandBufferDescriptor alloc] init];
            [desc setErrorOptions:MTLCommandBufferErrorOptionEncoderExecutionStatus];
            d->cmd = [[d->queue commandBufferWithDescriptor:desc] retain];
            [desc release];
        } else d->cmd = [[d->queue commandBuffer] retain];
    }
    if (d->cmd == nil) fatal(d, "Failed to create a Metal command buffer");
    d->cmd_serial = d->next_serial;
    // The handler runs on a thread owned by Metal, see internal.h. The driver
    // outlives it, see destroy().
    Driver *driver = d;
    const uint64_t serial = d->cmd_serial;
    [d->cmd addCompletedHandler:^(id<MTLCommandBuffer> cb) {
      if ([cb status] == MTLCommandBufferStatusError) {
          bool expected = false;
          // Only one failure is recorded until it has been reported
          if (atomic_compare_exchange_strong(&driver->gpu_error_pending, &expected, true)) {
              // The flag is set before the message is written, so the main
              // thread could read a partial message, which is harmless
              snprintf(driver->gpu_error, sizeof(driver->gpu_error), "%s", error_description([cb error]));
          }
      }
      mark_completed(driver, serial);
      dispatch_semaphore_signal(driver->in_flight);
    }];
    return d->cmd;
}

void
submit_commands(Driver *d, bool wait) {
    if (d->cmd == nil) return;
    end_encoding(d);
    id<MTLCommandBuffer> cmd = d->cmd;
    const uint64_t serial = d->cmd_serial;
    d->cmd = nil;
    d->next_serial++;
    [cmd commit];
    if (wait) {
        [cmd waitUntilCompleted];
        // The completed handler might not have run yet
        mark_completed(d, serial);
    }
    [cmd release];
    if (wait) check_gpu_errors(d);
}

void
wait_for_idle(Driver *d) {
    submit_commands(d, false);
    // Every command buffer holds a slot until its completed handler has run
    for (int i = 0; i < NUM_IN_FLIGHT; i++) dispatch_semaphore_wait(d->in_flight, DISPATCH_TIME_FOREVER);
    for (int i = 0; i < NUM_IN_FLIGHT; i++) dispatch_semaphore_signal(d->in_flight);
    check_gpu_errors(d);
}

void
end_rendering(Driver *d) {
    if (d->rendering.encoder == nil) return;
    [d->rendering.encoder endEncoding];
    [d->rendering.encoder release];
    d->rendering.encoder = nil;
    d->rendering.view = nil;
    d->rendering.texture = nil;
    d->rendering.pipeline = nil;
}

void
end_encoding(Driver *d) {
    end_rendering(d);
    if (d->blit != nil) {
        [d->blit endEncoding];
        [d->blit release];
        d->blit = nil;
    }
}

id<MTLBlitCommandEncoder>
blit_encoder(Driver *d) {
    end_rendering(d);
    if (d->blit == nil) {
        @autoreleasepool {
            d->blit = [[command_buffer(d) blitCommandEncoder] retain];
        }
        if (d->blit == nil) fatal(d, "Failed to create a Metal blit command encoder");
    }
    return d->blit;
}
// }}}

// Staging {{{
bool
allocate_staging(Driver *d, size_t size, size_t alignment, id<MTLBuffer> *buffer, size_t *offset, void **mapped) {
    const uint64_t serial = recording_serial(d), done = completed_serial(d);
    alignment = MAX((size_t)16u, alignment);
    if (size < STAGING_CHUNK_SIZE) {
        // Small uploads are sub-allocated from chunks, first from those
        // already used by the command buffer being encoded, then from those
        // no longer used by the GPU
        StagingChunk *found = NULL;
        size_t start = 0;
        for (size_t i = 0; i < d->num_staging && !found; i++) {
            StagingChunk *c = d->staging + i;
            if (c->serial != serial) continue;
            start = (c->used + alignment - 1) / alignment * alignment;
            if (start + size <= STAGING_CHUNK_SIZE) found = c;
        }
        for (size_t i = 0; i < d->num_staging && !found; i++) {
            StagingChunk *c = d->staging + i;
            if (c->serial <= done) {
                found = c;
                start = 0;
            }
        }
        if (!found && d->num_staging < arraysz(d->staging)) {
            id<MTLBuffer> b = [d->device newBufferWithLength:STAGING_CHUNK_SIZE options:MTLResourceStorageModeShared];
            if (b == nil) {
                set_error(d, "Failed to allocate %u bytes of staging memory", STAGING_CHUNK_SIZE);
                return false;
            }
            found = d->staging + d->num_staging++;
            *found = (StagingChunk){.buffer = b};
            start = 0;
        }
        if (found) {
            found->serial = serial;
            found->used = start + size;
            *buffer = found->buffer;
            *offset = start;
            *mapped = (uint8_t *)[found->buffer contents] + start;
            return true;
        }
    }
    // Uploads too large for a chunk, or when all chunks are in use, get a
    // buffer of their own. It is autoreleased, the command buffer retains it
    // once it is used by an encoded command.
    id<MTLBuffer> b = [d->device newBufferWithLength:size options:MTLResourceStorageModeShared];
    if (b == nil) {
        set_error(d, "Failed to allocate %zu bytes of staging memory", size);
        return false;
    }
    [b autorelease];
    *buffer = b;
    *offset = 0;
    *mapped = [b contents];
    return true;
}

void
release_staging(Driver *d) {
    for (size_t i = 0; i < d->num_staging; i++) [d->staging[i].buffer release];
    d->num_staging = 0;
}
// }}}

// Utility pipelines {{{
// Pipelines used by the driver itself, they draw a quad covering the viewport
// with a triangle strip of four vertices
static const char utility_shaders[] = "#include <metal_stdlib>\n"
                                      "using namespace metal;\n"
                                      "struct FullscreenVertex { float4 position [[position]]; };\n"
                                      "vertex FullscreenVertex kitty_fullscreen_vertex(uint vid [[vertex_id]]) {\n"
                                      "    FullscreenVertex v;\n"
                                      "    v.position = float4((vid & 1u) ? 1.0 : -1.0, (vid & 2u) ? 1.0 : -1.0, 0.0, 1.0);\n"
                                      "    return v;\n"
                                      "}\n"
                                      "fragment float4 kitty_clear_fragment(constant float4 &color [[buffer(0)]]) { return color; }\n"
                                      "fragment float4 kitty_copy_fragment(float4 position [[position]], texture2d<float, access::read> src [[texture(0)]],\n"
                                      "                                    constant int2 &origin [[buffer(0)]]) {\n"
                                      "    return src.read(uint2(int2(position.xy) + origin));\n"
                                      "}\n";

bool
create_utility_pipelines(Driver *d) {
    @autoreleasepool {
        NSError *err = nil;
        d->utility_library = [d->device newLibraryWithSource:[NSString stringWithUTF8String:utility_shaders] options:nil error:&err];
        if (d->utility_library == nil) {
            set_error(d, "Failed to compile the Metal utility shaders with error: %s", error_description(err));
            return false;
        }
        d->fullscreen_vertex = [d->utility_library newFunctionWithName:@"kitty_fullscreen_vertex"];
        d->clear_fragment = [d->utility_library newFunctionWithName:@"kitty_clear_fragment"];
        d->copy_fragment = [d->utility_library newFunctionWithName:@"kitty_copy_fragment"];
        if (d->fullscreen_vertex == nil || d->clear_fragment == nil || d->copy_fragment == nil) {
            set_error(d, "The Metal utility shaders are missing functions");
            return false;
        }
    }
    return true;
}

void
destroy_utility_pipelines(Driver *d) {
    for (size_t i = 0; i < d->num_clear_pipelines; i++) [d->clear_pipelines[i].state release];
    for (size_t i = 0; i < d->num_copy_pipelines; i++) [d->copy_pipelines[i].state release];
    d->num_clear_pipelines = d->num_copy_pipelines = 0;
    [d->fullscreen_vertex release];
    [d->clear_fragment release];
    [d->copy_fragment release];
    [d->utility_library release];
    d->fullscreen_vertex = d->clear_fragment = d->copy_fragment = nil;
    d->utility_library = nil;
}

static id<MTLRenderPipelineState>
utility_pipeline(Driver *d, bool is_copy, MTLPixelFormat format) {
    UtilityPipeline *cache = is_copy ? d->copy_pipelines : d->clear_pipelines;
    size_t *num = is_copy ? &d->num_copy_pipelines : &d->num_clear_pipelines;
    for (size_t i = 0; i < *num; i++) {
        if (cache[i].format == format) return cache[i].state;
    }
    if (*num >= MAX_UTILITY_FORMATS) {
        log_error(d, "Metal: Too many render target formats");
        return nil;
    }
    id<MTLRenderPipelineState> ans = nil;
    @autoreleasepool {
        MTLRenderPipelineDescriptor *desc = [[MTLRenderPipelineDescriptor alloc] init];
        [desc setLabel:is_copy ? @"kitty copy" : @"kitty clear"];
        [desc setVertexFunction:d->fullscreen_vertex];
        [desc setFragmentFunction:is_copy ? d->copy_fragment : d->clear_fragment];
        [[[desc colorAttachments] objectAtIndexedSubscript:0] setPixelFormat:format];
        NSError *err = nil;
        ans = [d->device newRenderPipelineStateWithDescriptor:desc error:&err];
        [desc release];
        if (ans == nil) {
            log_error(d, "Metal: Failed to create a utility pipeline with error: %s", error_description(err));
            return nil;
        }
    }
    cache[(*num)++] = (UtilityPipeline){.format = format, .state = ans};
    return ans;
}
// }}}

// Rendering {{{
// The image the current render target renders into
static bool
target_image(Driver *d, RenderImage *ans) {
    if (d->render_target) {
        Texture *t = d->render_target->texture;
        if (!t || t->texture == nil) return false;
        *ans = (RenderImage){
            .texture = t->texture,
            .unorm_view = t->unorm_view,
            .srgb_view = t->srgb_view,
            .width = (uint32_t)[t->texture width],
            .height = (uint32_t)[t->texture height]};
        return true;
    }
    return current_surface_image(d, ans);
}

// The view of the image to render into, honoring the sRGB output mode, nil if it cannot be rendered into
static id<MTLTexture>
render_view(Driver *d, const RenderImage *img) {
    return d->srgb_output && img->srgb_view != nil ? img->srgb_view : img->unorm_view;
}

// Begin a render pass into view, ending any active pass or blit encoder. If
// clear_color is not NULL the view is first cleared to it.
static void
start_render_pass(Driver *d, const RenderImage *img, id<MTLTexture> view, const float *clear_color) {
    end_encoding(d);
    id<MTLCommandBuffer> cmd = command_buffer(d);
    @autoreleasepool {
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        MTLRenderPassColorAttachmentDescriptor *a = [[rp colorAttachments] objectAtIndexedSubscript:0];
        [a setTexture:view];
        [a setLoadAction:clear_color ? MTLLoadActionClear : MTLLoadActionLoad];
        if (clear_color) [a setClearColor:MTLClearColorMake(clear_color[0], clear_color[1], clear_color[2], clear_color[3])];
        [a setStoreAction:MTLStoreActionStore];
        d->rendering.encoder = [[cmd renderCommandEncoderWithDescriptor:rp] retain];
    }
    if (d->rendering.encoder == nil) fatal(d, "Failed to create a Metal render command encoder");
    d->rendering.view = view;
    d->rendering.texture = img->texture;
    d->rendering.format = [view pixelFormat];
    d->rendering.width = img->width;
    d->rendering.height = img->height;
    // Encoder state does not carry over between encoders
    d->rendering.pipeline = nil;
    d->rendering.push_constants_of = NULL;
    d->rendering.push_constants_dirty = false;
    d->rendering.viewport_valid = d->rendering.scissor_valid = false;
}

// Begin a render pass for the current render target, if not already active.
// Returns false if there is nothing to render to.
static bool
begin_rendering(Driver *d) {
    RenderImage img;
    if (!target_image(d, &img)) return false;
    id<MTLTexture> view = render_view(d, &img);
    if (view == nil) {
        log_error(d, "Cannot render into a texture of this format");
        return false;
    }
    if (d->rendering.encoder != nil && d->rendering.view == view) return true;
    start_render_pass(d, &img, view, NULL);
    return true;
}

// The scissor rectangle, clipped to the render target of size width x height, as x, y, width, height
static void
current_scissor(Driver *d, uint32_t width, uint32_t height, int32_t ans[4]) {
    const int32_t w = (int32_t)width, h = (int32_t)height;
    int32_t x0 = 0, y0 = 0, x1 = w, y1 = h;
    if (d->scissor.enabled) {
        x0 = MAX(0, MIN(w, d->scissor.rect[0]));
        y0 = MAX(0, MIN(h, d->scissor.rect[1]));
        x1 = MAX(x0, MIN(w, d->scissor.rect[0] + d->scissor.rect[2]));
        y1 = MAX(y0, MIN(h, d->scissor.rect[1] + d->scissor.rect[3]));
    }
    ans[0] = x0;
    ans[1] = y0;
    ans[2] = x1 - x0;
    ans[3] = y1 - y0;
}

static void
apply_scissor(Driver *d, const int32_t sc[4]) {
    if (d->rendering.scissor_valid && memcmp(d->rendering.scissor, sc, sizeof(d->rendering.scissor)) == 0) return;
    const MTLScissorRect r = {.x = (NSUInteger)sc[0], .y = (NSUInteger)sc[1], .width = (NSUInteger)sc[2], .height = (NSUInteger)sc[3]};
    [d->rendering.encoder setScissorRect:r];
    memcpy(d->rendering.scissor, sc, sizeof(d->rendering.scissor));
    d->rendering.scissor_valid = true;
}

void
clear(void *driver, float r, float g, float b, float a) {
    Driver *d = driver;
    RenderImage img;
    if (!target_image(d, &img)) return;
    id<MTLTexture> view = render_view(d, &img);
    if (view == nil) return;
    int32_t sc[4];
    current_scissor(d, img.width, img.height, sc);
    if (sc[2] <= 0 || sc[3] <= 0) return;
    const float color[4] = {r, g, b, a};
    const bool whole = sc[0] == 0 && sc[1] == 0 && (uint32_t)sc[2] == img.width && (uint32_t)sc[3] == img.height;
    if (whole && !(d->rendering.encoder != nil && d->rendering.view == view)) {
        // Clearing the whole render target is done by the load action of a new render pass
        start_render_pass(d, &img, view, color);
        return;
    }
    // Otherwise draw a quad with the clear color, restricted to the scissor rectangle
    if (!begin_rendering(d)) return;
    id<MTLRenderPipelineState> ps = utility_pipeline(d, false, d->rendering.format);
    if (ps == nil) return;
    id<MTLRenderCommandEncoder> enc = d->rendering.encoder;
    [enc setRenderPipelineState:ps];
    d->rendering.pipeline = ps;
    // Clears are not affected by the viewport
    const MTLViewport vp = {.originX = 0, .originY = 0, .width = (double)img.width, .height = (double)img.height, .znear = 0, .zfar = 1};
    [enc setViewport:vp];
    d->rendering.viewport_valid = false;
    apply_scissor(d, sc);
    [enc setFragmentBytes:color length:sizeof(color) atIndex:0];
    // That replaced the buffer used for the push constants of kitty's pipelines
    d->rendering.push_constants_of = NULL;
    [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
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
// Check that the textures used by the pipeline are bound and are not being rendered into
static bool
check_textures(Driver *d, const Pipeline *p) {
    RenderImage target = {0};
    const bool has_target = target_image(d, &target);
    for (size_t i = 0; i < p->num_bindings; i++) {
        const PipelineBinding *b = p->bindings + i;
        if (b->kind != GPU_BINDING_TEXTURE) continue;
        const Texture *t = d->bound_textures[b->slot];
        if (!t || t->texture == nil) {
            log_error(d, "No texture is bound to the slot: %u used by the texture: %s", b->slot, b->name);
            return false;
        }
        if (has_target && target.texture == t->texture) {
            log_error(d, "Cannot sample from the texture: %s while rendering into it", b->name);
            return false;
        }
        // A pass rendering into the texture must end before it can be sampled
        if (d->rendering.texture == t->texture) end_rendering(d);
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
bind_resources(Driver *d, id<MTLRenderCommandEncoder> enc, const Pipeline *p) {
    for (size_t i = 0; i < p->num_bindings; i++) {
        const PipelineBinding *b = p->bindings + i;
        if (b->kind == GPU_BINDING_TEXTURE) {
            const Texture *t = d->bound_textures[b->slot];
            const NSUInteger ti = (NSUInteger)b->texture_index, si = (NSUInteger)b->sampler_index;
            [enc setVertexTexture:t->texture atIndex:ti];
            [enc setFragmentTexture:t->texture atIndex:ti];
            [enc setVertexSamplerState:t->sampler atIndex:si];
            [enc setFragmentSamplerState:t->sampler atIndex:si];
        } else {
            Buffer *buf = uniform_buffer_for_slot(d, p, b->slot);
            if (!buf || buf->storage.buffer == nil) {
                log_error(d, "No uniform buffer is bound to the slot: %u used by the uniform block: %s", b->slot, b->name);
                return false;
            }
            use_buffer(d, buf);
            const NSUInteger bi = (NSUInteger)b->buffer_index;
            [enc setVertexBuffer:buf->storage.buffer offset:0 atIndex:bi];
            [enc setFragmentBuffer:buf->storage.buffer offset:0 atIndex:bi];
        }
    }
    return true;
}

static bool
bind_vertex_buffers(Driver *d, id<MTLRenderCommandEncoder> enc, const PipelineVariantKey *key) {
    for (uint32_t loc = 0; loc < MAX_VERTEX_ATTRIBUTES; loc++) {
        if (key->inputs[loc].format == MTLVertexFormatInvalid) continue;
        const VertexAttribute *a = d->vertex_layout->attributes + loc;
        size_t offset;
        uint32_t stride;
        id<MTLBuffer> buf = vertex_buffer_for(d, a, vertex_attribute_size(a->components, a->type), &offset, &stride);
        if (buf == nil) {
            log_error(d, "The vertex buffer for the vertex input at location: %u has no storage", loc);
            return false;
        }
        [enc setVertexBuffer:buf offset:offset atIndex:VERTEX_BUFFER_INDEX(loc)];
    }
    return true;
}

void
draw_quad(void *driver, uint32_t instance_count, GPUBlendMode blend) {
    Driver *d = driver;
    Pipeline *p = d->pipeline;
    if (!p) return;
    @autoreleasepool {
        if (!check_textures(d, p) || !begin_rendering(d)) return;
        int32_t sc[4];
        current_scissor(d, d->rendering.width, d->rendering.height, sc);
        if (sc[2] <= 0 || sc[3] <= 0) return;
        PipelineVariantKey key;
        id<MTLRenderPipelineState> ps = pipeline_for_current_state(d, blend == GPU_BLEND_PREMULTIPLIED_ALPHA, &key);
        if (ps == nil) return;
        id<MTLRenderCommandEncoder> enc = d->rendering.encoder;
        if (d->rendering.pipeline != ps) {
            [enc setRenderPipelineState:ps];
            d->rendering.pipeline = ps;
        }
        if (!d->rendering.viewport_valid || memcmp(d->rendering.viewport, d->viewport, sizeof(d->viewport)) != 0) {
            const MTLViewport v = {
                .originX = d->viewport[0], .originY = d->viewport[1], .width = d->viewport[2], .height = d->viewport[3], .znear = 0, .zfar = 1};
            [enc setViewport:v];
            memcpy(d->rendering.viewport, d->viewport, sizeof(d->viewport));
            d->rendering.viewport_valid = true;
        }
        apply_scissor(d, sc);
        if (p->push_constants_index >= 0 && (d->rendering.push_constants_of != p || d->rendering.push_constants_dirty)) {
            // The block is used by every stage, see GPUParamBlock
            const NSUInteger idx = (NSUInteger)p->push_constants_index;
            [enc setVertexBytes:p->push_constants length:PUSH_CONSTANTS_SIZE atIndex:idx];
            [enc setFragmentBytes:p->push_constants length:PUSH_CONSTANTS_SIZE atIndex:idx];
            d->rendering.push_constants_of = p;
            d->rendering.push_constants_dirty = false;
        }
        if (!bind_resources(d, enc, p)) return;
        if (d->vertex_layout && !bind_vertex_buffers(d, enc, &key)) return;
        [enc drawIndexedPrimitives:MTLPrimitiveTypeTriangle
                        indexCount:6
                         indexType:MTLIndexTypeUInt16
                       indexBuffer:d->quad_indices
                 indexBufferOffset:0
                     instanceCount:MAX(1u, instance_count)];
    }
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
render_target_status(void *driver, gpu_render_target_t target) {
    const Driver *d = driver;
    // The drawable of the window surface is acquired lazily, so is always usable
    if (!target) return d->current_surface ? NULL : "No surface is current";
    const RenderTarget *rt = AS_RENDER_TARGET(target);
    if (!rt->texture || rt->texture->texture == nil) return "No texture";
    if (rt->texture->unorm_view == nil) return "The texture format cannot be rendered to";
    return NULL;
}

void
read_pixels(void *driver, int32_t x, int32_t y, uint32_t width, uint32_t height, void *dst) {
    Driver *d = driver;
    if (!width || !height) return;
    @autoreleasepool {
        RenderImage img;
        if (!target_image(d, &img)) return;
        if (x < 0 || y < 0 || (uint64_t)x + width > img.width || (uint64_t)y + height > img.height) {
            log_error(d, "Reading pixels outside the render target");
            return;
        }
        // The raw contents of the image, without decoding sRGB, as in the Vulkan driver
        const MTLPixelFormat format = [img.texture pixelFormat];
        const size_t bpp = bytes_per_pixel(format), row = (size_t)width * bpp, size = row * height;
        id<MTLBuffer> buf = [d->device newBufferWithLength:size options:MTLResourceStorageModeShared];
        if (buf == nil) {
            log_error(d, "Failed to allocate memory for reading back pixels");
            return;
        }
        [blit_encoder(d) copyFromTexture:img.texture
                             sourceSlice:0
                             sourceLevel:0
                            sourceOrigin:MTLOriginMake((NSUInteger)x, (NSUInteger)y, 0)
                              sourceSize:MTLSizeMake(width, height, 1)
                                toBuffer:buf
                       destinationOffset:0
                  destinationBytesPerRow:row
                destinationBytesPerImage:size];
        submit_commands(d, true);
        convert_to_rgba8(format, [buf contents], dst, (size_t)width * height);
        [buf release];
    }
}

void
copy_to_texture(void *driver, gpu_texture_t dst, int32_t x, int32_t y, uint32_t width, uint32_t height) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(dst);
    if (!t || t->texture == nil || !width || !height) return;
    @autoreleasepool {
        RenderImage img;
        if (!target_image(d, &img)) return;
        if (x < 0 || y < 0 || (uint64_t)x + width > img.width || (uint64_t)y + height > img.height || width > [t->texture width] ||
            height > [t->texture height]) {
            log_error(d, "Copying pixels outside the render target or the texture");
            return;
        }
        // Copy the raw contents, without decoding sRGB
        id<MTLTexture> src = img.unorm_view != nil ? img.unorm_view : img.texture;
        if ([src pixelFormat] == [t->texture pixelFormat]) {
            [blit_encoder(d) copyFromTexture:src
                                 sourceSlice:0
                                 sourceLevel:0
                                sourceOrigin:MTLOriginMake((NSUInteger)x, (NSUInteger)y, 0)
                                  sourceSize:MTLSizeMake(width, height, 1)
                                   toTexture:t->texture
                            destinationSlice:0
                            destinationLevel:0
                           destinationOrigin:MTLOriginMake(0, 0, 0)];
            return;
        }
        // Blits cannot convert between formats, such as from the BGRA
        // drawables of windows, so draw instead
        if (t->unorm_view == nil) {
            log_error(d, "Cannot copy into a texture of this format");
            return;
        }
        id<MTLRenderPipelineState> ps = utility_pipeline(d, true, [t->unorm_view pixelFormat]);
        if (ps == nil) return;
        const RenderImage dest = {
            .texture = t->texture, .unorm_view = t->unorm_view, .width = (uint32_t)[t->texture width], .height = (uint32_t)[t->texture height]};
        start_render_pass(d, &dest, t->unorm_view, NULL);
        id<MTLRenderCommandEncoder> enc = d->rendering.encoder;
        [enc setRenderPipelineState:ps];
        const MTLViewport vp = {.originX = 0, .originY = 0, .width = (double)width, .height = (double)height, .znear = 0, .zfar = 1};
        [enc setViewport:vp];
        [enc setScissorRect:(MTLScissorRect){.x = 0, .y = 0, .width = width, .height = height}];
        [enc setFragmentTexture:src atIndex:0];
        const int32_t origin[2] = {x, y};
        [enc setFragmentBytes:origin length:sizeof(origin) atIndex:0];
        [enc drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
        // Rendering continues into the current render target at the next draw
        end_rendering(d);
    }
}
// }}}
