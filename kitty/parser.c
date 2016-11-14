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
        screen_##name(screen, ch);
#else
#define CALL_SCREEN_HANDLER(name) \
        DRAW_TEXT; \
        screen_##name(screen, ch);
#endif
        
#define CHANGE_PARSER_STATE(state) screen->parser_state = state; return;
        switch(ch) {
            case BEL:
                CALL_SCREEN_HANDLER(bell);
            case BS:
                CALL_SCREEN_HANDLER(backspace);
            case HT:
                CALL_SCREEN_HANDLER(tab);
            case LF:
            case VT:
            case FF:
                CALL_SCREEN_HANDLER(linefeed);
            case CR:
                CALL_SCREEN_HANDLER(carriage_return);
            case SO:
                CALL_SCREEN_HANDLER(shift_out);
            case SI:
                CALL_SCREEN_HANDLER(shift_in);
            case ESC:
                CHANGE_PARSER_STATE(ESC_STATE);
            case CSI:
                CHANGE_PARSER_STATE(CSI_STATE);
            case NUL:
            case DEL:
                break;
            case OSC:
                CHANGE_PARSER_STATE(OSC_STATE);
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
HANDLER(esc) {
    screen->parser_state = NORMAL_STATE;
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
    if (!PyArg_ParseTuple(args, "OO!y*", &dump_callback, &Screen_Type, &screen, &pybuf)) return NULL;
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
