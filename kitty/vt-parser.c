/*
 * vt-parser.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// TODO: Test clipboard kitten with 52 and 5522
// TODO: Test screen_request_capabilities

#include "vt-parser.h"
#include "screen.h"
#include "control-codes.h"
#include "state.h"
#include "simd-string.h"
#include <stdalign.h>

#define BUF_SZ (1024u*1024u)
// The extra bytes are so loads of large integers such as for AVX 512 dont read past the end of the buffer
#define BUF_EXTRA (512u/8u)
#define MAX_ESCAPE_CODE_LENGTH (BUF_SZ / 4u)
#define MAX_CSI_PARAMS 256u


// Macros {{{

#define SET_STATE(x) \
    self->vte_state = VTE_##x;

#define DIGIT '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9'

static void
_report_unknown_escape_code(PyObject *dump_callback, id_type window_id, const char *name, const uint8_t *payload) {
    char buf[1024];
    if (strlen((const char*)payload) < 64) snprintf(buf, sizeof(buf), "Unknown %s escape code: %.64s", name, payload);
    else snprintf(buf, sizeof(buf), "Unknown %s escape code: %.64s...", name, payload);
    if (dump_callback) {
        Py_XDECREF(PyObject_CallFunction(dump_callback, "Kss", window_id, "error", buf)); PyErr_Clear();
    } else log_error(ERROR_PREFIX " " "%s", buf);
}

#define REPORT_UKNOWN_ESCAPE_CODE(name, data) _report_unknown_escape_code(self->dump_callback, self->window_id, name, data);

#ifdef DUMP_COMMANDS

static void
_report_error(PyObject *dump_callback, id_type window_id, const char *fmt, ...) {
    va_list argptr;
    va_start(argptr, fmt);
    RAII_PyObject(temp, PyUnicode_FromFormatV(fmt, argptr));
    va_end(argptr);
    if (temp != NULL) {
        RAII_PyObject(wid, PyLong_FromUnsignedLongLong(window_id));
        RAII_PyObject(err, PyUnicode_FromString("error"));
        if (wid && err) Py_XDECREF(PyObject_CallFunctionObjArgs(dump_callback, wid, err, temp, NULL));
    }
    PyErr_Clear();
}

static void
_report_params(PyObject *dump_callback, id_type window_id, const char *name, int *params, unsigned int count, bool is_group, Region *r) {
    static char buf[MAX_CSI_PARAMS*3] = {0};
    unsigned int i, p=0;
    if (r) p += snprintf(buf + p, sizeof(buf) - 2, "%u;%u;%u;%u;", r->top, r->left, r->bottom, r->right);
    const char *fmt = is_group ? "%i:" : "%i;";
    for(i = 0; i < count && p < arraysz(buf)-20; i++) {
        int n = snprintf(buf + p, arraysz(buf) - p, fmt, params[i]);
        if (n < 0) break;
        p += n;
    }
    buf[count ? p-1 : p] = 0;
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

#define REPORT_DRAW(chars, num) { \
    for (unsigned i = 0; i < (num); i++) { \
        uint32_t rd_ch = (chars)[i]; \
        switch(rd_ch) { \
            case BEL: REPORT_COMMAND(screen_bell); break; \
            case BS: REPORT_COMMAND(screen_backspace); break; \
            case HT: REPORT_COMMAND(screen_tab); break; \
            case SI: REPORT_COMMAND(screen_change_charset, 0); break; \
            case SO: REPORT_COMMAND(screen_change_charset, 1); break; \
            case LF: case VT: case FF: REPORT_COMMAND(screen_linefeed); break; \
            case CR: REPORT_COMMAND(screen_carriage_return); break; \
            default: \
                if (rd_ch >= ' ') { \
                    RAII_PyObject(t, PyObject_CallFunction(self->dump_callback, "KsC", self->window_id, "draw", rd_ch)); \
                    if (t == NULL) PyErr_Clear(); \
                } \
        } \
    } \
}


#define REPORT_PARAMS(name, params, num, is_group, region) _report_params(self->dump_callback, self->window_id, name, params, num_params, is_group, region)

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
#define REPORT_DRAW(...)
#define REPORT_PARAMS(...)
#define REPORT_OSC(name, string)
#define REPORT_OSC2(name, code, string)
#define REPORT_HYPERLINK(id, url)

#endif
// }}}

// Utils {{{
static const int64_t digit_multipliers[] = {
 10000000000000000l,
 1000000000000000l,
 100000000000000l,
 10000000000000l,
 1000000000000l,
 100000000000l,
 10000000000l,
 1000000000l,
 100000000l,
 10000000l,
 1000000l,
 100000l,
 10000l,
 1000l,
 100l,
 1l
};

// }}}

// Data structures {{{
typedef enum VTEState {
    VTE_NORMAL, VTE_ESC = ESC, VTE_CSI = ESC_CSI, VTE_OSC = ESC_OSC, VTE_DCS = ESC_DCS, VTE_APC = ESC_APC, VTE_PM = ESC_PM, VTE_SOS = ESC_SOS
} VTEState;

static inline const char*
vte_state_name(VTEState s) {
    switch(s) {
        case VTE_NORMAL: return "VTE_NORMAL";
        case VTE_ESC: return "VTE_ESC";
        case VTE_CSI: return "VTE_CSI";
        case VTE_OSC: return "VTE_OSC";
        case VTE_DCS: return "VTE_DCS";
        case VTE_APC: return "VTE_APC";
        case VTE_PM: return "VTE_PM";
        case VTE_SOS: return "VTE_SOS";
    }
    static char buf[16];
    snprintf(buf, sizeof(buf), "VTE_0x%x", s);
    return buf;
}

typedef enum { CSI_START, CSI_BODY, CSI_POST_SECONDARY } CSIState;

typedef struct ParsedCSI {
    char primary, secondary, trailer;
    CSIState state;
    unsigned num_params, num_digits;
    bool is_valid;
    uint64_t accumulator; int mult;
    int params[MAX_CSI_PARAMS];
    uint8_t is_sub_param[MAX_CSI_PARAMS];
} ParsedCSI;

typedef struct PS {
    alignas(BUF_EXTRA) uint8_t buf[BUF_SZ + BUF_EXTRA];
    UTF8Decoder utf8_decoder;

    id_type window_id;

    VTEState vte_state;
    ParsedCSI csi;

    // these are temporary variables set only for duration of a parse call
    PyObject *dump_callback;
    Screen *screen;
    monotonic_t now, new_input_at;
    pthread_mutex_t lock;

    // The buffer
    struct { size_t consumed, pos, sz; } read;
    struct { size_t offset, sz, pending; } write;
} PS;

static void
reset_csi(ParsedCSI *csi) {
    csi->num_params = 0; csi->primary = 0; csi->secondary = 0;
    csi->trailer = 0; csi->state = CSI_START; csi->num_digits = 0;
    csi->is_valid = false; csi->accumulator = 0; csi->mult = 1;
}
// }}}

// Normal mode {{{

static void
dispatch_single_byte_control(PS *self, uint32_t ch) {
    REPORT_DRAW(&ch, 1);
    screen_draw_text(self->screen, &ch, 1);
}

static void
consume_normal(PS *self) {
    do {
        const bool sentinel_found = utf8_decode_to_esc(&self->utf8_decoder, self->buf + self->read.pos, self->read.sz - self->read.pos);
        self->read.pos += self->utf8_decoder.num_consumed;
        if (self->utf8_decoder.output.pos) {
            REPORT_DRAW(self->utf8_decoder.output.storage, self->utf8_decoder.output.pos);
            screen_draw_text(self->screen, self->utf8_decoder.output.storage, self->utf8_decoder.output.pos);
        }
        if (sentinel_found) { SET_STATE(ESC); break; }
    } while (self->read.pos < self->read.sz);
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

static bool
consume_esc(PS *self) {
#define CALL_ED(name) REPORT_COMMAND(name); name(self->screen); SET_STATE(NORMAL);
#define CALL_ED1(name, ch) REPORT_COMMAND(name, ch); name(self->screen, ch); SET_STATE(NORMAL);
#define CALL_ED2(name, a, b) REPORT_COMMAND(name, a, b); name(self->screen, a, b); SET_STATE(NORMAL);
    const uint8_t ch = self->buf[self->read.pos++];
    const bool is_first_char = self->read.pos - self->read.consumed == 1;
    if (is_first_char) {
        switch(ch) {
            case ESC_DCS: SET_STATE(DCS); break;
            case ESC_OSC: SET_STATE(OSC); break;
            case ESC_CSI: SET_STATE(CSI); reset_csi(&self->csi); break;
            case ESC_APC: SET_STATE(APC); break;
            case ESC_SOS: SET_STATE(SOS); break;
            case ESC_PM: SET_STATE(PM); break;
            IS_ESCAPED_CHAR:
                return false;
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
            default:
                REPORT_ERROR("%s0x%x", "Unknown char after ESC: ", ch);
                SET_STATE(NORMAL); break;
        }
        return true;
    } else {
        const uint8_t prev_ch = self->buf[self->read.pos-2];
        SET_STATE(NORMAL);
        switch(prev_ch) {
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
                        CALL_ED2(screen_designate_charset, prev_ch - '(', ch); break;
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
                REPORT_ERROR("Unhandled charset related escape code: 0x%x 0x%x", prev_ch, ch); break;
        }
        return true;
    }
#undef CALL_ED
#undef CALL_ED1
} // }}}

// ST terminator {{{
static bool
find_st_terminator(PS *self, size_t *end_pos) {
    const size_t sz = self->read.sz - self->read.pos;
    const uint8_t *q = find_either_of_two_bytes(self->buf + self->read.pos, sz, BEL, ESC_ST);
    if (q == NULL) {
        self->read.pos += sz;
        return false;
    }
    switch(*q) {
        case ESC_ST:
            if (q > self->buf && *(q-1) == ESC) {
                *end_pos = q - 1 - self->buf;
                self->read.pos = *end_pos + 2;
                return true;
            }
            self->read.pos = (q - self->buf) + 1;
            break;
        case BEL:
            *end_pos = q - self->buf;
            self->read.pos = *end_pos + 1;
            return true;
    }
    return false;
}
// }}}

// OSC {{{

#include "parse-multicell-command.h"

static bool
is_osc_52(PS *self) {
    return memcmp(self->buf + self->read.consumed, "52;", 3) == 0;
}

static void
continue_osc_52(PS *self) {
    self->read.pos -= 4;
    self->read.consumed = self->read.pos;
    self->buf[self->read.pos++] = '5'; self->buf[self->read.pos++] = '2';
    self->buf[self->read.pos++] = ';'; self->buf[self->read.pos++] = ';';
}


static bool
accumulate_st_terminated_esc_code(PS *self, void(dispatch)(PS*, uint8_t*, size_t, bool)) {
    size_t pos;
    if (find_st_terminator(self, &pos)) {
        // technically we should check MAX_ESCAPE_CODE_LENGTH here but lets be generous in what we accept since  we
        // have a full escape code
        uint8_t *buf = self->buf + self->read.consumed;
        size_t sz = pos - self->read.consumed;
        buf[sz] = 0;  // ensure null termination, this is anyway an ST termination char
        dispatch(self, buf, sz, false);
        return true;
    }
    if (UNLIKELY((pos=self->read.pos - self->read.consumed) > MAX_ESCAPE_CODE_LENGTH)) {
        if (self->vte_state == VTE_OSC && is_osc_52(self)) {
            // null terminate
            self->read.pos--;
            uint8_t before = self->buf[self->read.pos];
            self->buf[self->read.pos] = 0;
            // send partial OSC 52
            dispatch(self, self->buf + self->read.consumed, self->read.pos - self->read.consumed, true);
            // continue OSC 52
            self->buf[self->read.pos] = before;
            continue_osc_52(self);
            return accumulate_st_terminated_esc_code(self, dispatch);
        }
        REPORT_ERROR("%s escape code too long (%zu bytes), ignoring it", vte_state_name(self->vte_state), pos);
        return true;
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
dispatch_hyperlink(PS *self, char *buf) {
    char *id = NULL, *url = NULL;
    if (parse_osc_8(buf, &id, &url)) {
        REPORT_HYPERLINK(id, url);
        set_active_hyperlink(self->screen, id, url);
    } else {
        REPORT_ERROR("Ignoring malformed OSC 8 code");
    }
}


static void
dispatch_osc(PS *self, uint8_t *buf, size_t limit, bool is_extended_osc) {
#define DISPATCH_OSC_WITH_CODE(name) REPORT_OSC2(name, code, mv); name(self->screen, code, mv);
#define DISPATCH_OSC(name) REPORT_OSC(name, mv); name(self->screen, mv);
#define START_DISPATCH {\
    RAII_PyObject(mv, PyMemoryView_FromMemory((char*)buf + i, limit - i, PyBUF_READ)); \
    if (mv) {
#define END_DISPATCH_WITHOUT_BREAK }; PyErr_Clear(); }
#define END_DISPATCH }; PyErr_Clear(); break; }

    int64_t accumulator = 0;
    int code=0;
    unsigned int i;
    for (i = 0; i < MIN(limit, 5u); i++) {
        int64_t num = buf[i] - '0';
        if (num < 0 || num > 9) break;
        accumulator += num * digit_multipliers[i];
    }
    if (i > 0) {
        code = accumulator / digit_multipliers[i - 1];
        if (i < limit && buf[i] == ';') i++;
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
        case 5: case 105: REPORT_ERROR("Ignoring OSC 5/105, used by XTerm to change special colors used for rendering bold/italic/underline"); break;
        case 6: case 106: {  // report only once as this is used by benchmark kitten causing log spam
            static bool reported = false;
            if (!reported) {
                reported = true;
                REPORT_ERROR("Ignoring OSC 6/106, used by XTerm to enable/disable special colors used for rendering bold/italic/underline");
            }
        } break;
        case 4:
        case 104:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(set_color_table_color);
            END_DISPATCH
        case 7:
#ifdef DUMP_COMMANDS
            START_DISPATCH
            REPORT_OSC2(process_cwd_notification, code, mv);
            END_DISPATCH_WITHOUT_BREAK
#endif
            process_cwd_notification(self->screen, code, (char*)buf + i, limit-i);
            break;
        case 8:
            dispatch_hyperlink(self, (char*)buf + i);
            break;
        case 9:
        case 99:
        case 777:
        case 1337:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(desktop_notify)
            END_DISPATCH
        case 13: case 14: case 15: case 16: case 18:
            REPORT_ERROR("Ignoring OSC 13,14,15,16 and 18 used for pointer and Textronic colors by XTerm"); break;
            break;
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
        case 21:
            START_DISPATCH
            DISPATCH_OSC_WITH_CODE(color_control);
            END_DISPATCH
        case 52: case 5522:
            START_DISPATCH
            if (is_extended_osc && code == 52) code = -52;
            DISPATCH_OSC_WITH_CODE(clipboard_control);
            END_DISPATCH
        case 46: REPORT_ERROR("Ignoring OSC 46 used for file logging in XTerm"); break;
        case 50: REPORT_ERROR("Ignoring OSC 50 used for font changing in XTerm"); break;
        case 51: REPORT_ERROR("Ignoring OSC 51 used by emacs shell"); break;
        case 60: case 61: REPORT_ERROR("Ignoring OSC 60/61 used for query control in XTerm"); break;
        case 66:
            parse_multicell_code(self, buf + i, limit - i);
            break;
        case 133:
#ifdef DUMP_COMMANDS
            START_DISPATCH
            REPORT_OSC2(shell_prompt_marking, code, mv);
            END_DISPATCH_WITHOUT_BREAK
#endif
            if (limit > i) {
                buf[limit] = 0; // safe to do as we have 8 extra bytes after PARSER_BUF_SZ
                shell_prompt_marking(self->screen, (char*)buf + i);
            }
            break;
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
        case 440: REPORT_ERROR("Ignoring OSC 440 used for audio by mintty"); break;
        case 633: REPORT_ERROR("Ignoring OSC 633, use by Windows Terminal for VSCode actions"); break;
        case 666: REPORT_ERROR("Ignoring OSC 666, typically used by VTE terminals for shell integration"); break;
        case 697: REPORT_ERROR("Ignoring OSC 697, typically used by Fig for shell integration"); break;
        case 701: REPORT_ERROR("Ignoring OSC 701, used by mintty for locale"); break;
        case 3008: REPORT_ERROR("Ignoring OSC 3008, used by systemd for OSC-context"); break;
        case 7704: REPORT_ERROR("Ignoring OSC 7704, used by mintty for ANSI colors"); break;
        case 7750: REPORT_ERROR("Ignoring OSC 7750, used by mintty for Emoji style"); break;
        case 7770: REPORT_ERROR("Ignoring OSC 7770, used by mintty for font size"); break;
        case 7721: REPORT_ERROR("Ignoring OSC 7721, used by mintty for copy window title"); break;
        case 7771: REPORT_ERROR("Ignoring OSC 7771, used by mintty for glyph coverage"); break;
        case 7777: REPORT_ERROR("Ignoring OSC 7777, used by mintty for window size"); break;
        case 77119: REPORT_ERROR("Ignoring OSC 7777, used by mintty for wide chars"); break;
        case 9001: REPORT_ERROR("Ignoring OSC 9001, used by windows terminal"); break;
        default:
            REPORT_UKNOWN_ESCAPE_CODE("OSC", buf);
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
startswith(const uint8_t *string, ssize_t sz, const char *prefix, ssize_t l) {
    if (sz < l) return false;
    for (ssize_t i = 0; i < l; i++) {
        if (string[i] != (unsigned char)prefix[i]) return false;
    }
    return true;
}

static bool
parse_kitty_dcs(PS *self, uint8_t *buf, size_t bufsz) {
#define starts_with(x) startswith(buf, bufsz, x, literal_strlen(x))
#define inc(x) buf += literal_strlen(x); bufsz -= literal_strlen(x)
#define dispatch(prefix, func, delta) {\
    if (starts_with(prefix)) {\
        inc(prefix); buf -= delta; bufsz += delta; \
        PyObject *cmd = PyMemoryView_FromMemory((char*)buf, bufsz, PyBUF_READ); \
        if (cmd) { \
            REPORT_OSC(func, cmd); \
            screen_handle_kitty_dcs(self->screen, #func, cmd); \
            Py_DECREF(cmd); \
        } else PyErr_Clear(); \
        return true; \
    }}
    if (!starts_with("kitty-")) return false;
    inc("kitty-");

    dispatch("cmd{", handle_remote_cmd, 1);
    dispatch("overlay-ready|", handle_overlay_ready, 0)
    dispatch("kitten-result|", handle_kitten_result, 0)
    dispatch("print|", handle_remote_print, 0)
    dispatch("echo|", handle_remote_echo, 0)
    dispatch("ssh|", handle_remote_ssh, 0)
    dispatch("ask|", handle_remote_askpass, 0)
    dispatch("clone|", handle_remote_clone, 0)
    dispatch("edit|", handle_remote_edit, 0)
    dispatch("restore-cursor-appearance|", handle_restore_cursor_appearance, 0)

    return false;
#undef dispatch
#undef starts_with
#undef inc
}

static void
dispatch_dcs(PS *self, uint8_t *buf, size_t bufsz, bool is_extended UNUSED) {
    if (bufsz < 2) return;
    switch (buf[0]) {
        case '+':
        case '$':
            if (buf[1] == 'q') {
                PyObject *mv = PyMemoryView_FromMemory((char*)buf + 2, bufsz-2, PyBUF_READ);
                if (mv) {
                    REPORT_OSC2(screen_request_capabilities, (char)buf[0], mv);
                    Py_DECREF(mv);
                } else PyErr_Clear();
                screen_request_capabilities(self->screen, (char)buf[0], (char*)buf + 2);
            } else {
                REPORT_UKNOWN_ESCAPE_CODE("DCS", buf);
            }
            break;
        case '=':
            if (bufsz > 2 && (buf[1] == '1' || buf[1] == '2') && buf[2] == 's') {
                if (buf[1] == '1') {
                    REPORT_COMMAND(screen_start_pending_mode)
                    if (!screen_pause_rendering(self->screen, true, 0)) {
                        REPORT_ERROR("Pending mode start requested while already in pending mode. This is most likely an application error.");
                    }
                } else {
                    REPORT_COMMAND(screen_stop_pending_mode);
                    if (!screen_pause_rendering(self->screen, false, 0)) {
                        REPORT_ERROR("Pending mode stop command issued while not in pending mode, this can"
                            " be either a bug in the terminal application or caused by a timeout with no data"
                            " received for too long or by too much data in pending mode");
                    }
                }
            } else {
                REPORT_UKNOWN_ESCAPE_CODE("DCS", buf);
            } break;
        case '@':
            if (!parse_kitty_dcs(self, buf + 1, bufsz-1)) REPORT_UKNOWN_ESCAPE_CODE("DCS", buf);
            break;
        default:
            REPORT_UKNOWN_ESCAPE_CODE("DCS", buf);
            break;
    }
}

// }}}

// CSI {{{

#define CSI_SECONDARY \
        ' ': \
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
        case '/'

#define CSI_TRAILER \
        '@': \
START_ALLOW_CASE_RANGE \
        case 'a' ... 'z': \
        case 'A' ... 'Z': \
END_ALLOW_CASE_RANGE \
        case '`': \
        case '{': \
        case '|': \
        case '}': \
        case '~'

#define CSI_NORMAL_MODE_EMBEDDINGS \
        BEL: \
        case BS: \
        case HT: \
        case LF: \
        case VT: \
        case FF: \
        case CR: \
        case SO: \
        case SI

static const char*
csi_letter(unsigned code) {
    static char buf[8];
    if (33 <= code && code <= 126) snprintf(buf, sizeof(buf), "%c", code);
    else snprintf(buf, sizeof(buf), "0x%x", code);
    return buf;
}

static bool
commit_csi_param(PS *self UNUSED, ParsedCSI *csi) {
    if (!csi->num_digits) return true;
    if (csi->num_params >= MAX_CSI_PARAMS) {
        REPORT_ERROR("CSI escape code has too many parameters, ignoring it");
        return false;
    }
    csi->params[csi->num_params++] = csi->mult * (csi->accumulator / digit_multipliers[csi->num_digits - 1]);
    csi->num_digits = 0; csi->mult = 1; csi->accumulator = 0;
    return true;
}

static void
csi_add_digit(ParsedCSI *csi, uint8_t ch) {
    if (UNLIKELY(csi->num_digits >= arraysz(digit_multipliers))) return;
    csi->accumulator += (ch - '0') * digit_multipliers[csi->num_digits++];
}

static bool
csi_parse_loop(PS *self, ParsedCSI *csi, const uint8_t *buf, size_t *pos, const size_t sz, const size_t start) {
    while (*pos < sz) {
        const uint8_t ch = buf[*pos]; *pos += 1;
        switch(csi->state) {
            case CSI_START:
                switch (ch) {
                    case CSI_NORMAL_MODE_EMBEDDINGS:
                        dispatch_single_byte_control(self, ch); break;
                    case ';':
                        csi->params[csi->num_params++] = 0;
                        csi->state = CSI_BODY;
                        break;
                    case DIGIT:
                        csi_add_digit(csi, ch);
                        csi->state = CSI_BODY;
                        break;
                    case '?':
                    case '>':
                    case '<':
                    case '=':
                        csi->state = CSI_BODY;
                        csi->primary = ch;
                        break;
                    case CSI_SECONDARY:
                        if (ch == '-') {
                            csi->mult = -1;
                            csi->num_digits++;
                            csi->state = CSI_BODY;
                        } else {
                            csi->secondary = ch;
                            csi->state = CSI_POST_SECONDARY;
                        }
                        break;
                    case CSI_TRAILER:
                        csi->is_valid = true;
                        csi->trailer = ch;
                        return true;
                    default:
                        REPORT_ERROR("Invalid character in CSI: %s (0x%x), ignoring the sequence", csi_letter(ch), ch);
                        return true;
                }
                break;
            case CSI_POST_SECONDARY:
                switch (ch) {
                    case CSI_NORMAL_MODE_EMBEDDINGS:
                        dispatch_single_byte_control(self, ch); break;
                    case CSI_TRAILER:
                        csi->is_valid = true;
                        csi->trailer = ch;
                        break;
                    default:
                        REPORT_ERROR("Invalid character in CSI: %s (0x%x), ignoring the sequence", csi_letter(ch), ch);
                        break;
                }
                return true;
            case CSI_BODY:
                switch(ch) {
                    case CSI_NORMAL_MODE_EMBEDDINGS:
                        dispatch_single_byte_control(self, ch); break;
                    case CSI_SECONDARY:
                        if (ch == '-' && csi->num_digits == 0) {
                            csi->mult = -1; csi->num_digits = 1;
                        } else {
                            if (!commit_csi_param(self, csi)) return true;
                            csi->secondary = ch;
                            csi->state = CSI_POST_SECONDARY;
                        }
                        break;
                    case CSI_TRAILER:
                        if (csi->num_digits == 1 && csi->secondary == 0 && csi->mult == -1) {
                            csi->num_digits = 0; csi->secondary = '-';
                        }
                        if (!commit_csi_param(self, csi)) return true;
                        csi->is_valid = true;
                        csi->trailer = ch;
                        return true;
                    case ':':
                        if (!commit_csi_param(self, csi)) return true;
                        csi->is_sub_param[csi->num_params] = true;
                        break;
                    case ';':
                        if (!csi->num_digits) csi->num_digits++;  // Empty means zero
                        if (!commit_csi_param(self, csi)) return true;
                        csi->is_sub_param[csi->num_params] = false;
                        break;
                    case DIGIT:
                        csi_add_digit(csi, ch);
                        break;
                    default:
                        REPORT_ERROR("Invalid character in CSI: %s (0x%x), ignoring the sequence", csi_letter(ch), ch);
                        return true;
                }
                break;
        }
    }
    if (UNLIKELY(*pos - start > MAX_ESCAPE_CODE_LENGTH)) {
        REPORT_ERROR("CSI escape too long ignoring and truncating");
        return true;
    }
    return false;
#undef COMMIT_PARAM
}

static bool
consume_csi(PS *self) {
    return csi_parse_loop(self, &self->csi, self->buf, &self->read.pos, self->read.sz, self->read.consumed);
}

static unsigned int
parse_region(const ParsedCSI *csi, Region *r) {
    switch(csi->num_params) {
        case 0:
            return 0;
        case 1:
            r->top = csi->params[0];
            return 1;
        case 2:
            r->top = csi->params[0]; r->left = csi->params[1];
            return 2;
        case 3:
            r->top = csi->params[0]; r->left = csi->params[1]; r->bottom = csi->params[2];
            return 3;
        default:
            r->top = csi->params[0]; r->left = csi->params[1]; r->bottom = csi->params[2]; r->right = csi->params[3];
            return 4;
    }
}


static bool
_parse_sgr(PS *self, ParsedCSI *csi) {
#define SEND_SGR if (num_params) { \
    REPORT_PARAMS(report_name, csi->params + first_param, num_params, state != NORMAL, region); \
    select_graphic_rendition(screen, csi->params + first_param, num_params, state != NORMAL, region); \
    state = NORMAL; first_param += num_params; num_params = 0; \
}
    Screen *screen = self->screen;
    size_t pos = 0, first_param, num_params = 0;
    Region r = {0}, *region = NULL;
    const char *report_name = "select_graphic_rendition";
    if (csi->trailer == 'r') {  // DECCARA
        region = &r;
        if (csi->num_params == 0) {
            for (; csi->num_params < 5; csi->num_params++) csi->params[csi->num_params] = 0;
        }
        pos = parse_region(csi, region);
        report_name = "deccara";
        (void)report_name;
    } else if (csi->num_params == 0) {
        csi->params[0] = 0;
        csi->num_params++;
    }
    enum State { NORMAL, SUB_PARAMS, COLOR, COLOR1, COLOR3 };
    enum State state = NORMAL;

    for (first_param = pos; pos < csi->num_params; pos++) {
        switch (state) {
            case NORMAL:
                if (csi->is_sub_param[pos]) {
                    if (num_params == 0 || pos == 0)  {
                        REPORT_ERROR("SGR escape code has an unexpected sub-parameter ignoring the full code");
                        return false;
                    }
                    num_params--;
                    SEND_SGR;
                    state = SUB_PARAMS;
                    first_param = pos - 1;
                    num_params = 1;
                }
                switch(csi->params[pos]) {
                    case 38: case 48: case DECORATION_FG_CODE:
                        SEND_SGR;
                        state = COLOR;
                        first_param = pos;
                        num_params = 1;
                        break;
                    default:
                        num_params++;
                        break;
                } break;
            case SUB_PARAMS:
                switch(csi->is_sub_param[pos]) {
                    case true:
                        num_params++; break;
                    case false:
                        SEND_SGR;
                        pos--;
                        break;
                } break;
            case COLOR:
                switch(csi->params[pos]) {
                    case 2:
                        state = csi->is_sub_param[pos] ? SUB_PARAMS : COLOR3;
                        num_params++;
                        break;
                    case 5:
                        state = csi->is_sub_param[pos] ? SUB_PARAMS : COLOR1;
                        num_params++;
                        break;
                    default:
                        REPORT_ERROR("SGR escape code has unknown color type: %d ignoring the full code", csi->params[pos]);
                        return false;
                } break;
            case COLOR1:
                num_params++;
                SEND_SGR;
                break;
            case COLOR3:
                num_params++;
                if (num_params >= 5) { SEND_SGR; }
                break;
        }
    }
    SEND_SGR;
    return true;
#undef SEND_SGR
}

#ifndef DUMP_COMMANDS
bool
parse_sgr(Screen *screen, const uint8_t *buf, unsigned int num, const char *report_name UNUSED, bool is_deccara) {
    ParsedCSI csi = {.mult=1};
    size_t pos = 0;
    RAII_ALLOC(uint8_t, _buf, malloc(num + 3));
    if (!_buf) return false;
    memcpy(_buf, buf, num);
    if (is_deccara) {
        _buf[num++] = '$'; _buf[num++] = 'r';
    } else {
        _buf[num++] = 'm';
    }
    _buf[num] = 0;
    PS *state = (PS*)screen->vt_parser->state;
    state->screen = screen;
    if (!csi_parse_loop(state, &csi, _buf, &pos, num, 0)) return false;
    return _parse_sgr(state, &csi);
}
#endif

static void
screen_cursor_up2(Screen *s, unsigned int count) { screen_cursor_up(s, count, false, -1); }
static void
screen_cursor_back1(Screen *s, unsigned int count) { screen_cursor_move(s, count, -1); }
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

static void
handle_mode(PS *self) {
    bool is_shifted = self->csi.primary == '?';
    int shift = is_shifted ? 5 : 0;
    for (unsigned i = 0; i < self->csi.num_params; i++) {
        int p = self->csi.params[i];
        if (p >= 0) {
            unsigned int sp = p << shift;
            switch (self->csi.trailer) {
                case SM:
                    screen_set_mode(self->screen, sp);
                    REPORT_COMMAND(screen_set_mode, p, is_shifted);
                    break;
                case RM:
                    screen_reset_mode(self->screen, sp);
                    REPORT_COMMAND(screen_reset_mode, p, is_shifted);
                    break;
                case 's':
                    screen_save_mode(self->screen, sp);
                    REPORT_COMMAND(screen_save_mode, p, is_shifted);
                    break;
                case 'r':
                    screen_restore_mode(self->screen, sp);
                    REPORT_COMMAND(screen_restore_mode, p, is_shifted);
                    break;
            }
        }
    }
}

static void
dispatch_csi(PS *self) {
#define num_params self->csi.num_params
#define code self->csi.trailer
#define params self->csi.params
#define start_modifier self->csi.primary
#define end_modifier self->csi.secondary

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

#define NO_MODIFIERS(modifier, special, special_msg) { \
    if (self->csi.primary || self->csi.secondary) { \
        if (special && modifier == special) { REPORT_ERROR(special_msg); } \
        else { REPORT_ERROR("CSI code %s has unsupported start modifier: %s or end modifier: %s", csi_letter(self->csi.trailer), csi_letter(self->csi.primary), csi_letter(self->csi.secondary));} \
        break; \
    } \
}

    int p1, p2; bool private;

    switch(self->csi.trailer) {
        case ICH:
            NO_MODIFIERS(self->csi.secondary, ' ', "Shift left escape code not implemented");
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
            handle_mode(self); break;
        case RM:
            handle_mode(self); break;
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
                } else handle_mode(self);
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
                    REPORT_ERROR("Escape codes to resize text area are not supported");
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
                } else handle_mode(self);
                break;
            } else if (!start_modifier && end_modifier == '$') {
                _parse_sgr(self, &self->csi);
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
            if (!start_modifier && !end_modifier) {
                _parse_sgr(self, &self->csi);
                break;
            }
            if (start_modifier == '>' && !end_modifier) {
                CALL_CSI_HANDLER1(screen_modify_other_keys, 0);
                break;
            }
            /* fallthrough */
        default:
            REPORT_ERROR("Unknown CSI code: '%c' with start_modifier: '%c' and end_modifier: '%c' and parameters: '%s'", code, start_modifier, end_modifier, repr_csi_params(params, num_params));
    }
