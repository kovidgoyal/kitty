/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "monotonic.h"

typedef struct {
    unsigned char action, transmission_type, compressed, delete_action;
    uint32_t format, more, id, image_number, data_sz, data_offset, placement_id, quiet, parent_id, parent_placement_id;
    uint32_t width, height, x_offset, y_offset;
    union { uint32_t cursor_movement, compose_mode; };
    union { uint32_t cell_x_offset, blend_mode; };
    union { uint32_t cell_y_offset, bgcolor; };
    union { uint32_t data_width, animation_state; };
    union { uint32_t data_height, loop_count; };
    union { uint32_t num_lines, frame_number; };
    union { uint32_t num_cells, other_frame_number; };
    union { int32_t z_index, gap; };
    size_t payload_sz;
    bool unicode_placement;
    int32_t offset_from_parent_x, offset_from_parent_y;
} GraphicsCommand;

typedef struct {
    float left, top, right, bottom;
} ImageRect;

typedef struct {
    ImageRect src_rect, dest_rect;
    uint32_t texture_id, group_count;
    int z_index;
    id_type image_id, ref_id;
} ImageRenderData;

typedef struct {
    uint32_t texture_id;
    unsigned int height, width;
    uint8_t* bitmap;
    uint32_t refcnt;
    size_t mmap_size;
} BackgroundImage;


#ifdef GRAPHICS_INTERNAL_APIS
typedef struct {
    float src_width, src_height, src_x, src_y;
    uint32_t cell_x_offset, cell_y_offset, num_cols, num_rows, effective_num_rows, effective_num_cols;
    int32_t z_index;
    int32_t start_row, start_column;
    uint32_t client_id;
    ImageRect src_rect;
    // Indicates whether this reference represents a cell ref that should be
    // removed when the corresponding cells are modified.
    // The internal id of the virtual ref this cell image was created from. Is a cell ref if this is non-zero.
    id_type virtual_ref_id;
    // Virtual refs are not displayed but they can be used as prototypes for
    // refs placed using unicode placeholders.
    bool is_virtual_ref;

    struct {
        id_type img, ref;
        struct { int32_t x, y; } offset;
    } parent;

    id_type internal_id;
} ImageRef;

typedef struct {
    uint32_t gap, id, width, height, x, y, base_frame_id, bgcolor;
    bool is_opaque, is_4byte_aligned, alpha_blend;
} Frame;

typedef enum { ANIMATION_STOPPED = 0, ANIMATION_LOADING = 1, ANIMATION_RUNNING = 2} AnimationState;

typedef struct TextureRef {
    uint32_t id, refcnt;
} TextureRef;

#define NAME ref_map
#define KEY_TY id_type
#define VAL_TY ImageRef*
#include "kitty-verstable.h"

typedef struct {
    uint32_t client_id, client_number, width, height;
    TextureRef *texture;
    id_type internal_id;

    bool root_frame_data_loaded;
    id_type ref_id_counter;
    Frame *extra_frames, root_frame;
    uint32_t current_frame_index, frame_id_counter;
    uint64_t animation_duration;
    size_t extra_framecnt;
    monotonic_t atime;
    size_t used_storage;
    bool is_drawn;
    AnimationState animation_state;
    uint32_t max_loops, current_loop;
    monotonic_t current_frame_shown_at;
    ref_map refs_by_internal_id;
} Image;

typedef struct {
    id_type image_id;
    uint32_t frame_id;
} ImageAndFrame;

typedef struct {
    uint8_t *buf;
    size_t buf_capacity, buf_used;

    uint8_t *mapped_file;
    size_t mapped_file_sz;

    size_t data_sz;
    uint8_t *data;
    bool is_4byte_aligned;
    bool is_opaque, loading_completed_successfully;
    uint32_t width, height;
    GraphicsCommand start_command;
    ImageAndFrame loading_for;
} LoadData;

#define NAME image_map
#define KEY_TY id_type
#define VAL_TY Image*
#include "kitty-verstable.h"

