#pragma once

#ifdef __APPLE__
#include <stdbool.h>
#include <stdint.h>
#include "data-types.h"
#include "monotonic.h"

#ifdef __cplusplus
extern "C" {
#endif

struct OSWindow;
struct MetalWindow;

// SpriteMap is defined in shaders.c as a typedef'd anonymous struct.
// We define a compatible struct here for the Metal functions.
// This must match the layout in shaders.c!
#ifndef SPRITEMAP_DEFINED
typedef struct {
    int xnum, ynum, x, y, z, last_num_of_layers, last_ynum;
    unsigned int texture_id;  // GLuint
    int max_texture_size, max_array_texture_layers;  // GLint
    struct {
        unsigned int texture_id;  // GLuint
        unsigned width, height;
        size_t count;
    } decorations_map;
#ifdef __APPLE__
    void *metal_texture;
    void *metal_decorations_texture;
#endif
} SpriteMap;
#define SPRITEMAP_DEFINED
#endif

// ============================================================================
// Backend Initialization
// ============================================================================

// Initialize global Metal device/queue. Returns true if Metal is usable.
bool metal_backend_init(void);

// Build Metal pipelines and static resources.
bool metal_build_pipelines(void);

// ============================================================================
// Window Management
// ============================================================================

// Attach a CAMetalLayer to the GLFW-created NSWindow and allocate per-window resources.
bool metal_window_attach(struct OSWindow *w);

// Resize drawable on framebuffer changes.
void metal_window_resize(struct OSWindow *w, int width, int height, float xscale, float yscale);

// Release per-window resources.
void metal_window_destroy(struct OSWindow *w);

// ============================================================================
// Rendering
// ============================================================================

// Render the window contents using the Metal backend.
// Returns true if rendering was successful.
bool metal_render_os_window(struct OSWindow *w, monotonic_t now, bool scan_for_animated_images);

// Present a solid fill (used for initial clear/fallback).
void metal_present_blank(struct OSWindow *w, float alpha, color_type background);

// ============================================================================
// Sprite Atlas Management (Glyphs and Decorations)
// ============================================================================

// Reallocate the sprite texture array with new dimensions.
bool metal_realloc_sprite_texture(SpriteMap *sm, unsigned width, unsigned height, unsigned layers);

// Reallocate the decoration index texture.
bool metal_realloc_decor_texture(SpriteMap *sm, unsigned width, unsigned height);

// Upload sprite data to the atlas.
bool metal_upload_sprite(SpriteMap *sm, unsigned x, unsigned y, unsigned layer, unsigned w, unsigned h, const void *rgba);

// Upload decoration index.
bool metal_upload_decor(SpriteMap *sm, unsigned x, unsigned y, uint32_t decoration_idx);

// Reload textures after context change.
void metal_reload_textures(SpriteMap *sm);

// ============================================================================
// Generic 2D Textures (Graphics Protocol, Background Images)
// ============================================================================

// Allocate a new texture ID for graphics protocol images.
uint32_t metal_image_alloc(void);

// Upload image data to a texture.
// Parameters:
//   tex_id: Texture ID from metal_image_alloc()
//   data: RGBA pixel data
//   width, height: Image dimensions
//   srgb: Use sRGB color space
//   is_opaque: Image has no transparency
//   linear_filter: Use linear filtering (vs nearest)
//   repeat_mode: 0=repeat, 1=mirror, 2=clamp
void metal_image_upload(uint32_t tex_id, const void *data, int width, int height, 
                        bool srgb, bool is_opaque, bool linear_filter, int repeat_mode);

// Free a texture.
void metal_image_free(uint32_t tex_id);

#ifdef __cplusplus
}
#endif

#endif // __APPLE__
