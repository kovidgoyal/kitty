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

typedef enum ScrollTypes { SCROLL_LINE = -999999, SCROLL_PAGE, SCROLL_FULL } ScrollType;

typedef struct {
    bool mLNM, mIRM, mDECTCEM, mDECSCNM, mDECOM, mDECAWM, mDECCOLM, mDECARM, mDECCKM, mCOLOR_PREFERENCE_NOTIFICATION,
         mBRACKETED_PASTE, mFOCUS_TRACKING, mDECSACE, mHANDLE_TERMIOS_SIGNALS, mINBAND_RESIZE_NOTIFICATION;
    MouseTrackingMode mouse_tracking_mode;
    MouseTrackingProtocol mouse_tracking_protocol;
} ScreenModes;

typedef struct {
    unsigned int x, y;
    bool in_left_half_of_cell;
} SelectionBoundary;

typedef enum SelectionExtendModes { EXTEND_CELL, EXTEND_WORD, EXTEND_LINE, EXTEND_LINE_FROM_POINT, EXTEND_WORD_AND_LINE_FROM_POINT } SelectionExtendMode;

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
    GPUCell *gpu_cells;
    index_type xstart, ynum, xnum, cursor_x, text_len;
    bool is_active;
    bool is_dirty;
    struct {
        CPUCell *cpu_cells;
        GPUCell *gpu_cells;
        Cursor cursor;
    } original_line;
    struct {
        index_type x, y;
    } last_ime_pos;
} OverlayLine;

typedef struct {
    PyObject_HEAD

    unsigned int columns, lines, margin_top, margin_bottom, scrolled_by;
    double pending_scroll_pixels_x, pending_scroll_pixels_y;
    CellPixelSize cell_size;
    OverlayLine overlay_line;
    id_type window_id;
    Selections selections, url_ranges;
    struct {
        unsigned int cursor_x, cursor_y, scrolled_by;
        index_type lines, columns;
        color_type cursor_bg;
    } last_rendered;
    bool is_dirty, scroll_changed, reload_all_gpu_data;
    Cursor *cursor;
    Savepoint main_savepoint, alt_savepoint;
    PyObject *callbacks, *test_child;
    TextCache *text_cache;
    LineBuf *linebuf, *main_linebuf, *alt_linebuf;
    GraphicsManager *grman, *main_grman, *alt_grman;
    HistoryBuf *historybuf;
    unsigned int history_line_added_count;
    bool *tabstops, *main_tabstops, *alt_tabstops;
    ScreenModes modes, saved_modes;
    ColorProfile *color_profile;
    monotonic_t start_visual_bell_at;

    uint8_t *write_buf;
    size_t write_buf_sz, write_buf_used;
    pthread_mutex_t write_buf_lock;

    CursorRenderInfo cursor_render_info;

    DisableLigature disable_ligatures;
    PyObject *marker;
    bool has_focus;
    bool has_activity_since_last_focus;
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
            unsigned int redraws_prompts_at_all: 1;
            unsigned int uses_special_keys_for_cursor_movement: 1;
            unsigned int supports_click_events: 1;
        };
        unsigned int val;
    } prompt_settings;
    char display_window_char;
    struct {
        char ch;
        uint8_t *canvas;
        size_t requested_height, width_px, height_px;
    } last_rendered_window_char;
    struct {
        unsigned int scrolled_by;
        index_type y;
        bool is_set;
    } last_visited_prompt;
    PyObject *last_reported_cwd;
    struct {
        hyperlink_id_type id;
        index_type x, y;
    } current_hyperlink_under_mouse;
    struct {
        uint8_t stack[16], count;
    } main_pointer_shape_stack, alternate_pointer_shape_stack;
    Parser *vt_parser;
    struct {
        monotonic_t expires_at;
        Cursor cursor;
        ColorProfile color_profile;
        bool inverted, cell_data_updated, cursor_visible;
        unsigned int scrolled_by;
        LineBuf *linebuf;
        GraphicsManager *grman;
        Selections selections, url_ranges;
    } paused_rendering;
    CharsetState charset;
    ListOfChars *lc;
    monotonic_t parsing_at;
} Screen;