#undef num_params
#undef code
#undef params
#undef start_modifier
#undef end_modifier
}

// }}}

// APC mode {{{

#include "parse-graphics-command.h"

static void
dispatch_apc(PS *self, uint8_t *buf, size_t bufsz, bool is_extended UNUSED) {
    if (bufsz < 2) return;
    switch(buf[0]) {
        case 'G':
            parse_graphics_code(self, buf, bufsz);
            break;
        default:
            REPORT_ERROR("Unrecognized APC code: 0x%x", buf[0]);
            break;
    }
}

// }}}

// PM mode {{{
static void
dispatch_pm(PS *self UNUSED, uint8_t *buf, size_t bufsz, bool is_extended UNUSED) {
    if (bufsz < 2) return;
    switch(buf[0]) {
        default:
            REPORT_ERROR("Unrecognized PM code: 0x%x", buf[0]);
            break;
    }
}


// }}}

// SOS mode {{{
static void
dispatch_sos(PS *self UNUSED, uint8_t *buf, size_t bufsz, bool is_extended UNUSED) {
    if (bufsz < 2) return;
    switch(buf[0]) {
        default:
            REPORT_ERROR("Unrecognized SOS code: 0x%x", buf[0]);
            break;
    }
}


// }}}

// Parse loop {{{
static void
consume_input(PS *self, PyObject *dump_callback UNUSED, id_type window_id UNUSED) {
#define consume(x) if (accumulate_st_terminated_esc_code(self, dispatch_##x)) { self->read.consumed = self->read.pos; SET_STATE(NORMAL); } break;

#ifdef DUMP_COMMANDS
    PyObject *dumped_bytes = PyBytes_FromStringAndSize((const char*)self->buf + self->read.pos, self->read.sz - self->read.pos);
    size_t pre_consume_pos = self->read.pos;
#endif

    switch (self->vte_state) {
        case VTE_NORMAL:
            consume_normal(self); self->read.consumed = self->read.pos; break;
        case VTE_ESC:
            if (consume_esc(self)) { self->read.consumed = self->read.pos; }
            break;
        case VTE_CSI:
            if (consume_csi(self)) { self->read.consumed = self->read.pos; if (self->csi.is_valid) dispatch_csi(self); SET_STATE(NORMAL); }
            break;
        case VTE_OSC:
            consume(osc);
        case VTE_APC:
            consume(apc);
        case VTE_PM:
            consume(pm);
        case VTE_DCS:
            consume(dcs);
        case VTE_SOS:
            consume(sos);
    }

#ifdef DUMP_COMMANDS
    if (dumped_bytes && dump_callback && self->read.pos > pre_consume_pos) {
        if (_PyBytes_Resize(&dumped_bytes, self->read.pos - pre_consume_pos) == 0) {
            PyObject *ret = PyObject_CallFunction(dump_callback, "KsO", window_id, "bytes", dumped_bytes);
            Py_DECREF(dumped_bytes);
            if (ret) { Py_DECREF(ret); } else { PyErr_Clear(); }
        }
    }
#endif

#undef consume
}

