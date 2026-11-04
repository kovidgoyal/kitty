/*
 * textures.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Textures and samplers

#include "internal.h"

#define AS_TEXTURE(handle) ((Texture *)(uintptr_t)(handle))

// Formats {{{
static MTLPixelFormat
mtl_format_for(GPUTextureFormat f) {
    switch (f) {
        case GPU_FORMAT_R8: return MTLPixelFormatR8Unorm;
        case GPU_FORMAT_R8UI: return MTLPixelFormatR8Uint;
        case GPU_FORMAT_RG8UI: return MTLPixelFormatRG8Uint;
        case GPU_FORMAT_R32UI: return MTLPixelFormatR32Uint;
        case GPU_FORMAT_RGBA8: return MTLPixelFormatRGBA8Unorm;
        case GPU_FORMAT_SRGB8_ALPHA8: return MTLPixelFormatRGBA8Unorm_sRGB;
        case GPU_FORMAT_RGBA16: return MTLPixelFormatRGBA16Unorm;
    }
    return MTLPixelFormatInvalid;
}

static bool
is_integer_format(MTLPixelFormat f) {
    return f == MTLPixelFormatR8Uint || f == MTLPixelFormatRG8Uint || f == MTLPixelFormatR32Uint;
}

size_t
bytes_per_pixel(MTLPixelFormat f) {
    switch (f) {
        case MTLPixelFormatR8Unorm:
        case MTLPixelFormatR8Uint: return 1;
        case MTLPixelFormatRG8Uint: return 2;
        case MTLPixelFormatRGBA16Unorm: return 8;
        default: return 4;
    }
}

// The number of 8 bit channels in a pixel, zero for formats that are not made of 8 bit channels
static unsigned
channels_8bit(MTLPixelFormat f) {
    switch (f) {
        case MTLPixelFormatR8Unorm:
        case MTLPixelFormatR8Uint: return 1;
        case MTLPixelFormatRG8Uint: return 2;
        case MTLPixelFormatRGBA8Unorm:
        case MTLPixelFormatRGBA8Unorm_sRGB:
        case MTLPixelFormatBGRA8Unorm:
        case MTLPixelFormatBGRA8Unorm_sRGB: return 4;
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

// Convert pixels from CPU memory into tightly packed pixels of the format
static bool
convert_pixels(const GPUPixelData *src, uint32_t width, uint32_t height, MTLPixelFormat format, uint8_t *dst) {
    const size_t sbpp = pixel_layout_size(src->layout), dbpp = bytes_per_pixel(format);
    const size_t sstride = row_stride(sbpp * width, src->row_alignment), dstride = dbpp * width;
    const uint8_t *s = src->data;
    if (src->layout == GPU_PIXELS_R32UI || format == MTLPixelFormatR32Uint) {
        if (src->layout != GPU_PIXELS_R32UI || format != MTLPixelFormatR32Uint) return false;
        for (uint32_t y = 0; y < height; y++) memcpy(dst + y * dstride, s + y * sstride, dstride);
        return true;
    }
    const unsigned dch = channels_8bit(format);
    // Fast path, the layout of the pixels is the same as that of the texture
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
            else if (format == MTLPixelFormatRGBA16Unorm) {
                uint16_t w[4];
                for (int i = 0; i < 4; i++) w[i] = (uint16_t)(c[i] * 257u);
                memcpy(out + x * 8, w, 8);
            } else return false;
        }
    }
    return true;
}

void
convert_to_rgba8(MTLPixelFormat format, const uint8_t *src, uint8_t *dst, size_t num_pixels) {
    switch (format) {
        case MTLPixelFormatBGRA8Unorm:
        case MTLPixelFormatBGRA8Unorm_sRGB:
            for (size_t i = 0; i < num_pixels; i++, src += 4, dst += 4) {
                dst[0] = src[2];
                dst[1] = src[1];
                dst[2] = src[0];
                dst[3] = src[3];
            }
            break;
        case MTLPixelFormatRGBA16Unorm:
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
static MTLSamplerAddressMode
address_mode(int wrap) {
    switch (wrap) {
        case 0: return MTLSamplerAddressModeClampToEdge;
        case 1: return MTLSamplerAddressModeClampToBorderColor;
        case 2: return MTLSamplerAddressModeRepeat;
        default: return MTLSamplerAddressModeMirrorRepeat;
    }
}

bool
create_samplers(Driver *d) {
    @autoreleasepool {
        for (int filter = 0; filter < 2; filter++) {
            for (int wrap = 0; wrap < 4; wrap++) {
                for (int integer = 0; integer < 2; integer++) {
                    // Integer textures cannot be filtered, they are only read from
                    const MTLSamplerMinMagFilter f = filter && !integer ? MTLSamplerMinMagFilterLinear : MTLSamplerMinMagFilterNearest;
                    MTLSamplerDescriptor *desc = [[MTLSamplerDescriptor alloc] init];
                    [desc setMinFilter:f];
                    [desc setMagFilter:f];
                    [desc setMipFilter:MTLSamplerMipFilterNotMipmapped];
                    [desc setSAddressMode:address_mode(wrap)];
                    [desc setTAddressMode:address_mode(wrap)];
                    [desc setRAddressMode:address_mode(wrap)];
                    [desc setBorderColor:MTLSamplerBorderColorTransparentBlack];
                    [desc setNormalizedCoordinates:YES];
                    d->samplers[filter][wrap][integer] = [d->device newSamplerStateWithDescriptor:desc];
                    [desc release];
                    if (d->samplers[filter][wrap][integer] == nil) {
                        set_error(d, "Failed to create a Metal sampler");
                        return false;
                    }
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
                [d->samplers[filter][wrap][integer] release];
                d->samplers[filter][wrap][integer] = nil;
            }
        }
    }
}

static id<MTLSamplerState>
sampler_for(Driver *d, const GPUTextureDesc *desc, MTLPixelFormat format) {
    const int filter = desc->filter == GPU_FILTER_LINEAR ? 1 : 0;
    int wrap = 0;
    switch (desc->wrap) {
        case GPU_WRAP_CLAMP_TO_EDGE: wrap = 0; break;
        case GPU_WRAP_CLAMP_TO_BORDER: wrap = 1; break;
        case GPU_WRAP_REPEAT: wrap = 2; break;
        case GPU_WRAP_MIRRORED_REPEAT: wrap = 3; break;
    }
    return d->samplers[filter][wrap][is_integer_format(format) ? 1 : 0];
}
// }}}

// Textures {{{
static void
release_texture_objects(Driver *d, Texture *t) {
    // Command buffers retain the textures they use, so they can be released
    // immediately, but a render pass into the texture must be ended first
    if (t->texture != nil && d->rendering.texture == t->texture) end_rendering(d);
    [t->unorm_view release];
    [t->srgb_view release];
    [t->texture release];
    t->texture = t->unorm_view = t->srgb_view = nil;
}

static bool
create_texture_objects(Driver *d, Texture *t, const GPUTextureDesc *desc) {
    const MTLPixelFormat format = mtl_format_for(desc->format);
    if (format == MTLPixelFormatInvalid) {
        set_error(d, "Unknown texture format: %d", (int)desc->format);
        return false;
    }
    const uint32_t width = MAX(1u, desc->width), height = MAX(1u, desc->height);
    const uint32_t layers = desc->kind == GPU_TEXTURE_2D_ARRAY ? MAX(1u, desc->layers) : 1;
    if (width > MAX_TEXTURE_SIZE || height > MAX_TEXTURE_SIZE || layers > MAX_TEXTURE_LAYERS) {
        set_error(d, "The texture of size %ux%ux%u is too large", width, height, layers);
        return false;
    }
    // Integer textures are only read from, others can also be rendered into
    const bool renderable = !is_integer_format(format);
    const bool is_srgb = format == MTLPixelFormatRGBA8Unorm_sRGB;
    @autoreleasepool {
        MTLTextureDescriptor *td = [[MTLTextureDescriptor alloc] init];
        [td setTextureType:desc->kind == GPU_TEXTURE_2D_ARRAY ? MTLTextureType2DArray : MTLTextureType2D];
        [td setPixelFormat:format];
        [td setWidth:width];
        [td setHeight:height];
        [td setArrayLength:layers];
        [td setMipmapLevelCount:1];
        [td setStorageMode:MTLStorageModePrivate];
        MTLTextureUsage usage = MTLTextureUsageShaderRead;
        if (renderable) usage |= MTLTextureUsageRenderTarget;
        // Rendering into sRGB textures encodes to sRGB only when sRGB output is
        // enabled, see set_srgb_output(), so they also need a non-sRGB view
        if (is_srgb) usage |= MTLTextureUsagePixelFormatView;
        [td setUsage:usage];
        t->texture = [d->device newTextureWithDescriptor:td];
        [td release];
    }
    if (t->texture == nil) {
        set_error(d, "Failed to create a Metal texture of size %ux%ux%u", width, height, layers);
        return false;
    }
    if (renderable) {
        if (is_srgb) {
            t->unorm_view = [t->texture newTextureViewWithPixelFormat:MTLPixelFormatRGBA8Unorm];
            t->srgb_view = [t->texture retain];
            if (t->unorm_view == nil) {
                set_error(d, "Failed to create a view of an sRGB texture");
                release_texture_objects(d, t);
                return false;
            }
        } else t->unorm_view = [t->texture retain];
    }
    t->format = format;
    t->desc = *desc;
    t->sampler = sampler_for(d, desc, format);
    return true;
}

static bool
upload(Driver *d, Texture *t, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels) {
    if (!width || !height) return true;
    const NSUInteger tw = [t->texture width], th = [t->texture height], tl = [t->texture arrayLength];
    if ((uint64_t)x + width > tw || (uint64_t)y + height > th || layer >= tl) {
        set_error(d, "Texture upload out of bounds");
        return false;
    }
    const size_t bpp = bytes_per_pixel(t->format), row = (size_t)width * bpp, size = row * height;
    id<MTLBuffer> buffer;
    size_t offset;
    void *mapped;
    if (!allocate_staging(d, size, bpp, &buffer, &offset, &mapped)) return false;
    if (!convert_pixels(pixels, width, height, t->format, mapped)) {
        set_error(d, "Cannot upload pixels of layout: %d to a texture of format: %d", (int)pixels->layout, (int)t->format);
        return false;
    }
    [blit_encoder(d) copyFromBuffer:buffer
                       sourceOffset:offset
                  sourceBytesPerRow:row
                sourceBytesPerImage:size
                         sourceSize:MTLSizeMake(width, height, 1)
                          toTexture:t->texture
                   destinationSlice:layer
                   destinationLevel:0
                  destinationOrigin:MTLOriginMake(x, y, 0)];
    return true;
}

static bool
init_texture(Driver *d, Texture *t, const GPUTextureDesc *desc, const GPUPixelData *initial) {
    if (!create_texture_objects(d, t, desc)) return false;
    if (initial) {
        // The pixels of all layers, one after the other
        const uint32_t w = (uint32_t)[t->texture width], h = (uint32_t)[t->texture height], layers = (uint32_t)[t->texture arrayLength];
        const size_t layer_size = row_stride(pixel_layout_size(initial->layout) * w, initial->row_alignment) * h;
        for (uint32_t layer = 0; layer < layers; layer++) {
            GPUPixelData p = *initial;
            p.data = (const uint8_t *)initial->data + layer * layer_size;
            if (!upload(d, t, 0, 0, layer, w, h, &p)) return false;
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
    bool ok;
    @autoreleasepool {
        ok = init_texture(d, t, desc, initial);
    }
    if (!ok) {
        release_texture_objects(d, t);
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
    release_texture_objects(d, t);
    bool ok;
    @autoreleasepool {
        ok = init_texture(d, t, desc, initial);
    }
    if (!ok) release_texture_objects(d, t);
    return ok;
}

void
texture_destroy(void *driver, gpu_texture_t texture) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(texture);
    if (!t) return;
    for (size_t i = 0; i < arraysz(d->bound_textures); i++) {
        if (d->bound_textures[i] == t) d->bound_textures[i] = NULL;
    }
    release_texture_objects(d, t);
    LIST_REMOVE(d->textures, t);
    free(t);
}

void
destroy_all_textures(Driver *d) {
    while (d->textures) texture_destroy(d, AS_HANDLE(d->textures));
}

void
texture_upload(void *driver, gpu_texture_t texture, uint32_t x, uint32_t y, uint32_t layer, uint32_t width, uint32_t height, const GPUPixelData *pixels) {
    Driver *d = driver;
    bool ok;
    @autoreleasepool {
        ok = upload(d, AS_TEXTURE(texture), x, y, layer, width, height, pixels);
    }
    if (!ok) log_error(d, "Failed to upload texture: %s", d->last_error);
}

void
texture_copy(void *driver, gpu_texture_t src, gpu_texture_t dst) {
    Driver *d = driver;
    Texture *s = AS_TEXTURE(src), *t = AS_TEXTURE(dst);
    const NSUInteger w = [s->texture width], h = [s->texture height];
    if (s->format != t->format || w > [t->texture width] || h > [t->texture height]) {
        log_error(d, "Cannot copy between incompatible textures");
        return;
    }
    @autoreleasepool {
        const NSUInteger layers = MIN([s->texture arrayLength], [t->texture arrayLength]);
        id<MTLBlitCommandEncoder> blit = blit_encoder(d);
        for (NSUInteger layer = 0; layer < layers; layer++) {
            [blit copyFromTexture:s->texture
                      sourceSlice:layer
                      sourceLevel:0
                     sourceOrigin:MTLOriginMake(0, 0, 0)
                       sourceSize:MTLSizeMake(w, h, 1)
                        toTexture:t->texture
                 destinationSlice:layer
                 destinationLevel:0
                destinationOrigin:MTLOriginMake(0, 0, 0)];
        }
    }
}

bool
texture_read(void *driver, gpu_texture_t texture, GPUPixelLayout layout, void *dst, size_t dst_size) {
    Driver *d = driver;
    Texture *t = AS_TEXTURE(texture);
    const uint32_t width = (uint32_t)[t->texture width], height = (uint32_t)[t->texture height];
    const size_t tsz = bytes_per_pixel(t->format), npx = (size_t)width * height;
    const size_t out_bpp = pixel_layout_size(layout), out_stride = row_stride(out_bpp * width, 4);
    if (dst_size < out_stride * height) {
        set_error(d, "The buffer for reading the texture is too small");
        return false;
    }
    const bool converts_to_rgba8 = channels_8bit(t->format) == 4 || t->format == MTLPixelFormatRGBA16Unorm;
    if (layout == GPU_PIXELS_RGBA8 ? !converts_to_rgba8 : out_bpp != tsz) {
        set_error(d, "Cannot read a texture of format %d as pixel layout %d", (int)t->format, (int)layout);
        return false;
    }
    @autoreleasepool {
        id<MTLBuffer> buf = [d->device newBufferWithLength:MAX((size_t)16u, npx * tsz) options:MTLResourceStorageModeShared];
        if (buf == nil) {
            set_error(d, "Failed to allocate memory for reading back a texture");
            return false;
        }
        [blit_encoder(d) copyFromTexture:t->texture
                             sourceSlice:0
                             sourceLevel:0
                            sourceOrigin:MTLOriginMake(0, 0, 0)
                              sourceSize:MTLSizeMake(width, height, 1)
                                toBuffer:buf
                       destinationOffset:0
                  destinationBytesPerRow:(NSUInteger)width * tsz
                destinationBytesPerImage:npx * tsz];
        submit_commands(d, true);
        const uint8_t *src = [buf contents];
        for (uint32_t y = 0; y < height; y++) {
            uint8_t *out = (uint8_t *)dst + y * out_stride;
            const uint8_t *in = src + (size_t)y * width * tsz;
            if (layout == GPU_PIXELS_RGBA8) convert_to_rgba8(t->format, in, out, width);
            else memcpy(out, in, (size_t)width * tsz);
        }
        [buf release];
    }
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
}
// }}}
