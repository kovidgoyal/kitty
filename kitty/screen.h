/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "vt-parser.h"
#include "graphics.h"
#include "monotonic.h"
#include "line-buf.h"
#include "history.h"
#include "glyph-protocol.h"

typedef enum ScrollTypes { SCROLL_LINE = -999999, SCROLL_PAGE, SCROLL_FULL } ScrollType;

typedef struct DnDCommand {
    char type;
    unsigned more;
    uint32_t client_id;
    size_t payload_sz;
    int32_t cell_x, cell_y, pixel_x, pixel_y;
    uint32_t operation;
} DnDCommand;

// A command of the smooth scrolling protocol, see docs/smooth-scrolling-protocol.rst
typedef struct SmoothScrollCommand {
    char action, query_action, orientation;
    uint32_t id, x, y, width, height, capacity, private_overflow;
    int32_t delta;
} SmoothScrollCommand;

typedef struct {
    bool mLNM, mIRM, mDECTCEM, mDECSCNM, mDECOM, mDECAWM, mDECCOLM, mDECARM, mDECCKM, mCOLOR_PREFERENCE_NOTIFICATION, mBRACKETED_PASTE, mFOCUS_TRACKING,
        mDECSACE, mHANDLE_TERMIOS_SIGNALS, mINBAND_RESIZE_NOTIFICATION, mPASTE_EVENTS, mVISIBILITY_REPORTS, mWHEEL_EVENTS, mBDSM, mBIDI_AUTODETECT;
    MouseTrackingMode mouse_tracking_mode;
    MouseTrackingProtocol mouse_tracking_protocol;
} ScreenModes;

typedef struct {
    unsigned int x, y;
    bool in_left_half_of_cell;
} SelectionBoundary;

typedef enum SelectionExtendModes {
    EXTEND_CELL,
    EXTEND_WORD,
    EXTEND_LINE,
    EXTEND_LINE_FROM_BEGIN,
    EXTEND_LINE_FROM_POINT,
    EXTEND_WORD_AND_LINE_FROM_POINT
} SelectionExtendMode;

typedef struct {
    index_type x, x_limit;
} XRange;

typedef struct {
    int y, y_limit;
    XRange first, body, last;
} IterationData;

typedef struct {
    SelectionBoundary start, end, input_start, input_current;
    unsigned int start_scrolled_by, end_scrolled_by;
    bool rectangle_select, adjusting_start, is_hyperlink;
    IterationData last_rendered;
    int sort_y, sort_x;
    struct {
        SelectionBoundary start, end;
        unsigned int scrolled_by;
    } initial_extent;
} Selection;

typedef struct {
    Selection *items;
    size_t count, capacity, last_rendered_count;
    bool in_progress, extension_in_progress;
    SelectionExtendMode extend_mode;
} Selections;

#define SAVEPOINTS_SZ 256

typedef struct CharsetState {
    uint32_t *zero, *one, *current, current_num;
} CharsetState;

typedef struct {
    Cursor cursor;
    bool mDECOM, mDECAWM, mDECSCNM;
    CharsetState charset;
    bool is_valid;
} Savepoint;


typedef struct {
    PyObject *overlay_text;
    CPUCell *cpu_cells;
    RenderCell *render_cells;
    index_type xstart, ynum, xnum, cursor_x, text_len;
    // Position of the IME cursor inside the pre-edit text in unicode code points, negative if unknown
    int preedit_cursor;
    bool is_active;
    bool is_dirty;
    struct {
        CPUCell *cpu_cells;
        RenderCell *render_cells;
        Cursor cursor;
    } original_line;
    struct {
        index_type x, y;
    } last_ime_pos;
    // The cursor position last sent as the IME anchor outside of a composition, see sync_ime_position_with_cursor()
    struct {
        index_type x, y;
        bool valid;
    } last_ime_cursor;
} OverlayLine;

typedef struct ExtraCursor {
    CursorShape shape;
    index_type cell;
} ExtraCursor;

typedef struct ExtraCursors {
    ExtraCursor *locations;
    unsigned count, capacity;
    struct {
        DynamicColor cursor, text;
    } color;
    bool dirty;
} ExtraCursors;

