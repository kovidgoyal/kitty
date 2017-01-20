/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "control-codes.h"

// utils {{{
static unsigned int pow10[10] = {
    1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000, 1000000000
};

static inline unsigned int 
utoi(uint32_t *buf, unsigned int sz) {
    unsigned int ans = 0;
    uint32_t *p = buf;
    // Ignore leading zeros
    while(sz > 0) {
        if (*p == '0') { p++; sz--; }
        else break;
    }
    if (sz < sizeof(pow10)/sizeof(pow10[10])) {
        for (int i = sz-1, j=0; i >=0; i--, j++) {
            ans += (p[i] - '0') * pow10[j];
        }
    }
    return ans;
}
// }}}

// Macros {{{
#define MAX_PARAMS 256
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
static void 
_report_error(PyObject *dump_callback, const char *fmt, ...) {
    va_list argptr;
    va_start(argptr, fmt);
    PyObject *temp = PyUnicode_FromFormatV(fmt, argptr);
    va_end(argptr);
    if (temp != NULL) {
        Py_XDECREF(PyObject_CallFunctionObjArgs(dump_callback, temp, NULL)); PyErr_Clear();
        Py_CLEAR(temp);
    }
}

static void 
_report_params(PyObject *dump_callback, const char *name, unsigned int *params, unsigned int count) {
    static char buf[MAX_PARAMS*3] = {0};
    unsigned int i, p;
    for(i = 0, p=0; i < count && p < MAX_PARAMS*3-20; i++) {
        p += snprintf(buf + p, MAX_PARAMS*3 - p, "%u ", params[i]);
    }
    buf[p] = 0;
    Py_XDECREF(PyObject_CallFunction(dump_callback, "ss", name, buf)); PyErr_Clear();
}

#define DUMP_UNUSED

#define REPORT_ERROR(...) _report_error(dump_callback, __VA_ARGS__);

#define REPORT_COMMAND1(name) \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "s", #name)); PyErr_Clear();

#define REPORT_COMMAND2(name, x) \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "si", #name, (int)x)); PyErr_Clear();

