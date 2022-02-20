/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Need _POSIX_C_SOURCE for strtok_r
#define _POSIX_C_SOURCE 200809L

#include "data-types.h"
#include "control-codes.h"
#include "screen.h"
#include "graphics.h"
#include "charsets.h"
#include "monotonic.h"
#include <time.h>

extern PyTypeObject Screen_Type;
#define EXTENDED_OSC_SENTINEL 0x1bu
#define PENDING_BUF_INCREMENT (16u * 1024u)

// utils {{{
static const uint64_t pow_10_array[] = {
    1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000, 1000000000, 10000000000
};

static int64_t
utoi(const uint32_t *buf, unsigned int sz) {
    int64_t ans = 0;
    const uint32_t *p = buf;
    int mult = 1;
    if (sz && *p == '-') {
        mult = -1; p++; sz--;
    }
    // Ignore leading zeros
    while(sz > 0) {
        if (*p == '0') { p++; sz--; }
        else break;
    }
    if (sz < sizeof(pow_10_array)/sizeof(pow_10_array[0])) {
        for (int i = sz-1, j=0; i >= 0; i--, j++) {
            ans += (p[i] - '0') * pow_10_array[j];
        }
    }
    return ans * mult;
}


static const char*
utf8(char_type codepoint) {
    if (!codepoint) return "";
    static char buf[8];
    int n = encode_utf8(codepoint, buf);
    buf[n] = 0;
    return buf;
}

// }}}

