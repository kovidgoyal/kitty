/*
 * screen.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT PyModule_AddIntMacro(module, SCROLL_LINE); PyModule_AddIntMacro(module, SCROLL_PAGE); PyModule_AddIntMacro(module, SCROLL_FULL);

#include "state.h"
#include "lineops.h"
#include "screen.h"
#include <structmember.h>
#include <limits.h>
#include <sys/types.h>                                                                                          
#include <sys/stat.h>
#include <fcntl.h>
#include "unicode-data.h"
#include "modes.h"
#include "wcwidth9.h"

static const ScreenModes empty_modes = {0, .mDECAWM=true, .mDECTCEM=true, .mDECARM=true};
static Selection EMPTY_SELECTION = {0};

// Constructor/destructor {{{

static inline void 
init_tabstops(bool *tabstops, index_type count) {
    // In terminfo we specify the number of initial tabstops (it) as 8
    for (unsigned int t=0; t < count; t++) {
        tabstops[t] = (t+1) % 8 == 0 ? true : false;
    }
}

#define RESET_CHARSETS \
        self->g0_charset = translation_table(0); \
        self->g1_charset = self->g0_charset; \
        self->g_charset = self->g0_charset; \
        self->utf8_state = 0; \
        self->utf8_codepoint = 0; \
        self->use_latin1 = false; 
#define CALLBACK(...) \
    if (self->callbacks != Py_None) { \
        PyObject *callback_ret = PyObject_CallMethod(self->callbacks, __VA_ARGS__); \
        if (callback_ret == NULL) PyErr_Print(); else Py_DECREF(callback_ret); \
    }

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Screen *self;
    int ret = 0;
    PyObject *callbacks = Py_None;
    unsigned int columns=80, lines=24, scrollback=0;
    if (!PyArg_ParseTuple(args, "|OIII", &callbacks, &lines, &columns, &scrollback)) return NULL;

    self = (Screen *)type->tp_alloc(type, 0);
    if (self != NULL) {
        if ((ret = pthread_mutex_init(&self->read_buf_lock, NULL)) != 0) {
            Py_CLEAR(self); PyErr_Format(PyExc_RuntimeError, "Failed to create Screen read_buf_lock mutex: %s", strerror(ret));
            return NULL;
        }
        if ((ret = pthread_mutex_init(&self->write_buf_lock, NULL)) != 0) {
            Py_CLEAR(self); PyErr_Format(PyExc_RuntimeError, "Failed to create Screen write_buf_lock mutex: %s", strerror(ret));
            return NULL;
        }
        self->columns = columns; self->lines = lines;
        self->write_buf = PyMem_RawMalloc(BUFSIZ);
        if (self->write_buf == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
        self->write_buf_sz = BUFSIZ;
        self->modes = empty_modes;
        self->is_dirty = true;
        self->scroll_changed = false;
        self->margin_top = 0; self->margin_bottom = self->lines - 1;
        self->history_line_added_count = 0;
        RESET_CHARSETS;
        self->callbacks = callbacks; Py_INCREF(callbacks);
        self->cursor = alloc_cursor();
        self->color_profile = alloc_color_profile();
        self->main_linebuf = alloc_linebuf(lines, columns); self->alt_linebuf = alloc_linebuf(lines, columns);
        self->linebuf = self->main_linebuf;
        self->historybuf = alloc_historybuf(MAX(scrollback, lines), columns);
        self->main_tabstops = PyMem_Calloc(2 * self->columns, sizeof(bool));
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->main_tabstops == NULL || self->historybuf == NULL || self->color_profile == NULL) {
            Py_CLEAR(self); return NULL;
        }
        self->alt_tabstops = self->main_tabstops + self->columns * sizeof(bool);
        self->tabstops = self->main_tabstops;
        init_tabstops(self->main_tabstops, self->columns);
        init_tabstops(self->alt_tabstops, self->columns);
    }
    return (PyObject*) self;
}

void 
screen_reset(Screen *self) {
    if (self->linebuf == self->alt_linebuf) screen_toggle_screen_buffer(self);
    linebuf_clear(self->linebuf, BLANK_CHAR);
    self->modes = empty_modes;
#define RC(name) self->color_profile->overridden.name = 0
    RC(default_fg); RC(default_bg); RC(cursor_color); RC(highlight_fg); RC(highlight_bg);
#undef RC
    RESET_CHARSETS;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_normal_keypad_mode(self);
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    cursor_reset(self->cursor);
    self->is_dirty = true;
    screen_cursor_position(self, 1, 1);
    set_dynamic_color(self, 110, NULL);
    set_dynamic_color(self, 111, NULL);
    set_color_table_color(self, 104, NULL);
}

static inline HistoryBuf* 
realloc_hb(HistoryBuf *old, unsigned int lines, unsigned int columns) {
    HistoryBuf *ans = alloc_historybuf(lines, columns);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    historybuf_rewrap(old, ans);
    return ans;
}

static inline LineBuf* 
realloc_lb(LineBuf *old, unsigned int lines, unsigned int columns, int *cursor_y, HistoryBuf *hb) {
    LineBuf *ans = alloc_linebuf(lines, columns);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    linebuf_rewrap(old, ans, cursor_y, hb);
    return ans;
}

static bool 
screen_resize(Screen *self, unsigned int lines, unsigned int columns) {
    lines = MAX(1, lines); columns = MAX(1, columns);

    bool is_main = self->linebuf == self->main_linebuf, is_x_shrink = columns < self->columns;
    int cursor_y = -1; unsigned int cursor_x = self->cursor->x;
    HistoryBuf *nh = realloc_hb(self->historybuf, self->historybuf->ynum, columns);
    if (nh == NULL) return false;
    Py_CLEAR(self->historybuf); self->historybuf = nh;
    LineBuf *n = realloc_lb(self->main_linebuf, lines, columns, &cursor_y, self->historybuf);
    if (n == NULL) return false;
    Py_CLEAR(self->main_linebuf); self->main_linebuf = n;
    bool index_after_resize = false;
    if (is_main) {
        index_type cy = MIN(self->cursor->y, lines - 1);
        linebuf_init_line(self->main_linebuf, cy);
        if (is_x_shrink && (self->main_linebuf->continued_map[cy] || line_length(self->main_linebuf->line) > columns)) {
            // If the client is in line drawing mode, it will redraw the cursor
            // line, this can cause rendering artifacts, so ensure that the
            // cursor is on a new line
            index_after_resize = true;
        }
        self->cursor->y = MAX(0, cursor_y);
    }
    cursor_y = -1;
    n = realloc_lb(self->alt_linebuf, lines, columns, &cursor_y, NULL);
    if (n == NULL) return false;
    Py_CLEAR(self->alt_linebuf); self->alt_linebuf = n;
    if (!is_main) self->cursor->y = MAX(0, cursor_y);
    self->linebuf = is_main ? self->main_linebuf : self->alt_linebuf;
    if (is_x_shrink && cursor_x >= columns) self->cursor->x = columns - 1;

    self->lines = lines; self->columns = columns;
    self->margin_top = 0; self->margin_bottom = self->lines - 1;

    PyMem_Free(self->main_tabstops);
    self->main_tabstops = PyMem_Calloc(2*self->columns, sizeof(bool));
    if (self->main_tabstops == NULL) { PyErr_NoMemory(); return false; }
    self->alt_tabstops = self->main_tabstops + self->columns * sizeof(bool);
    self->tabstops = self->main_tabstops;
    init_tabstops(self->main_tabstops, self->columns);
    init_tabstops(self->alt_tabstops, self->columns);
    self->is_dirty = true;
    self->selection = EMPTY_SELECTION;
    if (index_after_resize) screen_index(self);

    return true;
}


static void
screen_refresh_sprite_positions(Screen *self) {
    linebuf_refresh_sprite_positions(self->main_linebuf);
    linebuf_refresh_sprite_positions(self->alt_linebuf);
    historybuf_refresh_sprite_positions(self->historybuf);
}


static bool 
screen_change_scrollback_size(Screen *self, unsigned int size) {
    if (size != self->historybuf->ynum) return historybuf_resize(self->historybuf, size);
    return true;
}

static PyObject*
reset_callbacks(Screen *self) {
    Py_CLEAR(self->callbacks);
    self->callbacks = Py_None;
    Py_INCREF(self->callbacks);
    Py_RETURN_NONE;
}

static void
dealloc(Screen* self) {
    pthread_mutex_destroy(&self->read_buf_lock);
    pthread_mutex_destroy(&self->write_buf_lock);
    PyMem_RawFree(self->write_buf);
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->cursor); 
    Py_CLEAR(self->main_linebuf); 
    Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->historybuf);
    Py_CLEAR(self->color_profile);
    PyMem_Free(self->main_tabstops);
    Py_TYPE(self)->tp_free((PyObject*)self);
} // }}}

// Draw text {{{
 
void 
screen_change_charset(Screen *self, uint32_t which) {
    switch(which) {
        case 0:
            self->g_charset = self->g0_charset; break;
        case 1:
            self->g_charset = self->g1_charset; break;
    }
}

void 
screen_designate_charset(Screen *self, uint32_t which, uint32_t as) {
    bool change_g = false;
    switch(which) {
        case 0:
            change_g = self->g_charset == self->g0_charset;
            self->g0_charset = translation_table(as);
            if (change_g) self->g_charset = self->g0_charset;
            break;
        case 1:
            change_g = self->g_charset == self->g1_charset;
            self->g1_charset = translation_table(as);
            if (change_g) self->g_charset = self->g1_charset;
            break;
        // We dont care about default as this is guaranteed to only be called with correct which by the parser
    }
}

static int (*wcwidth_impl)(wchar_t) = wcwidth;

unsigned int 
safe_wcwidth(uint32_t ch) {
    int ans = wcwidth_impl(ch);
    if (ans < 0) ans = 1;
    return MIN(2, ans);
}

void
change_wcwidth(bool use9) {
    wcwidth_impl = (use9) ? wcwidth9 : wcwidth;
}


void
screen_draw(Screen *self, uint32_t och) {
    if (is_ignored_char(och)) return;
    uint32_t ch = och < 256 ? self->g_charset[och] : och;
    unsigned int char_width = safe_wcwidth(ch);
    if (self->columns - self->cursor->x < char_width) {
        if (self->modes.mDECAWM) {
            screen_carriage_return(self);
            screen_linefeed(self);
            self->linebuf->continued_map[self->cursor->y] = true;
        } else {
            self->cursor->x = self->columns - char_width;
        }
    }
    if (char_width > 0) {
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (self->modes.mIRM) {
            line_right_shift(self->linebuf->line, self->cursor->x, char_width);
        }
        line_set_char(self->linebuf->line, self->cursor->x, ch, char_width, self->cursor);
        self->cursor->x++;
        if (char_width == 2) {
            line_set_char(self->linebuf->line, self->cursor->x, 0, 0, self->cursor);
            self->cursor->x++;
        }
        self->is_dirty = true;
    } else if (is_combining_char(ch)) {
        if (self->cursor->x > 0) {
            linebuf_init_line(self->linebuf, self->cursor->y);
            line_add_combining_char(self->linebuf->line, ch, self->cursor->x - 1);
            self->is_dirty = true;
        } else if (self->cursor->y > 0) {
            linebuf_init_line(self->linebuf, self->cursor->y - 1);
            line_add_combining_char(self->linebuf->line, ch, self->columns - 1);
            self->is_dirty = true;
        }
    }
}

void
screen_align(Screen *self) {
    self->margin_top = 0; self->margin_bottom = self->lines - 1;
    screen_cursor_position(self, 1, 1);
    linebuf_clear(self->linebuf, 'E');
}

// }}}

// Graphics {{{

void screen_alignment_display(Screen *self) {
    // http://www.vt100.net/docs/vt510-rm/DECALN.html 
    screen_cursor_position(self, 1, 1);
    self->margin_top = 0; self->margin_bottom = self->columns - 1;
    for (unsigned int y = 0; y < self->linebuf->ynum; y++) {
        linebuf_init_line(self->linebuf, y);
        line_clear_text(self->linebuf->line, 0, self->linebuf->xnum, 'E');
    }
}

void select_graphic_rendition(Screen *self, unsigned int *params, unsigned int count) {
#define SET_COLOR(which) \
    if (i < count) { \
        attr = params[i++];\
        switch(attr) { \
            case 5: \
                if (i < count) \
                    self->cursor->which = (params[i++] & 0xFF) << 8 | 1; \
                break; \
            case 2: \
                if (i < count - 2) { \
                    r = params[i++] & 0xFF; \
                    g = params[i++] & 0xFF; \
                    b = params[i++] & 0xFF; \
                    self->cursor->which = r << 24 | g << 16 | b << 8 | 2; \
                }\
                break; \
        } \
    } \
    break;

    unsigned int i = 0, attr;
    uint8_t r, g, b;
    if (!count) { params[0] = 0; count = 1; }
    while (i < count) {
        attr = params[i++];
        switch(attr) {
            case 0:
                cursor_reset_display_attrs(self->cursor);  break;
            case 1:
                self->cursor->bold = true;  break;
            case 3:
                self->cursor->italic = true;  break;
            case 4:
                self->cursor->decoration = 1;  break;
            case UNDERCURL_CODE:
                self->cursor->decoration = 2;  break;
            case 7:
                self->cursor->reverse = true;  break;
            case 9:
                self->cursor->strikethrough = true;  break;
            case 22:
                self->cursor->bold = false;  break;
            case 23:
                self->cursor->italic = false;  break;
            case 24:
                self->cursor->decoration = 0;  break;
            case 27:
                self->cursor->reverse = false;  break;
            case 29:
                self->cursor->strikethrough = false;  break;
START_ALLOW_CASE_RANGE
            case 30 ... 37:
                self->cursor->fg = ((attr - 30) << 8) | 1;  break;
            case 38: 
                SET_COLOR(fg);
            case 39:
                self->cursor->fg = 0;  break;
            case 40 ... 47:
                self->cursor->bg = ((attr - 40) << 8) | 1;  break;
            case 48: 
                SET_COLOR(bg);
            case 49:
                self->cursor->bg = 0;  break;
            case 90 ... 97:
                self->cursor->fg = ((attr - 90 + 8) << 8) | 1;  break;
            case 100 ... 107:
                self->cursor->bg = ((attr - 100 + 8) << 8) | 1;  break;
END_ALLOW_CASE_RANGE
            case DECORATION_FG_CODE:
                SET_COLOR(decoration_fg);
            case DECORATION_FG_CODE + 1:
                self->cursor->decoration_fg = 0; break;
        }
    }
}

// }}}

// Modes {{{


void 
screen_toggle_screen_buffer(Screen *self) {
    bool to_alt = self->linebuf == self->main_linebuf;
    if (to_alt) {
        linebuf_clear(self->alt_linebuf, BLANK_CHAR);
        screen_save_cursor(self);
        self->linebuf = self->alt_linebuf;
        self->tabstops = self->alt_tabstops;
        screen_cursor_position(self, 1, 1);
        cursor_reset(self->cursor);
    } else {
        self->linebuf = self->main_linebuf;
        self->tabstops = self->main_tabstops;
        screen_restore_cursor(self);
    }
    CALLBACK("buf_toggled", "O", self->linebuf == self->main_linebuf ? Py_True : Py_False);
    self->is_dirty = true;
}

void screen_normal_keypad_mode(Screen UNUSED *self) {} // Not implemented as this is handled by the GUI
void screen_alternate_keypad_mode(Screen UNUSED *self) {}  // Not implemented as this is handled by the GUI

static inline void 
set_mode_from_const(Screen *self, unsigned int mode, bool val) {
#define SIMPLE_MODE(name) \
    case name: \
        self->modes.m##name = val; break;

#define MOUSE_MODE(name, attr, value) \
    case name: \
        self->modes.attr = val ? value : 0; break;

    bool private;
    switch(mode) {
        SIMPLE_MODE(LNM)
        SIMPLE_MODE(IRM)
        SIMPLE_MODE(DECARM)
        SIMPLE_MODE(BRACKETED_PASTE)
        SIMPLE_MODE(EXTENDED_KEYBOARD)
        SIMPLE_MODE(FOCUS_TRACKING)
        MOUSE_MODE(MOUSE_BUTTON_TRACKING, mouse_tracking_mode, BUTTON_MODE)
        MOUSE_MODE(MOUSE_MOTION_TRACKING, mouse_tracking_mode, MOTION_MODE)
        MOUSE_MODE(MOUSE_MOVE_TRACKING, mouse_tracking_mode, ANY_MODE)
        MOUSE_MODE(MOUSE_UTF8_MODE, mouse_tracking_protocol, UTF8_PROTOCOL)
        MOUSE_MODE(MOUSE_SGR_MODE, mouse_tracking_protocol, SGR_PROTOCOL)
        MOUSE_MODE(MOUSE_URXVT_MODE, mouse_tracking_protocol, URXVT_PROTOCOL)

        case DECSCLM:
        case DECNRCM:
            break;  // we ignore these modes
        case DECCKM:
            self->modes.mDECCKM = val; 
            break;
        case DECTCEM: 
            self->modes.mDECTCEM = val; 
            break;
        case DECSCNM: 
            // Render screen in reverse video
            if (self->modes.mDECSCNM != val) {
                self->modes.mDECSCNM = val; 
                self->is_dirty = true;
            }
            break;
        case DECOM: 
            self->modes.mDECOM = val; 
            // According to `vttest`, DECOM should also home the cursor, see
            // vttest/main.c:303.
            screen_cursor_position(self, 1, 1);
            break;
        case DECAWM: 
            self->modes.mDECAWM = val; break;
        case DECCOLM: 
            // When DECCOLM mode is set, the screen is erased and the cursor
            // moves to the home position.
            self->modes.mDECCOLM = val; 
            screen_erase_in_display(self, 2, false);
            screen_cursor_position(self, 1, 1);
            break;
        case CONTROL_CURSOR_BLINK:
            self->cursor->blink = val; 
            break;
        case ALTERNATE_SCREEN:
            if (val && self->linebuf == self->main_linebuf) screen_toggle_screen_buffer(self);
            else if (!val && self->linebuf != self->main_linebuf) screen_toggle_screen_buffer(self);
            break;  
        default:
            private = mode >= 1 << 5;
            if (private) mode >>= 5;
            fprintf(stderr, "%s %s %u %s\n", ERROR_PREFIX, "Unsupported screen mode: ", mode, private ? "(private)" : "");
    }
#undef SIMPLE_MODE
#undef MOUSE_MODE
}

void screen_set_mode(Screen *self, unsigned int mode) {
    set_mode_from_const(self, mode, true);
}

void screen_reset_mode(Screen *self, unsigned int mode) {
    set_mode_from_const(self, mode, false);
}

// }}}

// Cursor {{{

unsigned long
screen_current_char_width(Screen *self) {
    unsigned long ans = 1;
    if (self->cursor->x < self->columns - 1 && self->cursor->y < self->lines) {
        ans = linebuf_char_width_at(self->linebuf, self->cursor->x, self->cursor->y);
    }
    return ans;
}

bool
screen_is_cursor_visible(Screen *self) {
    return self->modes.mDECTCEM;
}

void 
screen_backspace(Screen *self) {
    screen_cursor_back(self, 1, -1);
}

void 
screen_tab(Screen *self) {
    // Move to the next tab space, or the end of the screen if there aren't anymore left.
    unsigned int found = 0;
    for (unsigned int i = self->cursor->x + 1; i < self->columns; i++) {
        if (self->tabstops[i]) { found = i; break; }
    }
    if (!found) found = self->columns - 1;
    if (found != self->cursor->x) {
        self->cursor->x = found;
    }
}

void 
screen_backtab(Screen *self, unsigned int count) {
    // Move back count tabs
    if (!count) count = 1;
    int i;
    while (count > 0 && self->cursor->x > 0) {
        count--;
        for (i = self->cursor->x - 1; i >= 0; i--) {
            if (self->tabstops[i]) { self->cursor->x = i; break; }
        }
        if (i <= 0) self->cursor->x = 0;
    }
}

void 
screen_clear_tab_stop(Screen *self, unsigned int how) {
    switch(how) {
        case 0:
            if (self->cursor->x < self->columns) self->tabstops[self->cursor->x] = false;
            break;
        case 2:
            break;  // no-op
        case 3:
            for (unsigned int i = 0; i < self->columns; i++) self->tabstops[i] = false;
            break;
        default:
            fprintf(stderr, "%s %s %u\n", ERROR_PREFIX, "Unsupported clear tab stop mode: ", how);
            break;
    }
}

void 
screen_set_tab_stop(Screen *self) {
    if (self->cursor->x < self->columns)
        self->tabstops[self->cursor->x] = true;
}

void 
screen_cursor_back(Screen *self, unsigned int count/*=1*/, int move_direction/*=-1*/) {
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->x) self->cursor->x = 0;
    else self->cursor->x += move_direction * count;
    screen_ensure_bounds(self, false);
}

