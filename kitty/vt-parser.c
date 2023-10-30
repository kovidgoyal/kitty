/*
 * vt-parser.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// TODO: Test clipboard kitten with 52 and 5522
// TODO: Test shell integration with secondary prompts
// TODO: Test screen_request_capabilities
// TODO: Test that C1 characters are ignored by screen_draw()

#include "vt-parser.h"
#include "charsets.h"
#include "screen.h"
#include "base64.h"
#include "control-codes.h"

#define EXTENDED_OSC_SENTINEL ESC
#define PARSER_BUF_SZ (8u * 1024u)
#define PENDING_BUF_INCREMENT (16u * 1024u)

// Macros {{{

#define SET_STATE(state) self->vte_state = state; self->parser_buf_pos = 0; self->utf8_state = UTF8_ACCEPT;

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
_report_error(PyObject *dump_callback, id_type window_id, const char *fmt, ...) {
    va_list argptr;
    va_start(argptr, fmt);
    RAII_PyObject(temp, PyUnicode_FromFormatV(fmt, argptr));
    va_end(argptr);
    if (temp != NULL) {
        RAII_PyObject(wid, PyLong_FromUnsignedLongLong(window_id));
        Py_XDECREF(PyObject_CallFunctionObjArgs(dump_callback, wid, temp, NULL)); PyErr_Clear();
    }
}

static void
_report_params(PyObject *dump_callback, id_type window_id, const char *name, int *params, unsigned int count, Region *r) {
    static char buf[MAX_PARAMS*3] = {0};
    unsigned int i, p=0;
    if (r) p += snprintf(buf + p, sizeof(buf) - 2, "%u %u %u %u ", r->top, r->left, r->bottom, r->right);
    for(i = 0; i < count && p < MAX_PARAMS*3-20; i++) {
        int n = snprintf(buf + p, MAX_PARAMS*3 - p, "%i ", params[i]);
        if (n < 0) break;
        p += n;
    }
    buf[p] = 0;
    Py_XDECREF(PyObject_CallFunction(dump_callback, "Kss", window_id, name, buf)); PyErr_Clear();
}

#define DUMP_UNUSED

#define REPORT_ERROR(...) _report_error(self->dump_callback, self->window_id, __VA_ARGS__);

#define REPORT_COMMAND1(name) \
        Py_XDECREF(PyObject_CallFunction(self->dump_callback, "Ks", self->window_id, #name)); PyErr_Clear();

#define REPORT_COMMAND2(name, x) \
        Py_XDECREF(PyObject_CallFunction(self->dump_callback, "Ksi", self->window_id, #name, (int)x)); PyErr_Clear();

#define REPORT_COMMAND3(name, x, y) \
        Py_XDECREF(PyObject_CallFunction(self->dump_callback, "Ksii", self->window_id, #name, (int)x, (int)y)); PyErr_Clear();

#define GET_MACRO(_1,_2,_3,NAME,...) NAME
#define REPORT_COMMAND(...) GET_MACRO(__VA_ARGS__, REPORT_COMMAND3, REPORT_COMMAND2, REPORT_COMMAND1, SENTINEL)(__VA_ARGS__)
#define REPORT_VA_COMMAND(...) Py_XDECREF(PyObject_CallFunction(self->dump_callback, __VA_ARGS__)); PyErr_Clear();

#define REPORT_DRAW(ch) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "KsC", self->window_id, "draw", ch)); PyErr_Clear();

#define REPORT_PARAMS(name, params, num, region) _report_params(self->dump_callback, self->window_id, name, params, num_params, region)

#define FLUSH_DRAW \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "KsO", self->window_id, "draw", Py_None)); PyErr_Clear();

#define REPORT_OSC(name, string) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "KsO", self->window_id, #name, string)); PyErr_Clear();

#define REPORT_OSC2(name, code, string) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "KsiO", self->window_id, #name, code, string)); PyErr_Clear();

#define REPORT_HYPERLINK(id, url) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "Kszz", self->window_id, "set_active_hyperlink", id, url)); PyErr_Clear();

#else
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
// }}}

// Utils {{{
static const uint64_t pow_10_array[] = {
    1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000, 1000000000, 10000000000
};

static int64_t
utoi(const uint8_t *buf, unsigned int sz) {
    int64_t ans = 0;
    const uint8_t *p = buf;
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
// }}}

typedef enum VTEState {
    VTE_NORMAL, VTE_ESC = ESC, VTE_CSI = ESC_CSI, VTE_OSC = ESC_OSC, VTE_DCS = ESC_DCS, VTE_APC = ESC_APC, VTE_PM = ESC_PM
} VTEState;

typedef struct PS {
    id_type window_id;

    unsigned parser_buf_pos;
    UTF8State utf8_state;
    VTEState vte_state;

    // this is used only during dispatch of a single byte, its present here just to avoid adding an extra parameter to accumulate_osc()
    bool extended_osc_code;

    struct {
        monotonic_t activated_at, wait_time;
        unsigned stop_escape_code_type;
        size_t capacity, used;
        uint8_t *buf;
    } pending_mode;

    // these are temporary variables set only for duration of a parse call
    PyObject *dump_callback;
    Screen *screen;
    const uint8_t *input_data;
    size_t input_sz, input_pos;
    monotonic_t now;
    uint8_t parser_buf[PARSER_BUF_SZ + 8];  // +8 to ensure we can always zero terminate
    bool draining_pending;
} PS;

// Normal mode {{{

static void
draw_byte(PS *self, uint8_t b) {
    uint32_t ch;
    switch (decode_utf8(&self->utf8_state, &ch, b)) {
        case UTF8_ACCEPT:
            REPORT_DRAW(ch);
            screen_draw(self->screen, ch, true);
            break;
        case UTF8_REJECT:
            self->utf8_state = UTF8_ACCEPT;
            break;
    }
}

static void
dispatch_normal_mode_byte(PS *self) {
#define CALL_SCREEN_HANDLER(name) REPORT_COMMAND(name); name(self->screen); break;
    uint8_t ch = self->input_data[self->input_pos++];
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
        case SI:
            REPORT_ERROR("Ignoring request to change charset as we only support UTF-8"); break;
        case SO:
            REPORT_ERROR("Ignoring request to change charset as we only support UTF-8"); break;
        case ESC:
            SET_STATE(VTE_ESC); break;
        case NUL:
        case DEL:
            break;  // no-op
        default:
            draw_byte(self, ch);
            break;
    }
#undef CALL_SCREEN_HANDLER
}
// }}}

// Esc mode {{{
#define IS_ESCAPED_CHAR \
        case '%': \
        case '(': \
        case ')': \
        case '*': \
        case '+': \
        case '-': \
        case '.': \
        case '/': \
        case ' ': \
        case '#'


static void
screen_nel(Screen *screen) { screen_carriage_return(screen); screen_linefeed(screen); }

static void
dispatch_esc_mode_byte(PS *self) {
#define CALL_ED(name) REPORT_COMMAND(name); name(self->screen); SET_STATE(VTE_NORMAL);
#define CALL_ED1(name, ch) REPORT_COMMAND(name, ch); name(self->screen, ch); SET_STATE(VTE_NORMAL);
#define CALL_ED2(name, a, b) REPORT_COMMAND(name, a, b); name(self->screen, a, b); SET_STATE(VTE_NORMAL);
    uint8_t ch = self->input_data[self->input_pos++];
    switch(self->parser_buf_pos) {
        case 0:
            switch (ch) {
                case ESC_DCS:
                    SET_STATE(VTE_DCS); break;
                case ESC_OSC:
                    SET_STATE(VTE_OSC); break;
                case ESC_CSI:
                    SET_STATE(VTE_CSI); break;
                case ESC_APC:
                    SET_STATE(VTE_APC); break;
                case ESC_PM:
                    SET_STATE(VTE_PM); break;
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
                IS_ESCAPED_CHAR:
                    self->parser_buf[self->parser_buf_pos++] = ch;
                    break;
                default:
                    REPORT_ERROR("%s0x%x", "Unknown char after ESC: ", ch);
                    SET_STATE(VTE_NORMAL); break;
            }
            break;
        default:
            switch(self->parser_buf[0]) {
                case '%':
                    switch(ch) {
                        case '@':
                            REPORT_ERROR("Ignoring attempt to switch to non-utf8 encoding");
                            break;
                        case 'G':
                            REPORT_ERROR("Ignoring attempt to switch to utf8 encoding as we are always utf-8");
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
                            // dont report this error as fish shell designates charsets for some unholy reason, creating lot of noise in the tests
                            /* REPORT_ERROR("Ignoring attempt to designate charset as we support only UTF-8"); */
                            break;
                        default:
                            REPORT_ERROR("Unknown charset: 0x%x", ch); break;
                    }
                    break;
                case ' ':
                    switch(ch) {
                        case 'F':
                        case 'G':
                            REPORT_ERROR("Ignoring attempt to turn on/off C1 controls as we only support C0 controls"); break;
                        default:
                            REPORT_ERROR("Unhandled ESC SP escape code: 0x%x", ch); break;
                    }
                    break;
                default:
                    REPORT_ERROR("Unhandled charset related escape code: 0x%x 0x%x", self->parser_buf[0], ch); break;
            }
            SET_STATE(VTE_NORMAL);
            break;
    }
