/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "graphics.h"

typedef enum ScrollTypes { SCROLL_LINE = -999999, SCROLL_PAGE, SCROLL_FULL } ScrollType;

typedef struct {
    bool mLNM, mIRM, mDECTCEM, mDECSCNM, mDECOM, mDECAWM, mDECCOLM, mDECARM, mDECCKM,
         mBRACKETED_PASTE, mFOCUS_TRACKING, mEXTENDED_KEYBOARD, mDECSACE;
    MouseTrackingMode mouse_tracking_mode;
    MouseTrackingProtocol mouse_tracking_protocol;
    bool eight_bit_controls;  // S8C1T
} ScreenModes;

typedef struct {
    unsigned int x, y;
} SelectionBoundary;

typedef struct {
    unsigned int start_x, start_y, start_scrolled_by, end_x, end_y, end_scrolled_by;
    bool in_progress;
} Selection;

typedef struct {
    PyObject_HEAD

    unsigned int columns, lines, margin_top, margin_bottom, charset, scrolled_by, last_selection_scrolled_by;
    id_type window_id;
    uint32_t utf8_state, utf8_codepoint, *g0_charset, *g1_charset, *g_charset;
    Selection selection;
    SelectionBoundary last_rendered_selection_start, last_rendered_selection_end, last_rendered_url_start, last_rendered_url_end;
    Selection url_range;
    bool use_latin1, selection_updated_once, is_dirty, scroll_changed, rectangle_select;
    Cursor *cursor;
    SavepointBuffer main_savepoints, alt_savepoints;
    PyObject *callbacks, *test_child;
    LineBuf *linebuf, *main_linebuf, *alt_linebuf;
    GraphicsManager *grman, *main_grman, *alt_grman;
    HistoryBuf *historybuf;
    unsigned int history_line_added_count;
    bool *tabstops, *main_tabstops, *alt_tabstops;
    ScreenModes modes;
    ColorProfile *color_profile;
    double start_visual_bell_at;

    uint32_t parser_buf[PARSER_BUF_SZ];
    unsigned int parser_state, parser_text_start, parser_buf_pos;
    bool parser_has_pending_text;
    uint8_t read_buf[READ_BUF_SZ], *write_buf;
    double new_input_at;
    size_t read_buf_sz, write_buf_sz, write_buf_used;
    pthread_mutex_t read_buf_lock, write_buf_lock;

    CursorRenderInfo cursor_render_info;

} Screen;


void parse_worker(Screen *screen, PyObject *dump_callback);
void parse_worker_dump(Screen *screen, PyObject *dump_callback);
void screen_align(Screen*);
void screen_restore_cursor(Screen *);
void screen_save_cursor(Screen *);
void write_escape_code_to_child(Screen *self, unsigned char which, const char *data);
void screen_cursor_position(Screen*, unsigned int, unsigned int);
void screen_cursor_back(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/);
void screen_erase_in_line(Screen *, unsigned int, bool);
void screen_erase_in_display(Screen *, unsigned int, bool);
void screen_draw(Screen *screen, uint32_t codepoint);
void screen_ensure_bounds(Screen *self, bool use_margins);
void screen_toggle_screen_buffer(Screen *self);
void screen_normal_keypad_mode(Screen *self);
void screen_alternate_keypad_mode(Screen *self);
void screen_change_default_color(Screen *self, unsigned int which, uint32_t col);
void screen_alignment_display(Screen *self);
void screen_reverse_index(Screen *self);
void screen_index(Screen *self);
void screen_scroll(Screen *self, unsigned int count);
void screen_reverse_scroll(Screen *self, unsigned int count);
void screen_reset(Screen *self);
void screen_set_tab_stop(Screen *self);
void screen_tab(Screen *self);
void screen_backtab(Screen *self, unsigned int);
void screen_clear_tab_stop(Screen *self, unsigned int how);
void screen_set_mode(Screen *self, unsigned int mode);
void screen_reset_mode(Screen *self, unsigned int mode);
void screen_decsace(Screen *self, unsigned int);
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
void screen_delete_characters(Screen *self, unsigned int count);
void screen_erase_characters(Screen *self, unsigned int count);
void screen_set_margins(Screen *self, unsigned int top, unsigned int bottom);
void screen_change_charset(Screen *, uint32_t to);
void screen_handle_cmd(Screen *, PyObject *cmd);
void screen_designate_charset(Screen *, uint32_t which, uint32_t as);
void screen_use_latin1(Screen *, bool);
void set_title(Screen *self, PyObject*);
void set_icon(Screen *self, PyObject*);
void set_dynamic_color(Screen *self, unsigned int code, PyObject*);
void set_color_table_color(Screen *self, unsigned int code, PyObject*);
uint32_t* translation_table(uint32_t which);
void screen_request_capabilities(Screen *, char, PyObject *);
void screen_set_8bit_controls(Screen *, bool);
void report_device_attributes(Screen *self, unsigned int UNUSED mode, char start_modifier);
void select_graphic_rendition(Screen *self, unsigned int *params, unsigned int count, Region*);
void report_device_status(Screen *self, unsigned int which, bool UNUSED);
void report_mode_status(Screen *self, unsigned int which, bool);
void screen_apply_selection(Screen *self, void *address, size_t size);
bool screen_is_selection_dirty(Screen *self);
bool screen_invert_colors(Screen *self);
void screen_update_cell_data(Screen *self, void *address, size_t sz);
bool screen_is_cursor_visible(Screen *self);
bool screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end);
bool screen_selection_range_for_word(Screen *self, index_type x, index_type y, index_type *start, index_type *end);
void screen_start_selection(Screen *self, index_type x, index_type y, bool);
void screen_update_selection(Screen *self, index_type x, index_type y, bool ended);
bool screen_history_scroll(Screen *self, int amt, bool upwards);
Line* screen_visual_line(Screen *self, index_type y);
unsigned long screen_current_char_width(Screen *self);
void screen_mark_url(Screen *self, index_type start_x, index_type start_y, index_type end_x, index_type end_y);
void screen_handle_graphics_command(Screen *self, const GraphicsCommand *cmd, const uint8_t *payload);
bool screen_open_url(Screen*);
#define DECLARE_CH_SCREEN_HANDLER(name) void screen_##name(Screen *screen);
DECLARE_CH_SCREEN_HANDLER(bell)
DECLARE_CH_SCREEN_HANDLER(backspace)
DECLARE_CH_SCREEN_HANDLER(tab)
DECLARE_CH_SCREEN_HANDLER(linefeed)
DECLARE_CH_SCREEN_HANDLER(carriage_return)