void 
screen_cursor_forward(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_back(self, count, 1);
}

void 
screen_cursor_up(Screen *self, unsigned int count/*=1*/, bool do_carriage_return/*=false*/, int move_direction/*=-1*/) {
    if (count == 0) count = 1;
    if (move_direction < 0 && count > self->cursor->y) self->cursor->y = 0;
    else self->cursor->y += move_direction * count;
    screen_ensure_bounds(self, true);
    if (do_carriage_return) self->cursor->x = 0;
}

void 
screen_cursor_up1(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, true, -1);
}

void 
screen_cursor_down(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, false, 1);
}

void 
screen_cursor_down1(Screen *self, unsigned int count/*=1*/) {
    screen_cursor_up(self, count, true, 1);
}

void 
screen_cursor_to_column(Screen *self, unsigned int column) {
    unsigned int x = MAX(column, 1) - 1;
    if (x != self->cursor->x) {
        self->cursor->x = x;
        screen_ensure_bounds(self, false);
    }
}

#define INDEX_UP \
    linebuf_index(self->linebuf, top, bottom); \
    if (self->linebuf == self->main_linebuf && bottom == self->lines - 1) { \
        /* Only add to history when no page margins have been set */ \
        linebuf_init_line(self->linebuf, bottom); \
        historybuf_add_line(self->historybuf, self->linebuf->line); \
        self->history_line_added_count++; \
    } \
    linebuf_clear_line(self->linebuf, bottom); \
    self->is_dirty = true;