#define REPORT_COMMAND3(name, x, y) \
        Py_XDECREF(PyObject_CallFunction(dump_callback, "sii", #name, (int)x, (int)y)); PyErr_Clear();

#define GET_MACRO(_1,_2,_3,NAME,...) NAME
#define REPORT_COMMAND(...) GET_MACRO(__VA_ARGS__, REPORT_COMMAND3, REPORT_COMMAND2, REPORT_COMMAND1, SENTINEL)(__VA_ARGS__)

#define REPORT_DRAW(ch) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sC", "draw", ch)); PyErr_Clear();

#define REPORT_PARAMS(name, params, num) _report_params(dump_callback, #name, params, num_params)

#define FLUSH_DRAW \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sO", "draw", Py_None)); PyErr_Clear();

#define REPORT_OSC(name, string) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sO", #name, string)); PyErr_Clear();

#else

#define DUMP_UNUSED UNUSED

#define REPORT_ERROR(...) fprintf(stderr, "%s ", ERROR_PREFIX); fprintf(stderr, __VA_ARGS__); fprintf(stderr, "\n");

#define REPORT_COMMAND(...)
#define REPORT_DRAW(ch)
#define REPORT_PARAMS(...)
#define FLUSH_DRAW
#define REPORT_OSC(name, string)

#endif

#define SET_STATE(state) screen->parser_state = state; screen->parser_buf_pos = 0;
// }}}

// Normal mode {{{
static inline void
screen_nel(Screen *screen) { screen_carriage_return(screen); screen_linefeed(screen); }

static inline void 
handle_normal_mode_char(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
#define CALL_SCREEN_HANDLER(name) REPORT_COMMAND(name); name(screen); break;
    switch(ch) {
        case BEL:
            CALL_SCREEN_HANDLER(screen_bell);
        case BS:
            CALL_SCREEN_HANDLER(screen_backspace);
        case HT:
            CALL_SCREEN_HANDLER(screen_tab);
        case NEL:
            CALL_SCREEN_HANDLER(screen_nel);
        case LF:
        case VT:
        case FF:
            CALL_SCREEN_HANDLER(screen_linefeed);
        case CR:
            CALL_SCREEN_HANDLER(screen_carriage_return);
        case SI:
            REPORT_COMMAND(screen_change_charset, 0);
            screen_change_charset(screen, 0); break;
        case SO:
            REPORT_COMMAND(screen_change_charset, 1);
            screen_change_charset(screen, 1); break;
        case IND:
            CALL_SCREEN_HANDLER(screen_index);
        case RI:
            CALL_SCREEN_HANDLER(screen_reverse_index);
        case HTS:
            CALL_SCREEN_HANDLER(screen_set_tab_stop);
        case ESC:
        case CSI:
        case OSC:
        case DCS:
            SET_STATE(ch); break;
        case NUL:
        case DEL:
            break;  // no-op
        default:
            REPORT_DRAW(ch);
            screen_draw(screen, ch);
            break;
    }
#undef CALL_SCREEN_HANDLER
} // }}}

// Esc mode {{{
static inline void 
handle_esc_mode_char(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
#define CALL_ED(name) REPORT_COMMAND(name); name(screen); SET_STATE(0); 
#define CALL_ED1(name, ch) REPORT_COMMAND(name, ch); name(screen, ch); SET_STATE(0); 
#define CALL_ED2(name, a, b) REPORT_COMMAND(name, a, b); name(screen, a, b); SET_STATE(0); 
    switch(screen->parser_buf_pos) {
        case 0:
            switch (ch) {
                case ESC_DCS:
                    SET_STATE(DCS); break;
                case ESC_OSC:
                    SET_STATE(OSC); break;
                case ESC_CSI:
                    SET_STATE(CSI); break;
                case ESC_APC:
                    SET_STATE(APC); break;
                case ESC_PM:
                    SET_STATE(PM); break;
                case ESC_RIS:
                    CALL_ED(screen_reset); break;
                case ESC_IND:
                    CALL_ED(screen_index); break;
                case ESC_NEL:
                    CALL_ED(screen_nel); break;
                case ESC_RI:
                    CALL_ED(screen_reverse_index); break;
                case ESC_HTS:
                    CALL_ED(screen_set_tab_stop); break;
                case ESC_DECSC:
                    CALL_ED(screen_save_cursor); break;
                case ESC_DECRC:
                    CALL_ED(screen_restore_cursor); break;
                case ESC_DECPNM: 
                    CALL_ED(screen_normal_keypad_mode); break;
                case ESC_DECPAM: 
                    CALL_ED(screen_alternate_keypad_mode); break;
                case '%':
                case '(':
                case ')':
                case '*':
                case '+':
                case '-':
                case '.':
                case '/':
                case ' ':
                case '#':
                    screen->parser_buf[screen->parser_buf_pos++] = ch;
                    break;
                default:
                    REPORT_ERROR("%s0x%x", "Unknown char after ESC: ", ch); 
                    SET_STATE(0); break;
            }
            break;
        default:
            switch(screen->parser_buf[0]) {
                case '%':
                    switch(ch) {
                        case '@':
                            REPORT_COMMAND(screen_use_latin1, 1);
                            screen->use_latin1 = true; screen->utf8_state = 0; break;
                        case 'G':
                            REPORT_COMMAND(screen_use_latin1, 0);
                            screen->use_latin1 = false; screen->utf8_state = 0; break;
                        default:
                            REPORT_ERROR("Unhandled Esc %% code: 0x%x", ch);  break;
                    }
                    break;
                case '#':
                    if (ch == '8') { CALL_ED(screen_align); }
                    else { REPORT_ERROR("Unhandled Esc # code: 0x%x", ch); }
                    break;
                case '(':
                case ')':
                    switch(ch) {
                        case 'A':
                        case 'B':
                        case '0':
                        case 'U':
                        case 'V':
                            CALL_ED2(screen_designate_charset, screen->parser_buf[0] - '(', ch); break;
                        default:
                            REPORT_ERROR("Unknown charset: 0x%x", ch); break;
                    }
                    break;
                default:
                    REPORT_ERROR("Unhandled charset related escape code: 0x%x 0x%x", screen->parser_buf[0], ch); break;
            }
            SET_STATE(0);
            break;
    }
#undef CALL_ED
#undef CALL_ED1
} // }}}

// OSC mode {{{
static inline void
dispatch_osc(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
#define DISPATCH_OSC(name) REPORT_OSC(name, string); name(screen, string);
#define SET_COLOR(name) REPORT_OSC(name, string); name(screen, code, string);
    const unsigned int limit = screen->parser_buf_pos;
    unsigned int code=0, i;
    for (i = 0; i < MIN(limit, 5); i++) {
        if (screen->parser_buf[i] < '0' || screen->parser_buf[i] > '9') break;
    }
    if (i > 0) {
        code = utoi(screen->parser_buf, i);
        if (i < limit - 1 && screen->parser_buf[i] == ';') i++;
    }
    PyObject *string = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + i, limit - i);
    if (string != NULL) {
        switch(code) {
            case 0:
                DISPATCH_OSC(set_title);
                DISPATCH_OSC(set_icon);
                break;
            case 1:
                DISPATCH_OSC(set_icon);
                break;
            case 2:
                DISPATCH_OSC(set_title);
                break;
            case 4:
            case 104:
                SET_COLOR(set_color_table_color);
                break;
            case 10:
            case 11:
            case 110:
            case 111:
                SET_COLOR(set_dynamic_color);
                break;
            default:
                REPORT_ERROR("Unknown OSC code: %u", code);
                break;
        }
        Py_CLEAR(string);
    }
#undef DISPATCH_OSC
#undef SET_COLOR
}
// }}}

// CSI mode {{{
#define CSI_SECONDARY \
        case ';': \
        case '"': \
        case '*': \
        case '\'': \
        case ' ':


static inline void 
screen_cursor_up2(Screen *s, unsigned int count) { screen_cursor_up(s, count, false, -1); }
static inline void 
screen_cursor_back1(Screen *s, unsigned int count) { screen_cursor_back(s, count, -1); }
static inline void 
screen_indexn(Screen *s, unsigned int count) { for (index_type i=0; i < MAX(1, count); i++) screen_index(s); }
static inline void 
screen_tabn(Screen *s, unsigned int count) { for (index_type i=0; i < MAX(1, count); i++) screen_tab(s); }
static inline void 
screen_reverse_indexn(Screen *s, unsigned int count) { for (index_type i=0; i < count; i++) screen_reverse_index(s); }
static inline void
save_cursor(Screen *s, unsigned int UNUSED param, bool private) {
    if (private) fprintf(stderr, "%s %s", ERROR_PREFIX, "CSI s in private mode not supported");
    else screen_save_cursor(s);
}
static inline void
restore_cursor(Screen *s, unsigned int UNUSED param, bool private) {
    if (private) fprintf(stderr, "%s %s", ERROR_PREFIX, "CSI u in private mode not supported");
    else screen_restore_cursor(s);
}

static inline void
dispatch_csi(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
#define CALL_CSI_HANDLER1(name, defval) \
    p1 = num_params > 0 ? params[0] : defval; \
    REPORT_COMMAND(name, p1); \
    name(screen, p1); \
    break;

#define CALL_CSI_HANDLER1P(name, defval, qch) \
    p1 = num_params > 0 ? params[0] : defval; \
    private = start_modifier == qch; \
    REPORT_COMMAND(name, p1, private); \
    name(screen, p1, private); \
    break;

#define CALL_CSI_HANDLER1M(name, defval) \
    p1 = num_params > 0 ? params[0] : defval; \
    REPORT_COMMAND(name, p1, end_modifier); \
    name(screen, p1, end_modifier); \
    break;

#define CALL_CSI_HANDLER2(name, defval1, defval2) \
    p1 = num_params > 0 ? params[0] : defval1; \
    p2 = num_params > 1 ? params[1] : defval2; \
    REPORT_COMMAND(name, p1, p2); \
    name(screen, p1, p2); \
    break;

#define SET_MODE(func) \
    p1 = start_modifier == '?' ? 5 : 0; \
    for (i = 0; i < num_params; i++) { \
        REPORT_COMMAND(func, params[i], start_modifier == '?'); \
        func(screen, params[i] << p1); \
    } \
    break;

#define CSI_HANDLER_MULTIPLE(name) \
    REPORT_PARAMS(name, params, num_params); \
    name(screen, params, num_params); \
    break;


    char start_modifier = 0, end_modifier = 0;
    uint32_t *buf = screen->parser_buf, code = screen->parser_buf[screen->parser_buf_pos];
    unsigned int num = screen->parser_buf_pos, start, i, num_params=0, p1, p2;
    static unsigned int params[MAX_PARAMS] = {0};
    bool private;
    if (buf[0] == '>' || buf[0] == '?' || buf[0] == '!') {
        start_modifier = (char)screen->parser_buf[0];
        buf++; num--;
    }
    if (num > 0) {
        switch(buf[num-1]) {
            CSI_SECONDARY
                end_modifier = (char)buf[--num];
        }
    }
    for (i=0, start=0; i < num; i++) {
        switch(buf[i]) {
            IS_DIGIT
                break;
            default:
                if (i > start) params[num_params++] = utoi(buf + start, i - start);
                else if (i == start && buf[i] == ';') params[num_params++] = 0;
                if (num_params >= MAX_PARAMS) { i = num; start = num + 1; }
                else { start = i + 1; break; }
        }
    }
    if (i > start) params[num_params++] = utoi(buf + start, i - start);
    switch(code) {
        case ICH: 
            CALL_CSI_HANDLER1(screen_insert_characters, 1); 
        case CUU: 
            CALL_CSI_HANDLER1(screen_cursor_up2, 1); 
        case CUD: 
        case VPR: 
            CALL_CSI_HANDLER1(screen_cursor_down, 1); 
        case CUF: 
        case HPR: 
            CALL_CSI_HANDLER1(screen_cursor_forward, 1); 
        case CUB: 
            CALL_CSI_HANDLER1(screen_cursor_back1, 1); 
        case CNL:  
            CALL_CSI_HANDLER1(screen_cursor_down1, 1); 
        case CPL:  
            CALL_CSI_HANDLER1(screen_cursor_up1, 1); 
        case CHA: 
        case HPA: 
            CALL_CSI_HANDLER1(screen_cursor_to_column, 1); 
        case VPA: 
            CALL_CSI_HANDLER1(screen_cursor_to_line, 1); 
        case CBT:
            CALL_CSI_HANDLER1(screen_backtab, 1); 
        case CHT:
            CALL_CSI_HANDLER1(screen_tabn, 1); 
        case CUP:  
        case HVP: 
            CALL_CSI_HANDLER2(screen_cursor_position, 1, 1); 
        case ED: 
            CALL_CSI_HANDLER1P(screen_erase_in_display, 0, '?'); 
        case EL: 
            CALL_CSI_HANDLER1P(screen_erase_in_line, 0, '?'); 
        case IL: 
            CALL_CSI_HANDLER1(screen_insert_lines, 1); 
        case DL: 
            CALL_CSI_HANDLER1(screen_delete_lines, 1); 
        case DCH: 
            CALL_CSI_HANDLER1(screen_delete_characters, 1); 
        case ECH: 
            CALL_CSI_HANDLER1(screen_erase_characters, 1); 
        case DA: 
            CALL_CSI_HANDLER1P(report_device_attributes, 0, '>'); 
        case TBC: 
            CALL_CSI_HANDLER1(screen_clear_tab_stop, 0); 
        case SM: 
            SET_MODE(screen_set_mode); 
        case RM: 
            SET_MODE(screen_reset_mode); 
        case SGR: 
            CSI_HANDLER_MULTIPLE(select_graphic_rendition); 
        case DSR: 
            CALL_CSI_HANDLER1P(report_device_status, 0, '?'); 
        case SC: 
            CALL_CSI_HANDLER1P(save_cursor, 0, '?'); 
        case RC: 
            CALL_CSI_HANDLER1P(restore_cursor, 0, '?'); 
        case DECSTBM: 
            CALL_CSI_HANDLER2(screen_set_margins, 0, 0); 
        case DECSCUSR: 
            CALL_CSI_HANDLER1M(screen_set_cursor, 1); 
        case SU:
            CALL_CSI_HANDLER1(screen_indexn, 1); 
        case SD:
            CALL_CSI_HANDLER1(screen_reverse_indexn, 1); 
        default:
            REPORT_ERROR("Unknown CSI code: 0x%x", code);
    }
}
// }}}

// DCS mode {{{
static inline void
dispatch_dcs(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
    PyObject *string = NULL;
    if (screen->parser_buf_pos < 2) return;
    switch(screen->parser_buf[0]) {
        case '+':
            if (screen->parser_buf[1] == 'q') {
                string = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + 2, screen->parser_buf_pos - 2);
                if (string != NULL) {
                    REPORT_OSC(screen_request_capabilities, string);
                    screen_request_capabilities(screen, string);
                    Py_CLEAR(string);
                }
            } else {
                REPORT_ERROR("Unrecognized DCS+ code: 0x%x", screen->parser_buf[1]);
            }
            break;
        default:
            REPORT_ERROR("Unrecognized DCS code: 0x%x", screen->parser_buf[0]);
            break;
    }
}
// }}}