#undef CALL_ED
#undef CALL_ED1
} // }}}

// OSC {{{
static bool
is_extended_osc(const PS *self) {
    return self->parser_buf_pos > 2 && self->parser_buf[0] == EXTENDED_OSC_SENTINEL && self->parser_buf[1] == 1 && self->parser_buf[2] == ';';
}

static void
continue_osc_52(PS *self) {
    self->parser_buf[0] = '5'; self->parser_buf[1] = '2'; self->parser_buf[2] = ';';
    self->parser_buf[3] = ';'; self->parser_buf_pos = 4;
}

static bool
handle_extended_osc_code(PS *self) {
    // Handle extra long OSC 52 codes
    if (self->parser_buf[0] != '5' || self->parser_buf[1] != '2' || self->parser_buf[2] != ';') return false;
    self->parser_buf[0] = EXTENDED_OSC_SENTINEL; self->parser_buf[1] = 1;
    return true;
}

static bool
accumulate_osc(PS *self) {
    uint8_t ch = self->input_data[self->input_pos++];
    self->extended_osc_code = false;
    switch(ch) {
        case BEL:
            return true;
        case NUL:
        case DEL:
            break;
        case ESC_ST:
            if (self->parser_buf_pos > 0 && self->parser_buf[self->parser_buf_pos - 1] == ESC) {
                self->parser_buf_pos--;
                return true;
            }
            /* fallthrough */
        default:
            if (!self->draining_pending && self->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                if (handle_extended_osc_code(self)) self->extended_osc_code = true;
                else REPORT_ERROR("OSC sequence too long (> %d bytes) truncating.", PARSER_BUF_SZ);
                return true;
            }
            self->parser_buf[self->parser_buf_pos++] = ch;
            break;
    }
    return false;
}