void 
screen_index(Screen *self) {
    // Move cursor down one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == bottom) {
        INDEX_UP;
    } else screen_cursor_down(self, 1);
}

void 
screen_scroll(Screen *self, unsigned int count) {
    // Scroll the screen up by count lines, not moving the cursor
    count = MIN(self->lines, count);
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    while (count > 0) {
        count--;
        INDEX_UP;
    }
}

#define INDEX_DOWN \
    linebuf_reverse_index(self->linebuf, top, bottom); \
    linebuf_clear_line(self->linebuf, top); \
    self->is_dirty = true;

void 
screen_reverse_index(Screen *self) {
    // Move cursor up one line, scrolling screen if needed
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (self->cursor->y == top) {
        INDEX_DOWN;
    } else screen_cursor_up(self, 1, false, -1);
}

void 
screen_reverse_scroll(Screen *self, unsigned int count) {
    // Scroll the screen down by count lines, not moving the cursor
    count = MIN(self->lines, count);
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    while (count > 0) {
        count--;
        INDEX_DOWN;
    }
}


void 
screen_carriage_return(Screen *self) {
    if (self->cursor->x != 0) {
        self->cursor->x = 0;
    }
}

void 
screen_linefeed(Screen *self) {
    screen_index(self);
    if (self->modes.mLNM) screen_carriage_return(self);
    screen_ensure_bounds(self, false);
}