// Parse loop {{{

static inline bool
accumulate_osc(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
    switch(ch) {
        case ST:
            return true;
        case ESC_ST:
            if (screen->parser_buf_pos > 0 && screen->parser_buf[screen->parser_buf_pos - 1] == ESC) {
                screen->parser_buf_pos--;
                return true;
            }
        case BEL:
            return true;
        case NUL:
        case DEL:
            break;
        default:
            if (screen->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                REPORT_ERROR("OSC sequence too long, truncating.");
                return true;
            }
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
    }
    return false;
}

static inline bool
accumulate_dcs(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
    switch(ch) {
        case ST:
            return true;
        case NUL:
        case DEL:
            break;
        case ESC:
START_ALLOW_CASE_RANGE
        case 32 ... 126:
END_ALLOW_CASE_RANGE
            if (screen->parser_buf_pos > 0 && screen->parser_buf[screen->parser_buf_pos-1] == ESC) {
                if (ch == '\\') { screen->parser_buf_pos--; return true; }
                REPORT_ERROR("DCS sequence contained non-printable character: 0x%x ignoring the sequence", ESC);
                SET_STATE(ESC); return false;
            }
            if (screen->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                REPORT_ERROR("DCS sequence too long, truncating.");
                return true;
            }
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
        default:
            REPORT_ERROR("DCS sequence contained non-printable character: 0x%x ignoring the sequence", ch);
    }
    return false;
}