// }}}

// API {{{

#define with_lock pthread_mutex_lock(&self->lock);
#define end_with_lock pthread_mutex_unlock(&self->lock);

static void
run_worker(void *p, ParseData *pd, bool flush) {
    Screen *screen = (Screen*)p;
    PS *self = (PS*)screen->vt_parser->state;
    screen->parsing_at = pd->now;
    with_lock {
        self->read.sz += self->write.pending; self->write.pending = 0;
        pd->has_pending_input = self->read.pos < self->read.sz;
        if (pd->has_pending_input) {
            pd->time_since_new_input = pd->now - self->new_input_at;
            if (flush || pd->time_since_new_input >= OPT(input_delay) || self->read.sz + 16 * 1024 > BUF_SZ) {
                pd->input_read = true;
                self->dump_callback = pd->dump_callback; self->now = pd->now;
                self->screen = screen;
                self->read.consumed = 0;
                do {
                    end_with_lock; {
                        consume_input(self, pd->dump_callback, screen->window_id);
                    } with_lock;
                    self->read.sz += self->write.pending; self->write.pending = 0;
                } while (self->read.pos < self->read.sz);
                self->new_input_at = 0;
                if (self->read.consumed) {
                    pd->write_space_created = self->read.sz >= BUF_SZ;
                    self->read.pos -= MIN(self->read.pos, self->read.consumed);
                    self->read.sz -= MIN(self->read.sz, self->read.consumed);
                    if (self->read.sz) memmove(self->buf, self->buf + self->read.consumed, self->read.sz);
                }
            }
        }
    } end_with_lock;
}