static inline Savepoint* 
savepoints_push(SavepointBuffer *self) {
    Savepoint *ans = self->buf + ((self->start_of_data + self->count) % SAVEPOINTS_SZ);
    if (self->count == SAVEPOINTS_SZ) self->start_of_data = (self->start_of_data + 1) % SAVEPOINTS_SZ;
    else self->count++;
    return ans;
}

static inline Savepoint* 
savepoints_pop(SavepointBuffer *self) {
    if (self->count == 0) return NULL;
    self->count--;
    return self->buf + ((self->start_of_data + self->count) % SAVEPOINTS_SZ);
}

#define COPY_CHARSETS(self, sp) \
    sp->utf8_state = self->utf8_state; \
    sp->utf8_codepoint = self->utf8_codepoint; \
    sp->g0_charset = self->g0_charset; \
    sp->g1_charset = self->g1_charset; \
    sp->g_charset = self->g_charset; \
    sp->use_latin1 = self->use_latin1;

void 
screen_save_cursor(Screen *self) {
    SavepointBuffer *pts = self->linebuf == self->main_linebuf ? &self->main_savepoints : &self->alt_savepoints;
    Savepoint *sp = savepoints_push(pts);
    cursor_copy_to(self->cursor, &(sp->cursor));
    sp->mDECOM = self->modes.mDECOM;
    sp->mDECAWM = self->modes.mDECAWM;
    sp->mDECSCNM = self->modes.mDECSCNM;
    COPY_CHARSETS(self, sp);
}

void 
screen_restore_cursor(Screen *self) {
    SavepointBuffer *pts = self->linebuf == self->main_linebuf ? &self->main_savepoints : &self->alt_savepoints;
    Savepoint *sp = savepoints_pop(pts);
    if (sp == NULL) {
        screen_cursor_position(self, 1, 1);
        screen_reset_mode(self, DECOM);
        RESET_CHARSETS;
        screen_reset_mode(self, DECSCNM);
    } else {
        COPY_CHARSETS(sp, self);
        set_mode_from_const(self, DECOM, sp->mDECOM);
        set_mode_from_const(self, DECAWM, sp->mDECAWM);
        set_mode_from_const(self, DECSCNM, sp->mDECSCNM);
        cursor_copy_to(&(sp->cursor), self->cursor);
        screen_ensure_bounds(self, false);
    }
}

void 
screen_ensure_bounds(Screen *self, bool force_use_margins/*=false*/) {
    unsigned int top, bottom;
    if (force_use_margins || self->modes.mDECOM) {
        top = self->margin_top; bottom = self->margin_bottom;
    } else {
        top = 0; bottom = self->lines - 1;
    }
    self->cursor->x = MIN(self->cursor->x, self->columns - 1);
    self->cursor->y = MAX(top, MIN(self->cursor->y, bottom));
}

void 
screen_cursor_position(Screen *self, unsigned int line, unsigned int column) {
    line = (line == 0 ? 1 : line) - 1;
    column = (column == 0 ? 1: column) - 1;
    if (self->modes.mDECOM) {
        line += self->margin_top;
        line = MAX(self->margin_top, MIN(line, self->margin_bottom));
    }
    self->cursor->x = column; self->cursor->y = line;
    screen_ensure_bounds(self, false);
}

void 
screen_cursor_to_line(Screen *self, unsigned int line) {
    screen_cursor_position(self, line, self->cursor->x + 1);
}

// }}}

// Editing {{{

void screen_erase_in_line(Screen *self, unsigned int how, bool private) {
    /*Erases a line in a specific way.

        :param int how: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of line, including cursor
              position.
            * ``1`` -- Erases from beginning of line to cursor,
              including cursor position.
            * ``2`` -- Erases complete line.
        :param bool private: when ``True`` character attributes are left
                             unchanged.
        */
    unsigned int s = 0, n = 0;
    switch(how) {
        case 0:
            s = self->cursor->x;
            n = self->columns - self->cursor->x;
            break;
        case 1:
            n = self->cursor->x + 1;
            break;
        case 2:
            n = self->columns;
            break;
        default:
            break;
    }
    if (n > 0) {
        linebuf_init_line(self->linebuf, self->cursor->y);
        if (private) {
            line_clear_text(self->linebuf->line, s, n, BLANK_CHAR);
        } else {
            line_apply_cursor(self->linebuf->line, self->cursor, s, n, true);
        }
        self->is_dirty = true;
    }
}