static bool
parse_osc_8(char *buf, char **id, char **url) {
    // the spec says only ASCII printable chars are allowed in OSC 8
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
dispatch_hyperlink(PS *self, size_t pos, size_t size) {
    if (!size) return;  // ignore empty OSC 8 since it must have two semi-colons to be valid, which means one semi-colon here
    char *buf = (char*)self->parser_buf + pos;
    buf[size] = 0;  // this is safe because we have an extra 8 bytes after PARSER_BUF_SZ

    char *id = NULL, *url = NULL;
    if (parse_osc_8(buf, &id, &url)) {
        REPORT_HYPERLINK(id, url);
        set_active_hyperlink(self->screen, id, url);
    } else {
        REPORT_ERROR("Ignoring malformed OSC 8 code");
    }
}


static void
dispatch_osc(PS *self) {
#define DISPATCH_OSC_WITH_CODE(name) REPORT_OSC2(name, code, mv); name(self->screen, code, mv);
#define DISPATCH_OSC(name) REPORT_OSC(name, mv); name(self->screen, mv);
#define START_DISPATCH {\
    PyObject *mv = PyMemoryView_FromMemory((char*)self->parser_buf + i, limit - i, PyBUF_READ); \
    if (mv) {
#define END_DISPATCH Py_CLEAR(mv); } PyErr_Clear(); break; }

    const unsigned int limit = self->parser_buf_pos;
    int code=0;
    unsigned int i;
    for (i = 0; i < MIN(limit, 5u); i++) {
        if (self->parser_buf[i] < '0' || self->parser_buf[i] > '9') break;
    }
    if (i > 0) {
        code = utoi(self->parser_buf, i);
        if (i < limit && self->parser_buf[i] == ';') i++;
    } else {
        if (is_extended_osc(self)) {
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
        case 6:
        case 7:
            START_DISPATCH
            REPORT_OSC2(shell_prompt_marking, code, mv);
            process_cwd_notification(self->screen, code, (char*)self->parser_buf + i, limit-i);
            END_DISPATCH
        case 8:
            dispatch_hyperlink(self, i, limit-i);
            break;
        case 9:
        case 99:
        case 777:
        case 1337:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(desktop_notify)
            END_DISPATCH
        case 10:
        case 11:
        case 12:
        case 17:
        case 19:
        case 22:
        case 110:
        case 111:
        case 112:
        case 117:
        case 119:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(set_dynamic_color);
            END_DISPATCH
        case 52: case -52: case 5522:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(clipboard_control);
            if (code == -52) continue_osc_52(self);
            END_DISPATCH
        case 133:
            START_DISPATCH
            REPORT_OSC2(shell_prompt_marking, code, mv);
            if (limit - 1 > 0) {
                self->parser_buf[limit] = 0; // safe to do as we have 8 extra bytes after PARSER_BUF_SZ
                shell_prompt_marking(self->screen, (char*)self->parser_buf + i);
            }
            END_DISPATCH
        case FILE_TRANSFER_CODE:
            START_DISPATCH
            DISPATCH_OSC(file_transmission);
            END_DISPATCH
        case 30001:
            REPORT_COMMAND(screen_push_dynamic_colors);
            screen_push_colors(self->screen, 0);
            break;
        case 30101:
            REPORT_COMMAND(screen_pop_dynamic_colors);
            screen_pop_colors(self->screen, 0);
            break;
        case 697:
            REPORT_ERROR("Ignoring OSC 697, typically used by Fig for shell integration");
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

// DCS {{{

static bool
accumulate_dcs(PS *self) {
    uint8_t ch = self->input_data[self->input_pos++];
    switch(ch) {
        case NUL:
        case DEL:
            break;
        case ESC:
START_ALLOW_CASE_RANGE
        case 32 ... 126:
END_ALLOW_CASE_RANGE
            if (self->parser_buf_pos > 0 && self->parser_buf[self->parser_buf_pos-1] == ESC) {
                if (ch == '\\') { self->parser_buf_pos--; return true; }
                REPORT_ERROR("DCS sequence contained ESC without trailing \\ at pos: %u ignoring the sequence", self->parser_buf_pos);
                SET_STATE(VTE_ESC); return false;
            }
            if (self->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                REPORT_ERROR("DCS sequence too long, truncating.");
                return true;
            }
            self->parser_buf[self->parser_buf_pos++] = ch;
            break;
        default:
            REPORT_ERROR("DCS sequence contained non-printable character: 0x%x ignoring the sequence", ch);
    }
    return false;
}


static bool
startswith(const uint8_t *string, ssize_t sz, const char *prefix, ssize_t l) {
    if (sz < l) return false;
    for (ssize_t i = 0; i < l; i++) {
        if (string[i] != (unsigned char)prefix[i]) return false;
    }
    return true;
}

#define PENDING_MODE_CHAR '='

static void
dispatch_dcs(PS *self) {
    if (self->parser_buf_pos < 2) return;
    switch(self->parser_buf[0]) {
        case '+':
        case '$':
            if (self->parser_buf[1] == 'q') {
                self->parser_buf[self->parser_buf_pos] = 0;  // safe to do since we have 8 extra bytes after PARSER_BUF_SZ
                PyObject *mv = PyMemoryView_FromMemory((char*)self->parser_buf + 2, self->parser_buf_pos-2, PyBUF_READ);
                if (mv) {
                    REPORT_OSC2(screen_request_capabilities, (char)self->parser_buf[0], mv);
                    Py_DECREF(mv);
                } else PyErr_Clear();
                screen_request_capabilities(self->screen, (char)self->parser_buf[0], (char*)self->parser_buf + 2);
            } else {
                REPORT_ERROR("Unrecognized DCS %c code: 0x%x", (char)self->parser_buf[0], self->parser_buf[1]);
            }
            break;
        case PENDING_MODE_CHAR:
            if (self->parser_buf_pos > 2 && (self->parser_buf[1] == '1' || self->parser_buf[1] == '2') && self->parser_buf[2] == 's') {
                if (self->parser_buf[1] == '1') {
                    self->pending_mode.activated_at = monotonic();
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
                REPORT_ERROR("Unrecognized DCS %c code: 0x%x", (char)self->parser_buf[0], self->parser_buf[1]);
            }
            break;
        case '@':
            if (startswith(self->parser_buf + 1, self->parser_buf_pos - 2, "kitty-", sizeof("kitty-") - 1)) {
                if (startswith(self->parser_buf + 7, self->parser_buf_pos - 2, "cmd{", sizeof("cmd{") - 1)) {
                    PyObject *cmd = PyMemoryView_FromMemory((char*)self->parser_buf + 10, self->parser_buf_pos - 10, PyBUF_READ);
                    if (cmd != NULL) {
                        REPORT_OSC2(screen_handle_cmd, (char)self->parser_buf[0], cmd);
                        screen_handle_cmd(self->screen, cmd);
                        Py_DECREF(cmd);
                    } else PyErr_Clear();
#define IF_SIMPLE_PREFIX(prefix, func) \
        if (startswith(self->parser_buf + 7, self->parser_buf_pos - 1, prefix, sizeof(prefix) - 1)) { \
            const size_t pp_size = sizeof("kitty") + sizeof(prefix); \
            PyObject *msg = PyMemoryView_FromMemory((char*)self->parser_buf + pp_size, self->parser_buf_pos - pp_size, PyBUF_READ); \
            if (msg != NULL) { \
                REPORT_OSC2(func, (char)self->parser_buf[0], msg); \
                screen_handle_kitty_dcs(self->screen, #func, msg); \
                Py_DECREF(msg); \
            } else PyErr_Clear();

                } else IF_SIMPLE_PREFIX("overlay-ready|", handle_overlay_ready)
                } else IF_SIMPLE_PREFIX("kitten-result|", handle_kitten_result)
                } else IF_SIMPLE_PREFIX("print|", handle_remote_print)
                } else IF_SIMPLE_PREFIX("echo|", handle_remote_echo)
                } else IF_SIMPLE_PREFIX("ssh|", handle_remote_ssh)
                } else IF_SIMPLE_PREFIX("ask|", handle_remote_askpass)
                } else IF_SIMPLE_PREFIX("clone|", handle_remote_clone)
                } else IF_SIMPLE_PREFIX("edit|", handle_remote_edit)
#undef IF_SIMPLE_PREFIX
                } else {
                    self->parser_buf[self->parser_buf_pos] = 0; // safe to do as we have 8 extra bytes after PARSER_BUF_SZ
                    REPORT_ERROR("Unrecognized DCS @ code: %s", self->parser_buf);
                }
            }
            break;
        default:
            REPORT_ERROR("Unrecognized DCS code: 0x%x", self->parser_buf[0]);
            break;
    }
}