#define MAX_SMOOTH_SCROLL_REGIONS 4u

// A rectangle of the screen that is scrolled smoothly, by fractions of a row,
// or of a column, for horizontal scrolling. The terminal moves the cells in
// the rectangle by whole rows (columns) and renders them shifted by the
// remaining fraction. Rows (columns) that move out of the rectangle are kept
// in overflow buffers, so that they can be drawn in the partially visible row
// (column) at the edge and restored when the scroll direction is reversed.
// See the "Smooth scroll regions" section of screen.c. In the following,
// before means above or to the left of the rectangle and after below or to
// its right.
typedef struct SmoothScrollRegion {
    uint32_t id;
    // The rectangle [left, right) x [top, bottom) in cells
    index_type left, top, right, bottom;
    // The maximum number of rows (columns) kept in each of the overflow buffers
    index_type capacity;
    // The number of rows (columns) currently kept before and after the rectangle
    index_type num_before, num_after;
    // The distance in pixels from the top (left) edge of the rectangle to the
    // top (left) of its first row (column) of cells. Its magnitude is less
    // than the cell height (width). When positive, the row (column) before
    // the rectangle is partially visible, when negative, the one after it.
    int offset;
    // Scrolled horizontally rather than vertically
    bool horizontal;
    // Do not use the scrollback as the overflow buffer above the rectangle
    bool private_overflow;
    // The number of rows moved from the rectangle into the scrollback, when it
    // is the overflow buffer. Only these rows are taken back from it.
    index_type pushed_to_history;
    // For vertical scrolling, rows [0, capacity) are the rows above the
    // rectangle, nearest first, and rows [capacity, 2 * capacity) the rows
    // below it, nearest first, each of the width of the rectangle. For
    // horizontal scrolling, row i of the rectangle has its columns to the left
    // in row i, of capacity cells with the nearest last, and its columns to
    // the right in row height + i, with the nearest first.
    LineBuf *overflow;
} SmoothScrollRegion;

typedef struct SmoothScroll {
    SmoothScrollRegion regions[MAX_SMOOTH_SCROLL_REGIONS];
    unsigned count;
    // Set when the offset of a region changes, to render it
    bool offsets_changed;
    // The screen buffer the regions are on, regions are removed when switching buffers
    const LineBuf *linebuf;
} SmoothScroll;

// How a smooth scroll region is rendered in a frame. A region that is
// shifted, that is, has a non-zero offset, has a strip of cells after the
// cells of the screen in the cell buffer. For vertical scrolling the strip is
// height + 2 rows of width cells: the row above the rectangle, its rows and
// the row below it. For horizontal scrolling it is height rows of width + 2
// cells: the column to the left of the rectangle, its columns and the column
// to its right. The strip is drawn in a separate pass, clipped to the
// rectangle, and the cells of the rectangle are skipped when drawing the screen.
typedef struct SmoothScrollRenderRegion {
    uint32_t id;
    index_type left, top, width, height;
    int offset;
    // The distance in pixels by which the rows of the screen are drawn below
    // their usual position, when the screen is scrolled back. Regions are
    // never shifted then, they are only used to clip the images moving with them.
    int y_offset;
    bool horizontal;
    // Whether the scrollback is the overflow buffer above the region, the
    // images in it are then not clipped when the screen is scrolled back
    bool uses_history;
    // The index in the cell buffer of the first cell of the strip, when shifted
    unsigned base_cell;
} SmoothScrollRenderRegion;

typedef struct SmoothScrollRender {
    SmoothScrollRenderRegion regions[MAX_SMOOTH_SCROLL_REGIONS];
    unsigned count;
    // The number of cells in the strips of the shifted regions
    unsigned num_strip_cells;
} SmoothScrollRender;

#define smooth_scroll_render_region_is_shifted(r) ((r)->offset != 0)
#define smooth_scroll_render_region_strip_width(r) ((r)->width + ((r)->horizontal ? 2u : 0u))
#define smooth_scroll_render_region_strip_height(r) ((r)->height + ((r)->horizontal ? 0u : 2u))