// Macros {{{
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
_report_params(PyObject *dump_callback, const char *name, int *params, unsigned int count, Region *r) {
    static char buf[MAX_PARAMS*3] = {0};
    unsigned int i, p=0;
    if (r) p += snprintf(buf + p, sizeof(buf) - 2, "%u %u %u %u ", r->top, r->left, r->bottom, r->right);
    for(i = 0; i < count && p < MAX_PARAMS*3-20; i++) {
        int n = snprintf(buf + p, MAX_PARAMS*3 - p, "%i ", params[i]);
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
    Py_XDECREF(PyObject_CallFunction(dump_callback, "siO", #name, code, string)); PyErr_Clear();

#define REPORT_HYPERLINK(id, url) \
    Py_XDECREF(PyObject_CallFunction(dump_callback, "szz", "set_active_hyperlink", id, url)); PyErr_Clear();

#else

#define DUMP_UNUSED UNUSED

#define REPORT_ERROR(...) log_error(ERROR_PREFIX " " __VA_ARGS__);

#define REPORT_COMMAND(...)
#define REPORT_VA_COMMAND(...)
#define REPORT_DRAW(ch)
#define REPORT_PARAMS(...)
#define FLUSH_DRAW
#define REPORT_OSC(name, string)
#define REPORT_OSC2(name, code, string)
#define REPORT_HYPERLINK(id, url)

#endif

#define SET_STATE(state) screen->parser_state = state; screen->parser_buf_pos = 0;
// }}}

// Normal mode {{{
static void
screen_nel(Screen *screen) { screen_carriage_return(screen); screen_linefeed(screen); }

static void
dispatch_normal_mode_char(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
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
            screen_draw(screen, ch, true);
            break;
    }
#undef CALL_SCREEN_HANDLER
} // }}}

// Esc mode {{{
static void
dispatch_esc_mode_char(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
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
                case ESC_DECKPNM:
                    CALL_ED(screen_normal_keypad_mode); break;
                case ESC_DECKPAM:
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

static bool
parse_osc_8(char *buf, char **id, char **url) {
    char *boundary = strstr(buf, ";");
    if (boundary == NULL) return false;
    *boundary = 0;
    if (*(boundary + 1)) *url = boundary + 1;
    char *save = NULL, *token = strtok_r(buf, ":", &save);
    while (token != NULL) {
        size_t len = strlen(token);
        if (len > 3 && token[0] == 'i' && token[1] == 'd' && token[2] == '=' && token[3]) {
            *id = token + 3;
            break;
        }
        token = strtok_r(NULL, ":", &save);
    }
    return true;
}

static void
dispatch_hyperlink(Screen *screen, size_t pos, size_t size, PyObject DUMP_UNUSED *dump_callback) {
    // since the spec says only ASCII printable chars are allowed in OSC 8, we
    // can just convert to char* directly
    if (!size) return;  // ignore empty OSC 8 since it must have two semi-colons to be valid, which means one semi-colon here
    char *id = NULL, *url = NULL;
    char *data = malloc(size + 1);
    if (!data) fatal("Out of memory");
    for (size_t i = 0; i < size; i++) {
        data[i] = screen->parser_buf[i + pos] & 0x7f;
        if (data[i] < 32 || data[i] > 126) data[i] = '_';
    }
    data[size] = 0;

    if (parse_osc_8(data, &id, &url)) {
        REPORT_HYPERLINK(id, url);
        set_active_hyperlink(screen, id, url);
    } else {
        REPORT_ERROR("Ignoring malformed OSC 8 code");
    }

    free(data);
}

static void
continue_osc_52(Screen *screen) {
    screen->parser_buf[0] = '5'; screen->parser_buf[1] = '2'; screen->parser_buf[2] = ';';
    screen->parser_buf[3] = ';'; screen->parser_buf_pos = 4;
}

static bool
is_extended_osc(const Screen *screen) {
    return screen->parser_buf_pos > 2 && screen->parser_buf[0] == EXTENDED_OSC_SENTINEL && screen->parser_buf[1] == 1 && screen->parser_buf[2] == ';';
}

static void
dispatch_osc(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
#define DISPATCH_OSC_WITH_CODE(name) REPORT_OSC2(name, code, string); name(screen, code, string);
#define DISPATCH_OSC(name) REPORT_OSC(name, string); name(screen, string);
#define START_DISPATCH {\
    PyObject *string = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + i, limit - i); \
    if (string) {
#define END_DISPATCH Py_CLEAR(string); } PyErr_Clear(); break; }

    const unsigned int limit = screen->parser_buf_pos;
    int code=0;
    unsigned int i;
    for (i = 0; i < MIN(limit, 5u); i++) {
        if (screen->parser_buf[i] < '0' || screen->parser_buf[i] > '9') break;
    }
    if (i > 0) {
        code = utoi(screen->parser_buf, i);
        if (i < limit && screen->parser_buf[i] == ';') i++;
    } else {
        if (is_extended_osc(screen)) {
            // partial OSC 52
            i = 3;
            code = -52;
        }
    }
    switch(code) {
        case 0:
            START_DISPATCH
            DISPATCH_OSC(set_title);
            DISPATCH_OSC(set_icon);
            END_DISPATCH
        case 1:
            START_DISPATCH
            DISPATCH_OSC(set_icon);
            END_DISPATCH
        case 2:
            START_DISPATCH
            DISPATCH_OSC(set_title);
            END_DISPATCH
        case 4:
        case 104:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(set_color_table_color);
            END_DISPATCH
        case 7:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(process_cwd_notification);
            END_DISPATCH
        case 8:
            dispatch_hyperlink(screen, i, limit-i, dump_callback);
            break;
        case 9:
        case 99:
        case 777:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(desktop_notify)
            END_DISPATCH
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
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(set_dynamic_color);
            END_DISPATCH
        case 52:
        case -52:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(clipboard_control);
            if (code == -52) continue_osc_52(screen);
            END_DISPATCH
        case 133:
            START_DISPATCH
            DISPATCH_OSC(shell_prompt_marking);
            END_DISPATCH
        case FILE_TRANSFER_CODE:
            START_DISPATCH
            DISPATCH_OSC(file_transmission);
            END_DISPATCH
        case 30001:
            REPORT_COMMAND(screen_push_dynamic_colors);
            screen_push_colors(screen, 0);
            break;
        case 30101:
            REPORT_COMMAND(screen_pop_dynamic_colors);
            screen_pop_colors(screen, 0);
            break;
        default:
            REPORT_ERROR("Unknown OSC code: %u", code);
            break;
    }
#undef DISPATCH_OSC
#undef DISPATCH_OSC_WITH_CODE
#undef START_DISPATCH
#undef END_DISPATCH
}
// }}}

// CSI mode {{{
// As per ECMA 48 section 5.4 secondary byte is column 02 of the 7-bit ascii table
#define CSI_SECONDARY \
        case ' ': \
        case '!': \
        case '"': \
        case '#': \
        case '$': \
        case '%': \
        case '&': \
        case '\'': \
        case '(': \
        case ')': \
        case '*': \
        case '+': \
        case ',': \
        case '-': \
        case '.': \
        case '/':


static void
screen_cursor_up2(Screen *s, unsigned int count) { screen_cursor_up(s, count, false, -1); }
static void
screen_cursor_back1(Screen *s, unsigned int count) { screen_cursor_back(s, count, -1); }
static void
screen_tabn(Screen *s, unsigned int count) { for (index_type i=0; i < MAX(1u, count); i++) screen_tab(s); }

static const char*
repr_csi_params(int *params, unsigned int num_params) {
    if (!num_params) return "";
    static char buf[256];
    unsigned int pos = 0, i = 0;
    while (pos < 200 && i++ < num_params && sizeof(buf) > pos + 1) {
        const char *fmt = i < num_params ? "%i, " : "%i";
        int ret = snprintf(buf + pos, sizeof(buf) - pos - 1, fmt, params[i-1]);
        if (ret < 0) return "An error occurred formatting the params array";
        pos += ret;
    }
    buf[pos] = 0;
    return buf;
}

#ifdef DUMP_COMMANDS
static
#endif
void
parse_sgr(Screen *screen, uint32_t *buf, unsigned int num, int *params, PyObject DUMP_UNUSED *dump_callback, const char *report_name DUMP_UNUSED, Region *region) {
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

static unsigned int
parse_region(Region *r, uint32_t *buf, unsigned int num) {
    unsigned int i, start, num_params = 0;
    int params[8] = {0};
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

static const char*
csi_letter(unsigned code) {
    static char buf[8];
    if (33 <= code && code <= 126) snprintf(buf, sizeof(buf), "%c", code);
    else snprintf(buf, sizeof(buf), "0x%x", code);
    return buf;
}

static void
dispatch_csi(Screen *screen, PyObject DUMP_UNUSED *dump_callback) {
#define AT_MOST_ONE_PARAMETER { \
    if (num_params > 1) { \
        REPORT_ERROR("CSI code %s has %u > 1 parameters", csi_letter(code), num_params); \
        break; \
    } \
}
#define NON_NEGATIVE_PARAM(x) { \
    if (x < 0) { \
        REPORT_ERROR("CSI code %s is not allowed to have negative parameter (%d)", csi_letter(code), x); \
        break; \
    } \
}

#define CALL_CSI_HANDLER1(name, defval) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    REPORT_COMMAND(name, p1); \
    name(screen, p1); \
    break;

#define CALL_CSI_HANDLER1P(name, defval, qch) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    private = start_modifier == qch; \
    REPORT_COMMAND(name, p1, private); \
    name(screen, p1, private); \
    break;

#define CALL_CSI_HANDLER1S(name, defval) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    REPORT_COMMAND(name, p1, start_modifier); \
    name(screen, p1, start_modifier); \
    break;

#define CALL_CSI_HANDLER1M(name, defval) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    REPORT_COMMAND(name, p1, end_modifier); \
    name(screen, p1, end_modifier); \
    break;

#define CALL_CSI_HANDLER2(name, defval1, defval2) \
    if (num_params > 2) { \
        REPORT_ERROR("CSI code %s has %u > 2 parameters", csi_letter(code), num_params); \
        break; \
    } \
    p1 = num_params > 0 ? params[0] : defval1; \
    p2 = num_params > 1 ? params[1] : defval2; \
    NON_NEGATIVE_PARAM(p1); \
    NON_NEGATIVE_PARAM(p2); \
    REPORT_COMMAND(name, p1, p2); \
    name(screen, p1, p2); \
    break;

#define SET_MODE(func) \
    p1 = start_modifier == '?' ? 5 : 0; \
    for (i = 0; i < num_params; i++) { \
        NON_NEGATIVE_PARAM(params[i]); \
        REPORT_COMMAND(func, params[i], start_modifier == '?'); \
        func(screen, params[i] << p1); \
    } \
    break;

#define NO_MODIFIERS(modifier, special, special_msg) { \
    if (start_modifier || end_modifier) { \
        if (special && modifier == special) { REPORT_ERROR(special_msg); } \
        else { REPORT_ERROR("CSI code %s has unsupported start modifier: %s or end modifier: %s", csi_letter(code), csi_letter(start_modifier), csi_letter(end_modifier));} \
        break; \
    } \
}

    char start_modifier = 0, end_modifier = 0;
    uint32_t *buf = screen->parser_buf, code = screen->parser_buf[screen->parser_buf_pos];
    unsigned int num = screen->parser_buf_pos, start, i, num_params=0;
    static int params[MAX_PARAMS] = {0}, p1, p2;
    bool private;
    if (buf[0] == '>' || buf[0] == '<' || buf[0] == '?' || buf[0] == '!' || buf[0] == '=') {
        start_modifier = (char)screen->parser_buf[0];
        buf++; num--;
    }
    if (num > 0) {
        switch(buf[num-1]) {
            CSI_SECONDARY
                end_modifier = (char)buf[--num];
                break;
        }
    }
    if (code == SGR && !start_modifier && !end_modifier) {
        parse_sgr(screen, buf, num, params, dump_callback, "select_graphic_rendition", NULL);
        return;
    }
    if (code == 'r' && !start_modifier && end_modifier == '$') {
        // DECCARA
        Region r = {0};
        unsigned int consumed = parse_region(&r, buf, num);
        num -= consumed; buf += consumed;
        parse_sgr(screen, buf, num, params, dump_callback, "deccara", &r);
        return;
    }

    for (i=0, start=0; i < num; i++) {
        switch(buf[i]) {
            IS_DIGIT
                break;
            case '-':
                if (i > start) {
                    REPORT_ERROR("CSI code can contain hyphens only at the start of numbers");
                    return;
                }
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
            NO_MODIFIERS(end_modifier, ' ', "Shift left escape code not implemented");
            CALL_CSI_HANDLER1(screen_insert_characters, 1);
        case REP:
            CALL_CSI_HANDLER1(screen_repeat_character, 1);
        case CUU:
            NO_MODIFIERS(end_modifier, ' ', "Shift right escape code not implemented");
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
            if (end_modifier == '#' && !start_modifier) {
                CALL_CSI_HANDLER1(screen_push_colors, 0);
            } else {
                CALL_CSI_HANDLER1(screen_delete_characters, 1);
            }
        case 'Q':
            if (end_modifier == '#' && !start_modifier) { CALL_CSI_HANDLER1(screen_pop_colors, 0); }
            REPORT_ERROR("Unknown CSI Q sequence with start and end modifiers: '%c' '%c' and %u parameters", start_modifier, end_modifier, num_params);
            break;
        case 'R':
            if (end_modifier == '#' && !start_modifier) {
                REPORT_COMMAND(screen_report_color_stack);
                screen_report_color_stack(screen);
                break;
            }
            REPORT_ERROR("Unknown CSI R sequence with start and end modifiers: '%c' '%c' and %u parameters", start_modifier, end_modifier, num_params);
            break;
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
        case 's':
            if (!start_modifier && !end_modifier && !num_params) {
                REPORT_COMMAND(screen_save_cursor);
                screen_save_cursor(screen);
                break;
            } else if (start_modifier == '?' && !end_modifier) {
                if (!num_params) {
                    REPORT_COMMAND(screen_save_modes);
                    screen_save_modes(screen);
                } else { SET_MODE(screen_save_mode); }
                break;
            }
            REPORT_ERROR("Unknown CSI s sequence with start and end modifiers: '%c' '%c' and %u parameters", start_modifier, end_modifier, num_params);
            break;
        case 't':
            if (!num_params) {
                REPORT_ERROR("Unknown CSI t sequence with start and end modifiers: '%c' '%c' and no parameters", start_modifier, end_modifier);
                break;
            }
            if (start_modifier || end_modifier) {
                REPORT_ERROR("Unknown CSI t sequence with start and end modifiers: '%c' '%c', %u parameters and first parameter: %d", start_modifier, end_modifier, num_params, params[0]);
                break;
            }
            switch(params[0]) {
                case 4:
                case 8:
                    log_error("Escape codes to resize text area are not supported");
                    break;
                case 14:
                case 16:
                case 18:
                    CALL_CSI_HANDLER1(screen_report_size, 0);
                    break;
                case 22:
                case 23:
                    if (num_params == 3 && !params[2]) num_params = 2; // ignore extra 0, generated by weechat or ncurses
                    CALL_CSI_HANDLER2(screen_manipulate_title_stack, 22, 0);
                    break;
                default:
                    REPORT_ERROR("Unknown CSI t window manipulation sequence with %u parameters and first parameter: %d", num_params, params[0]);
                    break;
            }
            break;
        case 'u':
            if (!start_modifier && !end_modifier && !num_params) {
                REPORT_COMMAND(screen_restore_cursor);
                screen_restore_cursor(screen);
                break;
            }
            if (!end_modifier && start_modifier == '?') {
                REPORT_COMMAND(screen_report_key_encoding_flags);
                screen_report_key_encoding_flags(screen);
                break;
            }
            if (!end_modifier && start_modifier == '=') {
                CALL_CSI_HANDLER2(screen_set_key_encoding_flags, 0, 1);
                break;
            }
            if (!end_modifier && start_modifier == '>') {
                CALL_CSI_HANDLER1(screen_push_key_encoding_flags, 0);
                break;
            }
            if (!end_modifier && start_modifier == '<') {
                CALL_CSI_HANDLER1(screen_pop_key_encoding_flags, 1);
                break;
            }
            REPORT_ERROR("Unknown CSI u sequence with start and end modifiers: '%c' '%c' and %u parameters", start_modifier, end_modifier, num_params);
            break;
        case 'r':
            if (!start_modifier && !end_modifier) {
                // DECSTBM
                CALL_CSI_HANDLER2(screen_set_margins, 0, 0);
            } else if (start_modifier == '?' && !end_modifier) {
                if (!num_params) {
                    REPORT_COMMAND(screen_restore_modes);
                    screen_restore_modes(screen);
                } else { SET_MODE(screen_restore_mode); }
                break;
            }
            REPORT_ERROR("Unknown CSI r sequence with start and end modifiers: '%c' '%c' and %u parameters", start_modifier, end_modifier, num_params);
            break;
        case 'x':
            if (!start_modifier && end_modifier == '*') {
                CALL_CSI_HANDLER1(screen_decsace, 0);
            }
            REPORT_ERROR("Unknown CSI x sequence with start and end modifiers: '%c' '%c'", start_modifier, end_modifier);
            break;
        case DECSCUSR:
            if (!start_modifier && end_modifier == ' ') {
                CALL_CSI_HANDLER1M(screen_set_cursor, 1);
            }
            if (start_modifier == '>' && !end_modifier) {
                CALL_CSI_HANDLER1(screen_xtversion, 0);
            }
            REPORT_ERROR("Unknown CSI q sequence with start and end modifiers: '%c' '%c'", start_modifier, end_modifier);
            break;
        case SU:
            NO_MODIFIERS(end_modifier, ' ', "Select presentation directions escape code not implemented");
            CALL_CSI_HANDLER1(screen_scroll, 1);
        case SD:
            if (!start_modifier && end_modifier == '+') {
                CALL_CSI_HANDLER1(screen_reverse_scroll_and_fill_from_scrollback, 1);
            } else {
                NO_MODIFIERS(start_modifier, 0, "");
                CALL_CSI_HANDLER1(screen_reverse_scroll, 1);
            }
            break;
        case DECSTR:
            if (end_modifier == '$') {
                // DECRQM
                CALL_CSI_HANDLER1P(report_mode_status, 0, '?');
            } else {
                REPORT_ERROR("Unknown DECSTR CSI sequence with start and end modifiers: '%c' '%c'", start_modifier, end_modifier);
            }
            break;
        case 'm':
            if (start_modifier == '>' && !end_modifier) {
                REPORT_ERROR(
                    "The application is trying to use XTerm's modifyOtherKeys."
                    " This is superseded by the kitty keyboard protocol: https://sw.kovidgoyal.net/kitty/keyboard-protocol/"
                    " the application should be updated to use that"
                );
                break;
            }
            /* fallthrough */
        default:
            REPORT_ERROR("Unknown CSI code: '%s' with start_modifier: '%c' and end_modifier: '%c' and parameters: '%s'", utf8(code), start_modifier, end_modifier, repr_csi_params(params, num_params));
    }
}
// }}}

// DCS mode {{{

static bool
startswith(const uint32_t *string, size_t sz, const char *prefix) {
    size_t l = strlen(prefix);
    if (sz < l) return false;
    for (size_t i = 0; i < l; i++) {
        if (string[i] != (unsigned char)prefix[i]) return false;
    }
    return true;
}

#define PENDING_MODE_CHAR '='

static void
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
        case PENDING_MODE_CHAR:
            if (screen->parser_buf_pos > 2 && (screen->parser_buf[1] == '1' || screen->parser_buf[1] == '2') && screen->parser_buf[2] == 's') {
                if (screen->parser_buf[1] == '1') {
                    screen->pending_mode.activated_at = monotonic();
                    REPORT_COMMAND(screen_start_pending_mode);
                } else {
                    // ignore stop without matching start, see queue_pending_bytes()
                    // for how stop is detected while in pending mode.
                    REPORT_ERROR("Pending mode stop command issued while not in pending mode, this can"
                        " be either a bug in the terminal application or caused by a timeout with no data"
                        " received for too long or by too much data in pending mode");
                    REPORT_COMMAND(screen_stop_pending_mode);
                }
            } else {
                REPORT_ERROR("Unrecognized DCS %c code: 0x%x", (char)screen->parser_buf[0], screen->parser_buf[1]);
            }
            break;
        case '@':
#define CMD_PREFIX "kitty-cmd{"
            if (startswith(screen->parser_buf + 1, screen->parser_buf_pos - 2, CMD_PREFIX)) {
                PyObject *cmd = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + 10, screen->parser_buf_pos - 10);
                if (cmd != NULL) {
                    REPORT_OSC2(screen_handle_cmd, (char)screen->parser_buf[0], cmd);
                    screen_handle_cmd(screen, cmd);
                    Py_DECREF(cmd);
                } else PyErr_Clear();
#undef CMD_PREFIX
#define PRINT_PREFIX "kitty-print|"
            } else if (startswith(screen->parser_buf + 1, screen->parser_buf_pos - 1, PRINT_PREFIX)) {
                const size_t pp_size = sizeof(PRINT_PREFIX);
                PyObject *msg = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + pp_size, screen->parser_buf_pos - pp_size);
                if (msg != NULL) {
                    REPORT_OSC2(screen_handle_print, (char)screen->parser_buf[0], msg);
                    screen_handle_print(screen, msg);
                    Py_DECREF(msg);
                } else PyErr_Clear();
#undef PRINT_PREFIX
#define ECHO_PREFIX "kitty-echo|"
            } else if (startswith(screen->parser_buf + 1, screen->parser_buf_pos - 1, ECHO_PREFIX)) {
                const size_t pp_size = sizeof(ECHO_PREFIX);
                PyObject *msg = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, screen->parser_buf + pp_size, screen->parser_buf_pos - pp_size);
                if (msg != NULL) {
                    REPORT_OSC2(screen_handle_echo, (char)screen->parser_buf[0], msg);
                    screen_handle_echo(screen, msg);
                    Py_DECREF(msg);
                } else PyErr_Clear();
#undef ECHO_PREFIX

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

#include "parse-graphics-command.h"

static void
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
static void
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

static bool
handle_extended_osc_code(Screen *screen) {
    // Handle extra long OSC 52 codes
    if (screen->parser_buf[0] != '5' || screen->parser_buf[1] != '2' || screen->parser_buf[2] != ';') return false;
    screen->parser_buf[0] = EXTENDED_OSC_SENTINEL; screen->parser_buf[1] = 1;
    return true;
}

static bool
accumulate_osc(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback, bool *extended_osc_code) {
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
                if (handle_extended_osc_code(screen)) *extended_osc_code = true;
                else REPORT_ERROR("OSC sequence too long, truncating.");
                return true;
            }
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
    }
    return false;
}

