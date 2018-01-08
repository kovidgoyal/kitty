/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "control-codes.h"
#include "screen.h"
#include "graphics.h"
#include <time.h>

extern PyTypeObject Screen_Type;

// utils {{{
static uint64_t pow10[] = {
    1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000, 1000000000, 10000000000
};

static inline uint64_t
utoi(uint32_t *buf, unsigned int sz) {
    uint64_t ans = 0;
    uint32_t *p = buf;
    // Ignore leading zeros
    while(sz > 0) {
        if (*p == '0') { p++; sz--; }
        else break;
    }
    if (sz < sizeof(pow10)/sizeof(pow10[0])) {
        for (int i = sz-1, j=0; i >= 0; i--, j++) {
            ans += (p[i] - '0') * pow10[j];
        }
    }
    return ans;
}


static inline const char*
utf8(char_type codepoint) {
    if (!codepoint) return "";
    static char buf[8];
    int n = encode_utf8(codepoint, buf);
    buf[n] = 0;
    return buf;
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
_report_params(PyObject *dump_callback, const char *name, unsigned int *params, unsigned int count, Region *r) {
    static char buf[MAX_PARAMS*3] = {0};
    unsigned int i, p=0;
    if (r) p += snprintf(buf + p, sizeof(buf) - 2, "%u %u %u %u ", r->top, r->left, r->bottom, r->right);
    for(i = 0; i < count && p < MAX_PARAMS*3-20; i++) {
        int n = snprintf(buf + p, MAX_PARAMS*3 - p, "%u ", params[i]);
        if (n < 0) break;
        p += n;
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
#define REPORT_VA_COMMAND(...) Py_XDECREF(PyObject_CallFunction(dump_callback, __VA_ARGS__)); PyErr_Clear();

#define REPORT_DRAW(ch) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sC", "draw", ch)); PyErr_Clear();

#define REPORT_PARAMS(name, params, num, region) _report_params(dump_callback, name, params, num_params, region)

#define FLUSH_DRAW \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sO", "draw", Py_None)); PyErr_Clear();

#define REPORT_OSC(name, string) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sO", #name, string)); PyErr_Clear();

#define REPORT_OSC2(name, code, string) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sIO", #name, code, string)); PyErr_Clear();

#else

#define DUMP_UNUSED UNUSED

#define REPORT_ERROR(...) fprintf(stderr, "%s ", ERROR_PREFIX); fprintf(stderr, __VA_ARGS__); fprintf(stderr, "\n");

#define REPORT_COMMAND(...)
#define REPORT_VA_COMMAND(...)
#define REPORT_DRAW(ch)
#define REPORT_PARAMS(...)
#define FLUSH_DRAW
#define REPORT_OSC(name, string)
#define REPORT_OSC2(name, code, string)

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
        case APC:
        case PM:
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
                            screen_use_latin1(screen, true);
                            break;
                        case 'G':
                            REPORT_COMMAND(screen_use_latin1, 0);
                            screen_use_latin1(screen, false);
                            break;
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
                case ' ':
                    switch(ch) {
                        case 'F':
                        case 'G':
                            REPORT_COMMAND(screen_set_8bit_controls, ch == 'G');
                            screen_set_8bit_controls(screen, ch == 'G');
                            break;
                        default:
                            REPORT_ERROR("Unhandled ESC SP escape code: 0x%x", ch); break;
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
#define SET_COLOR(name) REPORT_OSC2(name, code, string); name(screen, code, string);
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
            case 12:
            case 17:
            case 19:
            case 110:
            case 111:
            case 112:
            case 117:
            case 119:
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
        case ':': \
        case '"': \
        case '*': \
        case '\'': \
        case ' ': \
        case '$':


static inline void
screen_cursor_up2(Screen *s, unsigned int count) { screen_cursor_up(s, count, false, -1); }
static inline void
screen_cursor_back1(Screen *s, unsigned int count) { screen_cursor_back(s, count, -1); }
static inline void
screen_tabn(Screen *s, unsigned int count) { for (index_type i=0; i < MAX(1, count); i++) screen_tab(s); }
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

static inline const char*
repr_csi_params(unsigned int *params, unsigned int num_params) {
    if (!num_params) return "";
    static char buf[256];
    unsigned int pos = 0;
    while (pos < 200 && num_params && sizeof(buf) > pos + 1) {
        const char *fmt = num_params > 1 ? "%u " : "%u";
        int ret = snprintf(buf + pos, sizeof(buf) - pos - 1, fmt, params[num_params--]);
        if (ret < 0) return "An error occurred formatting the params array";
        pos += ret;
    }
    buf[pos] = 0;
    return buf;
}

static inline void
parse_sgr(Screen *screen, uint32_t *buf, unsigned int num, unsigned int *params, PyObject DUMP_UNUSED *dump_callback, const char *report_name DUMP_UNUSED, Region *region) {
    enum State { START, NORMAL, MULTIPLE, COLOR, COLOR1, COLOR3 };
    enum State state = START;
    unsigned int num_params, num_start, i;

#define READ_PARAM { params[num_params++] = utoi(buf + num_start, i - num_start); }
#define SEND_SGR { REPORT_PARAMS(report_name, params, num_params, region); select_graphic_rendition(screen, params, num_params, region); state = START; num_params = 0; }

    for (i=0, num_start=0, num_params=0; i < num && num_params < MAX_PARAMS; i++) {
        switch(buf[i]) {
            IS_DIGIT
                switch(state) {
                    case START:
                        num_start = i;
                        state = NORMAL;
                        num_params = 0;
                        break;
                    default:
                        break;
                }
                break;
            case ';':
                switch(state) {
                    case START:
                        params[num_params++] = 0;
                        SEND_SGR;
                        break;
                    case NORMAL:
                        READ_PARAM;
                        switch(params[0]) {
                            case 38:
                            case 48:
                            case 58:
                                state = COLOR;
                                num_start = i + 1;
                                break;
                            default:
                                SEND_SGR;
                                break;
                        }
                        break;
                    case MULTIPLE:
                        READ_PARAM;
                        SEND_SGR;
                        break;
                    case COLOR:
                        READ_PARAM;
                        switch(params[1]) {
                            case 2:
                                state = COLOR3;
                                break;
                            case 5:
                                state = COLOR1;
                                break;
                            default:
                                REPORT_ERROR("Invalid SGR color code with unknown color type: %u", params[1]);
                                return;
                        }
                        num_start = i + 1;
                        break;
                    case COLOR1:
                        READ_PARAM;
                        SEND_SGR;
                        break;
                    case COLOR3:
                        READ_PARAM;
                        if (num_params == 5) { SEND_SGR; }
                        else num_start = i + 1;
                        break;
                }
                break;
            case ':':
                switch(state) {
                    case START:
                        REPORT_ERROR("Invalid SGR code containing ':' at an invalid location: %u", i);
                        return;
                    case NORMAL:
                        READ_PARAM;
                        state = MULTIPLE;
                        num_start = i + 1;
                        break;
                    case MULTIPLE:
                        READ_PARAM;
                        num_start = i + 1;
                        break;
                    case COLOR:
                    case COLOR1:
                    case COLOR3:
                        REPORT_ERROR("Invalid SGR code containing disallowed character: %s", utf8(buf[i]));
                        return;
                }
                break;
            default:
                REPORT_ERROR("Invalid SGR code containing disallowed character: %s", utf8(buf[i]));
                return;
        }
    }
    switch(state) {
        case START:
            if (num_params < MAX_PARAMS) params[num_params++] = 0;
            SEND_SGR;
            break;
        case COLOR1:
        case NORMAL:
        case MULTIPLE:
            if (i > num_start && num_params < MAX_PARAMS) { READ_PARAM; }
            if (num_params) { SEND_SGR; }
            else { REPORT_ERROR("Incomplete SGR code"); }
            break;
        case COLOR:
            REPORT_ERROR("Invalid SGR code containing incomplete semi-colon separated color sequence");
            break;
        case COLOR3:
            if (i > num_start && num_params < MAX_PARAMS) READ_PARAM;
            if (num_params != 5) {
                REPORT_ERROR("Invalid SGR code containing incomplete semi-colon separated color sequence");
                break;
            }
            if (num_params) { SEND_SGR; }
            else { REPORT_ERROR("Incomplete SGR code"); }
            break;
    }
#undef READ_PARAM
#undef SEND_SGR
}

static inline unsigned int
parse_region(Region *r, uint32_t *buf, unsigned int num) {
    unsigned int i, start, params[8] = {0}, num_params=0;
    for (i=0, start=0; i < num && num_params < 4; i++) {
        switch(buf[i]) {
            IS_DIGIT
                break;
            default:
                if (i > start) params[num_params++] = utoi(buf + start, i - start);
                else if (i == start && buf[i] == ';') params[num_params++] = 0;
                start = i + 1;
                break;
        }
    }

    switch(num_params) {
        case 0:
            break;
        case 1:
            r->top = params[0];
            break;
        case 2:
            r->top = params[0]; r->left = params[1];
            break;
        case 3:
            r->top = params[0]; r->left = params[1]; r->bottom = params[2];
            break;
        default:
            r->top = params[0]; r->left = params[1]; r->bottom = params[2]; r->right = params[3];
            break;
    }
    return i;
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

#define CALL_CSI_HANDLER1S(name, defval) \
    p1 = num_params > 0 ? params[0] : defval; \
    REPORT_COMMAND(name, p1, start_modifier); \
    name(screen, p1, start_modifier); \
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

    char start_modifier = 0, end_modifier = 0;
    uint32_t *buf = screen->parser_buf, code = screen->parser_buf[screen->parser_buf_pos];
    unsigned int num = screen->parser_buf_pos, start, i, num_params=0, p1, p2;
    static unsigned int params[MAX_PARAMS] = {0};
    bool private;
    if (buf[0] == '>' || buf[0] == '?' || buf[0] == '!') {
        start_modifier = (char)screen->parser_buf[0];
        buf++; num--;
    }
    if (code == SGR && !start_modifier) {
        parse_sgr(screen, buf, num, params, dump_callback, "select_graphic_rendition", NULL);
        return;
    }
    if (code == 'r' && !start_modifier && num > 0 && buf[num - 1] == '$') {
        // DECCARA
        Region r = {0};
        unsigned int consumed = parse_region(&r, buf, --num);
        num -= consumed; buf += consumed;
        parse_sgr(screen, buf, num, params, dump_callback, "deccara", &r);
        return;
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
            CALL_CSI_HANDLER1S(report_device_attributes, 0);
        case TBC:
            CALL_CSI_HANDLER1(screen_clear_tab_stop, 0);
        case SM:
            SET_MODE(screen_set_mode);
        case RM:
            SET_MODE(screen_reset_mode);
        case DSR:
            CALL_CSI_HANDLER1P(report_device_status, 0, '?');
        case SC:
            CALL_CSI_HANDLER1P(save_cursor, 0, '?');
        case RC:
            CALL_CSI_HANDLER1P(restore_cursor, 0, '?');
        case 'r':
            if (!start_modifier && !end_modifier) {
                // DECSTBM
                CALL_CSI_HANDLER2(screen_set_margins, 0, 0);
            }
            REPORT_ERROR("Unknown CSI r sequence with start and end modifiers: '%c' '%c'", start_modifier, end_modifier);
            break;
        case 'x':
            if (!start_modifier && end_modifier == '*') {
                CALL_CSI_HANDLER1(screen_decsace, 0);
            }
            REPORT_ERROR("Unknown CSI x sequence with start and end modifiers: '%c' '%c'", start_modifier, end_modifier);
            break;
        case DECSCUSR:
            CALL_CSI_HANDLER1M(screen_set_cursor, 1);
        case SU:
            CALL_CSI_HANDLER1(screen_scroll, 1);
        case SD:
            CALL_CSI_HANDLER1(screen_reverse_scroll, 1);
        case DECSTR:
            if (end_modifier == '$') {
                // DECRQM
                CALL_CSI_HANDLER1P(report_mode_status, 0, '?');
            } else {
                REPORT_ERROR("Unknown DECSTR CSI sequence with start and end modifiers: '%c' '%c'", start_modifier, end_modifier);
            }
            break;
        default:
            REPORT_ERROR("Unknown CSI code: '%s' with start_modifier: '%c' and end_modifier: '%c' and parameters: '%s'", utf8(code), start_modifier, end_modifier, repr_csi_params(params, num_params));
    }
}
// }}}

// DCS mode {{{

static inline bool
startswith(const uint32_t *string, size_t sz, const char *prefix) {
    size_t l = strlen(prefix);
    if (sz < l) return false;
    for (size_t i = 0; i < l; i++) {
        if (string[i] != (unsigned char)prefix[i]) return false;
    }
    return true;
}

static inline void
dispatch_dcs(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
    if (screen->parser_buf_pos < 2) return;
    switch(screen->parser_buf[0]) {
        case '+':
        case '$':
            if (screen->parser_buf[1] == 'q') {
                PyObject *string = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + 2, screen->parser_buf_pos - 2);
                if (string != NULL) {
                    REPORT_OSC2(screen_request_capabilities, (char)screen->parser_buf[0], string);
                    screen_request_capabilities(screen, (char)screen->parser_buf[0], string);
                    Py_DECREF(string);
                } else PyErr_Clear();
            } else {
                REPORT_ERROR("Unrecognized DCS %c code: 0x%x", (char)screen->parser_buf[0], screen->parser_buf[1]);
            }
            break;
        case '@':
            if (startswith(screen->parser_buf + 1, screen->parser_buf_pos - 2, "kitty-cmd{")) {
                PyObject *cmd = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + 10, screen->parser_buf_pos - 10);
                if (cmd != NULL) {
                    REPORT_OSC2(screen_handle_cmd, (char)screen->parser_buf[0], cmd);
                    screen_handle_cmd(screen, cmd);
                    Py_DECREF(cmd);
                } else PyErr_Clear();
            } else {
                REPORT_ERROR("Unrecognized DCS @ code: 0x%x", screen->parser_buf[1]);
            }
            break;
        default:
            REPORT_ERROR("Unrecognized DCS code: 0x%x", screen->parser_buf[0]);
            break;
    }
}
// }}}

// APC mode {{{

static inline void
parse_graphics_code(Screen *screen, PyObject UNUSED *dump_callback) {
    unsigned int pos = 1;
    enum GR_STATES { KEY, EQUAL, UINT, INT, FLAG, AFTER_VALUE, PAYLOAD };
    enum GR_STATES state = KEY, value_state = FLAG;
    enum KEYS {
        action='a',
        delete_action='d',
        transmission_type='t',
        compressed='o',
        format = 'f',
        more = 'm',
        id = 'i',
        width = 'w',
        height = 'h',
        x_offset = 'x',
        y_offset = 'y',
        data_height = 'v',
        data_width = 's',
        data_sz = 'S',
        data_offset = 'O',
        num_cells = 'c',
        num_lines = 'r',
        cell_x_offset = 'X',
        cell_y_offset = 'Y',
        z_index = 'z'
    };
    enum KEYS key = 'a';
    static GraphicsCommand g;
    unsigned int i, code;
    unsigned long lcode;
    bool is_negative;
    memset(&g, 0, sizeof(g));
    static uint8_t payload[4096];
    size_t sz;
    const char *err;

    while (pos < screen->parser_buf_pos) {
        switch(state) {

            case KEY:
                key = screen->parser_buf[pos++];
                switch(key) {
#define KS(n, vs) case n: state = EQUAL; value_state = vs; break
#define U(x) KS(x, UINT)
                    KS(action, FLAG); KS(delete_action, FLAG); KS(transmission_type, FLAG); KS(compressed, FLAG); KS(z_index, INT);
                    U(format); U(more); U(id); U(data_sz); U(data_offset); U(width); U(height); U(x_offset); U(y_offset); U(data_height); U(data_width); U(num_cells); U(num_lines); U(cell_x_offset); U(cell_y_offset);
#undef U
#undef KS
                    default:
                        REPORT_ERROR("Malformed graphics control block, invalid key character: 0x%x", key);
                        return;
                }
                break;

            case EQUAL:
                if (screen->parser_buf[pos++] != '=') {
                    REPORT_ERROR("Malformed graphics control block, no = after key, found: 0x%x instead", screen->parser_buf[pos-1]);
                    return;
                }
                state = value_state;
                break;

            case FLAG:
                switch(key) {
#define F(a) case a: g.a = screen->parser_buf[pos++] & 0xff; break
                    F(action); F(delete_action); F(transmission_type); F(compressed);
                    default:
                        break;
                }
                state = AFTER_VALUE;
                break;
#undef F

            case INT:
#define READ_UINT \
                for (i = pos; i < MIN(screen->parser_buf_pos, pos + 10); i++) { \
                    if (screen->parser_buf[i] < '0' || screen->parser_buf[i] > '9') break; \
                } \
                if (i == pos) { REPORT_ERROR("Malformed graphics control block, expecting an integer value for key: %c", key & 0xFF); return; } \
                lcode = utoi(screen->parser_buf + pos, i - pos); pos = i; \
                if (lcode > UINT32_MAX) { REPORT_ERROR("id is too large"); return; } \
                code = lcode;

                is_negative = false;
                if(screen->parser_buf[pos] == '-') { is_negative = true; pos++; }
#define U(x) case x: g.x = is_negative ? 0 - (int32_t)code : (int32_t)code; break
                READ_UINT;
                switch(key) {
                    U(z_index);
                    default: break;
                }
                state = AFTER_VALUE;
                break;
#undef U
            case UINT:
                READ_UINT;
#define U(x) case x: g.x = code; break
                switch(key) {
                    U(format); U(more); U(id); U(data_sz); U(data_offset); U(width); U(height); U(x_offset); U(y_offset); U(data_height); U(data_width); U(num_cells); U(num_lines); U(cell_x_offset); U(cell_y_offset);
                    default: break;
                }
                state = AFTER_VALUE;
                break;
#undef U
#undef SET_ATTR
#undef READ_UINT
            case AFTER_VALUE:
                switch (screen->parser_buf[pos++]) {
                    case ',':
                        state = KEY;
                        break;
                    case ';':
                        state = PAYLOAD;
                        break;
                    default:
                        REPORT_ERROR("Malformed graphics control block, expecting a comma or semi-colon after a value, found: 0x%x", screen->parser_buf[pos - 1]);
                        return;
                }
                break;

            case PAYLOAD:
                sz = screen->parser_buf_pos - pos;
                err = base64_decode(screen->parser_buf + pos, sz, payload, sizeof(payload), &g.payload_sz);
                if (err != NULL) { REPORT_ERROR("Failed to parse graphics command payload with error: %s", err); return; }
                pos = screen->parser_buf_pos;
                break;
        }
    }
    switch(state) {
        case EQUAL:
            REPORT_ERROR("Malformed graphics control block, no = after key"); return;
        case INT:
        case UINT:
            REPORT_ERROR("Malformed graphics control block, expecting an integer value"); return;
        case FLAG:
            REPORT_ERROR("Malformed graphics control block, expecting a flag value"); return;
        default:
            break;
    }
#define A(x) #x, g.x
#define U(x) #x, (unsigned int)(g.x)
#define I(x) #x, (int)(g.x)
    REPORT_VA_COMMAND("s {sc sc sc sc sI sI sI sI sI  sI sI sI sI sI sI sI sI sI sI  sI si} y#", "graphics_command",
            A(action), A(delete_action), A(transmission_type), A(compressed),
            U(format), U(more), U(id), U(data_sz), U(data_offset),
            U(width), U(height), U(x_offset), U(y_offset), U(data_height), U(data_width), U(num_cells), U(num_lines), U(cell_x_offset), U(cell_y_offset),
            U(payload_sz), I(z_index),
            payload, g.payload_sz
    );
#undef U
#undef A
#undef I
    screen_handle_graphics_command(screen, &g, payload);
}

static inline void
dispatch_apc(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
    if (screen->parser_buf_pos < 2) return;
    switch(screen->parser_buf[0]) {
        case 'G':
            parse_graphics_code(screen, dump_callback);
            break;
        default:
            REPORT_ERROR("Unrecognized APC code: 0x%x", screen->parser_buf[0]);
            break;
    }
}

// }}}

// PM mode {{{
static inline void
dispatch_pm(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
    if (screen->parser_buf_pos < 2) return;
    switch(screen->parser_buf[0]) {
        default:
            REPORT_ERROR("Unrecognized PM code: 0x%x", screen->parser_buf[0]);
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
        case BEL:
            return true;
        case NUL:
        case DEL:
            break;
        case ESC_ST:
            if (screen->parser_buf_pos > 0 && screen->parser_buf[screen->parser_buf_pos - 1] == ESC) {
                screen->parser_buf_pos--;
                return true;
            }
            /* fallthrough */
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
            /* fallthrough */
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
            if (accumulate_oth(screen, codepoint, dump_callback)) { dispatch_apc(screen, dump_callback); SET_STATE(0); }
            break;
        case PM:
            if (accumulate_oth(screen, codepoint, dump_callback)) { dispatch_pm(screen, dump_callback); SET_STATE(0); }
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

extern uint32_t *latin1_charset;

static inline void
_parse_bytes(Screen *screen, uint8_t *buf, Py_ssize_t len, PyObject DUMP_UNUSED *dump_callback) {
    uint32_t prev = screen->utf8_state;
    for (unsigned int i = 0; i < (unsigned int)len; i++) {
        if (screen->use_latin1) dispatch_unicode_char(screen, latin1_charset[buf[i]], dump_callback);
        else {
            switch (decode_utf8(&screen->utf8_state, &screen->utf8_codepoint, buf[i])) {
                case UTF8_ACCEPT:
                    dispatch_unicode_char(screen, screen->utf8_codepoint, dump_callback);
                    break;
                case UTF8_REJECT:
                    screen->utf8_state = UTF8_ACCEPT;
                    if (prev != UTF8_ACCEPT && i > 0) i--;
                    break;
            }
            prev = screen->utf8_state;
        }
    }
FLUSH_DRAW;
}
// }}}

// Entry points {{{
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


void
FNAME(parse_worker)(Screen *screen, PyObject *dump_callback) {
#ifdef DUMP_COMMANDS
    Py_XDECREF(PyObject_CallFunction(dump_callback, "sy#", "bytes", screen->read_buf, screen->read_buf_sz)); PyErr_Clear();
#endif
    _parse_bytes(screen, screen->read_buf, screen->read_buf_sz, dump_callback);
#undef FNAME
}
// }}}