static inline bool
accumulate_oth(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
    switch(ch) {
        case ST:
            return true;
        case ESC_ST:
            if (screen->parser_buf_pos > 0 && screen->parser_buf[screen->parser_buf_pos - 1] == ESC) {
                screen->parser_buf_pos--;
                return true;
            }
        default:
            if (screen->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                REPORT_ERROR("OTH sequence too long, truncating.");
                return true;
            }
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
    }
    return false;
}


static inline bool
accumulate_csi(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
#define ENSURE_SPACE \
    if (screen->parser_buf_pos > PARSER_BUF_SZ - 1) { \
        REPORT_ERROR("CSI sequence too long, ignoring"); \
        SET_STATE(0); \
        return false; \
    } 

    switch(ch) {
        IS_DIGIT
        CSI_SECONDARY
            ENSURE_SPACE;
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
        case '?':
        case '>':
        case '!':
            if (screen->parser_buf_pos != 0) {
                REPORT_ERROR("Invalid character in CSI: 0x%x, ignoring the sequence", ch);
                SET_STATE(0);
                return false;
            }
            ENSURE_SPACE;
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
START_ALLOW_CASE_RANGE
        case 'a' ... 'z':
        case 'A' ... 'Z':
END_ALLOW_CASE_RANGE
        case '@':
        case '`':
        case '{':
        case '|':
        case '}':
        case '~':
            screen->parser_buf[screen->parser_buf_pos] = ch;
            return true;
        case BEL:
        case BS:
        case HT:
        case LF:
        case VT:
        case FF:
        case NEL:
        case CR:
        case SO:
        case SI:
        case IND:
        case RI:
        case HTS:
            handle_normal_mode_char(screen, ch, dump_callback);
            break;
        case NUL: 
        case DEL: 
            break;  // no-op
        default:
            REPORT_ERROR("Invalid character in CSI: 0x%x, ignoring the sequence", ch);
            SET_STATE(0);
            return false;

    }
    return false;
#undef ENSURE_SPACE
}

