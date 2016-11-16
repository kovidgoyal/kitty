/*
 * parser.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <stdio.h>
#include <stdlib.h>
#include "data-types.h"
#include "control-codes.h"

#define NORMAL_STATE 0
#define ESC_STATE 1
#define CSI_STATE 2
#define OSC_STATE 3
#define DCS_STATE 4

#define IS_DIGIT \
    case '0': \
    case '1': \
    case '2': \
    case '3': \
    case '4': \
    case '5': \
    case '6': \
    case '7': \
    case '8': \
    case '9':

#ifdef DUMP_COMMANDS
static void _report_error(PyObject *dump_callback, const char *fmt, ...) {
    va_list argptr;
    va_start(argptr, fmt);
    PyObject *temp = PyUnicode_FromFormatV(fmt, argptr);
    va_end(argptr);
    if (temp != NULL) {
        Py_XDECREF(PyObject_CallFunctionObjArgs(dump_callback, temp, NULL)); PyErr_Clear();
        Py_CLEAR(temp);
    }
}

#define REPORT_ERROR(...) _report_error(dump_callback, __VA_ARGS__);

#define REPORT_COMMAND1(name) \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "s", #name)); PyErr_Clear();

#define REPORT_COMMAND2(name, x) \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "si", #name, (int)x)); PyErr_Clear();

#define REPORT_COMMAND3(name, x, y) \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "sii", #name, (int)x, (int)y)); PyErr_Clear();

#define GET_MACRO(_1,_2,_3,NAME,...) NAME
#define REPORT_COMMAND(...) GET_MACRO(__VA_ARGS__, REPORT_COMMAND3, REPORT_COMMAND2, REPORT_COMMAND1, SENTINEL)(__VA_ARGS__)

#define HANDLER(name) \
    static inline void read_##name(Screen *screen, uint8_t UNUSED *buf, unsigned int UNUSED buflen, unsigned int UNUSED *pos, PyObject UNUSED *dump_callback)

#else

#define REPORT_ERROR(...) fprintf(stderr, "[PARSE ERROR] "); fprintf(stderr, __VA_ARGS__); fprintf(stderr, "\n");

#define REPORT_COMMAND(...)

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

#define CALL_SCREEN_HANDLER(name) \
        DRAW_TEXT; REPORT_COMMAND(name, ch); \
        name(screen, ch); break;
        
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
#define moo 1
// }}}

// Parse ESC {{{

static inline void screen_linefeed2(Screen *screen) { screen_linefeed(screen, '\n'); }

static inline void escape_dispatch(Screen *screen, uint8_t ch, PyObject UNUSED *dump_callback) {
#define CALL_ED(name) REPORT_COMMAND(name); name(screen); break;
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
        default:
            REPORT_ERROR("%s%d", "Unknown char in escape_dispatch: ", ch); 
    }
#undef CALL_ED
}

static inline void sharp_dispatch(Screen *screen, uint8_t ch, PyObject UNUSED *dump_callback) {
    switch(ch) {
        case DECALN:
            REPORT_COMMAND(screen_alignment_display);
            screen_alignment_display(screen); 
            break;
        default:
            REPORT_ERROR("%s%d", "Unknown char in sharp_dispatch: ", ch);
    }
}

HANDLER(esc) {
#define ESC_DISPATCH(which, extra) REPORT_COMMAND(which, ch, extra); which(screen, ch, extra); SET_STATE(NORMAL_STATE); return;
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
#undef ESC_DISPATCH
#undef ESC_DELEGATE
}

// }}}

// Parse CSI {{{

#define MAX_PARAMS 8

static inline unsigned int fill_params(Screen *screen, unsigned int *params, unsigned int expect) {
    unsigned int start_pos = 1, i = 1, pi = 0;
    uint8_t ch = 1;
    screen->parser_buf[screen->parser_buf_pos] = 0;

    while (pi < MIN(MAX_PARAMS, expect) && i < PARSER_BUF_SZ - 1 && ch != 0) {
        ch = screen->parser_buf[i++];
        if (ch == 0 || ch == ';') {
            if (start_pos < i - 1) {
                params[pi++] = atoi((const char *)screen->parser_buf + start_pos);
            }
            start_pos = i;
        }
    }
    return pi;
}

static inline void screen_cursor_up2(Screen *s, unsigned int count) { screen_cursor_up(s, count, false, -1); }
static inline void screen_cursor_back1(Screen *s, unsigned int count) { screen_cursor_back(s, count, -1); }

HANDLER(csi) {
#define CALL_BASIC_HANDLER(name) REPORT_COMMAND(screen, ch); name(screen, ch); break;
#define HANDLE_BASIC_CH \
    case BEL: \
        CALL_BASIC_HANDLER(screen_bell); \
    case BS: \
        CALL_BASIC_HANDLER(screen_backspace); \
    case HT: \
        CALL_BASIC_HANDLER(screen_tab); \
    case LF: \
    case VT: \
    case FF: \
        CALL_BASIC_HANDLER(screen_linefeed); \
    case CR: \
        CALL_BASIC_HANDLER(screen_carriage_return); \
    case NUL: \
    case DEL: \
        break;  // no-op
#define CALL_CSI_HANDLER1(name, defval) \
    p1 = fill_params(screen, params, 1) > 0 ? params[0] : defval; \
    REPORT_COMMAND(name, p1); \
    name(screen, p1); \
    SET_STATE(NORMAL_STATE); \
    break; 

#define CALL_CSI_HANDLER2(name, defval1, defval2) \
    count = fill_params(screen, params, 2); \
    p1 = count > 0 ? params[0] : defval1; \
    p2 = count > 1 ? params[1] : defval2; \
    REPORT_COMMAND(name, p1, p2); \
    name(screen, p1, p2); \
    SET_STATE(NORMAL_STATE); \
    break; 

#define DISPATCH_CSI \
    case ICH: \
        CALL_CSI_HANDLER1(screen_insert_characters, 1); \
    case CUU: \
        CALL_CSI_HANDLER1(screen_cursor_up2, 1); \
    case CUD: \
        CALL_CSI_HANDLER1(screen_cursor_down, 1); \
    case CUF: \
        CALL_CSI_HANDLER1(screen_cursor_forward, 1); \
    case CUB: \
        CALL_CSI_HANDLER1(screen_cursor_back1, 1); \
    case CNL:  \
        CALL_CSI_HANDLER1(screen_cursor_down1, 1); \
    case CPL:  \
        CALL_CSI_HANDLER1(screen_cursor_up1, 1); \
    case CHA: \
        CALL_CSI_HANDLER1(screen_cursor_to_column, 1); \
    case CUP:  \
        CALL_CSI_HANDLER2(screen_cursor_position, 1, 1);

    uint8_t ch = buf[(*pos)++];
    unsigned int params[MAX_PARAMS], p1, p2, count;
    switch(screen->parser_buf_pos) {
        case 0:  // CSI starting
            screen->parser_buf[0] = 0;
            screen->parser_buf[1] = 0;
            switch(ch) {
                IS_DIGIT
                    screen->parser_buf_pos = 2;
                    screen->parser_buf[1] = ch;
                    break;
                case '?':
                case '>':
                case '!':
                    screen->parser_buf[0] = ch; screen->parser_buf_pos = 1;
                    break;
                HANDLE_BASIC_CH
                DISPATCH_CSI
                default:
                    REPORT_ERROR("Invalid first character for CSI: 0x%x", ch);
                    SET_STATE(NORMAL_STATE); 
                    break;
            }
            break;
        default: // CSI started
            switch(ch) {
                IS_DIGIT
                case ';':
                    if (screen->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                        REPORT_ERROR("%s",  "CSI sequence too long, ignoring.");
                        SET_STATE(NORMAL_STATE); 
                    } else screen->parser_buf[screen->parser_buf_pos++] = ch;
                    break;
                HANDLE_BASIC_CH
                DISPATCH_CSI
                default:
                    REPORT_ERROR("Invalid character for CSI: 0x%x", ch);
                    SET_STATE(NORMAL_STATE); 
                    break;
            }
            break;
    }
#undef CALL_BASIC_HANDLER
#undef HANDLE_BASIC_CH
#undef CALL_CSI_HANDLER1
}
#undef MAX_PARAMS
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