// }}}

// CSI {{{

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



static bool
accumulate_csi(PS *self) {
#define ENSURE_SPACE \
    if (self->parser_buf_pos > PARSER_BUF_SZ - 1) { \
        REPORT_ERROR("CSI sequence too long, ignoring"); \
        SET_STATE(VTE_NORMAL); \
        return false; \
    }

    uint8_t ch = self->input_data[self->input_pos++];
    switch(ch) {
        IS_DIGIT
        CSI_SECONDARY
        case ':':
        case ';':
            ENSURE_SPACE;
            self->parser_buf[self->parser_buf_pos++] = ch;
            break;
        case '?':
        case '>':
        case '<':
        case '=':
            if (self->parser_buf_pos != 0) {
                REPORT_ERROR("Invalid character in CSI: 0x%x, ignoring the sequence", ch);
                SET_STATE(VTE_NORMAL);
                return false;
            }
            ENSURE_SPACE;
            self->parser_buf[self->parser_buf_pos++] = ch;
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
            self->parser_buf[self->parser_buf_pos] = ch;
            return true;
        case BEL:
        case BS:
        case HT:
        case LF:
        case VT:
        case FF:
        case CR:
        case SO:
        case SI:
            self->input_pos--;
            dispatch_normal_mode_byte(self);
            break;
        case NUL:
        case DEL:
            SET_STATE(VTE_NORMAL);
            break;  // no-op
        default:
            REPORT_ERROR("Invalid character in CSI: 0x%x, ignoring the sequence", ch);
            SET_STATE(VTE_NORMAL);
            return false;

    }
    return false;
#undef ENSURE_SPACE
}