typedef struct {
    PyObject_HEAD

        unsigned int columns,
        lines, margin_top, margin_bottom, scrolled_by, pixel_scroll_offset_y;
    CellPixelSize cell_size;
    OverlayLine overlay_line;
    id_type window_id;
    Selections selections, url_ranges;
    struct {
        unsigned int scrolled_by;
        index_type lines, columns;
        color_type cursor_bg;
        CursorRenderInfo cursor;
    } last_rendered;
    bool is_dirty, scroll_changed, reload_all_gpu_data, sgr_blink_was_used;
    // When the text cache was last garbage collected to stay within the glyph protocol limits
    monotonic_t last_glyph_limit_gc_at;
    // set once a multiline (scale > 1) char has been drawn, used to skip scanning for such chars in hot paths
    bool multiline_chars_used;
    // set when multiline chars may be cut off at the bottom of the main ([0]) or
    // alternate ([1]) screen, which only happens when scrolling down, used to
    // avoid scanning for them on every linefeed
    bool multiline_chars_cut_off_at_bottom[2];
    Cursor *cursor;
    Savepoint main_savepoint, alt_savepoint;
    PyObject *callbacks, *test_child;
    TextCache *text_cache;
    CellStyleTable *style_table; // owned by text_cache
    uint32_t hyperlink_style_idx_cache;
    // The texture holding the style table for the shaders, see sync_style_texture() in shaders.c
    struct {
        gpu_texture_t texture;
        uint32_t width, height, count, generation;
    } style_texture;
    LineBuf *linebuf, *main_linebuf, *alt_linebuf;
    GraphicsManager *grman, *main_grman, *alt_grman;
    HistoryBuf *historybuf;
    bool *tabstops, *main_tabstops, *alt_tabstops;
    ScreenModes modes, saved_modes;
    ColorProfile *color_profile;
    monotonic_t start_visual_bell_at;
    // Shell integration (OSC 133) command state and alternate screen
    // changes, used by custom shaders. Times are zero until the first change.
    struct {
        monotonic_t started_at, finished_at;
        bool running;
    } command_state;
    struct {
        monotonic_t entered_at, exited_at;
    } alternate_screen;
    monotonic_t start_drag_overlay_at; // 0 = inactive
    uint8_t drag_overlay_quadrant;     // 1=left 2=right 3=top 4=bottom 0=none

    uint8_t *write_buf;
    size_t write_buf_sz, write_buf_used, write_buf_start;
    pthread_mutex_t write_buf_lock;

    CursorRenderInfo cursor_render_info;

    DisableLigature disable_ligatures;
    PyObject *marker;
    bool has_focus;
    uint8_t visibility_state; // 0 = unknown, 1 = potentially visible, 2 = not visible
    bool has_activity_since_last_focus;
    bool track_activity;
    hyperlink_id_type active_hyperlink_id;
    HYPERLINK_POOL_HANDLE hyperlink_pool;
    ANSIBuf as_ansi_buf;
    char_type last_graphic_char;
    uint8_t main_key_encoding_flags[8], alt_key_encoding_flags[8], *key_encoding_flags;
    struct {
        monotonic_t start, duration;
    } ignore_bells;
    union {
        struct {
            unsigned int redraws_prompts_at_all : 1;
            unsigned int uses_special_keys_for_cursor_movement : 1;
            unsigned int supports_click_events : 1;
            unsigned int relative_click_events : 1;
        };
        unsigned int val;
    } prompt_settings;
    char display_window_char;
    ProgressBarState progress_state;
    uint8_t progress_percent;                   // 0-100
    monotonic_t progress_indeterminate_anim_at; // animation start time for indeterminate progress
    uint8_t progress_previous_percent;          // the value of progress_percent before the last change
    ProgressBarState progress_previous_state;   // the value of progress_state before the last change
    monotonic_t progress_changed_at;            // when progress_state or progress_percent last changed, zero if never
    struct {
        char ch;
        uint8_t *canvas;
        size_t requested_height, width_px, height_px;
    } last_rendered_window_char;
    struct {
        // The row of the visited line in the coordinate system used by
        // range_line_(): 0 is the top of the live screen and negative rows are
        // in the scrollback. This is the only position that is kept up to date
        // as lines move, the scroll offset is derived from it when needed.
        int row;
        // The viewport row the line was visited at, used only as a hint for
        // where to show it when jumping back to it.
        index_type preferred_y;
        bool is_set;
    } last_visited_prompt;
    PyObject *last_reported_cwd;
    struct {
        hyperlink_id_type id;
        index_type x, y;
        bool has_detected_url;
    } current_hyperlink_under_mouse;
    struct {
        uint8_t stack[16], count;
    } main_pointer_shape_stack, alternate_pointer_shape_stack;
    Parser *vt_parser;
    struct {
        monotonic_t expires_at;
        Cursor cursor;
        ColorProfile color_profile;
        bool inverted, cell_data_updated, cursor_visible, pixel_scroll, on_main_screen;
        unsigned int scrolled_by, pixel_scroll_offset_y, history_count;
        LineBuf *linebuf;
        GraphicsManager *grman;
        Selections selections, url_ranges;
        ExtraCursors extra_cursors;
        struct {
            SmoothScrollRenderRegion regions[MAX_SMOOTH_SCROLL_REGIONS];
            unsigned count;
            // Copies of the regions, with copies of their overflow buffers
            SmoothScrollRegion copies[MAX_SMOOTH_SCROLL_REGIONS];
            // A copy of the last line of the scrollback, for the region using it
            // as its overflow buffer, whose index plus one is history_row_region,
            // zero if no region uses it
            LineBuf *history_row;
            unsigned history_row_region;
        } smooth_scroll;
    } paused_rendering;
    SmoothScroll smooth_scroll;
    // The smooth scroll regions as rendered in the current frame
    SmoothScrollRender smooth_scroll_render;
    // Scratch space for building the selection data when there are smooth scroll strips
    uint8_t *selection_scratch;
    size_t selection_scratch_sz;
    CharsetState charset;
    ListOfChars *lc;
    struct {
        // Memoized text cache indices for the ('\t', diff) text written by
        // screen_tab(), keyed by diff. Entries are idx + 1 with 0 meaning
        // unset. Must be cleared when the text cache is garbage collected.
        char_type idx_plus_1[16];
    } tab_cache;
    monotonic_t parsing_at;
    ExtraCursors extra_cursors;
    struct {
        bool active;
        DnDCommand metadata;
    } dnd_chunking;
    struct {
        bool rtl;       // direction set by SCP for the current buffer
        bool saved_rtl; // SCP direction saved by the bare XTSAVE, terminal-global like saved_modes
        struct {
            bool mBDSM, mBIDI_AUTODETECT, rtl;
        } main_stash; // main's controls while alt is active
    } bidi;
    struct BidiMaps *bidi_maps;      // allocated by the first upload of a stamped buffer
    uint64_t bidi_layout_generation; // bumped where rows move or the inputs of their layout change, which reused maps would miss
    bool bidi_records_writes;        // see screen_bidi_records_writes_changed()
    bool bidi_history_bits_stale;    // see bidi_note_line_from_history()
} Screen;

