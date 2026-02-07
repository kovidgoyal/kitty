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
struct SpriteMap;

// Initialize global Metal device/queue. Returns true if Metal is usable.
bool metal_backend_init(void);

// Attach a CAMetalLayer to the GLFW-created NSWindow and allocate per-window resources.
bool metal_window_attach(struct OSWindow *w);

// Resize drawable on framebuffer changes.
void metal_window_resize(struct OSWindow *w, int width, int height, float xscale, float yscale);

// Release per-window resources.
void metal_window_destroy(struct OSWindow *w);

// Render the window contents using the Metal backend.
bool metal_render_os_window(struct OSWindow *w, monotonic_t now, bool scan_for_animated_images);

// Present a solid fill (used for initial clear/fallback).
void metal_present_blank(struct OSWindow *w, float alpha, color_type background);

// Sprite atlas management (glyphs and decorations)
bool metal_realloc_sprite_texture(struct SpriteMap *sm, unsigned width, unsigned height, unsigned layers);
bool metal_realloc_decor_texture(struct SpriteMap *sm, unsigned width, unsigned height);
bool metal_upload_sprite(struct SpriteMap *sm, unsigned x, unsigned y, unsigned layer, unsigned w, unsigned h, const void *rgba);
bool metal_upload_decor(struct SpriteMap *sm, unsigned x, unsigned y, uint32_t decoration_idx);

// Generic 2D textures (graphics, bg images)
uint32_t metal_image_alloc(void);
void metal_image_upload(uint32_t tex_id, const void *data, int width, int height, bool srgb, bool is_opaque, bool linear_filter, int repeat_mode);
void metal_image_free(uint32_t tex_id);

// Build Metal pipelines and static resources.
bool metal_build_pipelines(void);

#ifdef __cplusplus
}
#endif

#endif