void screen_erase_in_display(Screen *self, unsigned int how, bool private) {
    /* Erases display in a specific way.

        :param int how: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
        :param bool private: when ``True`` character attributes are left unchanged
    */
    unsigned int a, b;
    switch(how) {
        case 0:
            a = self->cursor->y + 1; b = self->lines; break;
        case 1:
            a = 0; b = self->cursor->y; break;
        case 2:
            a = 0; b = self->lines; break;
        default:
            return;
    }
    if (b > a) {
        for (unsigned int i=a; i < b; i++) {
            linebuf_init_line(self->linebuf, i);
            if (private) {
                line_clear_text(self->linebuf->line, 0, self->columns, BLANK_CHAR);
            } else {
                line_apply_cursor(self->linebuf->line, self->cursor, 0, self->columns, true);
            }
        }
        self->is_dirty = true;
    }
    if (how != 2) {
        screen_erase_in_line(self, how, private);
    }
}

void screen_insert_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        linebuf_insert_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        screen_carriage_return(self);
    }
}

void screen_delete_lines(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        linebuf_delete_lines(self->linebuf, count, self->cursor->y, bottom);
        self->is_dirty = true;
        screen_carriage_return(self);
    }
}

void screen_insert_characters(Screen *self, unsigned int count) {
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        line_right_shift(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
        self->is_dirty = true;
    }
}

void screen_delete_characters(Screen *self, unsigned int count) {
    // Delete characters, later characters are moved left
    unsigned int top = self->margin_top, bottom = self->margin_bottom;
    if (count == 0) count = 1;
    if (top <= self->cursor->y && self->cursor->y <= bottom) {
        unsigned int x = self->cursor->x;
        unsigned int num = MIN(self->columns - x, count);
        linebuf_init_line(self->linebuf, self->cursor->y);
        left_shift_line(self->linebuf->line, x, num);
        line_apply_cursor(self->linebuf->line, self->cursor, self->columns - num, num, true);
        self->is_dirty = true;
    }
}

void screen_erase_characters(Screen *self, unsigned int count) {
    // Delete characters replacing them by spaces
    if (count == 0) count = 1;
    unsigned int x = self->cursor->x;
    unsigned int num = MIN(self->columns - x, count);
    linebuf_init_line(self->linebuf, self->cursor->y);
    line_apply_cursor(self->linebuf->line, self->cursor, x, num, true);
    self->is_dirty = true;
}

// }}}

// Device control {{{

void
screen_use_latin1(Screen *self, bool on) {
    self->use_latin1 = on; self->utf8_state = 0; self->utf8_codepoint = 0; 
    CALLBACK("use_utf8", "O", on ? Py_False : Py_True);
}

bool
screen_invert_colors(Screen *self) {
    bool inverted = false;
    if (self->start_visual_bell_at > 0) {
        if (monotonic() - self->start_visual_bell_at <= global_state.opts.visual_bell_duration) inverted = true;
        else self->start_visual_bell_at = 0;
    }
    if (self->modes.mDECSCNM) inverted = inverted ? false : true;
    return inverted;
}

void 
screen_bell(Screen UNUSED *self) {  
    if (global_state.opts.enable_audio_bell) {
        int fd = open("/dev/tty", O_WRONLY | O_CLOEXEC | O_NOCTTY);
        if (fd > 0) {
            static const char bell[2] = {7, 0};
            while(true) {
                if (write(fd, &bell, sizeof(bell)) == sizeof(bell)) break;
                if (errno == EINTR) continue;
                break;
            }
            close(fd);
        }
    }
    if (global_state.opts.visual_bell_duration > 0) {
        self->start_visual_bell_at = monotonic();
    }
    CALLBACK("bell", NULL);
} 

static inline void 
callback(const char *name, Screen *self, const char *data, unsigned int sz) {
    if (sz) { CALLBACK(name, "y#", data, sz); }
    else { CALLBACK(name, "y", data); }
}

void 
report_device_attributes(Screen *self, unsigned int mode, char start_modifier) {
    if (mode == 0) {
        switch(start_modifier) {
            case 0:
                callback("write_to_child", self, "\x1b[?62;c", 0);  // VT-220 with no extra info
                break;
            case '>':
                callback("write_to_child", self, "\x1b[>1;" xstr(PRIMARY_VERSION) ";" xstr(SECONDARY_VERSION) "c", 0);  // VT-220 + primary version + secondary version
                break;
        }
    }
}

void 
report_device_status(Screen *self, unsigned int which, bool private) {
    // We dont implement the private device status codes, since I haven't come
    // across any programs that use them
    unsigned int x, y;
    char buf[50] = {0};
    switch(which) {
        case 5:  // device status
            callback("write_to_child", self, "\x1b[0n", 0); 
            break;
        case 6:  // cursor position
            x = self->cursor->x; y = self->cursor->y;
            if (x >= self->columns) {
                if (y < self->lines - 1) { x = 0; y++; }
                else x--;
            }
            if (self->modes.mDECOM) y -= MAX(y, self->margin_top);
            x++; y++;  // 1-based indexing
            if (snprintf(buf, sizeof(buf) - 1, "\x1b[%s%u;%uR", (private ? "?": ""), y, x) > 0) callback("write_to_child", self, buf, 0);
            break;
    }
}

void 
report_mode_status(Screen *self, unsigned int which, bool private) {
    unsigned int q = private ? which << 5 : which;
    unsigned int ans = 0;
    char buf[50] = {0};
    switch(q) {
#define KNOWN_MODE(x) \
        case x: \
            ans = self->modes.m##x ? 1 : 2; break;
        KNOWN_MODE(LNM);
        KNOWN_MODE(IRM);
        KNOWN_MODE(DECTCEM);
        KNOWN_MODE(DECSCNM);
        KNOWN_MODE(DECOM);
        KNOWN_MODE(DECAWM);
        KNOWN_MODE(DECCOLM);
        KNOWN_MODE(DECARM);
        KNOWN_MODE(DECCKM);
        KNOWN_MODE(BRACKETED_PASTE);
        KNOWN_MODE(EXTENDED_KEYBOARD);
        KNOWN_MODE(FOCUS_TRACKING);
#undef KNOWN_MODE
        case STYLED_UNDERLINES:
            ans = 3; break;
    }
    if (snprintf(buf, sizeof(buf) - 1, "\x1b[%s%u;%u$y", (private ? "?" : ""), which, ans)) callback("write_to_child", self, buf, 0);
}

void 
screen_set_margins(Screen *self, unsigned int top, unsigned int bottom) {
    if (!top) top = 1;
    if (!bottom) bottom = self->lines;
    top = MIN(self->lines, top);
    bottom = MIN(self->lines, bottom);
    top--; bottom--;  // 1 based indexing
    if (bottom > top) {
        // Even though VT102 and VT220 require DECSTBM to ignore regions
        // of width less than 2, some programs (like aptitude for example)
        // rely on it. Practicality beats purity.
        self->margin_top = top; self->margin_bottom = bottom;
        // The cursor moves to the home position when the top and
        // bottom margins of the scrolling region (DECSTBM) changes.
        screen_cursor_position(self, 1, 1);
    }
}

