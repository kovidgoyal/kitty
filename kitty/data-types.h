/*
 * data-types.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once


#include <stdint.h>
#include <stdbool.h>
#include <poll.h>
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define UNUSED __attribute__ ((unused))
#define EXPORTED __attribute__ ((visibility ("default")))
#define LIKELY(x)    __builtin_expect (!!(x), 1)
#define UNLIKELY(x)  __builtin_expect (!!(x), 0)
#define MAX(x, y) (((x) > (y)) ? (x) : (y))
#define MIN(x, y) (((x) > (y)) ? (y) : (x))
#define xstr(s) str(s)
#define str(s) #s

typedef uint32_t char_type;
typedef uint32_t color_type;
typedef uint32_t combining_type;
typedef unsigned int index_type;
typedef uint16_t sprite_index;

#define ERROR_PREFIX "[PARSE ERROR]"
#define ANY_MODE 3
#define MOTION_MODE 2
#define BUTTON_MODE 1
#define NORMAL_PROTOCOL 0
#define UTF8_PROTOCOL 1
#define SGR_PROTOCOL 2
#define URXVT_PROTOCOL 3

#define DATA_CELL_SIZE 6

#define BLANK_CHAR 32
#define CHAR_MASK 0xFFFFFF
#define ATTRS_SHIFT 24
#define ATTRS_MASK_WITHOUT_WIDTH 0xFC000000
#define WIDTH_MASK  3
#define DECORATION_SHIFT  2
#define DECORATION_MASK 3
#define BOLD_SHIFT 4
#define ITALIC_SHIFT 5
#define POSCHAR_MASK 0x30FFFFFF
#define REVERSE_SHIFT 6
#define STRIKE_SHIFT 7
#define COL_MASK 0xFFFFFFFF
#define CC_MASK 0xFFFF
#define CC_SHIFT 16
#define UTF8_ACCEPT 0
#define UTF8_REJECT 1
#define UNDERCURL_CODE 6
#define DECORATION_FG_CODE 58

#define CURSOR_BLOCK 1
#define CURSOR_BEAM 2
#define CURSOR_UNDERLINE 3
#define FG 1
#define BG 2

#define CURSOR_TO_ATTRS(c, w) \
    ((w) | (((c->decoration & 3) << DECORATION_SHIFT) | ((c->bold & 1) << BOLD_SHIFT) | \
            ((c->italic & 1) << ITALIC_SHIFT) | ((c->reverse & 1) << REVERSE_SHIFT) | ((c->strikethrough & 1) << STRIKE_SHIFT))) << ATTRS_SHIFT

#define ATTRS_TO_CURSOR(a, c) \
    c->decoration = (a >> DECORATION_SHIFT) & 3; c->bold = (a >> BOLD_SHIFT) & 1; c->italic = (a >> ITALIC_SHIFT) & 1; \
    c->reverse = (a >> REVERSE_SHIFT) & 1; c->strikethrough = (a >> STRIKE_SHIFT) & 1;

#define COPY_CELL(src, s, dest, d) \
    (dest)->cells[d] = (src)->cells[s];

#define COPY_SELF_CELL(s, d) COPY_CELL(self, s, self, d)

#define METHOD(name, arg_type) {#name, (PyCFunction)name, arg_type, name##_doc},

#define BOOL_GETSET(type, x) \
    static PyObject* x##_get(type *self, void UNUSED *closure) { PyObject *ans = self->x ? Py_True : Py_False; Py_INCREF(ans); return ans; } \
    static int x##_set(type *self, PyObject *value, void UNUSED *closure) { if (value == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } self->x = PyObject_IsTrue(value) ? true : false; return 0; }

#define GETSET(x) \
    {#x, (getter) x##_get, (setter) x##_set, #x, NULL},

#ifndef EXTRA_INIT
#define EXTRA_INIT
#endif
#define INIT_TYPE(type) \
    int init_##type(PyObject *module) {\
        if (PyType_Ready(&type##_Type) < 0) return 0; \
        if (PyModule_AddObject(module, #type, (PyObject *)&type##_Type) != 0) return 0; \
        Py_INCREF(&type##_Type); \
        EXTRA_INIT; \
        return 1; \
    }

#define RICHCMP(type) \
    static PyObject * richcmp(PyObject *obj1, PyObject *obj2, int op) { \
        PyObject *result = NULL; \
        int eq; \
        if (op != Py_EQ && op != Py_NE) { Py_RETURN_NOTIMPLEMENTED; } \
        if (!PyObject_TypeCheck(obj1, &type##_Type)) { Py_RETURN_FALSE; } \
        if (!PyObject_TypeCheck(obj2, &type##_Type)) { Py_RETURN_FALSE; } \
        eq = __eq__((type*)obj1, (type*)obj2); \
        if (op == Py_NE) result = eq ? Py_False : Py_True; \
        else result = eq ? Py_True : Py_False; \
        Py_INCREF(result); \
        return result; \
    }

#ifdef __clang__
#define START_ALLOW_CASE_RANGE _Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wpedantic\"")
#define END_ALLOW_CASE_RANGE _Pragma("clang diagnostic pop")
#define ALLOW_UNUSED_RESULT _Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wunused-result\"")
#define END_ALLOW_UNUSED_RESULT _Pragma("clang diagnostic pop")
#else
#define START_ALLOW_CASE_RANGE _Pragma("GCC diagnostic ignored \"-Wpedantic\"")
#define END_ALLOW_CASE_RANGE _Pragma("GCC diagnostic pop")
#define ALLOW_UNUSED_RESULT _Pragma("GCC diagnostic ignored \"-Wunused-result\"")
#define END_ALLOW_UNUSED_RESULT _Pragma("GCC diagnostic pop")
#endif

typedef struct {
    char_type ch;
    color_type fg, bg, decoration_fg;
    combining_type cc;
} Cell;

typedef struct {
    PyObject_HEAD

    Cell *cells;
    index_type xnum, ynum;
    bool continued;
    bool needs_free;
} Line;
PyTypeObject Line_Type;


typedef struct {
    PyObject_HEAD

    Cell *buf;
    index_type xnum, ynum, *line_map, *scratch;
    bool *continued_map;
    Line *line;
} LineBuf;
PyTypeObject LineBuf_Type;


typedef struct {
    PyObject_HEAD

    Cell *buf;
    index_type xnum, ynum;
    Line *line;
    index_type start_of_data, count;
    bool *continued_map;
} HistoryBuf;
PyTypeObject HistoryBuf_Type;

typedef struct {
    PyObject_HEAD

    bool bold, italic, reverse, strikethrough, blink;
    unsigned int x, y;
    uint8_t decoration, shape;
    unsigned long fg, bg, decoration_fg;

} Cursor;
PyTypeObject Cursor_Type;

PyTypeObject Face_Type;
PyTypeObject Window_Type;

typedef struct {
    color_type default_fg, default_bg, cursor_color, highlight_fg, highlight_bg;
} DynamicColor;

typedef struct {
    PyObject_HEAD

    PyObject *dirty, *ubo;
    uint32_t color_table[256];
    uint32_t orig_color_table[256];
    DynamicColor configured, overridden;
} ColorProfile;
PyTypeObject ColorProfile_Type;

typedef struct {
    PyObject_HEAD

    index_type xnum, ynum;
    bool screen_changed;
    bool cursor_changed;
    bool dirty;
    bool *changed_lines;
    bool *lines_with_changed_cells;
    bool *changed_cells;
    unsigned int history_line_added_count;
} ChangeTracker;
PyTypeObject ChangeTracker_Type;


typedef struct {
    bool mLNM, mIRM, mDECTCEM, mDECSCNM, mDECOM, mDECAWM, mDECCOLM, mDECARM, mDECCKM,
         mBRACKETED_PASTE, mFOCUS_TRACKING, mEXTENDED_KEYBOARD;
    unsigned long mouse_tracking_mode, mouse_tracking_protocol;
} ScreenModes;
PyTypeObject ScreenModes_Type;

#define SAVEPOINTS_SZ 256

typedef struct {
    uint32_t utf8_state, utf8_codepoint, *g0_charset, *g1_charset, *g_charset;
    bool use_latin1;
    Cursor cursor;
    bool mDECOM, mDECAWM, mDECSCNM;

} Savepoint;


typedef struct {
    Savepoint buf[SAVEPOINTS_SZ];
    index_type start_of_data, count;
} SavepointBuffer;


#define PARSER_BUF_SZ (8 * 1024)
#define READ_BUF_SZ (1024*1024)

typedef struct {
    PyObject_HEAD

    unsigned int columns, lines, margin_top, margin_bottom, charset;
    uint32_t utf8_state, utf8_codepoint, *g0_charset, *g1_charset, *g_charset;
    bool use_latin1;
    Cursor *cursor;
    SavepointBuffer main_savepoints, alt_savepoints;
    PyObject *callbacks;
    LineBuf *linebuf, *main_linebuf, *alt_linebuf;
    HistoryBuf *historybuf;
    bool *tabstops, *main_tabstops, *alt_tabstops;
    ChangeTracker *change_tracker;
    ScreenModes modes;
    ColorProfile *color_profile;

    uint32_t parser_buf[PARSER_BUF_SZ];
    unsigned int parser_state, parser_text_start, parser_buf_pos;
    bool parser_has_pending_text;
    uint8_t read_buf[READ_BUF_SZ];

} Screen;
PyTypeObject Screen_Type;

typedef struct {
    double at;
    PyObject *callback;
    PyObject *args;
} TimerEvent;

typedef struct {
    PyObject_HEAD

    TimerEvent *events, *buf1, *buf2;
    size_t capacity;
    size_t count;
} Timers;
PyTypeObject Timers_Type;

typedef struct {
    Screen *screen;
    PyObject *on_exit, *write_func, *update_screen;
    bool needs_write;
} Child;

typedef struct {
    PyObject_HEAD

    PyObject *wakeup_func, *signal_func, *dump_callback;
    Timers *timers;
    int wakeup_fd, singal_fd;
    struct pollfd *fds;
    Child *children;
    size_t count;
    bool shutting_down;
    double repaint_delay;
} ChildMonitor;
PyTypeObject ChildMonitor_Type;

#define left_shift_line(line, at, num) \
    for(index_type __i__ = (at); __i__ < (line)->xnum - (num); __i__++) { \
        COPY_CELL(line, __i__ + (num), line, __i__) \
    } \
    if ((((line)->cells[(at)].ch >> ATTRS_SHIFT) & WIDTH_MASK) != 1) (line)->cells[(at)].ch = (1 << ATTRS_SHIFT) | BLANK_CHAR;


// Global functions 
Line* alloc_line();
Cursor* alloc_cursor();
LineBuf* alloc_linebuf(unsigned int, unsigned int);
HistoryBuf* alloc_historybuf(unsigned int, unsigned int);
ChangeTracker* alloc_change_tracker(unsigned int, unsigned int);
ColorProfile* alloc_color_profile();
int init_LineBuf(PyObject *);
int init_HistoryBuf(PyObject *);
int init_Cursor(PyObject *);
int init_Timers(PyObject *);
int init_ChildMonitor(PyObject *);
int init_Line(PyObject *);
int init_ColorProfile(PyObject *);
int init_ChangeTracker(PyObject *);
int init_Screen(PyObject *);
int init_Face(PyObject *);
int init_Window(PyObject *);
PyObject* create_256_color_table();
bool read_bytes(int fd, Screen *screen, PyObject *dump_callback);
bool read_bytes_dump(int fd, Screen *screen, PyObject *dump_callback);
PyObject* parse_bytes_dump(PyObject UNUSED *, PyObject *);
PyObject* parse_bytes(PyObject UNUSED *, PyObject *);
uint32_t decode_utf8(uint32_t*, uint32_t*, uint8_t byte);
void cursor_reset(Cursor*);
Cursor* cursor_copy(Cursor*);
void cursor_copy_to(Cursor *src, Cursor *dest);
void cursor_reset_display_attrs(Cursor*);
bool update_cell_range_data(ScreenModes *modes, Line *, unsigned int, unsigned int, unsigned int *);

PyObject* line_text_at(char_type, combining_type);
void line_clear_text(Line *self, unsigned int at, unsigned int num, int ch);
void line_apply_cursor(Line *self, Cursor *cursor, unsigned int at, unsigned int num, bool clear_char);
void line_set_char(Line *, unsigned int , uint32_t , unsigned int , Cursor *);
void line_right_shift(Line *, unsigned int , unsigned int );
void line_add_combining_char(Line *, uint32_t , unsigned int );
index_type line_as_ansi(Line *self, Py_UCS4 *buf, index_type buflen);
unsigned int line_length(Line *self);

void linebuf_init_line(LineBuf *, index_type);
void linebuf_clear(LineBuf *, char_type ch);
void linebuf_init_line(LineBuf *, index_type);
void linebuf_index(LineBuf* self, index_type top, index_type bottom);
void linebuf_reverse_index(LineBuf *self, index_type top, index_type bottom);
void linebuf_clear_line(LineBuf *self, index_type y);
void linebuf_insert_lines(LineBuf *self, unsigned int num, unsigned int y, unsigned int bottom);
void linebuf_delete_lines(LineBuf *self, index_type num, index_type y, index_type bottom);
void linebuf_set_attribute(LineBuf *, unsigned int , unsigned int );
void linebuf_rewrap(LineBuf *self, LineBuf *other, int *cursor_y_out, HistoryBuf *);
unsigned int linebuf_char_width_at(LineBuf *self, index_type x, index_type y);
bool historybuf_resize(HistoryBuf *self, index_type lines);
void historybuf_add_line(HistoryBuf *self, const Line *line);
void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other);
void historybuf_init_line(HistoryBuf *self, index_type num, Line *l);

double timers_timeout(Timers*);
void timers_call(Timers*);
bool timers_add_if_missing(Timers *self, double delay, PyObject *callback, PyObject *args);

color_type colorprofile_to_color(ColorProfile *self, color_type entry, color_type defval);

unsigned int safe_wcwidth(uint32_t ch);
void change_wcwidth(bool use9);
void screen_align(Screen*);
void screen_restore_cursor(Screen *);
void screen_save_cursor(Screen *);
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
void screen_designate_charset(Screen *, uint32_t which, uint32_t as);
void screen_use_latin1(Screen *, bool);
void set_title(Screen *self, PyObject*);
void set_icon(Screen *self, PyObject*);
void set_dynamic_color(Screen *self, unsigned int code, PyObject*);
void set_color_table_color(Screen *self, unsigned int code, PyObject*);
uint32_t* translation_table(uint32_t which);
uint32_t *latin1_charset;
void screen_request_capabilities(Screen *, PyObject *);
void report_device_attributes(Screen *self, unsigned int UNUSED mode, char start_modifier);
void select_graphic_rendition(Screen *self, unsigned int *params, unsigned int count);
void report_device_status(Screen *self, unsigned int which, bool UNUSED);
void report_mode_status(Screen *self, unsigned int which, bool);
#define DECLARE_CH_SCREEN_HANDLER(name) void screen_##name(Screen *screen);
DECLARE_CH_SCREEN_HANDLER(bell)
DECLARE_CH_SCREEN_HANDLER(backspace)
DECLARE_CH_SCREEN_HANDLER(tab)
DECLARE_CH_SCREEN_HANDLER(linefeed)
DECLARE_CH_SCREEN_HANDLER(carriage_return)

bool init_freetype_library(PyObject*);
bool init_fontconfig_library(PyObject*);
PyObject *get_fontconfig_font(PyObject *self, PyObject *args);