// Text is drawn by the recording loop while bidi mode is on or the active buffer has a stamp, so that one load picks the loop
static inline void
screen_bidi_records_writes_changed(Screen *self) {
    self->bidi_records_writes = self->modes.mBDSM || self->linebuf->bidi_stamped;
}

static inline void
bidi_layout_moved(Screen *self) {
    self->bidi_layout_generation++;
}

#define live_pixel_scroll_enabled(screen) (OPT(pixel_scroll) && (screen)->linebuf == (screen)->main_linebuf)
// While rendering is paused the pixel scroll state captured at pause time is used so that pausing does not change what is rendered
#define pixel_scroll_enabled(screen) ((screen)->paused_rendering.expires_at ? (screen)->paused_rendering.pixel_scroll : live_pixel_scroll_enabled(screen))
#define rendered_pixel_scroll_offset_y(screen) \
    ((screen)->paused_rendering.expires_at ? (screen)->paused_rendering.pixel_scroll_offset_y : (screen)->pixel_scroll_offset_y)
// The scroll position and scrollback size of the frame being rendered. While
// rendering is paused these are the values captured at pause time, so that
// everything drawn over the frozen text (images, cursor, scrollbar, etc.)
// stays aligned with it even as new output changes the live values.
#define rendered_scrolled_by(screen) ((screen)->paused_rendering.expires_at ? (screen)->paused_rendering.scrolled_by : (screen)->scrolled_by)
#define rendered_history_count(screen) ((screen)->paused_rendering.expires_at ? (screen)->paused_rendering.history_count : (screen)->historybuf->count)
#define rendered_on_main_screen(screen) \
    ((screen)->paused_rendering.expires_at ? (screen)->paused_rendering.on_main_screen : (screen)->linebuf == (screen)->main_linebuf)