void 
screen_set_cursor(Screen *self, unsigned int mode, uint8_t secondary) {
    uint8_t shape; bool blink;
    switch(secondary) {
        case 0: // DECLL
            break;
        case '"':  // DECCSA
            break;
        case ' ': // DECSCUSR
            shape = 0; blink = false;
            if (mode > 0) {
                blink = mode % 2;
                shape = (mode < 3) ? CURSOR_BLOCK : (mode < 5) ? CURSOR_UNDERLINE : (mode < 7) ? CURSOR_BEAM : NO_CURSOR_SHAPE;
            }
            if (shape != self->cursor->shape || blink != self->cursor->blink) {
                self->cursor->shape = shape; self->cursor->blink = blink;
            }
            break;
    }
}

void 
set_title(Screen *self, PyObject *title) {
    CALLBACK("title_changed", "O", title);
}

void set_icon(Screen *self, PyObject *icon) {
    CALLBACK("icon_changed", "O", icon);
}

void set_dynamic_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) { CALLBACK("set_dynamic_color", "Is", code, ""); }
    else { CALLBACK("set_dynamic_color", "IO", code, color); }
}

void set_color_table_color(Screen *self, unsigned int code, PyObject *color) {
    if (color == NULL) { CALLBACK("set_color_table_color", "Is", code, ""); }
    else { CALLBACK("set_color_table_color", "IO", code, color); }
}

void screen_request_capabilities(Screen *self, PyObject *q) {
    CALLBACK("request_capabilities", "O", q);
}

// }}}

// Rendering {{{
static inline void
update_line_data(Line *line, unsigned int dest_y, uint8_t *data) {
    size_t base = dest_y * line->xnum * sizeof(Cell);
    memcpy(data + base, line->cells, line->xnum * sizeof(Cell));
}


static inline void
screen_reset_dirty(Screen *self) {
    self->is_dirty = false;
    self->history_line_added_count = 0;
}

void
screen_update_cell_data(Screen *self, void *address, size_t UNUSED sz) {
    unsigned int history_line_added_count = self->history_line_added_count;
    bool selection_must_be_cleared = self->is_dirty ? true : false;
    if (self->scrolled_by) self->scrolled_by = MIN(self->scrolled_by + history_line_added_count, self->historybuf->count);
    screen_reset_dirty(self);
    self->scroll_changed = false;
    for (index_type y = 0; y < MIN(self->lines, self->scrolled_by); y++) {
        historybuf_init_line(self->historybuf, self->scrolled_by - 1 - y, self->historybuf->line);
        update_line_data(self->historybuf->line, y, address);
    }
    for (index_type y = self->scrolled_by; y < self->lines; y++) {
        linebuf_init_line(self->linebuf, y - self->scrolled_by);
        update_line_data(self->linebuf->line, y, address);
    }
    if (selection_must_be_cleared) self->selection = EMPTY_SELECTION;
}

static inline bool
is_selection_empty(Screen *self, unsigned int start_x, unsigned int start_y, unsigned int end_x, unsigned int end_y) {
    return (start_x >= self->columns || start_y >= self->lines || end_x >= self->columns || end_y >= self->lines || (start_x == end_x && start_y == end_y)) ? true : false;
}

static inline void
selection_coord(Screen *self, unsigned int x, unsigned int y, unsigned int ydelta, SelectionBoundary *ans) {
    if (y + self->scrolled_by < ydelta) {
        ans->x = 0; ans->y = 0;
    } else {
        y = y - ydelta + self->scrolled_by;
        if (y >= self->lines) {
            ans->x = self->columns - 1; ans->y = self->lines - 1;
        } else {
            ans->x = x; ans->y = y;
        }
    }
}

static inline void
selection_limits_(Screen *self, SelectionBoundary *left, SelectionBoundary *right) {
    SelectionBoundary a, b;
    selection_coord(self, self->selection.start_x, self->selection.start_y, self->selection.start_scrolled_by, &a);
    selection_coord(self, self->selection.end_x, self->selection.end_y, self->selection.end_scrolled_by, &b);
    if (a.y < b.y || (a.y == b.y && a.x <= b.x)) { *left = a; *right = b; }
    else { *left = b; *right = a; }
}

static inline Line*
visual_line_(Screen *self, index_type y) {
    if (self->scrolled_by) {
        if (y < self->scrolled_by) {
            historybuf_init_line(self->historybuf, self->scrolled_by - 1 - y, self->historybuf->line);
            return self->historybuf->line;
        } 
        y -= self->scrolled_by;
    }
    linebuf_init_line(self->linebuf, y);
    return self->linebuf->line;
}

void
screen_apply_selection(Screen *self, void *address, size_t size) {
#define start (self->last_rendered_selection_start)
#define end (self->last_rendered_selection_end)
    float *data = address;
    memset(data, 0, size);
    selection_limits_(self, &start, &end);
    self->last_selection_scrolled_by = self->scrolled_by;
    self->selection_updated_once = true;
    if (is_selection_empty(self, start.x, start.y, end.x, end.y)) { return; }
    for (index_type y = start.y; y <= end.y; y++) {
        Line *line = visual_line_(self, y);
        index_type xlimit = xlimit_for_line(line);
        if (y == end.y) xlimit = MIN(end.x + 1, xlimit);
        float *line_start = data + self->columns * y;
        for (index_type x = (y == start.y ? start.x : 0); x < xlimit; x++) line_start[x] = 1.0;
    }
#undef start
#undef end
}

// }}}

// Python interface {{{
#define WRAP0(name) static PyObject* name(Screen *self) { screen_##name(self); Py_RETURN_NONE; }
#define WRAP0x(name) static PyObject* xxx_##name(Screen *self) { screen_##name(self); Py_RETURN_NONE; }
#define WRAP1(name, defval) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; if(!PyArg_ParseTuple(args, "|I", &v)) return NULL; screen_##name(self, v); Py_RETURN_NONE; }
#define WRAP1E(name, defval, ...) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; if(!PyArg_ParseTuple(args, "|I", &v)) return NULL; screen_##name(self, v, __VA_ARGS__); Py_RETURN_NONE; }
#define WRAP1B(name, defval) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; int b=false; if(!PyArg_ParseTuple(args, "|Ip", &v, &b)) return NULL; screen_##name(self, v, b); Py_RETURN_NONE; }
#define WRAP1E(name, defval, ...) static PyObject* name(Screen *self, PyObject *args) { unsigned int v=defval; if(!PyArg_ParseTuple(args, "|I", &v)) return NULL; screen_##name(self, v, __VA_ARGS__); Py_RETURN_NONE; }
#define WRAP2(name, defval1, defval2) static PyObject* name(Screen *self, PyObject *args) { unsigned int a=defval1, b=defval2; if(!PyArg_ParseTuple(args, "|II", &a, &b)) return NULL; screen_##name(self, a, b); Py_RETURN_NONE; }

static PyObject*
line(Screen *self, PyObject *val) {
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (y >= self->lines) { PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL; }
    linebuf_init_line(self->linebuf, y);
    Py_INCREF(self->linebuf->line);
    return (PyObject*) self->linebuf->line;
}

