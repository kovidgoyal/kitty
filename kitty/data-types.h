/*
 * data-types.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <poll.h>
#include <pthread.h>
#include "glfw-wrapper.h"
#include "banned.h"
// Required minimum OpenGL version
#define OPENGL_REQUIRED_VERSION_MAJOR 3
#ifdef __APPLE__
#define OPENGL_REQUIRED_VERSION_MINOR 3
#else
#define OPENGL_REQUIRED_VERSION_MINOR 1
#endif
#define GLSL_VERSION 140
#define GLFW_MOD_KITTY (GLFW_MOD_LAST * 2)
#define UNUSED __attribute__ ((unused))
#define PYNOARG PyObject *__a1 UNUSED, PyObject *__a2 UNUSED
#define EXPORTED __attribute__ ((visibility ("default")))
#define LIKELY(x)    __builtin_expect (!!(x), 1)
#define UNLIKELY(x)  __builtin_expect (!!(x), 0)
#define MAX(x, y) __extension__ ({ \
    __typeof__ (x) a = (x); __typeof__ (y) b = (y); \
        a > b ? a : b;})
#define MIN(x, y) __extension__ ({ \
    __typeof__ (x) a = (x); __typeof__ (y) b = (y); \
        a < b ? a : b;})
#define SWAP(x, y) do { __typeof__(x) _sw_ = y; y = x; x = _sw_; } while(0)
#define xstr(s) str(s)
#define str(s) #s
#define arraysz(x) (sizeof(x)/sizeof(x[0]))
#define zero_at_i(array, idx) memset((array) + (idx), 0, sizeof((array)[0]))
#define zero_at_ptr(p) memset((p), 0, sizeof((p)[0]))
#define zero_at_ptr_count(p, count) memset((p), 0, (count) * sizeof((p)[0]))
void log_error(const char *fmt, ...) __attribute__ ((format (printf, 1, 2)));
#define fatal(...) { log_error(__VA_ARGS__); exit(EXIT_FAILURE); }
static inline void cleanup_free(void *p) { free(*(void**)p); }
#define FREE_AFTER_FUNCTION __attribute__((cleanup(cleanup_free)))
static inline void cleanup_clear(void *p) { Py_XDECREF((PyObject *)p); }
#define DECREF_AFTER_FUNCTION __attribute__((cleanup(cleanup_clear)))
#define FREE_BUFFER_AFTER_FUNCTION __attribute__((cleanup(PyBuffer_Release)))

typedef unsigned long long id_type;
typedef uint32_t char_type;
typedef uint32_t color_type;
typedef uint16_t hyperlink_id_type;
typedef int key_type;
#define HYPERLINK_MAX_NUMBER UINT16_MAX
typedef uint16_t combining_type;
typedef uint16_t glyph_index;
typedef uint32_t pixel;
typedef unsigned int index_type;
typedef uint16_t sprite_index;
typedef enum CursorShapes { NO_CURSOR_SHAPE, CURSOR_BLOCK, CURSOR_BEAM, CURSOR_UNDERLINE, NUM_OF_CURSOR_SHAPES } CursorShape;
typedef enum { DISABLE_LIGATURES_NEVER, DISABLE_LIGATURES_CURSOR, DISABLE_LIGATURES_ALWAYS } DisableLigature;

#define ERROR_PREFIX "[PARSE ERROR]"
typedef enum MouseTrackingModes { NO_TRACKING, BUTTON_MODE, MOTION_MODE, ANY_MODE } MouseTrackingMode;
typedef enum MouseTrackingProtocols { NORMAL_PROTOCOL, UTF8_PROTOCOL, SGR_PROTOCOL, URXVT_PROTOCOL, SGR_PIXEL_PROTOCOL} MouseTrackingProtocol;
typedef enum MouseShapes { BEAM, HAND, ARROW } MouseShape;
typedef enum { NONE, MENUBAR, WINDOW, ALL } WindowTitleIn;
typedef enum { TILING, SCALED, MIRRORED, CLAMPED, CENTER_CLAMPED, CENTER_SCALED } BackgroundImageLayout;
typedef struct ImageAnchorPosition {
    float canvas_x, canvas_y, image_x, image_y;
} ImageAnchorPosition;

#define MAX_CHILDREN 512
#define BLANK_CHAR 0
#define COL_MASK 0xFFFFFFFF
#define DECORATION_FG_CODE 58
#define CHAR_IS_BLANK(ch) ((ch) == 32 || (ch) == 0)

// PUA character used as an image placeholder.
#define IMAGE_PLACEHOLDER_CHAR 0x10EEEE

#define FG 1
#define BG 2

#define COPY_CELL(src, s, dest, d) \
    (dest)->cpu_cells[d] = (src)->cpu_cells[s]; (dest)->gpu_cells[d] = (src)->gpu_cells[s];

#define COPY_SELF_CELL(s, d) COPY_CELL(self, s, self, d)

#define METHOD(name, arg_type) {#name, (PyCFunction)name, arg_type, name##_doc},
#define METHODB(name, arg_type) {#name, (PyCFunction)name, arg_type, ""}

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
#define IGNORE_PEDANTIC_WARNINGS _Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wpedantic\"")
#define END_IGNORE_PEDANTIC_WARNINGS _Pragma("clang diagnostic pop")
#define ALLOW_UNUSED_RESULT _Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wunused-result\"")
#define END_ALLOW_UNUSED_RESULT _Pragma("clang diagnostic pop")
#else
#define IGNORE_PEDANTIC_WARNINGS _Pragma("GCC diagnostic ignored \"-Wpedantic\"")
#define END_IGNORE_PEDANTIC_WARNINGS _Pragma("GCC diagnostic pop")
#define ALLOW_UNUSED_RESULT _Pragma("GCC diagnostic ignored \"-Wunused-result\"")
#define END_ALLOW_UNUSED_RESULT _Pragma("GCC diagnostic pop")
#endif
#define START_ALLOW_CASE_RANGE IGNORE_PEDANTIC_WARNINGS
#define END_ALLOW_CASE_RANGE END_IGNORE_PEDANTIC_WARNINGS
#define BIT_MASK(__TYPE__, __ONE_COUNT__) \
    (((__TYPE__) (-((__ONE_COUNT__) != 0))) \
    & (((__TYPE__) -1) >> ((sizeof(__TYPE__) * CHAR_BIT) - (__ONE_COUNT__))))
#define ADD_TYPE(which) \
    if (PyType_Ready(&which##_Type) < 0) return false; \
    if (PyModule_AddObject(module, #which, (PyObject *)&which##_Type) != 0) return false; \
    Py_INCREF(&which##_Type);


typedef enum UTF8State { UTF8_ACCEPT = 0, UTF8_REJECT = 1} UTF8State;

typedef struct {
    uint32_t left, top, right, bottom;
} Region;

typedef union CellAttrs {
    struct {
        uint16_t width : 2;
        uint16_t decoration : 3;
        uint16_t bold : 1;
        uint16_t italic : 1;
        uint16_t reverse : 1;
        uint16_t strike : 1;
        uint16_t dim : 1;
        uint16_t mark : 2;
        uint16_t next_char_was_wrapped : 1;
    };
    uint16_t val;
} CellAttrs;
#define MARK_MASK (3u)
#define WIDTH_MASK (3u)
#define DECORATION_MASK (7u)
#define NUM_UNDERLINE_STYLES (5u)
#define SGR_MASK (~(((CellAttrs){.width=WIDTH_MASK, .mark=MARK_MASK, .next_char_was_wrapped=1}).val))

typedef struct {
    color_type fg, bg, decoration_fg;
    sprite_index sprite_x, sprite_y, sprite_z;
    CellAttrs attrs;
} GPUCell;
static_assert(sizeof(GPUCell) == 20, "Fix the ordering of GPUCell");

typedef struct {
    char_type ch;
    hyperlink_id_type hyperlink_id;
    combining_type cc_idx[3];
} CPUCell;
static_assert(sizeof(CPUCell) == 12, "Fix the ordering of CPUCell");

typedef enum { UNKNOWN_PROMPT_KIND = 0, PROMPT_START = 1, SECONDARY_PROMPT = 2, OUTPUT_START = 3 } PromptKind;
typedef union LineAttrs {
    struct {
        uint8_t is_continued : 1;
        uint8_t has_dirty_text : 1;
        uint8_t has_image_placeholders : 1;
        PromptKind prompt_kind : 2;
    };
    uint8_t val;
} LineAttrs ;

typedef struct {
    PyObject_HEAD

    GPUCell *gpu_cells;
    CPUCell *cpu_cells;
    index_type xnum, ynum;
    bool needs_free;
    LineAttrs attrs;
} Line;


typedef struct {
    PyObject_HEAD

    GPUCell *gpu_cell_buf;
    CPUCell *cpu_cell_buf;
    index_type xnum, ynum, *line_map, *scratch;
    LineAttrs *line_attrs;
    Line *line;
} LineBuf;

typedef struct {
    GPUCell *gpu_cells;
    CPUCell *cpu_cells;
    LineAttrs *line_attrs;
} HistoryBufSegment;

typedef struct {
    void *ringbuf;
    size_t maximum_size;
    bool rewrap_needed;
} PagerHistoryBuf;

typedef struct {int x;} *HYPERLINK_POOL_HANDLE;
typedef struct {
    Py_UCS4 *buf;
    size_t len, capacity;
    HYPERLINK_POOL_HANDLE hyperlink_pool;
    hyperlink_id_type active_hyperlink_id;
} ANSIBuf;

typedef struct {
    PyObject_HEAD

    index_type xnum, ynum, num_segments;
    HistoryBufSegment *segments;
    PagerHistoryBuf *pagerhist;
    Line *line;
    index_type start_of_data, count;
} HistoryBuf;

typedef struct {
    PyObject_HEAD

    bool bold, italic, reverse, strikethrough, dim, non_blinking;
    unsigned int x, y;
    uint8_t decoration;
    CursorShape shape;
    color_type fg, bg, decoration_fg;
} Cursor;

typedef struct {
    bool is_visible, is_focused;
    CursorShape shape;
    unsigned int x, y;
} CursorRenderInfo;

typedef enum DynamicColorType {
    COLOR_NOT_SET, COLOR_IS_SPECIAL, COLOR_IS_INDEX, COLOR_IS_RGB
} DynamicColorType;

typedef union DynamicColor {
    struct {
        color_type rgb: 24;
        DynamicColorType type: 8;
    };
    color_type val;
} DynamicColor;

typedef struct {
    DynamicColor default_fg, default_bg, cursor_color, cursor_text_color, highlight_fg, highlight_bg, visual_bell_color;
} DynamicColors;


typedef struct {
    DynamicColors dynamic_colors;
    uint32_t color_table[256];
} ColorStackEntry;

typedef struct {
    PyObject_HEAD

    bool dirty;
    uint32_t color_table[256];
    uint32_t orig_color_table[256];
    ColorStackEntry *color_stack;
    unsigned int color_stack_idx, color_stack_sz;
    DynamicColors configured, overridden;
    color_type mark_foregrounds[MARK_MASK+1], mark_backgrounds[MARK_MASK+1];
} ColorProfile;

typedef struct {
    unsigned int width, height;
} CellPixelSize;

typedef struct {int x;} *SPRITE_MAP_HANDLE;
#define FONTS_DATA_HEAD SPRITE_MAP_HANDLE sprite_map; double logical_dpi_x, logical_dpi_y, font_sz_in_pts; unsigned int cell_width, cell_height;
typedef struct {FONTS_DATA_HEAD} *FONTS_DATA_HANDLE;

#define PARSER_BUF_SZ (8 * 1024)
#define READ_BUF_SZ (1024*1024)

#define clear_sprite_position(cell) (cell).sprite_x = 0; (cell).sprite_y = 0; (cell).sprite_z = 0;

#define ensure_space_for(base, array, type, num, capacity, initial_cap, zero_mem) \
    if ((base)->capacity < num) { \
        size_t _newcap = MAX((size_t)initial_cap, MAX(2 * (base)->capacity, (size_t)num)); \
        (base)->array = realloc((base)->array, sizeof(type) * _newcap); \
        if ((base)->array == NULL) fatal("Out of memory while ensuring space for %zu elements in array of %s", (size_t)num, #type); \
        if (zero_mem) memset((base)->array + (base)->capacity, 0, sizeof(type) * (_newcap - (base)->capacity)); \
        (base)->capacity = _newcap; \
    }

#define remove_i_from_array(array, i, count) { \
    (count)--; \
    if ((i) < (count)) { \
        memmove((array) + (i), (array) + (i) + 1, sizeof((array)[0]) * ((count) - (i))); \
    }}

static inline CellAttrs
cursor_to_attrs(const Cursor *c, const uint16_t width) {
    CellAttrs ans = {
        .width=width, .decoration=c->decoration, .bold=c->bold, .italic=c->italic, .reverse=c->reverse,
        .strike=c->strikethrough, .dim=c->dim};
    return ans;
}

static inline void
attrs_to_cursor(const CellAttrs attrs, Cursor *c) {
    c->decoration = attrs.decoration; c->bold = attrs.bold;  c->italic = attrs.italic;
    c->reverse = attrs.reverse; c->strikethrough = attrs.strike; c->dim = attrs.dim;
}


// Global functions
const char* base64_decode(const uint32_t *src, size_t src_sz, uint8_t *dest, size_t dest_capacity, size_t *dest_sz);
Line* alloc_line(void);
Cursor* alloc_cursor(void);
LineBuf* alloc_linebuf(unsigned int, unsigned int);
HistoryBuf* alloc_historybuf(unsigned int, unsigned int, unsigned int);
ColorProfile* alloc_color_profile(void);
void copy_color_profile(ColorProfile*, ColorProfile*);
PyObject* create_256_color_table(void);
PyObject* parse_bytes_dump(PyObject UNUSED *, PyObject *);
PyObject* parse_bytes(PyObject UNUSED *, PyObject *);
void cursor_reset(Cursor*);
Cursor* cursor_copy(Cursor*);
void cursor_copy_to(Cursor *src, Cursor *dest);
void cursor_reset_display_attrs(Cursor*);
void cursor_from_sgr(Cursor *self, int *params, unsigned int count);
void apply_sgr_to_cells(GPUCell *first_cell, unsigned int cell_count, int *params, unsigned int count);
const char* cell_as_sgr(const GPUCell *, const GPUCell *);
const char* cursor_as_sgr(const Cursor *);

PyObject* cm_thread_write(PyObject *self, PyObject *args);
bool schedule_write_to_child(unsigned long id, unsigned int num, ...);
bool schedule_write_to_child_python(unsigned long id, const char *prefix, PyObject* tuple_of_str_or_bytes, const char *suffix);
bool set_iutf8(int, bool);

DynamicColor colorprofile_to_color(ColorProfile *self, DynamicColor entry, DynamicColor defval);
color_type
colorprofile_to_color_with_fallback(ColorProfile *self, DynamicColor entry, DynamicColor defval, DynamicColor fallback, DynamicColor falback_defval);
void copy_color_table_to_buffer(ColorProfile *self, color_type *address, int offset, size_t stride);
bool colorprofile_push_colors(ColorProfile*, unsigned int);
bool colorprofile_pop_colors(ColorProfile*, unsigned int);
void colorprofile_report_stack(ColorProfile*, unsigned int*, unsigned int*);

void set_mouse_cursor(MouseShape);
void enter_event(void);
void mouse_event(const int, int, int);
void focus_in_event(void);
void scroll_event(double, double, int, int);
void on_key_input(GLFWkeyevent *ev);
void request_window_attention(id_type, bool);
#ifndef __APPLE__
void play_canberra_sound(const char *which_sound, const char *event_id, bool is_path, const char *role, const char *theme_name);
#endif
SPRITE_MAP_HANDLE alloc_sprite_map(unsigned int, unsigned int);
SPRITE_MAP_HANDLE free_sprite_map(SPRITE_MAP_HANDLE);
const char* get_hyperlink_for_id(const HYPERLINK_POOL_HANDLE, hyperlink_id_type id, bool only_url);
void log_event(const char *format, ...) __attribute__((format(printf, 1, 2)));