static inline void
dispatch_unicode_char(Screen *screen, uint32_t codepoint, PyObject DUMP_UNUSED *dump_callback) {
#define HANDLE(name) handle_##name(screen, codepoint, dump_callback); break
    switch(screen->parser_state) {
        case ESC:
            HANDLE(esc_mode_char);
        case CSI:
            if (accumulate_csi(screen, codepoint, dump_callback)) { dispatch_csi(screen, dump_callback); SET_STATE(0); }
            break;
        case OSC:
            if (accumulate_osc(screen, codepoint, dump_callback)) { dispatch_osc(screen, dump_callback); SET_STATE(0); }
            break;
        case APC:
            if (accumulate_oth(screen, codepoint, dump_callback)) { SET_STATE(0); }
            break;
        case PM:
            if (accumulate_oth(screen, codepoint, dump_callback)) { SET_STATE(0); }
            break;
        case DCS:
            if (accumulate_dcs(screen, codepoint, dump_callback)) { dispatch_dcs(screen, dump_callback); SET_STATE(0); }
            if (screen->parser_state == ESC) { HANDLE(esc_mode_char); }
            break;
        default:
            HANDLE(normal_mode_char);
    }
#undef HANDLE
}

static inline void 
_parse_bytes(Screen *screen, uint8_t *buf, Py_ssize_t len, PyObject DUMP_UNUSED *dump_callback) {
    uint32_t prev = screen->utf8_state, codepoint = 0;
    for (unsigned int i = 0; i < len; i++) {
        if (screen->use_latin1) dispatch_unicode_char(screen, latin1_charset[buf[i]], dump_callback);
        else {
            switch (decode_utf8(&screen->utf8_state, &codepoint, buf[i])) {
                case UTF8_ACCEPT:
                    dispatch_unicode_char(screen, codepoint, dump_callback);
                    break;
                case UTF8_REJECT:
                    screen->utf8_state = UTF8_ACCEPT;
                    if (prev != UTF8_ACCEPT) i--;
                    break;
            }
            prev = screen->utf8_state;
        }
    }
FLUSH_DRAW;
}
// }}}