#define render_lines_for_screen(screen) (screen->lines + pixel_scroll_enabled(screen))

// The fraction of a line by which the rendered content is scrolled when pixel scrolling
#define scroll_offset_lines_for_screen(screen) \
    ((pixel_scroll_enabled(screen) && (screen)->cell_size.height) ? (float)(rendered_pixel_scroll_offset_y(screen) / (double)(screen)->cell_size.height) : 0.f)

void screen_align(Screen *);
void screen_garbage_collect_text_cache(Screen *screen);
void screen_garbage_collect_style_table(Screen *screen);
void screen_restore_cursor(Screen *);
void screen_save_cursor(Screen *);
void screen_restore_modes(Screen *);
void screen_restore_mode(Screen *, unsigned int);
void screen_save_modes(Screen *);
void screen_save_mode(Screen *, unsigned int);
bool write_escape_code_to_child(Screen *self, unsigned char which, const char *data);
void screen_visibility_changed(Screen *self, bool potentially_visible);
void screen_cursor_position(Screen *, unsigned int, unsigned int);
void screen_cursor_move(Screen *self, unsigned int count /*=1*/, int move_direction /*=-1*/, bool allow_move_to_previous_line);
void screen_erase_in_line(Screen *, unsigned int, bool);
void screen_erase_in_display(Screen *, unsigned int, bool);
void screen_draw_text(Screen *self, const uint32_t *chars, size_t num_chars);
void screen_ensure_bounds(Screen *self, bool use_margins, bool cursor_was_within_margins);
void screen_toggle_screen_buffer(Screen *self, bool, bool);
void screen_normal_keypad_mode(Screen *self);
void screen_alternate_keypad_mode(Screen *self);
void screen_change_default_color(Screen *self, unsigned int which, uint32_t col);
void screen_alignment_display(Screen *self);
void screen_reverse_index(Screen *self);
void screen_index(Screen *self);
void screen_scroll(Screen *self, unsigned int count);
void screen_reverse_scroll(Screen *self, unsigned int count);
void screen_reverse_scroll_and_fill_from_scrollback(Screen *self, unsigned int count);
void screen_reset(Screen *self);
void screen_soft_reset(Screen *self);
void screen_set_tab_stop(Screen *self);
void screen_tab(Screen *self);
void screen_tabn(Screen *self, unsigned int count);
void screen_backtab(Screen *self, unsigned int);
void screen_clear_tab_stop(Screen *self, unsigned int how);
void screen_reset_tab_stops(Screen *self);
void screen_set_mode(Screen *self, unsigned int mode);
void screen_reset_mode(Screen *self, unsigned int mode);
void screen_decsace(Screen *self, unsigned int);
void screen_xtversion(Screen *self, unsigned int);
void screen_insert_characters(Screen *self, unsigned int count);
void screen_cursor_up(Screen *self, unsigned int count /*=1*/, bool do_carriage_return /*=false*/, int move_direction /*=-1*/);
void screen_set_cursor(Screen *self, unsigned int mode, uint8_t secondary);
void screen_set_bidi_direction(Screen *self, unsigned int direction, unsigned int path_extent);
void screen_cursor_to_column(Screen *self, unsigned int column);
void screen_cursor_down(Screen *self, unsigned int count /*=1*/);
void screen_cursor_forward(Screen *self, unsigned int count /*=1*/);
void screen_cursor_down1(Screen *self, unsigned int count /*=1*/);
void screen_cursor_up1(Screen *self, unsigned int count /*=1*/);
void screen_cursor_to_line(Screen *screen, unsigned int line);
MouseShape screen_pointer_shape(Screen *self);
void screen_insert_lines(Screen *self, unsigned int count /*=1*/);
void screen_delete_lines(Screen *self, unsigned int count /*=1*/);
void screen_repeat_character(Screen *self, unsigned int count);
void screen_delete_characters(Screen *self, unsigned int count);
void screen_erase_characters(Screen *self, unsigned int count);
void screen_set_margins(Screen *self, unsigned int top, unsigned int bottom);
void screen_push_colors(Screen *, unsigned int);
void screen_pop_colors(Screen *, unsigned int);
void screen_report_color_stack(Screen *);
void screen_handle_kitty_dcs(Screen *, const char *callback_name, PyObject *cmd);
void set_title(Screen *self, PyObject *);
void osc_context(Screen *self, PyObject *ctx);
void program_status_report(Screen *self, PyObject *data);
void desktop_notify(Screen *self, unsigned int, PyObject *);
void set_icon(Screen *self, PyObject *);
void set_dynamic_color(Screen *self, unsigned int code, PyObject *);
void color_control(Screen *self, unsigned int code, PyObject *);
void clipboard_control(Screen *self, int code, PyObject *);
void shell_prompt_marking(Screen *self, char *buf);
void file_transmission(Screen *self, PyObject *);
void set_color_table_color(Screen *self, unsigned int code, PyObject *);
void process_cwd_notification(Screen *self, unsigned int code, const char *, size_t);
void screen_request_capabilities(Screen *, char, const char *);
void report_device_attributes(Screen *self, unsigned int UNUSED mode, char start_modifier);
void select_graphic_rendition(Screen *self, int *params, unsigned int count, bool is_group, Region *r);
void report_device_status(Screen *self, unsigned int which, bool UNUSED);
void report_mode_status(Screen *self, unsigned int which, bool);
// Write the selection state of num_cells cells, one byte per cell, to the
// first byte of consecutive elements of stride bytes starting at address
void screen_apply_selection(Screen *self, void *address, size_t num_cells, size_t stride);
bool screen_update_graphics_layers(Screen *self);
void screen_scrollbar_geometry(const Screen *self, float *handle_position, float *visible_fraction);
bool screen_has_scrollbar(const Screen *self, bool is_hovering);
bool screen_is_selection_dirty(Screen *self);
bool screen_has_selection(Screen *);
bool screen_is_cell_selected(Screen *, index_type x, index_type y);
bool screen_invert_colors(Screen *self);
void screen_update_cell_data(Screen *self, void *address, FONTS_DATA_HANDLE, bool cursor_has_moved);
// Replaces x, the visual column of a click on screen row y, by its logical column
void screen_bidi_logical_click(Screen *self, index_type *x, index_type y, bool *in_left_half);
bool screen_is_cursor_visible(const Screen *self);
unsigned screen_multi_cursor_count(const Screen *self);
bool screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end);
bool
screen_selection_range_for_word(Screen *self, const index_type x, const index_type y, index_type *, index_type *, index_type *start, index_type *end, bool);
void screen_start_selection(Screen *self, index_type x, index_type y, bool, bool, SelectionExtendMode);
typedef struct SelectionUpdate {
    bool ended, start_extended_selection, set_as_nearest_extend;
} SelectionUpdate;
void screen_update_selection(Screen *self, index_type x, index_type y, bool in_left_half, SelectionUpdate upd);
bool screen_history_scroll(Screen *self, int amt, bool upwards);
void screen_history_scroll_to_absolute(Screen *self, double target_scrolled_by);
bool screen_apply_pixel_scroll(Screen *self, double delta_pixels);
bool screen_smooth_scroll_define(
    Screen *self,
    uint32_t id,
    index_type left,
    index_type top,
    index_type right,
    index_type bottom,
    index_type capacity,
    bool private_overflow,
    bool horizontal);
