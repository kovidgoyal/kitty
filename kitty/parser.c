/*
 * parser.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "control-codes.h"

extern PyTypeObject Screen_Type;

#define NORMAL_STATE 0
#define ESC_STATE 1
#define CSI_STATE 2
#define OSC_STATE 3
#define DCS_STATE 4

#define DECLARE_CH_SCREEN_HANDLER(name) extern bool screen_##name(Screen *screen, uint8_t ch);
DECLARE_CH_SCREEN_HANDLER(bell)
DECLARE_CH_SCREEN_HANDLER(backspace)
DECLARE_CH_SCREEN_HANDLER(tab)
DECLARE_CH_SCREEN_HANDLER(linefeed)
DECLARE_CH_SCREEN_HANDLER(carriage_return)
DECLARE_CH_SCREEN_HANDLER(shift_out)
DECLARE_CH_SCREEN_HANDLER(shift_in)
extern bool screen_draw(Screen *screen, uint8_t *buf, unsigned int buflen);

// Parse text {{{
static inline bool
read_text(Screen *screen, uint8_t *buf, unsigned int buflen, unsigned int *pos) {
    bool ret;
    uint8_t ch;

    while(*pos < buflen) {
        ch = buf[(*pos)++];
#define DRAW_TEXT \
        if (screen->parser_has_pending_text) { \
            screen->parser_has_pending_text = false; \
            ret = screen_draw(screen, buf + screen->parser_text_start, (*pos) - screen->parser_text_start); \
            screen->parser_text_start = 0; \
            if (!ret) return false; \
        } 

#define CALL_SCREEN_HANDLER(name) \
        DRAW_TEXT; \
        if (!screen_##name(screen, ch)) return false;
        
#define CHANGE_PARSER_STATE(state) screen->parser_state = state; return true;
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
    return true;
}
// }}}

// Parse ESC {{{
static inline bool
read_esc(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos) {
    screen->parser_state = NORMAL_STATE;
    return true;
}
// }}}

// Parse CSI {{{
static inline bool
read_csi(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos) {
    screen->parser_state = NORMAL_STATE;
    return true;
}
// }}}

// Parse OSC {{{
static inline bool
read_osc(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos) {
    screen->parser_state = NORMAL_STATE;
    return true;
}
// }}}

// Parse DCS {{{
static inline bool
read_dcs(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos) {
    screen->parser_state = NORMAL_STATE;
    return true;
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
#define CALL_HANDLER(name) \
    if (!name(screen, buf, pybuf.len, &i)) return NULL; break; \
        
    while (i < pybuf.len) {
        switch(screen->parser_state) {
            case ESC_STATE:
                CALL_HANDLER(read_esc);
            case CSI_STATE:
                CALL_HANDLER(read_csi);
            case OSC_STATE:
                CALL_HANDLER(read_osc);
            case DCS_STATE:
                CALL_HANDLER(read_dcs);
            default:
                CALL_HANDLER(read_text);
        }
    }
    Py_RETURN_NONE;
}
