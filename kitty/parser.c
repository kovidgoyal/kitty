/*
 * parser.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "control-codes.h"

#define NORMAL_STATE 0
#define ESC_STATE 1
#define CSI_STATE 2
#define OSC_STATE 3
#define DCS_STATE 4

#ifdef DUMP_COMMANDS
#define HANDLER(name) \
    static inline void read_##name(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos, PyObject UNUSED *dump_callback)
#else
#define HANDLER(name) \
    static inline void read_##name(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos)
#endif

#define SET_STATE(state) screen->parser_state = state; screen->parser_buf_pos = 0;

// Parse text {{{
HANDLER(text) {
    uint8_t ch;

    while(*pos < buflen) {
        ch = buf[(*pos)++];
#define DRAW_TEXT \
        if (screen->parser_has_pending_text) { \
            screen->parser_has_pending_text = false; \
            screen_draw(screen, buf + screen->parser_text_start, (*pos) - screen->parser_text_start); \
            screen->parser_text_start = 0; \
        } 

#ifdef DUMP_COMMANDS
#define CALL_SCREEN_HANDLER(name) \
        DRAW_TEXT; \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "sC", #name, (int)ch)); PyErr_Clear(); \
        name(screen, ch); break;
#else
#define CALL_SCREEN_HANDLER(name) \
        DRAW_TEXT; \
        name(screen, ch); break;
#endif
        
        switch(ch) {
            case BEL:
                CALL_SCREEN_HANDLER(screen_bell);
            case BS:
                CALL_SCREEN_HANDLER(screen_backspace);
            case HT:
                CALL_SCREEN_HANDLER(screen_tab);
            case LF:
            case VT:
            case FF:
                CALL_SCREEN_HANDLER(screen_linefeed);
            case CR:
                CALL_SCREEN_HANDLER(screen_carriage_return);
            case SO:
                CALL_SCREEN_HANDLER(screen_shift_out);
            case SI:
                CALL_SCREEN_HANDLER(screen_shift_in);
            case ESC:
                DRAW_TEXT; SET_STATE(ESC_STATE); return;
            case CSI:
                DRAW_TEXT; SET_STATE(CSI_STATE); return;
            case OSC:
                DRAW_TEXT; SET_STATE(OSC_STATE); return;
            case NUL:
            case DEL:
                break;  // no-op
            default:
                if (!screen->parser_has_pending_text) {
                    screen->parser_has_pending_text = true;
                    screen->parser_text_start = (*pos) - 1;
                }
        }
    }
    DRAW_TEXT;
}
// }}}

// Parse ESC {{{

static inline void screen_linefeed2(Screen *screen) { screen_linefeed(screen, '\n'); }

static inline void escape_dispatch(Screen *screen, uint8_t ch, PyObject UNUSED *dump_callback) {
#ifdef DUMP_COMMANDS
#define CALL_ED(name) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "s", #name)); PyErr_Clear(); \
    name(screen); break;
#else
#define CALL_ED(name) name(screen); break;
#endif
    switch (ch) {
        case RIS:
            CALL_ED(screen_reset);
        case IND:
            CALL_ED(screen_index);
        case NEL:
            CALL_ED(screen_linefeed2);
        case RI:
            CALL_ED(screen_reverse_index);
        case HTS:
            CALL_ED(screen_set_tab_stop);
        case DECSC:
            CALL_ED(screen_save_cursor);
        case DECRC:
            CALL_ED(screen_restore_cursor);
        case DECPNM: 
            CALL_ED(screen_normal_keypad_mode);
        case DECPAM: 
            CALL_ED(screen_alternate_keypad_mode);
#ifdef DUMP_COMMANDS
        default:
            Py_XDECREF(PyObject_CallFunction(dump_callback, "sB", "Unknown char in escape_dispatch: ", ch)); PyErr_Clear();
#endif
    }
}

static inline void sharp_dispatch(Screen *screen, uint8_t ch, PyObject UNUSED *dump_callback) {
    switch(ch) {
        case DECALN:
#ifdef DUMP_COMMANDS
            Py_XDECREF(PyObject_CallFunction(dump_callback, "s", "screen_alignment_display")); PyErr_Clear();
#endif
            screen_alignment_display(screen); 
            break;
#ifdef DUMP_COMMANDS
        default:
            Py_XDECREF(PyObject_CallFunction(dump_callback, "sB", "Unknown char in sharp_dispatch: ", ch)); PyErr_Clear();
#endif
    }
}

HANDLER(esc) {
#ifdef DUMP_COMMANDS
#define ESC_DISPATCH(which, extra) which(screen, ch, extra); SET_STATE(NORMAL_STATE); \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sCC", #which, (int)ch, (int)(extra))); PyErr_Clear(); \
    return;
#else
#define ESC_DISPATCH(which, extra) which(screen, ch, extra); SET_STATE(NORMAL_STATE); return;
#endif
#ifdef DUMP_COMMANDS
#define ESC_DELEGATE(which) which(screen, ch, dump_callback); SET_STATE(NORMAL_STATE); return;
#else
#define ESC_DELEGATE(which) which(screen, ch, NULL); SET_STATE(NORMAL_STATE); return;
#endif
    uint8_t ch = buf[(*pos)++];
    switch(screen->parser_buf_pos) {
        case 0:
            switch(ch) {
                case '[':
                    SET_STATE(CSI_STATE); return;
                case ']':
                    SET_STATE(OSC_STATE); return;
                case 'P':
                    SET_STATE(DCS_STATE); return;
                case '#':
                case '%':
                case '(':
                case ')':
                    screen->parser_buf[0] = ch; screen->parser_buf_pos++; return;
                default:
                    ESC_DELEGATE(escape_dispatch);
            }
            break;
        case 1:
            switch(screen->parser_buf[0]) {
                case '#':
                    ESC_DELEGATE(sharp_dispatch);
                case '%':
                    ESC_DISPATCH(screen_select_other_charset, 0);
                case '(':
                case ')':
                    ESC_DISPATCH(screen_define_charset, screen->parser_buf[0]);
            }
            break;
    }
}

// }}}

// Parse CSI {{{
HANDLER(csi) {
    screen->parser_state = NORMAL_STATE;
}
// }}}

// Parse OSC {{{
HANDLER(osc) {
    screen->parser_state = NORMAL_STATE;
}
// }}}

// Parse DCS {{{
HANDLER(dcs) {
    screen->parser_state = NORMAL_STATE;
}
// }}}

PyObject*
#ifdef DUMP_COMMANDS
parse_bytes_dump(PyObject UNUSED *self, PyObject *args) {
    PyObject *dump_callback = NULL;
#else
parse_bytes(PyObject UNUSED *self, PyObject *args) {
#endif
    Py_buffer pybuf;
    Screen *screen;
#ifdef DUMP_COMMANDS
    if (!PyArg_ParseTuple(args, "O!y*O", &Screen_Type, &screen, &pybuf, &dump_callback)) return NULL;
    if (!PyCallable_Check(dump_callback)) { PyErr_SetString(PyExc_TypeError, "The dump callback must be a callable object"); return NULL; }
#else
    if (!PyArg_ParseTuple(args, "O!y*", &Screen_Type, &screen, &pybuf)) return NULL;
#endif
    uint8_t *buf = pybuf.buf;
    unsigned int i = 0;
#ifdef DUMP_COMMANDS
#define CALL_HANDLER(name) read_##name(screen, buf, pybuf.len, &i, dump_callback); break;
#else
#define CALL_HANDLER(name) read_##name(screen, buf, pybuf.len, &i); break;
#endif
        
    while (i < pybuf.len) {
        switch(screen->parser_state) {
            case ESC_STATE:
                CALL_HANDLER(esc);
            case CSI_STATE:
                CALL_HANDLER(csi);
            case OSC_STATE:
                CALL_HANDLER(osc);
            case DCS_STATE:
                CALL_HANDLER(dcs);
            default:
                CALL_HANDLER(text);
        }
    }
    Py_RETURN_NONE;
}