#ifdef DUMP_COMMANDS
static void
parse_sgr_dump(PS *self, uint8_t *buf, unsigned int num, int *params, const char *report_name UNUSED, Region *region) {
    Screen *screen = self->screen;
#else
void
parse_sgr(Screen *screen, const uint8_t *buf, unsigned int num, int *params, const char *report_name UNUSED, Region *region) {
#endif
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
                        REPORT_ERROR("Invalid SGR code containing disallowed character: %c (U+%x)", buf[i], buf[i]);
                        return;
                }
                break;
            default:
                REPORT_ERROR("Invalid SGR code containing disallowed character: %c (U+%x)", buf[i], buf[i]);
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
parse_region(Region *r, uint8_t *buf, unsigned int num) {
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

static void
screen_cursor_up2(Screen *s, unsigned int count) { screen_cursor_up(s, count, false, -1); }
static void
screen_cursor_back1(Screen *s, unsigned int count) { screen_cursor_back(s, count, -1); }
static void
screen_tabn(Screen *s, unsigned int count) { for (index_type i=0; i < MAX(1u, count); i++) screen_tab(s); }

static const char*
csi_letter(unsigned code) {
    static char buf[8];
    if (33 <= code && code <= 126) snprintf(buf, sizeof(buf), "%c", code);
    else snprintf(buf, sizeof(buf), "0x%x", code);
    return buf;
}

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

static void
dispatch_csi(PS *self) {
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
    name(self->screen, p1); \
    break;

#define CALL_CSI_HANDLER1P(name, defval, qch) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    private = start_modifier == qch; \
    REPORT_COMMAND(name, p1, private); \
    name(self->screen, p1, private); \
    break;

#define CALL_CSI_HANDLER1S(name, defval) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    REPORT_COMMAND(name, p1, start_modifier); \
    name(self->screen, p1, start_modifier); \
    break;

#define CALL_CSI_HANDLER1M(name, defval) \
    AT_MOST_ONE_PARAMETER; \
    p1 = num_params > 0 ? params[0] : defval; \
    NON_NEGATIVE_PARAM(p1); \
    REPORT_COMMAND(name, p1, end_modifier); \
    name(self->screen, p1, end_modifier); \
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
    name(self->screen, p1, p2); \
    break;

#define SET_MODE(func) \
    p1 = start_modifier == '?' ? 5 : 0; \
    for (i = 0; i < num_params; i++) { \
        NON_NEGATIVE_PARAM(params[i]); \
        REPORT_COMMAND(func, params[i], start_modifier == '?'); \
        func(self->screen, params[i] << p1); \
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
    uint8_t *buf = self->parser_buf, code = self->parser_buf[self->parser_buf_pos];
    unsigned int num = self->parser_buf_pos, start, i, num_params=0;
    static int params[MAX_PARAMS] = {0}, p1, p2;
    bool private;
    if (buf[0] == '>' || buf[0] == '<' || buf[0] == '?' || buf[0] == '!' || buf[0] == '=') {
        start_modifier = (char)self->parser_buf[0];
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
#ifdef DUMP_COMMANDS
        parse_sgr_dump(self, buf, num, params, "select_graphic_rendition", NULL);
#else
        parse_sgr(self->screen, buf, num, params, "select_graphic_rendition", NULL);
#endif
        return;
    }
    if (code == 'r' && !start_modifier && end_modifier == '$') {
        // DECCARA
        Region r = {0};
        unsigned int consumed = parse_region(&r, buf, num);
        num -= consumed; buf += consumed;
#ifdef DUMP_COMMANDS
        parse_sgr_dump(self, buf, num, params, "deccara", &r);
#else
        parse_sgr(self->screen, buf, num, params, "deccara", &r);
#endif
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
                screen_report_color_stack(self->screen);
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
                screen_save_cursor(self->screen);
                break;
            } else if (start_modifier == '?' && !end_modifier) {
                if (!num_params) {
                    REPORT_COMMAND(screen_save_modes);
                    screen_save_modes(self->screen);
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
                screen_restore_cursor(self->screen);
                break;
            }
            if (!end_modifier && start_modifier == '?') {
                REPORT_COMMAND(screen_report_key_encoding_flags);
                screen_report_key_encoding_flags(self->screen);
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
                    screen_restore_modes(self->screen);
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
                    "The application is trying to use xterm's modifyOtherKeys."
                    " This is superseded by the kitty keyboard protocol: https://sw.kovidgoyal.net/kitty/keyboard-protocol/"
                    " the application should be updated to use that"
                );
                break;
            }
            /* fallthrough */
        default:
            REPORT_ERROR("Unknown CSI code: '%c' with start_modifier: '%c' and end_modifier: '%c' and parameters: '%s'", code, start_modifier, end_modifier, repr_csi_params(params, num_params));
    }
}

// }}}

// APC mode {{{

#include "parse-graphics-command.h"

static void
dispatch_apc(PS *self) {
    if (self->parser_buf_pos < 2) return;
    switch(self->parser_buf[0]) {
        case 'G':
            parse_graphics_code(self, self->parser_buf, self->parser_buf_pos);
            break;
        default:
            REPORT_ERROR("Unrecognized APC code: 0x%x", self->parser_buf[0]);
            break;
    }
}

// }}}

// PM mode {{{
static void
dispatch_pm(PS *self) {
    if (self->parser_buf_pos < 2) return;
    switch(self->parser_buf[0]) {
        default:
            REPORT_ERROR("Unrecognized PM code: 0x%x", self->parser_buf[0]);
            break;
    }
}


// }}}

static bool
accumulate_oth(PS *self) {
    uint8_t ch = self->input_data[self->input_pos++];
    switch(ch) {
        case BEL:
            return true;
        case DEL:
        case NUL:
            break;
        case ESC_ST:
            if (self->parser_buf_pos > 0 && self->parser_buf[self->parser_buf_pos - 1] == ESC) {
                self->parser_buf_pos--;
                return true;
            }
            /* fallthrough */
        default:
            if (self->parser_buf_pos >= PARSER_BUF_SZ - 1) {
                REPORT_ERROR("OTH sequence too long, truncating.");
                return true;
            }
            self->parser_buf[self->parser_buf_pos++] = ch;
            break;
    }
    return false;
}

#define dispatch_single_byte(dispatch, watch_for_pending) { \
    switch(self->vte_state) { \
        case VTE_ESC: \
            dispatch##_esc_mode_byte(self); \
            break; \
        case VTE_CSI: \
            if (accumulate_csi(self)) { dispatch##_csi(self); SET_STATE(VTE_NORMAL); watch_for_pending; } \
            break; \
        case VTE_OSC: \
            if (accumulate_osc(self)) {  \
                dispatch##_osc(self); \
                if (self->extended_osc_code) { \
                    self->input_pos--; \
                    if (accumulate_osc(self)) { dispatch##_osc(self); SET_STATE(VTE_NORMAL); } \
                } else { SET_STATE(VTE_NORMAL); } \
            } \
            break; \
        case VTE_APC: \
            if (accumulate_oth(self)) { dispatch##_apc(self); SET_STATE(VTE_NORMAL); } \
            break; \
        case VTE_PM: \
            if (accumulate_oth(self)) { dispatch##_pm(self); SET_STATE(VTE_NORMAL); } \
            break; \
        case VTE_DCS: \
            if (accumulate_dcs(self)) { dispatch##_dcs(self); SET_STATE(VTE_NORMAL); watch_for_pending; } \
            if (self->vte_state == ESC) { self->input_pos--; dispatch##_esc_mode_byte(self); } \
            break; \
        case VTE_NORMAL: \
            dispatch##_normal_mode_byte(self); \
            break; \
    } \
} \

// Pending mode {{{
static void
ensure_pending_space(PS *self, size_t amt) {
    if (self->pending_mode.capacity < self->pending_mode.used + amt) {
        if (self->pending_mode.capacity) {
            self->pending_mode.capacity += self->pending_mode.capacity >= READ_BUF_SZ ? PENDING_BUF_INCREMENT : self->pending_mode.capacity;
        } else self->pending_mode.capacity = PENDING_BUF_INCREMENT;
        self->pending_mode.buf = realloc(self->pending_mode.buf, self->pending_mode.capacity);
        if (!self->pending_mode.buf) fatal("Out of memory");
    }
}

static void
pending_normal_mode_byte(PS *self) {
    uint8_t ch = self->input_data[self->input_pos++];
    switch(ch) {
        case ESC:
            SET_STATE(VTE_ESC); break;
        default:
            ensure_pending_space(self, 1);
            self->pending_mode.buf[self->pending_mode.used++] = ch;
            break;
    }
}

static void
pending_esc_mode_byte(PS *self) {
    uint8_t ch = self->input_data[self->input_pos++];
    if (self->parser_buf_pos > 0) {
        ensure_pending_space(self, 3);
        self->pending_mode.buf[self->pending_mode.used++] = ESC;
        self->pending_mode.buf[self->pending_mode.used++] = self->parser_buf[self->parser_buf_pos - 1];
        self->pending_mode.buf[self->pending_mode.used++] = ch;
        SET_STATE(VTE_NORMAL);
        return;
    }
    switch (ch) {
        case ESC_DCS:
            SET_STATE(VTE_DCS); break;
        case ESC_OSC:
            SET_STATE(VTE_OSC); break;
        case ESC_CSI:
            SET_STATE(VTE_CSI); break;
        case ESC_APC:
            SET_STATE(VTE_APC); break;
        case ESC_PM:
            SET_STATE(VTE_PM); break;
        IS_ESCAPED_CHAR:
            self->parser_buf[self->parser_buf_pos++] = ch;
            break;
        default:
            ensure_pending_space(self, 2);
            self->pending_mode.buf[self->pending_mode.used++] = ESC;
            self->pending_mode.buf[self->pending_mode.used++] = ch;
            SET_STATE(VTE_NORMAL); break;
    }
}

#define pb(i) self->parser_buf[i]

static void
pending_escape_code(PS *self, char_type start_ch, char_type end_ch) {
    ensure_pending_space(self, 4 + self->parser_buf_pos);
    self->pending_mode.buf[self->pending_mode.used++] = ESC;
    self->pending_mode.buf[self->pending_mode.used++] = start_ch;
    memcpy(self->pending_mode.buf + self->pending_mode.used, self->parser_buf, self->parser_buf_pos);
    self->pending_mode.used += self->parser_buf_pos;
    if (start_ch != ESC_CSI) self->pending_mode.buf[self->pending_mode.used++] = ESC;
    self->pending_mode.buf[self->pending_mode.used++] = end_ch;
}

static void pending_pm(PS *self) { pending_escape_code(self, ESC_PM, ESC_ST); }
static void pending_apc(PS *self) { pending_escape_code(self, ESC_APC, ESC_ST); }

static void
pending_osc(PS *self) {
    const bool extended = is_extended_osc(self);
    pending_escape_code(self, ESC_OSC, ESC_ST);
    if (extended) continue_osc_52(self);
}

static void
pending_dcs(PS *self) {
    if (self->parser_buf_pos >= 3 && pb(0) == '=' && (pb(1) == '1' || pb(1) == '2') && pb(2) == 's') {
        self->pending_mode.activated_at = pb(1) == '1' ? monotonic() : 0;
        if (pb(1) == '1') {
            REPORT_COMMAND(screen_start_pending_mode);
            self->pending_mode.activated_at = monotonic();
        } else {
            self->pending_mode.stop_escape_code_type = ESC_DCS;
            self->pending_mode.activated_at = 0;
        }
    } else pending_escape_code(self, ESC_DCS, ESC_ST);
}

static void
pending_csi(PS *self) {
    if (self->parser_buf_pos == 5 && pb(0) == '?' && pb(1) == '2' && pb(2) == '0' && pb(3) == '2' && pb(4) == '6' && (pb(5) == 'h' || pb(5) == 'l')) {
        if (pb(5) == 'h') {
            REPORT_COMMAND(screen_set_mode, 2026, 1);
            self->pending_mode.activated_at = monotonic();
        } else {
            self->pending_mode.activated_at = 0;
            self->pending_mode.stop_escape_code_type = ESC_CSI;
        }
    } else pending_escape_code(self, ESC_CSI, pb(self->parser_buf_pos));
}
#undef pb

static void
queue_pending_bytes(PS *self) {
    while (self->input_pos < self->input_sz) {
        dispatch_single_byte(pending, if (!self->pending_mode.activated_at) goto end);
    }
end:
FLUSH_DRAW;
}

static void
parse_pending_bytes(PS *self) {
    const uint8_t *orig_input_data = self->input_data; size_t orig_input_sz = self->input_sz, orig_input_pos = self->input_pos;
    self->input_data = self->pending_mode.buf; self->input_sz = self->pending_mode.used; self->input_pos = 0;
    self->draining_pending = true;
    while (self->input_pos < self->input_sz) {
        dispatch_single_byte(dispatch, ;);
    }
    self->draining_pending = false;
    self->input_data = orig_input_data; self->input_sz = orig_input_sz; self->input_pos = orig_input_pos;
}

static void
dump_partial_escape_code_to_pending(PS *self) {
    ensure_pending_space(self, self->parser_buf_pos + 2);
    if (self->parser_buf_pos) {
        switch(self->vte_state) {
            case VTE_NORMAL: case VTE_ESC: break;
            case VTE_CSI: case VTE_OSC: case VTE_DCS: case VTE_APC: case VTE_PM:
                self->pending_mode.buf[self->pending_mode.used++] = ESC;
                self->pending_mode.buf[self->pending_mode.used++] = self->vte_state;
                break;
        }
        memcpy(self->pending_mode.buf + self->pending_mode.used, self->parser_buf, self->parser_buf_pos);
        self->pending_mode.used += self->parser_buf_pos;
    } else if (self->vte_state == VTE_ESC) {
        self->pending_mode.buf[self->pending_mode.used++] = ESC;
    }
}
// }}}

static void
parse_bytes_watching_for_pending(PS *self) {
    while (self->input_pos < self->input_sz) {
        dispatch_single_byte(dispatch, if (self->pending_mode.activated_at) goto end);
    }
end:
FLUSH_DRAW;
}

static void
do_parse_vt(PS *self) {
    enum STATE {START, PARSE_PENDING, PARSE_READ_BUF, QUEUE_PENDING};
    enum STATE state = START;
    VTEState vte_state_at_start_of_pending = VTE_NORMAL;

    do {
        switch(state) {
            case START:
                if (self->pending_mode.activated_at) {
                    if (self->pending_mode.activated_at + self->pending_mode.wait_time < self->now) {
                        dump_partial_escape_code_to_pending(self);
                        self->pending_mode.activated_at = 0;
                        state = START;
                    } else state = QUEUE_PENDING;
                } else {
                    state = self->pending_mode.used ? PARSE_PENDING : PARSE_READ_BUF;
                }
                break;

            case PARSE_PENDING:
                self->vte_state = vte_state_at_start_of_pending;
                vte_state_at_start_of_pending = VTE_NORMAL;
                parse_pending_bytes(self);
                self->pending_mode.used = 0;
                self->pending_mode.activated_at = 0;  // ignore any pending starts in the pending bytes
                if (self->pending_mode.capacity > READ_BUF_SZ + PENDING_BUF_INCREMENT) {
                    self->pending_mode.capacity = READ_BUF_SZ;
                    self->pending_mode.buf = realloc(self->pending_mode.buf, self->pending_mode.capacity);
                    if (!self->pending_mode.buf) fatal("Out of memory");
                }
                if (self->pending_mode.stop_escape_code_type) {
                    if (self->pending_mode.stop_escape_code_type == ESC_DCS) { REPORT_COMMAND(screen_stop_pending_mode); }
                    else if (self->pending_mode.stop_escape_code_type == ESC_CSI) { REPORT_COMMAND(screen_reset_mode, 2026, 1); }
                    self->pending_mode.stop_escape_code_type = 0;
                }
                state = START;
                break;

            case PARSE_READ_BUF:
                self->pending_mode.activated_at = 0;
                parse_bytes_watching_for_pending(self);
                state = START;
                break;

            case QUEUE_PENDING: {
                self->pending_mode.stop_escape_code_type = 0;
                if (self->pending_mode.used >= READ_BUF_SZ) {
                    dump_partial_escape_code_to_pending(self);
                    self->pending_mode.activated_at = 0;
                    state = START;
                    break;
                }
                if (!self->pending_mode.used) vte_state_at_start_of_pending = self->vte_state;
                queue_pending_bytes(self);
                state = START;
            }   break;
        }
    } while(self->input_pos < self->input_sz || (!self->pending_mode.activated_at && self->pending_mode.used));
}

// Boilerplate {{{
#define setup_worker \

static void
run_worker(Screen *screen, PyObject *dump_callback, monotonic_t now) {
    PS *self = (PS*)screen->vt_parser->state;
#ifdef DUMP_COMMANDS
    self->window_id = screen->window_id;
    if (screen->read_buf_sz && dump_callback) {
        RAII_PyObject(mv, PyMemoryView_FromMemory((char*)screen->read_buf, screen->read_buf_sz, PyBUF_READ));
        PyObject *ret = PyObject_CallFunction(dump_callback, "KsO", screen->window_id, "bytes", mv);
        if (ret) { Py_DECREF(ret); } else { PyErr_Clear(); }
    }
#endif
    self->input_data = screen->read_buf; self->input_sz = screen->read_buf_sz; self->input_pos = 0;
    self->dump_callback = dump_callback; self->now = now; self->screen = screen;
    do_parse_vt(self);
    screen->read_buf_sz = 0;
}

#ifdef DUMP_COMMANDS
void
parse_vt_dump(Parser *p) {
    do_parse_vt((PS*)p->state);
}

void
parse_worker_dump(Screen *screen, PyObject *dump_callback, monotonic_t now) { run_worker(screen, dump_callback, now); }
#else
static void
parse_vt(Parser *p) {
    do_parse_vt((PS*)p->state);
}
extern void parse_vt_dump(Parser *p);

void
parse_worker(Screen *screen, PyObject *dump_callback, monotonic_t now) { run_worker(screen, dump_callback, now); }
#endif

#ifndef DUMP_COMMANDS
static PyObject*
new(PyTypeObject *type UNUSED, PyObject *args, PyObject UNUSED *kwds) {
    id_type window_id=0;
    if (!PyArg_ParseTuple(args, "|K", &window_id)) return NULL;
    return (PyObject*) alloc_vt_parser(window_id);
}

void
free_vt_parser(Parser* self) {
    if (self->state) {
        PS *s = (PS*)self->state;
        free(s->pending_mode.buf); s->pending_mode.buf = NULL;
        free(self->state); self->state = NULL;
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static void
reset(PS *self) {
    self->vte_state = VTE_NORMAL;
    self->utf8_state = UTF8_ACCEPT;
    self->parser_buf_pos = 0;

    self->pending_mode.activated_at = 0;
    self->pending_mode.stop_escape_code_type = 0;
}

void
reset_vt_parser(Parser *self) {
    reset((PS*)self->state);
}

extern PyTypeObject Screen_Type;

static PyObject*
py_parse(Parser *p, PyObject *args) {
    PS *self = (PS*)p->state;
    const uint8_t *data; Py_ssize_t sz;
    PyObject *dump_callback = NULL;
    if (!PyArg_ParseTuple(args, "O!y#|O", &Screen_Type, &self->screen, &data, &sz, &dump_callback)) return NULL;

    self->input_data = data; self->input_sz = sz; self->dump_callback = dump_callback;
    self->input_pos = 0; self->now = monotonic();
    if (dump_callback) parse_vt_dump(p); else parse_vt(p);
    self->input_data = NULL; self->input_sz = 0; self->dump_callback = NULL; self->screen = NULL;

    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"parse_bytes", (PyCFunction)py_parse, METH_VARARGS, ""},
    {NULL},
};

PyTypeObject Parser_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Parser",
    .tp_basicsize = sizeof(Parser),
    .tp_dealloc = (destructor)free_vt_parser,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "VT Escape code parser",
    .tp_methods = methods,
    .tp_new = new,
};

Parser*
alloc_vt_parser(id_type window_id) {
    Parser *self = (Parser*)Parser_Type.tp_alloc(&Parser_Type, 1);
    if (self != NULL) {
        self->state = calloc(1, sizeof(PS));
        if (!self->state) { Py_CLEAR(self); PyErr_NoMemory(); return NULL; }
        PS *state = (PS*)self->state;
        state->window_id = window_id;
        state->pending_mode.wait_time = s_double_to_monotonic_t(2.0);
    }
    return self;
}

bool vt_parser_has_pending_data(Parser* p) { return ((PS*)p->state)->pending_mode.used != 0; }
monotonic_t vt_parser_pending_activated_at(Parser*p) { return ((PS*)p->state)->pending_mode.activated_at; }
void vt_parser_set_pending_activated_at(Parser*p, monotonic_t n) { ((PS*)p->state)->pending_mode.activated_at = n; }
monotonic_t vt_parser_pending_wait_time(Parser*p) { return ((PS*)p->state)->pending_mode.wait_time; }
void vt_parser_set_pending_wait_time(Parser*p, monotonic_t n) { ((PS*)p->state)->pending_mode.wait_time = n; }
INIT_TYPE(Parser)
#endif
// }}}