Line*
screen_visual_line(Screen *self, index_type y) {
    if (y >= self->lines) return NULL;
    return visual_line_(self, y);
}

static PyObject*
visual_line(Screen *self, PyObject *args) {
    // The line corresponding to the yth visual line, taking into account scrolling
    unsigned int y;
    if (!PyArg_ParseTuple(args, "I", &y)) return NULL;
    if (y >= self->lines) { Py_RETURN_NONE; }
    return Py_BuildValue("O", visual_line_(self, y));
}
 
static PyObject*
draw(Screen *self, PyObject *src) {
    if (!PyUnicode_Check(src)) { PyErr_SetString(PyExc_TypeError, "A unicode string is required"); return NULL; }
    if (PyUnicode_READY(src) != 0) { return PyErr_NoMemory(); }
    int kind = PyUnicode_KIND(src);
    void *buf = PyUnicode_DATA(src);
    Py_ssize_t sz = PyUnicode_GET_LENGTH(src);
    for (Py_ssize_t i = 0; i < sz; i++) screen_draw(self, PyUnicode_READ(kind, buf, i));
    Py_RETURN_NONE;
}

static PyObject*
reset_mode(Screen *self, PyObject *args) {
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_reset_mode(self, mode);
    Py_RETURN_NONE;
}
 
static PyObject*
_select_graphic_rendition(Screen *self, PyObject *args) {
    unsigned int params[256] = {0};
    for (int i = 0; i < PyTuple_GET_SIZE(args); i++) { params[i] = PyLong_AsUnsignedLong(PyTuple_GET_ITEM(args, i)); }
    select_graphic_rendition(self, params, PyList_GET_SIZE(args));
    Py_RETURN_NONE;
}

static PyObject*
set_mode(Screen *self, PyObject *args) {
    int private = false;
    unsigned int mode;
    if (!PyArg_ParseTuple(args, "I|p", &mode, &private)) return NULL;
    if (private) mode <<= 5;
    screen_set_mode(self, mode);
    Py_RETURN_NONE;
}

static PyObject*
reset_dirty(Screen *self) {
    screen_reset_dirty(self);
    Py_RETURN_NONE;
}

WRAP1E(cursor_back, 1, -1)
WRAP1B(erase_in_line, 0)
WRAP1B(erase_in_display, 0)

#define MODE_GETSET(name, uname) \
    static PyObject* name##_get(Screen *self, void UNUSED *closure) { PyObject *ans = self->modes.m##uname ? Py_True : Py_False; Py_INCREF(ans); return ans; } \
    static int name##_set(Screen *self, PyObject *val, void UNUSED *closure) { if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } set_mode_from_const(self, uname, PyObject_IsTrue(val) ? true : false); return 0; }

MODE_GETSET(in_bracketed_paste_mode, BRACKETED_PASTE)
MODE_GETSET(extended_keyboard, EXTENDED_KEYBOARD)
MODE_GETSET(focus_tracking_enabled, FOCUS_TRACKING)
MODE_GETSET(auto_repeat_enabled, DECARM)
MODE_GETSET(cursor_visible, DECTCEM)
MODE_GETSET(cursor_key_mode, DECCKM)

static PyObject*
cursor_up(Screen *self, PyObject *args) {
    unsigned int count = 1;
    int do_carriage_return = false, move_direction = -1;
    if (!PyArg_ParseTuple(args, "|Ipi", &count, &do_carriage_return, &move_direction)) return NULL;
    screen_cursor_up(self, count, do_carriage_return, move_direction);
    Py_RETURN_NONE;
}

WRAP0x(index)
WRAP0(reverse_index)
WRAP0(refresh_sprite_positions)
WRAP0(reset)
WRAP0(set_tab_stop)
WRAP1(clear_tab_stop, 0)
WRAP0(backspace)
WRAP0(tab)
WRAP0(linefeed)
WRAP0(carriage_return)
WRAP2(resize, 1, 1)
WRAP2(set_margins, 1, 1)

static PyObject*
change_scrollback_size(Screen *self, PyObject *args) {
    unsigned int count = 1; 
    if (!PyArg_ParseTuple(args, "|I", &count)) return NULL; 
    if (!screen_change_scrollback_size(self, MAX(self->lines, count))) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
text_for_selection(Screen *self) {
    SelectionBoundary start, end;
    selection_limits_(self, &start, &end);
    if (is_selection_empty(self, start.x, start.y, end.x, end.y)) return PyTuple_New(0);
    Py_ssize_t i = 0, num_of_lines = end.y - start.y + 1;
    PyObject *ans = PyTuple_New(num_of_lines);
    if (ans == NULL) return PyErr_NoMemory();
    for (index_type y = start.y; y <= end.y; y++, i++) {
        Line *line = visual_line_(self, y);
        index_type xlimit = xlimit_for_line(line);
        if (y == end.y) xlimit = MIN(end.x + 1, xlimit);
        index_type xstart = (y == start.y ? start.x : 0);
        char leading_char = i > 0 && !line->continued ? '\n' : 0;
        PyObject *text = unicode_in_range(line, xstart, xlimit, true, leading_char);
        if (text == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); }
        PyTuple_SET_ITEM(ans, i, text);
    }
    return ans;
}
 
bool
screen_selection_range_for_line(Screen *self, index_type y, index_type *start, index_type *end) {
    if (y >= self->lines) { return false; }
    Line *line = visual_line_(self, y);
    index_type xlimit = line->xnum, xstart = 0;
    while (xlimit > 0 && CHAR_IS_BLANK(line->cells[xlimit - 1].ch)) xlimit--;
    while (xstart < xlimit && CHAR_IS_BLANK(line->cells[xstart].ch)) xstart++;
    *start = xstart; *end = xlimit;
    return true;
}

static inline bool
is_opt_word_char(char_type ch) {
    for (size_t i = 0; i < OPT(select_by_word_characters_count); i++) {
        if (OPT(select_by_word_characters[i]) == ch) return true;
    }
    return false;
}

bool
screen_selection_range_for_word(Screen *self, index_type x, index_type y, index_type *s, index_type *e) {
    if (y >= self->lines || x >= self->columns) return false;
    index_type start, end;
    Line *line = visual_line_(self, y);
#define is_ok(x) (is_word_char((line->cells[x].ch) & CHAR_MASK) || is_opt_word_char(line->cells[x].ch & CHAR_MASK))
    if (!is_ok(x)) {
        start = x; end = x + 1;
    } else {
        start = x, end = x;
        while(start > 0 && is_ok(start - 1)) start--;
        while(end < self->columns - 1 && is_ok(end + 1)) end++; 
    }
    *s = start; *e = end;
    return true;
#undef is_ok
}

bool
screen_history_scroll(Screen *self, int amt, bool upwards) {
    switch(amt) {
        case SCROLL_LINE:
            amt = 1;
            break;
        case SCROLL_PAGE:
            amt = self->lines - 1;
            break;
        case SCROLL_FULL:
            amt = self->historybuf->count;
            break;
        default:
            amt = MAX(0, amt);
            break;
    }
    if (!upwards) {
        amt = MIN((unsigned int)amt, self->scrolled_by);
        amt *= -1;
    }
    if (amt == 0) return false;
    unsigned int new_scroll = MIN(self->scrolled_by + amt, self->historybuf->count);
    if (new_scroll != self->scrolled_by) {
        self->scrolled_by = new_scroll;
        self->scroll_changed = true;
        return true;
    }
    return false;
}