void screen_align(Screen*);
void screen_restore_cursor(Screen *);
void screen_save_cursor(Screen *);
void screen_restore_modes(Screen *);
void screen_restore_mode(Screen *, unsigned int);
void screen_save_modes(Screen *);
void screen_save_mode(Screen *, unsigned int);
bool write_escape_code_to_child(Screen *self, unsigned char which, const char *data);
void screen_cursor_position(Screen*, unsigned int, unsigned int);
void screen_cursor_move(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/);
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
void screen_set_tab_stop(Screen *self);
void screen_tab(Screen *self);
void screen_backtab(Screen *self, unsigned int);
void screen_clear_tab_stop(Screen *self, unsigned int how);
void screen_set_mode(Screen *self, unsigned int mode);
void screen_reset_mode(Screen *self, unsigned int mode);
void screen_decsace(Screen *self, unsigned int);
void screen_xtversion(Screen *self, unsigned int);
void screen_insert_characters(Screen *self, unsigned int count);
void screen_cursor_up(Screen *self, unsigned int count/*=1*/, bool do_carriage_return/*=false*/, int move_direction/*=-1*/);
void screen_set_cursor(Screen *self, unsigned int mode, uint8_t secondary);
void screen_cursor_to_column(Screen *self, unsigned int column);
void screen_cursor_down(Screen *self, unsigned int count/*=1*/);
void screen_cursor_forward(Screen *self, unsigned int count/*=1*/);
void screen_cursor_down1(Screen *self, unsigned int count/*=1*/);
void screen_cursor_up1(Screen *self, unsigned int count/*=1*/);
void screen_cursor_to_line(Screen *screen, unsigned int line);
MouseShape screen_pointer_shape(Screen *self);
void screen_insert_lines(Screen *self, unsigned int count/*=1*/);
void screen_delete_lines(Screen *self, unsigned int count/*=1*/);
void screen_repeat_character(Screen *self, unsigned int count);
void screen_delete_characters(Screen *self, unsigned int count);
void screen_erase_characters(Screen *self, unsigned int count);
void screen_set_margins(Screen *self, unsigned int top, unsigned int bottom);
void screen_push_colors(Screen *, unsigned int);
void screen_pop_colors(Screen *, unsigned int);
void screen_report_color_stack(Screen *);
void screen_handle_kitty_dcs(Screen *, const char *callback_name, PyObject *cmd);
void set_title(Screen *self, PyObject*);
void desktop_notify(Screen *self, unsigned int, PyObject*);
void set_icon(Screen *self, PyObject*);
void set_dynamic_color(Screen *self, unsigned int code, PyObject*);
void color_control(Screen *self, unsigned int code, PyObject*);
void clipboard_control(Screen *self, int code, PyObject*);
void shell_prompt_marking(Screen *self, char *buf);
void file_transmission(Screen *self, PyObject*);
void set_color_table_color(Screen *self, unsigned int code, PyObject*);
void process_cwd_notification(Screen *self, unsigned int code, const char*, size_t);
void screen_request_capabilities(Screen *, char, const char *);
void report_device_attributes(Screen *self, unsigned int UNUSED mode, char start_modifier);
void select_graphic_rendition(Screen *self, int *params, unsigned int count, bool is_group, Region *r);
void report_device_status(Screen *self, unsigned int which, bool UNUSED);
void report_mode_status(Screen *self, unsigned int which, bool);
void screen_apply_selection(Screen *self, void *address, size_t size);
bool screen_is_selection_dirty(Screen *self);
bool screen_has_selection(Screen*);
bool screen_invert_colors(Screen *self);
void screen_update_cell_data(Screen *self, void *address, FONTS_DATA_HANDLE, bool cursor_has_moved);
bool screen_is_cursor_visible(const Screen *self);
bool screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end);
bool screen_selection_range_for_word(Screen *self, const index_type x, const index_type y, index_type *, index_type *, index_type *start, index_type *end, bool);
void screen_start_selection(Screen *self, index_type x, index_type y, bool, bool, SelectionExtendMode);
typedef struct SelectionUpdate {
    bool ended, start_extended_selection, set_as_nearest_extend;
} SelectionUpdate;
void screen_update_selection(Screen *self, index_type x, index_type y, bool in_left_half, SelectionUpdate upd);
bool screen_history_scroll(Screen *self, int amt, bool upwards);
PyObject* as_text_history_buf(HistoryBuf *self, PyObject *args, ANSIBuf *output);
Line* screen_visual_line(Screen *self, index_type y);
void screen_mark_url(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y);
void set_active_hyperlink(Screen*, char*, char*);
hyperlink_id_type screen_mark_hyperlink(Screen*, index_type, index_type);
void screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload);
void screen_handle_multicell_command(Screen *self, const MultiCellCommand *cmd, const uint8_t *payload);
bool screen_open_url(Screen*);
bool screen_set_last_visited_prompt(Screen*, index_type);
bool screen_select_cmd_output(Screen*, index_type);
void screen_dirty_sprite_positions(Screen *self);
void screen_rescale_images(Screen *self);
void screen_report_size(Screen *, unsigned int which);
void screen_manipulate_title_stack(Screen *, unsigned int op, unsigned int which);
bool screen_is_overlay_active(Screen *self);
void screen_update_overlay_text(Screen *self, const char *utf8_text);
void screen_set_key_encoding_flags(Screen *self, uint32_t val, uint32_t how);
void screen_push_key_encoding_flags(Screen *self, uint32_t val);
void screen_pop_key_encoding_flags(Screen *self, uint32_t num);
uint8_t screen_current_key_encoding_flags(Screen *self);
void screen_modify_other_keys(Screen *self, unsigned int);
void screen_report_key_encoding_flags(Screen *self);
int screen_detect_url(Screen *screen, unsigned int x, unsigned int y);
int screen_cursor_at_a_shell_prompt(const Screen *);
bool screen_prompt_supports_click_events(const Screen *);
bool screen_fake_move_cursor_to_position(Screen *, index_type x, index_type y);
bool screen_send_signal_for_key(Screen *, char key);
bool get_line_edge_colors(Screen *self, color_type *left, color_type *right);
bool parse_sgr(Screen *screen, const uint8_t *buf, unsigned int num, const char *report_name, bool is_deccara);
bool screen_pause_rendering(Screen *self, bool pause, int for_in_ms);
void screen_check_pause_rendering(Screen *self, monotonic_t now);
void screen_designate_charset(Screen *self, uint32_t which, uint32_t as);
#define DECLARE_CH_SCREEN_HANDLER(name) void screen_##name(Screen *screen);
DECLARE_CH_SCREEN_HANDLER(bell)
DECLARE_CH_SCREEN_HANDLER(backspace)
DECLARE_CH_SCREEN_HANDLER(tab)
DECLARE_CH_SCREEN_HANDLER(linefeed)
DECLARE_CH_SCREEN_HANDLER(carriage_return)
#undef DECLARE_CH_SCREEN_HANDLER