typedef struct {
    PyObject_HEAD

    size_t storage_limit;
    LoadData currently_loading;
    id_type image_id_counter;
    struct {
        size_t count, capacity;
        ImageRenderData *item;
    } render_data;
    bool layers_dirty;
    // The number of images below MIN_ZINDEX / 2, then the number of refs between MIN_ZINDEX / 2 and -1 inclusive, then the number of refs above 0 inclusive.
    size_t num_of_below_refs, num_of_negative_refs, num_of_positive_refs;
    unsigned int last_scrolled_by;
    size_t used_storage;
    PyObject *disk_cache;
    bool has_images_needing_animation, context_made_current_for_this_command;
    id_type window_id;
    image_map images_by_internal_id;
} GraphicsManager;
#else
typedef struct {int x;} *GraphicsManager;
#endif

typedef struct {
    int32_t amt, limit;
    index_type margin_top, margin_bottom;
    bool has_margins;
} ScrollData;


static inline float
gl_size(const unsigned int sz, const unsigned int viewport_size) {
    // convert pixel sz to OpenGL coordinate system.
    const float px = 2.f / viewport_size;
    return px * sz;
}

static inline float
clamp_position_to_nearest_pixel(float pos, const unsigned int viewport_size) {
    // clamp the specified opengl position to the nearest pixel
    const float px = 2.f / viewport_size;
    const float distance =  pos + 1.f;
    const float num_of_pixels = roundf(distance / px);
    return -1.f + num_of_pixels * px;
}

static inline float
gl_pos_x(const unsigned int px_from_left_margin, const unsigned int viewport_size) {
    const float px = 2.f / viewport_size;
    return -1.f + px_from_left_margin * px;
}

static inline float
gl_pos_y(const unsigned int px_from_top_margin, const unsigned int viewport_size) {
    const float px = 2.f / viewport_size;
    return 1.f - px_from_top_margin * px;
}

typedef struct GraphicsRenderData {
    size_t count, capacity, num_of_below_refs, num_of_negative_refs, num_of_positive_refs;
    ImageRenderData *images;
} GraphicsRenderData;

GraphicsManager* grman_alloc(bool for_paused_rendering);
void grman_clear(GraphicsManager*, bool, CellPixelSize fg);
const char* grman_handle_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload, Cursor *c, bool *is_dirty, CellPixelSize fg);
void grman_put_cell_image(GraphicsManager *self, uint32_t row, uint32_t col, uint32_t image_id, uint32_t placement_id, uint32_t x, uint32_t y, uint32_t w, uint32_t h, CellPixelSize cell);
bool grman_update_layers(GraphicsManager *self, unsigned int scrolled_by, float screen_left, float screen_top, float dx, float dy, unsigned int num_cols, unsigned int num_rows, CellPixelSize);
void grman_scroll_images(GraphicsManager *self, const ScrollData*, CellPixelSize fg);
void grman_resize(GraphicsManager*, index_type, index_type, index_type, index_type, index_type, index_type);
void grman_rescale(GraphicsManager *self, CellPixelSize fg);
void grman_remove_cell_images(GraphicsManager *self, int32_t top, int32_t bottom);
void grman_remove_all_cell_images(GraphicsManager *self);
void gpu_data_for_image(ImageRenderData *ans, float left, float top, float right, float bottom);
bool png_from_file_pointer(FILE* fp, const char *path, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz);
bool png_path_to_bitmap(const char *path, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz);
bool png_from_data(void *png_data, size_t png_data_sz, const char *path_for_error_messages, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz);
bool image_path_to_bitmap(const char *path, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz);
bool scan_active_animations(GraphicsManager *self, const monotonic_t now, monotonic_t *minimum_gap, bool os_window_context_set);
void scale_rendered_graphic(ImageRenderData*, float xstart, float ystart, float x_scale, float y_scale);
void grman_pause_rendering(GraphicsManager *self, GraphicsManager *dest);
void grman_mark_layers_dirty(GraphicsManager *self);
void grman_set_window_id(GraphicsManager *self, id_type id);
GraphicsRenderData grman_render_data(GraphicsManager *self);
