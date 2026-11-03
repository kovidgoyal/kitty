/*
 * textures.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Textures, images and samplers

#include "internal.h"

#define AS_TEXTURE(handle) ((Texture *)(uintptr_t)(handle))

// Formats {{{
VkFormat
vk_format_for(GPUTextureFormat f) {
    switch (f) {
        case GPU_FORMAT_R8: return VK_FORMAT_R8_UNORM;
        case GPU_FORMAT_R8UI: return VK_FORMAT_R8_UINT;
        case GPU_FORMAT_RG8UI: return VK_FORMAT_R8G8_UINT;
        case GPU_FORMAT_R32UI: return VK_FORMAT_R32_UINT;
        case GPU_FORMAT_RGBA8: return VK_FORMAT_R8G8B8A8_UNORM;
        case GPU_FORMAT_SRGB8_ALPHA8: return VK_FORMAT_R8G8B8A8_SRGB;
        case GPU_FORMAT_RGBA16: return VK_FORMAT_R16G16B16A16_UNORM;
    }
    return VK_FORMAT_UNDEFINED;
}

static bool
is_integer_format(VkFormat f) {
    return f == VK_FORMAT_R8_UINT || f == VK_FORMAT_R8G8_UINT || f == VK_FORMAT_R32_UINT;
}

static size_t
texel_size(VkFormat f) {
    switch (f) {
        case VK_FORMAT_R8_UNORM:
        case VK_FORMAT_R8_UINT: return 1;
        case VK_FORMAT_R8G8_UINT: return 2;
        case VK_FORMAT_R16G16B16A16_UNORM: return 8;
        default: return 4;
    }
}

// The number of 8 bit channels in a texel, zero for formats that are not made of 8 bit channels
static unsigned
channels_8bit(VkFormat f) {
    switch (f) {
        case VK_FORMAT_R8_UNORM:
        case VK_FORMAT_R8_UINT: return 1;
        case VK_FORMAT_R8G8_UINT: return 2;
        case VK_FORMAT_R8G8B8A8_UNORM:
        case VK_FORMAT_R8G8B8A8_SRGB:
        case VK_FORMAT_B8G8R8A8_UNORM:
        case VK_FORMAT_B8G8R8A8_SRGB: return 4;
        default: return 0;
    }
}

static size_t
pixel_layout_size(GPUPixelLayout l) {
    switch (l) {
        case GPU_PIXELS_R8: return 1;
        case GPU_PIXELS_RG8: return 2;
        case GPU_PIXELS_RGB8: return 3;
        case GPU_PIXELS_RGBA8:
        case GPU_PIXELS_RGBA8_PACKED:
        case GPU_PIXELS_R32UI: return 4;
    }
    return 4;
}

static size_t
row_stride(size_t row_bytes, uint32_t alignment) {
    if (alignment < 1) alignment = 1;
    return (row_bytes + alignment - 1) / alignment * alignment;
}

// Convert pixels from CPU memory into tightly packed texels of the format
static bool
convert_pixels(const GPUPixelData *src, uint32_t width, uint32_t height, VkFormat format, uint8_t *dst) {
    const size_t sbpp = pixel_layout_size(src->layout), dbpp = texel_size(format);
    const size_t sstride = row_stride(sbpp * width, src->row_alignment), dstride = dbpp * width;
    const uint8_t *s = src->data;
    if (src->layout == GPU_PIXELS_R32UI || format == VK_FORMAT_R32_UINT) {
        if (src->layout != GPU_PIXELS_R32UI || format != VK_FORMAT_R32_UINT) return false;
        for (uint32_t y = 0; y < height; y++) memcpy(dst + y * dstride, s + y * sstride, dstride);
        return true;
    }
    const unsigned dch = channels_8bit(format);
    // Fast path, the layout of the pixels is the same as that of the texels
    if (dch && src->layout != GPU_PIXELS_RGBA8_PACKED && dch == sbpp) {
        for (uint32_t y = 0; y < height; y++) memcpy(dst + y * dstride, s + y * sstride, dstride);
        return true;
    }
    for (uint32_t y = 0; y < height; y++) {
        const uint8_t *row = s + y * sstride;
        uint8_t *out = dst + y * dstride;
        for (uint32_t x = 0; x < width; x++) {
            uint8_t c[4] = {0, 0, 0, 255};
            const uint8_t *p = row + x * sbpp;
            switch (src->layout) {
                case GPU_PIXELS_R8: c[0] = p[0]; break;
                case GPU_PIXELS_RG8:
                    c[0] = p[0];
                    c[1] = p[1];
                    break;
                case GPU_PIXELS_RGB8: memcpy(c, p, 3); break;
                case GPU_PIXELS_RGBA8: memcpy(c, p, 4); break;
                case GPU_PIXELS_RGBA8_PACKED: {
                    uint32_t v;
                    memcpy(&v, p, 4);
                    c[0] = (uint8_t)(v >> 24);
                    c[1] = (uint8_t)(v >> 16);
                    c[2] = (uint8_t)(v >> 8);
                    c[3] = (uint8_t)v;
                } break;
                case GPU_PIXELS_R32UI: break;
            }
            if (dch) memcpy(out + x * dch, c, dch);
            else if (format == VK_FORMAT_R16G16B16A16_UNORM) {
                uint16_t w[4];
                for (int i = 0; i < 4; i++) w[i] = (uint16_t)(c[i] * 257u);
                memcpy(out + x * 8, w, 8);
            } else return false;
        }
    }
    return true;
}

void
convert_to_rgba8(VkFormat format, const uint8_t *src, uint8_t *dst, size_t num_pixels) {
    switch (format) {
        case VK_FORMAT_B8G8R8A8_UNORM:
        case VK_FORMAT_B8G8R8A8_SRGB:
            for (size_t i = 0; i < num_pixels; i++, src += 4, dst += 4) {
                dst[0] = src[2];
                dst[1] = src[1];
                dst[2] = src[0];
                dst[3] = src[3];
            }
            break;
        case VK_FORMAT_R16G16B16A16_UNORM:
            for (size_t i = 0; i < num_pixels * 4; i++) {
                uint16_t v;
                memcpy(&v, src + 2 * i, 2);
                dst[i] = (uint8_t)(v >> 8);
            }
            break;
        default: memcpy(dst, src, num_pixels * 4); break;
    }
}
// }}}

// Samplers {{{
static VkSamplerAddressMode
address_mode(int wrap) {
    switch (wrap) {
        case 0: return VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
        case 1: return VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER;
        case 2: return VK_SAMPLER_ADDRESS_MODE_REPEAT;
        default: return VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT;
    }
}

bool
create_samplers(Driver *d) {
    for (int filter = 0; filter < 2; filter++) {
        for (int wrap = 0; wrap < 4; wrap++) {
            for (int integer = 0; integer < 2; integer++) {
                // Integer textures cannot be filtered, they are only fetched from
                const VkFilter f = filter && !integer ? VK_FILTER_LINEAR : VK_FILTER_NEAREST;
                const VkSamplerCreateInfo info = {
                    .sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
                    .magFilter = f,
                    .minFilter = f,
                    .mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
                    .addressModeU = address_mode(wrap),
                    .addressModeV = address_mode(wrap),
                    .addressModeW = address_mode(wrap),
                    .borderColor = integer ? VK_BORDER_COLOR_INT_TRANSPARENT_BLACK : VK_BORDER_COLOR_FLOAT_TRANSPARENT_BLACK,
                    .maxLod = 0.f,
                };
                VkResult r = vkCreateSampler(d->device, &info, NULL, &d->samplers[filter][wrap][integer]);
                if (r != VK_SUCCESS) {
                    set_error(d, "Failed to create a Vulkan sampler with error: %s", vk_result_string(r));
                    return false;
                }
            }
        }
    }
    return true;
}

void
destroy_samplers(Driver *d) {
    for (int filter = 0; filter < 2; filter++) {
        for (int wrap = 0; wrap < 4; wrap++) {
            for (int integer = 0; integer < 2; integer++) {
                if (d->samplers[filter][wrap][integer]) vkDestroySampler(d->device, d->samplers[filter][wrap][integer], NULL);
                d->samplers[filter][wrap][integer] = VK_NULL_HANDLE;
            }
        }
    }
}

static VkSampler
sampler_for(Driver *d, const GPUTextureDesc *desc) {
    const int filter = desc->filter == GPU_FILTER_LINEAR ? 1 : 0;
    int wrap = 0;
    switch (desc->wrap) {
        case GPU_WRAP_CLAMP_TO_EDGE: wrap = 0; break;
        case GPU_WRAP_CLAMP_TO_BORDER: wrap = 1; break;
        case GPU_WRAP_REPEAT: wrap = 2; break;
        case GPU_WRAP_MIRRORED_REPEAT: wrap = 3; break;
    }
    return d->samplers[filter][wrap][is_integer_format(vk_format_for(desc->format)) ? 1 : 0];
}
// }}}

// Images {{{
static VkImageView
create_view(Driver *d, VkImage image, VkFormat format, VkImageViewType type, uint32_t layers) {
    const VkImageViewCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
        .image = image,
        .viewType = type,
        .format = format,
        .subresourceRange = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .levelCount = 1, .layerCount = layers},
    };
    VkImageView ans = VK_NULL_HANDLE;
    VkResult r = vkCreateImageView(d->device, &info, NULL, &ans);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create a Vulkan image view with error: %s", vk_result_string(r));
        return VK_NULL_HANDLE;
    }
    return ans;
}

bool
create_image_views(Driver *d, Image *img, VkImageViewType sampled_type) {
    // Views for sampling use all layers, views for rendering only the first
    if (sampled_type != VK_IMAGE_VIEW_TYPE_MAX_ENUM) {
        if (!(img->sampled_view = create_view(d, img->image, img->format, sampled_type, img->layers))) return false;
    }
    if (img->unorm_format && !(img->unorm_view = create_view(d, img->image, img->unorm_format, VK_IMAGE_VIEW_TYPE_2D, 1))) return false;
    if (img->srgb_format && !(img->srgb_view = create_view(d, img->image, img->srgb_format, VK_IMAGE_VIEW_TYPE_2D, 1))) return false;
    return true;
}

void
destroy_image_views(Driver *d, Image *img) {
    if (img->sampled_view) vkDestroyImageView(d->device, img->sampled_view, NULL);
    if (img->unorm_view) vkDestroyImageView(d->device, img->unorm_view, NULL);
    if (img->srgb_view) vkDestroyImageView(d->device, img->srgb_view, NULL);
    img->sampled_view = img->unorm_view = img->srgb_view = VK_NULL_HANDLE;
}

static bool
create_texture_image(Driver *d, Image *img, const GPUTextureDesc *desc) {
    *img = (Image){0};
    const VkFormat format = vk_format_for(desc->format);
    if (format == VK_FORMAT_UNDEFINED) {
        set_error(d, "Unknown texture format: %d", (int)desc->format);
        return false;
    }
    VkFormatProperties fp;
    vkGetPhysicalDeviceFormatProperties(d->physical_device, format, &fp);
    const VkFormatFeatureFlags needed = VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_TRANSFER_DST_BIT | VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;
    if ((fp.optimalTilingFeatures & needed) != needed) {
        set_error(d, "The GPU does not support textures of the format: %d", (int)format);
        return false;
    }
    const bool renderable = !is_integer_format(format) && (fp.optimalTilingFeatures & VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BLEND_BIT);
    img->format = format;
    img->width = MAX(1u, desc->width);
    img->height = MAX(1u, desc->height);
    img->layers = desc->kind == GPU_TEXTURE_2D_ARRAY ? MAX(1u, desc->layers) : 1;
    const bool is_srgb = format == VK_FORMAT_R8G8B8A8_SRGB;
    if (renderable) {
        // Rendering into sRGB textures encodes to sRGB only when sRGB output
        // is enabled, see set_srgb_output(), so they need both kinds of views
        img->unorm_format = is_srgb ? VK_FORMAT_R8G8B8A8_UNORM : format;
        img->srgb_format = is_srgb ? VK_FORMAT_R8G8B8A8_SRGB : VK_FORMAT_UNDEFINED;
    }
    const VkFormat view_formats[2] = {VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_R8G8B8A8_SRGB};
    const VkImageFormatListCreateInfo format_list = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_FORMAT_LIST_CREATE_INFO, .viewFormatCount = 2, .pViewFormats = view_formats};
    const VkImageCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .pNext = is_srgb && renderable ? &format_list : NULL,
        .flags = is_srgb && renderable ? VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT : 0,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = format,
        .extent = {img->width, img->height, 1},
        .mipLevels = 1,
        .arrayLayers = img->layers,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                 (renderable ? VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT : 0),
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    VkResult r = vkCreateImage(d->device, &info, NULL, &img->image);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create a Vulkan image of size %ux%ux%u with error: %s", img->width, img->height, img->layers, vk_result_string(r));
        return false;
    }
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(d->device, img->image, &req);
    if (!allocate_memory(d, &req, MEMORY_DEVICE, &img->alloc)) goto fail;
    if ((r = vkBindImageMemory(d->device, img->image, img->alloc.memory, img->alloc.offset)) != VK_SUCCESS) {
        set_error(d, "Failed to bind image memory with error: %s", vk_result_string(r));
        goto fail;
    }
    if (!create_image_views(d, img, desc->kind == GPU_TEXTURE_2D_ARRAY ? VK_IMAGE_VIEW_TYPE_2D_ARRAY : VK_IMAGE_VIEW_TYPE_2D)) goto fail;
    img->state = (ImageState){.layout = VK_IMAGE_LAYOUT_UNDEFINED};
    return true;
fail:
    destroy_image_views(d, img);
    vkDestroyImage(d->device, img->image, NULL);
    free_memory(d, &img->alloc);
    *img = (Image){0};
    return false;
}
// }}}

// Textures {{{
static bool
upload(Driver *d, Texture *t, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels) {
    Image *img = &t->image;
    if (!width || !height) return true;
    if ((uint64_t)x + width > img->width || (uint64_t)y + height > img->height || layer >= img->layers) {
        set_error(d, "Texture upload out of bounds");
        return false;
    }
    const VkDeviceSize size = (VkDeviceSize)width * height * texel_size(img->format);
    VkBuffer buffer;
    VkDeviceSize offset;
    void *mapped;
    if (!allocate_staging(d, size, MAX(16u, texel_size(img->format)), &buffer, &offset, &mapped)) return false;
    if (!convert_pixels(pixels, width, height, img->format, mapped)) {
        set_error(d, "Cannot upload pixels of layout: %d to a texture of format: %d", (int)pixels->layout, (int)img->format);
        return false;
    }
    transition_image(d, img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT);
    const VkBufferImageCopy region = {
        .bufferOffset = offset,
        .imageSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .baseArrayLayer = layer, .layerCount = 1},
        .imageOffset = {(int32_t)x, (int32_t)y, 0},
        .imageExtent = {width, height, 1},
    };
    vkCmdCopyBufferToImage(command_buffer(d), buffer, img->image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
    return true;
}

static bool
init_texture(Driver *d, Texture *t, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    if (!create_texture_image(d, &t->image, desc)) return false;
    t->desc = *desc;
    t->sampler = sampler_for(d, desc);
    if (initial) {
        // The pixels of all layers, one after the other
        const size_t layer_size = row_stride(pixel_layout_size(initial->layout) * t->image.width, initial->row_alignment) * t->image.height;
        for (uint32_t layer = 0; layer < t->image.layers; layer++) {
            GPUPixelData p = *initial;
            p.data = (const uint8_t *)initial->data + layer * layer_size;
            if (!upload(d, t, 0, 0, layer, t->image.width, t->image.height, &p)) return false;
        }
    }
    return true;
}

gpu_texture_t
texture_create(void *driver, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    Driver *d = driver;
    Texture *t = calloc(1, sizeof(Texture));
    if (!t) {
        set_error(d, "Out of memory");
        return GPU_NULL_HANDLE;
    }
    if (!init_texture(d, t, desc, initial)) {
        if (t->image.image) defer_destroy_image(d, &t->image);
        free(t);
        return GPU_NULL_HANDLE;
    }
    LIST_ADD(d->textures, t);
    return AS_HANDLE(t);
}

bool
texture_reset(void *driver, gpu_texture_t texture, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(texture);
    defer_destroy_image(d, &t->image);
    if (!init_texture(d, t, desc, initial)) {
        if (t->image.image) defer_destroy_image(d, &t->image);
        return false;
    }
    return true;
}

void
texture_destroy(void *driver, gpu_texture_t texture) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(texture);
    if (!t) return;
    for (size_t i = 0; i < arraysz(d->bound_textures); i++) {
        if (d->bound_textures[i] == t) d->bound_textures[i] = NULL;
    }
    if (t->image.image) defer_destroy_image(d, &t->image);
    LIST_REMOVE(d->textures, t);
    free(t);
}

void
destroy_all_textures(Driver *d) {
    while (d->textures) {
        Texture *t = d->textures;
        destroy_image_views(d, &t->image);
        if (t->image.image) vkDestroyImage(d->device, t->image.image, NULL);
        free_memory(d, &t->image.alloc);
        LIST_REMOVE(d->textures, t);
        free(t);
    }
}

void
texture_upload(void *driver, gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels) {
    Driver *d = driver;
    if (!upload(d, AS_TEXTURE(texture), x, y, layer, width, height, pixels)) log_error(d, "Failed to upload texture: %s", d->last_error);
}

void
texture_copy(void *driver, gpu_texture_t src, gpu_texture_t dst) {
    Driver *d = driver;
    Texture *s = AS_TEXTURE(src), *t = AS_TEXTURE(dst);
    if (s->image.format != t->image.format || s->image.width > t->image.width || s->image.height > t->image.height) {
        log_error(d, "Cannot copy between incompatible textures");
        return;
    }
    transition_image(d, &s->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
    transition_image(d, &t->image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT);
    const uint32_t layers = MIN(s->image.layers, t->image.layers);
    const VkImageCopy region = {
        .srcSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = layers},
        .dstSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = layers},
        .extent = {s->image.width, s->image.height, 1},
    };
    vkCmdCopyImage(command_buffer(d), s->image.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, t->image.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
}

bool
texture_read(void *driver, gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(texture);
    Image *img = &t->image;
    const size_t tsz = texel_size(img->format), npx = (size_t)img->width * img->height;
    const size_t out_bpp = pixel_layout_size(layout), out_stride = row_stride(out_bpp * img->width, 4);
    if (dst_size < out_stride * img->height) {
        set_error(d, "The buffer for reading the texture is too small");
        return false;
    }
    const bool converts_to_rgba8 = channels_8bit(img->format) == 4 || img->format == VK_FORMAT_R16G16B16A16_UNORM;
    if (layout == GPU_PIXELS_RGBA8 ? !converts_to_rgba8 : out_bpp != tsz) {
        set_error(d, "Cannot read a texture of format %d as pixel layout %d", (int)img->format, (int)layout);
        return false;
    }
    VkBuffer buffer;
    Allocation alloc;
    if (!create_buffer_with_memory(d, npx * tsz, VK_BUFFER_USAGE_TRANSFER_DST_BIT, MEMORY_READBACK, &buffer, &alloc)) return false;
    transition_image(d, img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
    const VkBufferImageCopy region = {
        .imageSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1},
        .imageExtent = {img->width, img->height, 1},
    };
    vkCmdCopyImageToBuffer(command_buffer(d), img->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &region);
    submit_commands(d, NULL, 0, true);
    const uint8_t *src = alloc.mapped;
    for (uint32_t y = 0; y < img->height; y++) {
        uint8_t *out = (uint8_t *)dst + y * out_stride;
        const uint8_t *in = src + (size_t)y * img->width * tsz;
        if (layout == GPU_PIXELS_RGBA8) convert_to_rgba8(img->format, in, out, img->width);
        else memcpy(out, in, (size_t)img->width * tsz);
    }
    vkDestroyBuffer(d->device, buffer, NULL);
    free_memory(d, &alloc);
    return true;
}

void
texture_get_desc(void *driver UNUSED, gpu_texture_t texture, GPUTextureDesc *ans) {
    *ans = AS_TEXTURE(texture)->desc;
}

void
bind_texture(void *driver, uint32_t slot, gpu_texture_t texture) {
    Driver *d = driver;
    if (slot >= MAX_BINDING_SLOTS) {
        log_error(d, "Invalid texture binding slot: %u", slot);
        return;
    }
    d->bound_textures[slot] = AS_TEXTURE(texture);
    d->cmd_state.descriptors_dirty = true;
}
// }}}