#ifndef DUMP_COMMANDS

uint8_t*
vt_parser_create_write_buffer(Parser *p, size_t *sz) {
    PS *self = (PS*)p->state;
    uint8_t *ans;
    with_lock {
        if (self->write.sz) fatal("vt_parser_create_write_buffer() called with an already existing write buffer");
        self->write.offset = self->read.sz + self->write.pending;
        *sz = BUF_SZ - self->write.offset;
        self->write.sz = *sz;
        ans = self->buf + self->write.offset;
    } end_with_lock;
    return ans;
}

void
vt_parser_commit_write(Parser *p, size_t sz) {
    PS *self = (PS*)p->state;
    with_lock {
        size_t off = self->read.sz + self->write.pending;
        if (self->new_input_at == 0) self->new_input_at = monotonic();
        if (self->write.offset > off) memmove(self->buf + off, self->buf + self->write.offset, sz);
        self->write.pending += sz;
        self->write.sz = 0;
    } end_with_lock;
}

bool
vt_parser_has_space_for_input(const Parser *p) {
    PS *self = (PS*)p->state;
    bool ans;
    with_lock {
        ans = self->read.sz + self->write.pending < BUF_SZ;
    } end_with_lock;
    return ans;
}
#endif

// }}}

// Boilerplate {{{

