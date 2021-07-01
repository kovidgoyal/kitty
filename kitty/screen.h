/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "graphics.h"
#include "monotonic.h"
#define MAX_PARAMS 256

typedef enum ScrollTypes { SCROLL_LINE = -999999, SCROLL_PAGE, SCROLL_FULL } ScrollType;

typedef struct {
    bool mLNM, mIRM, mDECTCEM, mDECSCNM, mDECOM, mDECAWM, mDECCOLM, mDECARM, mDECCKM,
         mBRACKETED_PASTE, mFOCUS_TRACKING, mDECSACE;
    MouseTrackingMode mouse_tracking_mode;
    MouseTrackingProtocol mouse_tracking_protocol;
    bool eight_bit_controls;  // S8C1T
} ScreenModes;

typedef struct {
    unsigned int x, y;
    bool in_left_half_of_cell;
} SelectionBoundary;

typedef enum SelectionExtendModes { EXTEND_CELL, EXTEND_WORD, EXTEND_LINE, EXTEND_LINE_FROM_POINT } SelectionExtendMode;

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
    bool rectangle_select;
    IterationData last_rendered;
    int sort_y, sort_x;
} Selection;

typedef struct {
    Selection *items;
    size_t count, capacity, last_rendered_count;
    bool in_progress;
    SelectionExtendMode extend_mode;
} Selections;

#define SAVEPOINTS_SZ 256

typedef struct {
    uint32_t utf8_state, utf8_codepoint, *g0_charset, *g1_charset;
    unsigned int current_charset;
    bool use_latin1;
    Cursor cursor;
    bool mDECOM, mDECAWM, mDECSCNM;
    bool is_valid;
} Savepoint;


typedef struct {
    ScreenModes buf[SAVEPOINTS_SZ];
    index_type start_of_data, count;
} SavemodesBuffer;

typedef struct {
    CPUCell *cpu_cells;
    GPUCell *gpu_cells;
    bool is_active;
    index_type xstart, ynum, xnum;
} OverlayLine;

typedef struct {
    PyObject_HEAD

    unsigned int columns, lines, margin_top, margin_bottom, charset, scrolled_by;
    double pending_scroll_pixels;
    CellPixelSize cell_size;
    OverlayLine overlay_line;
    id_type window_id;
    uint32_t utf8_codepoint, *g0_charset, *g1_charset, *g_charset;
    UTF8State utf8_state;
    unsigned int current_charset;
    Selections selections, url_ranges;
    struct {
        unsigned int cursor_x, cursor_y, scrolled_by;
        index_type lines, columns;
    } last_rendered;
    bool use_latin1, is_dirty, scroll_changed, reload_all_gpu_data;
    Cursor *cursor;
    Savepoint main_savepoint, alt_savepoint;
    SavemodesBuffer modes_savepoints;
    PyObject *callbacks, *test_child;
    LineBuf *linebuf, *main_linebuf, *alt_linebuf;
    GraphicsManager *grman, *main_grman, *alt_grman;
    HistoryBuf *historybuf;
    unsigned int history_line_added_count;
    bool *tabstops, *main_tabstops, *alt_tabstops;
    ScreenModes modes;
    ColorProfile *color_profile;
    monotonic_t start_visual_bell_at;

    uint32_t parser_buf[PARSER_BUF_SZ];
    unsigned int parser_state, parser_text_start, parser_buf_pos;
    bool parser_has_pending_text;
    uint8_t read_buf[READ_BUF_SZ], *write_buf;
    monotonic_t new_input_at;
    size_t read_buf_sz, write_buf_sz, write_buf_used;
    pthread_mutex_t read_buf_lock, write_buf_lock;

    CursorRenderInfo cursor_render_info;

    struct {
        size_t capacity, used;
        uint8_t *buf;
        monotonic_t activated_at, wait_time;
    } pending_mode;
    DisableLigature disable_ligatures;
    PyObject *marker;
    bool has_focus;
    bool has_activity_since_last_focus;
    hyperlink_id_type active_hyperlink_id;
    HYPERLINK_POOL_HANDLE hyperlink_pool;
    ANSIBuf as_ansi_buf;
    char_type last_graphic_char;
    uint8_t main_key_encoding_flags[8], alt_key_encoding_flags[8], *key_encoding_flags;
} Screen;