bool screen_smooth_scroll_remove(Screen *self, uint32_t id);
void screen_smooth_scroll_remove_all(Screen *self);
bool screen_smooth_scroll(Screen *self, uint32_t id, int delta_pixels, int *rows_shifted);
bool screen_prepare_smooth_scroll_render(Screen *self);
void screen_handle_smooth_scroll_command(Screen *self, const SmoothScrollCommand *cmd);
PyObject *as_text_history_buf(HistoryBuf *self, PyObject *args, ANSIBuf *output);
Line *screen_visual_line(Screen *self, index_type y);
void screen_mark_url(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y);
void set_active_hyperlink(Screen *, char *, char *);
hyperlink_id_type screen_mark_hyperlink(Screen *, index_type, index_type);
void screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload);
void screen_handle_multicell_command(Screen *self, const MultiCellCommand *cmd, const uint8_t *payload);
void screen_handle_dnd_command(Screen *self, const DnDCommand *cmd, const uint8_t *payload);
void screen_handle_glyph_command(Screen *self, const GlyphCommand *cmd, const uint8_t *buf);
bool screen_open_url(Screen *self, const char *callback);
bool screen_set_last_visited_prompt(Screen *, index_type);
bool screen_select_cmd_output(Screen *, index_type);
void screen_dirty_sprite_positions(Screen *self);
void screen_rescale_images(Screen *self);
void screen_report_size(Screen *, unsigned which, unsigned modifier);
void screen_manipulate_title_stack(Screen *, unsigned int op, unsigned int which);
bool screen_is_overlay_active(Screen *self);
index_type screen_overlay_line_start(const Screen *self);
void screen_update_overlay_text(Screen *self, const char *utf8_text, int preedit_cursor);
bool screen_ime_text_around_cursor(Screen *self, char **before, char **after);
void screen_set_key_encoding_flags(Screen *self, uint32_t val, uint32_t how);
void screen_push_key_encoding_flags(Screen *self, uint32_t val);
void screen_pop_key_encoding_flags(Screen *self, uint32_t num);
uint8_t screen_current_key_encoding_flags(Screen *self);
void screen_modify_other_keys(Screen *self, unsigned, unsigned);
void screen_report_key_encoding_flags(Screen *self);
int screen_detect_url(Screen *screen, unsigned int x, unsigned int y, bool mark);
int screen_cursor_at_a_shell_prompt(const Screen *);
bool screen_prompt_supports_click_events(const Screen *, bool *is_relative);
bool screen_fake_move_cursor_to_position(Screen *, index_type x, index_type y);
bool screen_send_signal_for_key(Screen *, char key);
bool get_line_edge_colors(Screen *self, color_type *left, color_type *right);
bool get_line_edge_colors_at_row(Screen *self, index_type y, color_type *left, color_type *right, bool *left_is_default, bool *right_is_default);
bool parse_sgr(Screen *screen, const uint8_t *buf, unsigned int num, const char *report_name, bool is_deccara);
bool screen_pause_rendering(Screen *self, bool pause, int for_in_ms);
void screen_check_pause_rendering(Screen *self, monotonic_t now);
Line *screen_line_for_cursor(Screen *self, index_type x, index_type y, Line *overlay_line);
index_type screen_multicell_char_rows_for_cursor(Screen *self, const CPUCell *ref, index_type x, index_type y);
void screen_designate_charset(Screen *self, uint32_t which, uint32_t as);
void screen_multi_cursor(Screen *self, int queried_shape, int *params, unsigned num_params);
bool range_line_is_continued(Screen *self, int y);
#define DECLARE_CH_SCREEN_HANDLER(name) void screen_##name(Screen *screen);
DECLARE_CH_SCREEN_HANDLER(bell)
DECLARE_CH_SCREEN_HANDLER(backspace)
DECLARE_CH_SCREEN_HANDLER(tab)
DECLARE_CH_SCREEN_HANDLER(linefeed)
DECLARE_CH_SCREEN_HANDLER(carriage_return)
#undef DECLARE_CH_SCREEN_HANDLER

static inline uint32_t
screen_cursor_style_idx(Screen *self) {
    return style_table_intern_cached(self->style_table, &self->cursor->style, &self->cursor->style_idx);
}