// Boilerplate {{{
#ifdef DUMP_COMMANDS
#define FNAME(x) x##_dump
#else
#define FNAME(x) x
#endif

PyObject*
FNAME(parse_bytes)(PyObject UNUSED *self, PyObject *args) {
    PyObject *dump_callback = NULL;
    Py_buffer pybuf;
    Screen *screen;
#ifdef DUMP_COMMANDS
    if (!PyArg_ParseTuple(args, "OO!y*", &dump_callback, &Screen_Type, &screen, &pybuf)) return NULL;
#else
    if (!PyArg_ParseTuple(args, "O!y*", &Screen_Type, &screen, &pybuf)) return NULL;
#endif
    _parse_bytes(screen, pybuf.buf, pybuf.len, dump_callback);
    Py_RETURN_NONE;
}

PyObject*
FNAME(read_bytes)(PyObject UNUSED *self, PyObject *args) {
    PyObject *dump_callback = NULL;
    Py_ssize_t len;
    Screen *screen;
    int fd;
#ifdef DUMP_COMMANDS
    if (!PyArg_ParseTuple(args, "OOi", &dump_callback, &screen, &fd)) return NULL;
#else
    if (!PyArg_ParseTuple(args, "Oi", &screen, &fd)) return NULL;
#endif

    while(true) {
        Py_BEGIN_ALLOW_THREADS;
        len = read(fd, screen->read_buf, READ_BUF_SZ);
        Py_END_ALLOW_THREADS;
        if (len == -1) {
            if (errno == EINTR) continue;
            if (errno == EIO) { Py_RETURN_FALSE; }
            return PyErr_SetFromErrno(PyExc_OSError);
        }
        /* PyObject_Print(Py_BuildValue("y#", screen->read_buf, len), stderr, 0); */
        break;
    }
    _parse_bytes(screen, screen->read_buf, len, dump_callback);
    if(len > 0) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}
#undef FNAME
// }}}