static bool
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
                REPORT_ERROR("DCS sequence contained ESC without trailing \\ ignoring the sequence");
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


static bool
accumulate_oth(Screen *screen, uint32_t ch, PyObject DUMP_UNUSED *dump_callback) {
    switch(ch) {
        case ST:
            return true;
        case DEL:
        case NUL:
            break;
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


static bool
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
        case ':':
        case ';':
            ENSURE_SPACE;
            screen->parser_buf[screen->parser_buf_pos++] = ch;
            break;
        case '?':
        case '>':
        case '<':
        case '=':
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
            dispatch_normal_mode_char(screen, ch, dump_callback);
            break;
        case NUL:
        case DEL:
            SET_STATE(0);
            break;  // no-op
        default:
            REPORT_ERROR("Invalid character in CSI: 0x%x, ignoring the sequence", ch);
            SET_STATE(0);
            return false;

    }
    return false;
#undef ENSURE_SPACE
}

#define dispatch_unicode_char(codepoint, dispatch, watch_for_pending) { \
    switch(screen->parser_state) { \
        case ESC: \
            dispatch##_esc_mode_char(screen, codepoint, dump_callback); \
            break; \
        case CSI: \
            if (accumulate_csi(screen, codepoint, dump_callback)) { dispatch##_csi(screen, dump_callback); SET_STATE(0); watch_for_pending; } \
            break; \
        case OSC: \
            { \
                bool extended_osc_code = false; \
                if (accumulate_osc(screen, codepoint, dump_callback, &extended_osc_code)) {  \
                    dispatch##_osc(screen, dump_callback); \
                    if (extended_osc_code) { \
                        if (accumulate_osc(screen, codepoint, dump_callback, &extended_osc_code)) { dispatch##_osc(screen, dump_callback); SET_STATE(0); } \
                    } else { SET_STATE(0); } \
                } \
            } \
            break; \
        case APC: \
            if (accumulate_oth(screen, codepoint, dump_callback)) { dispatch##_apc(screen, dump_callback); SET_STATE(0); } \
            break; \
        case PM: \
            if (accumulate_oth(screen, codepoint, dump_callback)) { dispatch##_pm(screen, dump_callback); SET_STATE(0); } \
            break; \
        case DCS: \
            if (accumulate_dcs(screen, codepoint, dump_callback)) { dispatch##_dcs(screen, dump_callback); SET_STATE(0); watch_for_pending; } \
            if (screen->parser_state == ESC) { dispatch##_esc_mode_char(screen, codepoint, dump_callback); } \
            break; \
        default: \
            dispatch##_normal_mode_char(screen, codepoint, dump_callback); \
            break; \
    } \
} \

extern uint32_t *latin1_charset;

#define decode_loop(dispatch, watch_for_pending) { \
    i = 0; \
    uint32_t prev = screen->utf8_state; \
    while(i < (size_t)len) { \
        uint8_t ch = buf[i++]; \
        if (screen->use_latin1) { \
            dispatch_unicode_char(latin1_charset[ch], dispatch, watch_for_pending); \
        } else { \
            switch (decode_utf8(&screen->utf8_state, &screen->utf8_codepoint, ch)) { \
                case UTF8_ACCEPT: \
                    dispatch_unicode_char(screen->utf8_codepoint, dispatch, watch_for_pending); \
                    break; \
                case UTF8_REJECT: \
                    screen->utf8_state = UTF8_ACCEPT; \
                    if (prev != UTF8_ACCEPT && i > 0) i--; \
                    break; \
            } \
            prev = screen->utf8_state; \
        } \
    }  \
}

static void
_parse_bytes(Screen *screen, const uint8_t *buf, Py_ssize_t len, PyObject DUMP_UNUSED *dump_callback) {
    unsigned int i;
    decode_loop(dispatch, ;);
FLUSH_DRAW;
}

static size_t
_parse_bytes_watching_for_pending(Screen *screen, const uint8_t *buf, Py_ssize_t len, PyObject DUMP_UNUSED *dump_callback) {
    unsigned int i;
    decode_loop(dispatch, if (screen->pending_mode.activated_at) goto end);
end:
FLUSH_DRAW;
    return i;
}

static void
write_pending_char(Screen *screen, uint32_t ch) {
    if (screen->pending_mode.capacity < screen->pending_mode.used + 8) {
        if (screen->pending_mode.capacity) {
            screen->pending_mode.capacity += screen->pending_mode.capacity >= READ_BUF_SZ ? PENDING_BUF_INCREMENT : screen->pending_mode.capacity;
        } else screen->pending_mode.capacity = PENDING_BUF_INCREMENT;
        screen->pending_mode.buf = realloc(screen->pending_mode.buf, screen->pending_mode.capacity);
        if (!screen->pending_mode.buf) fatal("Out of memory");
    }
    screen->pending_mode.used += encode_utf8(ch, (char*)screen->pending_mode.buf + screen->pending_mode.used);
}

static void
pending_normal_mode_char(Screen *screen, uint32_t ch, PyObject *dump_callback UNUSED) {
    switch(ch) {
        case ESC: case CSI: case OSC: case DCS: case APC: case PM:
            SET_STATE(ch); break;
        default:
            write_pending_char(screen, ch); break;
    }
}

static void
pending_esc_mode_char(Screen *screen, uint32_t ch, PyObject *dump_callback UNUSED) {
    if (screen->parser_buf_pos > 0) {
        write_pending_char(screen, ESC);
        write_pending_char(screen, screen->parser_buf[screen->parser_buf_pos - 1]);
        write_pending_char(screen, ch);
        SET_STATE(0);
        return;
    }
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
            write_pending_char(screen, ESC); write_pending_char(screen, ch);
            SET_STATE(0); break;
    }
}

#define pb(i) screen->parser_buf[i]
static void
pending_escape_code(Screen *screen, char_type start_ch, char_type end_ch) {
    write_pending_char(screen, start_ch);
    for (unsigned i = 0; i < screen->parser_buf_pos; i++) write_pending_char(screen, pb(i));
    write_pending_char(screen, end_ch);
}

static void pending_pm(Screen *screen, PyObject *dump_callback UNUSED) { pending_escape_code(screen, PM, ST); }
static void pending_apc(Screen *screen, PyObject *dump_callback UNUSED) { pending_escape_code(screen, APC, ST); }

static void
pending_osc(Screen *screen, PyObject *dump_callback UNUSED) {
    const bool extended = is_extended_osc(screen);
    pending_escape_code(screen, OSC, ST);
    if (extended) continue_osc_52(screen);
}


static void
pending_dcs(Screen *screen, PyObject *dump_callback DUMP_UNUSED) {
    if (screen->parser_buf_pos >= 3 && pb(0) == '=' && (pb(1) == '1' || pb(1) == '2') && pb(2) == 's') {
        screen->pending_mode.activated_at = pb(1) == '1' ? monotonic() : 0;
        if (pb(1) == '1') {
            REPORT_COMMAND(screen_start_pending_mode);
            screen->pending_mode.activated_at = monotonic();
        } else {
            screen->pending_mode.stop_escape_code_type = DCS;
            screen->pending_mode.activated_at = 0;
        }
    } else pending_escape_code(screen, DCS, ST);
}

static void
pending_csi(Screen *screen, PyObject *dump_callback DUMP_UNUSED) {
    if (screen->parser_buf_pos == 5 && pb(0) == '?' && pb(1) == '2' && pb(2) == '0' && pb(3) == '2' && pb(4) == '6' && (pb(5) == 'h' || pb(5) == 'l')) {
        if (pb(5) == 'h') {
            REPORT_COMMAND(screen_set_mode, 2026, 1);
            screen->pending_mode.activated_at = monotonic();
        } else {
            screen->pending_mode.activated_at = 0;
            screen->pending_mode.stop_escape_code_type = CSI;
        }
    } else pending_escape_code(screen, CSI, pb(screen->parser_buf_pos));
}

#undef pb

static size_t
queue_pending_bytes(Screen *screen, const uint8_t *buf, size_t len, PyObject *dump_callback DUMP_UNUSED) {
    unsigned int i;
    decode_loop(pending, if (!screen->pending_mode.activated_at) goto end);
end:
    return i;
}

static void
dump_partial_escape_code_to_pending(Screen *screen) {
    if (screen->parser_buf_pos) {
        write_pending_char(screen, screen->parser_state);
        for (unsigned i = 0; i < screen->parser_buf_pos; i++) write_pending_char(screen, screen->parser_buf[i]);
    }
}

static void
do_parse_bytes(Screen *screen, const uint8_t *read_buf, const size_t read_buf_sz, monotonic_t now, PyObject *dump_callback DUMP_UNUSED) {
    enum STATE {START, PARSE_PENDING, PARSE_READ_BUF, QUEUE_PENDING};
    enum STATE state = START;
    size_t read_buf_pos = 0;
    unsigned int parser_state_at_start_of_pending = 0;

    do {
        switch(state) {
            case START:
                if (screen->pending_mode.activated_at) {
                    if (screen->pending_mode.activated_at + screen->pending_mode.wait_time < now) {
                        dump_partial_escape_code_to_pending(screen);
                        screen->pending_mode.activated_at = 0;
                        state = START;
                    } else state = QUEUE_PENDING;
                } else {
                    state = screen->pending_mode.used ? PARSE_PENDING : PARSE_READ_BUF;
                }
                break;

            case PARSE_PENDING:
                screen->parser_state = parser_state_at_start_of_pending;
                parser_state_at_start_of_pending = 0;
                _parse_bytes(screen, screen->pending_mode.buf, screen->pending_mode.used, dump_callback);
                screen->pending_mode.used = 0;
                screen->pending_mode.activated_at = 0;  // ignore any pending starts in the pending bytes
                if (screen->pending_mode.capacity > READ_BUF_SZ + PENDING_BUF_INCREMENT) {
                    screen->pending_mode.capacity = READ_BUF_SZ;
                    screen->pending_mode.buf = realloc(screen->pending_mode.buf, screen->pending_mode.capacity);
                    if (!screen->pending_mode.buf) fatal("Out of memory");
                }
                if (screen->pending_mode.stop_escape_code_type) {
                    if (screen->pending_mode.stop_escape_code_type == DCS) { REPORT_COMMAND(screen_stop_pending_mode); }
                    else if (screen->pending_mode.stop_escape_code_type == CSI) { REPORT_COMMAND(screen_reset_mode, 2026, 1); }
                    screen->pending_mode.stop_escape_code_type = 0;
                }
                state = START;
                break;

            case PARSE_READ_BUF:
                screen->pending_mode.activated_at = 0;
                read_buf_pos += _parse_bytes_watching_for_pending(screen, read_buf + read_buf_pos, read_buf_sz - read_buf_pos, dump_callback);
                state = START;
                break;

            case QUEUE_PENDING: {
                screen->pending_mode.stop_escape_code_type = 0;
                if (screen->pending_mode.used >= READ_BUF_SZ) {
                    dump_partial_escape_code_to_pending(screen);
                    screen->pending_mode.activated_at = 0;
                    state = START;
                    break;
                }
                if (!screen->pending_mode.used) parser_state_at_start_of_pending = screen->parser_state;
                read_buf_pos += queue_pending_bytes(screen, read_buf + read_buf_pos, read_buf_sz - read_buf_pos, dump_callback);
                state = START;
            }   break;
        }
    } while(read_buf_pos < read_buf_sz || (!screen->pending_mode.activated_at && screen->pending_mode.used));

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
    do_parse_bytes(screen, pybuf.buf, pybuf.len, monotonic(), dump_callback);
    Py_RETURN_NONE;
}


void
FNAME(parse_worker)(Screen *screen, PyObject *dump_callback, monotonic_t now) {
#ifdef DUMP_COMMANDS
    if (screen->read_buf_sz) {
        Py_XDECREF(PyObject_CallFunction(dump_callback, "sy#", "bytes", screen->read_buf, screen->read_buf_sz)); PyErr_Clear();
    }
#endif
    do_parse_bytes(screen, screen->read_buf, screen->read_buf_sz, now, dump_callback);
    screen->read_buf_sz = 0;
}
#undef FNAME
// }}}