static PyObject*
scroll(Screen *self, PyObject *args) {
    int amt, upwards;
    if (!PyArg_ParseTuple(args, "ip", &amt, &upwards)) return NULL;
    if (screen_history_scroll(self, amt, upwards)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

bool
screen_is_selection_dirty(Screen *self) {
    SelectionBoundary start, end;
    selection_limits_(self, &start, &end);
    if (self->last_selection_scrolled_by != self->scrolled_by || start.x != self->last_rendered_selection_start.x || start.y != self->last_rendered_selection_start.y || end.x != self->last_rendered_selection_end.x || end.y != self->last_rendered_selection_end.y || !self->selection_updated_once) return true;
    return false;
}

void
screen_start_selection(Screen *self, index_type x, index_type y) {
#define A(attr, val) self->selection.attr = val;
    A(start_x, x); A(end_x, x); A(start_y, y); A(end_y, y); A(start_scrolled_by, self->scrolled_by); A(end_scrolled_by, self->scrolled_by); A(in_progress, true);
#undef A
}

void
screen_update_selection(Screen *self, index_type x, index_type y, bool ended) {
    self->selection.end_x = x; self->selection.end_y = y; self->selection.end_scrolled_by = self->scrolled_by;
    if (ended) self->selection.in_progress = false;
}

static PyObject* 
mark_as_dirty(Screen *self) {
    self->is_dirty = true;
    Py_RETURN_NONE;
}

static PyObject* 
current_char_width(Screen *self) {
#define current_char_width_doc "The width of the character under the cursor"
    return PyLong_FromUnsignedLong(screen_current_char_width(self));
}

static PyObject* 
is_main_linebuf(Screen *self) {
    PyObject *ans = (self->linebuf == self->main_linebuf) ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
toggle_alt_screen(Screen *self) {
    screen_toggle_screen_buffer(self);
    Py_RETURN_NONE;
}

WRAP2(cursor_position, 1, 1)

#define COUNT_WRAP(name) WRAP1(name, 1)
COUNT_WRAP(insert_lines)
COUNT_WRAP(delete_lines)
COUNT_WRAP(insert_characters)
COUNT_WRAP(delete_characters)
COUNT_WRAP(erase_characters)
COUNT_WRAP(cursor_up1)
COUNT_WRAP(cursor_down)
COUNT_WRAP(cursor_down1)
COUNT_WRAP(cursor_forward)

#define MND(name, args) {#name, (PyCFunction)name, args, #name},
#define MODEFUNC(name) MND(name, METH_NOARGS) MND(set_##name, METH_O)

static PyMethodDef methods[] = {
    MND(line, METH_O)
    MND(visual_line, METH_VARARGS)
    MND(draw, METH_O)
    MND(cursor_position, METH_VARARGS)
    MND(set_mode, METH_VARARGS)
    MND(reset_mode, METH_VARARGS)
    MND(reset, METH_NOARGS)
    MND(reset_dirty, METH_NOARGS)
    MND(is_main_linebuf, METH_NOARGS)
    MND(cursor_back, METH_VARARGS)
    MND(erase_in_line, METH_VARARGS)
    MND(erase_in_display, METH_VARARGS)
    METHOD(current_char_width, METH_NOARGS)
    MND(insert_lines, METH_VARARGS)
    MND(delete_lines, METH_VARARGS)
    MND(insert_characters, METH_VARARGS)
    MND(delete_characters, METH_VARARGS)
    MND(change_scrollback_size, METH_VARARGS)
    MND(erase_characters, METH_VARARGS)
    MND(cursor_up, METH_VARARGS)
    MND(cursor_up1, METH_VARARGS)
    MND(cursor_down, METH_VARARGS)
    MND(cursor_down1, METH_VARARGS)
    MND(cursor_forward, METH_VARARGS)
    {"index", (PyCFunction)xxx_index, METH_VARARGS, ""},
    MND(tab, METH_NOARGS)
    MND(backspace, METH_NOARGS)
    MND(linefeed, METH_NOARGS)
    MND(carriage_return, METH_NOARGS)
    MND(set_tab_stop, METH_NOARGS)
    MND(clear_tab_stop, METH_VARARGS)
    MND(reverse_index, METH_NOARGS)
    MND(refresh_sprite_positions, METH_NOARGS)
    MND(mark_as_dirty, METH_NOARGS)
    MND(resize, METH_VARARGS)
    MND(set_margins, METH_VARARGS)
    MND(text_for_selection, METH_NOARGS)
    MND(scroll, METH_VARARGS)
    MND(toggle_alt_screen, METH_NOARGS)
    MND(reset_callbacks, METH_NOARGS)
    {"select_graphic_rendition", (PyCFunction)_select_graphic_rendition, METH_VARARGS, ""},

    {NULL}  /* Sentinel */
};

static PyGetSetDef getsetters[] = {
    GETSET(in_bracketed_paste_mode)
    GETSET(extended_keyboard)
    GETSET(auto_repeat_enabled)
    GETSET(focus_tracking_enabled)
    GETSET(cursor_visible)
    GETSET(cursor_key_mode)
    {NULL}  /* Sentinel */
};

#if UINT_MAX == UINT32_MAX
#define T_COL T_UINT
#elif ULONG_MAX == UINT32_MAX
#define T_COL T_ULONG
#else
#error Neither int nor long is 4-bytes in size
#endif

static PyMemberDef members[] = {
    {"callbacks", T_OBJECT_EX, offsetof(Screen, callbacks), 0, "callbacks"},
    {"cursor", T_OBJECT_EX, offsetof(Screen, cursor), READONLY, "cursor"},
    {"color_profile", T_OBJECT_EX, offsetof(Screen, color_profile), READONLY, "color_profile"},
    {"linebuf", T_OBJECT_EX, offsetof(Screen, linebuf), READONLY, "linebuf"},
    {"historybuf", T_OBJECT_EX, offsetof(Screen, historybuf), READONLY, "historybuf"},
    {"scrolled_by", T_UINT, offsetof(Screen, scrolled_by), READONLY, "scrolled_by"},
    {"lines", T_UINT, offsetof(Screen, lines), READONLY, "lines"},
    {"columns", T_UINT, offsetof(Screen, columns), READONLY, "columns"},
    {"margin_top", T_UINT, offsetof(Screen, margin_top), READONLY, "margin_top"},
    {"margin_bottom", T_UINT, offsetof(Screen, margin_bottom), READONLY, "margin_bottom"},
    {"history_line_added_count", T_UINT, offsetof(Screen, history_line_added_count), 0, "history_line_added_count"},
    {NULL}
};
 
PyTypeObject Screen_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Screen",
    .tp_basicsize = sizeof(Screen),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "Screen",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,                
    .tp_getset = getsetters,
};

INIT_TYPE(Screen)
// }}}