void parse_worker(Screen *screen, PyObject *dump_callback, monotonic_t now);
void parse_worker_dump(Screen *screen, PyObject *dump_callback, monotonic_t now);
void screen_align(Screen*);
void screen_restore_cursor(Screen *);
void screen_save_cursor(Screen *);
void screen_restore_modes(Screen *);
void screen_save_modes(Screen *);
void write_escape_code_to_child(Screen *self, unsigned char which, const char *data);
void screen_cursor_position(Screen*, unsigned int, unsigned int);
void screen_cursor_back(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/);
void screen_erase_in_line(Screen *, unsigned int, bool);
void screen_erase_in_display(Screen *, unsigned int, bool);
void screen_draw(Screen *screen, uint32_t codepoint, bool);
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
void screen_insert_lines(Screen *self, unsigned int count/*=1*/);
void screen_delete_lines(Screen *self, unsigned int count/*=1*/);
void screen_repeat_character(Screen *self, unsigned int count);
void screen_delete_characters(Screen *self, unsigned int count);
void screen_erase_characters(Screen *self, unsigned int count);
void screen_set_margins(Screen *self, unsigned int top, unsigned int bottom);
void screen_change_charset(Screen *, uint32_t to);
void screen_handle_cmd(Screen *, PyObject *cmd);
void screen_push_colors(Screen *, unsigned int);
void screen_pop_colors(Screen *, unsigned int);
void screen_report_color_stack(Screen *);
void screen_handle_print(Screen *, PyObject *cmd);
void screen_designate_charset(Screen *, uint32_t which, uint32_t as);
void screen_use_latin1(Screen *, bool);
void set_title(Screen *self, PyObject*);
void desktop_notify(Screen *self, unsigned int, PyObject*);
void set_icon(Screen *self, PyObject*);
void set_dynamic_color(Screen *self, unsigned int code, PyObject*);
void clipboard_control(Screen *self, PyObject*);
void set_color_table_color(Screen *self, unsigned int code, PyObject*);
void process_cwd_notification(Screen *self, unsigned int code, PyObject*);
uint32_t* translation_table(uint32_t which);
void screen_request_capabilities(Screen *, char, PyObject *);
void screen_set_8bit_controls(Screen *, bool);
void report_device_attributes(Screen *self, unsigned int UNUSED mode, char start_modifier);
void select_graphic_rendition(Screen *self, int *params, unsigned int count, Region*);
void report_device_status(Screen *self, unsigned int which, bool UNUSED);
void report_mode_status(Screen *self, unsigned int which, bool);
void screen_apply_selection(Screen *self, void *address, size_t size);
bool screen_is_selection_dirty(Screen *self);
bool screen_has_selection(Screen*);
bool screen_invert_colors(Screen *self);
void screen_update_cell_data(Screen *self, void *address, FONTS_DATA_HANDLE, bool cursor_has_moved);
bool screen_is_cursor_visible(Screen *self);
bool screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end);
bool screen_selection_range_for_word(Screen *self, const index_type x, const index_type y, index_type *, index_type *, index_type *start, index_type *end, bool);
void screen_start_selection(Screen *self, index_type x, index_type y, bool, bool, SelectionExtendMode);
void screen_update_selection(Screen *self, index_type x, index_type y, bool in_left_half, bool ended, bool start_extended_selection);
bool screen_history_scroll(Screen *self, int amt, bool upwards);
Line* screen_visual_line(Screen *self, index_type y);
unsigned long screen_current_char_width(Screen *self);
void screen_mark_url(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y);
void set_active_hyperlink(Screen*, char*, char*);
hyperlink_id_type screen_mark_hyperlink(Screen*, index_type, index_type);
void screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload);
bool screen_open_url(Screen*);
void screen_dirty_sprite_positions(Screen *self);
void screen_rescale_images(Screen *self);
void screen_report_size(Screen *, unsigned int which);
void screen_escape_resize(Screen *, unsigned int which, unsigned int lines, unsigned int cols);
void screen_manipulate_title_stack(Screen *, unsigned int op, unsigned int which);
void screen_draw_overlay_text(Screen *self, const char *utf8_text);
void screen_set_key_encoding_flags(Screen *self, uint32_t val, uint32_t how);
void screen_push_key_encoding_flags(Screen *self, uint32_t val);
void screen_pop_key_encoding_flags(Screen *self, uint32_t num);
uint8_t screen_current_key_encoding_flags(Screen *self);
void screen_report_key_encoding_flags(Screen *self);
void screen_xtmodkeys(Screen *self, uint32_t p1, uint32_t p2);
bool screen_detect_url(Screen *screen, unsigned int x, unsigned int y);
#define DECLARE_CH_SCREEN_HANDLER(name) void screen_##name(Screen *screen);
DECLARE_CH_SCREEN_HANDLER(bell)
DECLARE_CH_SCREEN_HANDLER(backspace)
DECLARE_CH_SCREEN_HANDLER(tab)
DECLARE_CH_SCREEN_HANDLER(linefeed)
DECLARE_CH_SCREEN_HANDLER(carriage_return)
#undef DECLARE_CH_SCREEN_HANDLER