#ifdef DUMP_COMMANDS
void
parse_worker_dump(void *p, ParseData *pd, bool flush) { run_worker(p, pd, flush); }
#else
void
parse_worker(void *p, ParseData *pd, bool flush) { run_worker(p, pd, flush); }
#endif

#ifndef DUMP_COMMANDS
static PyObject*
new_vtparser_object(PyTypeObject *type UNUSED, PyObject *args, PyObject UNUSED *kwds) {
    id_type window_id=0;
    if (!PyArg_ParseTuple(args, "|K", &window_id)) return NULL;
    return (PyObject*) alloc_vt_parser(window_id);
}

void
free_vt_parser(Parser* self) {
    if (self->state) {
        PS *s = (PS*)self->state;
        utf8_decoder_free(&s->utf8_decoder);
        pthread_mutex_destroy(&s->lock);
        free(self->state); self->state = NULL;
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static void
reset(PS *self) {
    SET_STATE(NORMAL);
    reset_csi(&self->csi);
    utf8_decoder_reset(&self->utf8_decoder);
}

void
reset_vt_parser(Parser *self) {
    reset((PS*)self->state);
}

extern PyTypeObject Screen_Type;

static PyObject*
current_state(Parser *self, PyObject *closure UNUSED) {
    PS *state = (PS*)self->state;
    return PyUnicode_FromString(vte_state_name(state->vte_state));
}

static PyGetSetDef getsetters[] = {
    {"vte_state", (getter)current_state, NULL, "The VTE parser state", NULL},
    {NULL}  /* Sentinel */
};


static PyMethodDef methods[] = {
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
    .tp_getset = getsetters,
    .tp_new = new_vtparser_object,
};

Parser*
alloc_vt_parser(id_type window_id) {
    Parser *self = (Parser*)Parser_Type.tp_alloc(&Parser_Type, 1);
    if (self != NULL) {
        int ret;
        if ((ret = posix_memalign((void**)&self->state, BUF_EXTRA, sizeof(PS))) != 0) {
            Py_CLEAR(self);
            PyErr_Format(PyExc_RuntimeError, "Failed to call posix_memalign: %s", strerror(ret));
            return NULL;
        }
        memset(self->state, 0, sizeof(PS));
        PS *state = (PS*)self->state;
        if ((intptr_t)state->buf % BUF_EXTRA != 0) {
            Py_CLEAR(self); PyErr_SetString(PyExc_TypeError, "PS->buf is not aligned");
            return NULL;
        }
        if ((ret = pthread_mutex_init(&state->lock, NULL)) != 0) {
            Py_CLEAR(self); PyErr_Format(PyExc_RuntimeError, "Failed to create Parser lock mutex: %s", strerror(ret));
            return NULL;
        }
        state->window_id = window_id;
        utf8_decoder_reset(&state->utf8_decoder);
        reset_csi(&state->csi);
    }
    return self;
}

#undef EXTRA_INIT
#define EXTRA_INIT \
    if (0 != PyModule_AddIntConstant(module, "VT_PARSER_BUFFER_SIZE", BUF_SZ)) return 0; \
    if (0 != PyModule_AddIntConstant(module, "VT_PARSER_MAX_ESCAPE_CODE_SIZE", MAX_ESCAPE_CODE_LENGTH)) return 0; \
    if (!init_simd(module)) return 0; \

INIT_TYPE(Parser)

#endif
// }}}
