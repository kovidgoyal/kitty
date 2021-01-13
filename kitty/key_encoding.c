/*
 * key_encoding.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "keys.h"
#include "charsets.h"

typedef enum { SHIFT=1, ALT=2, CTRL=4, SUPER=8 } ModifierMasks;
typedef enum { PRESS = 0, REPEAT = 1, RELEASE = 2} KeyAction;
typedef struct {
    uint32_t key, shifted_key, alternate_key;
    struct {
        bool shift, alt, ctrl, super;
        unsigned value;
        char encoded[4];
    } mods;
    KeyAction action;
    bool cursor_key_mode, disambiguate, report_all_event_types, report_alternate_key;
    const char *text;
    bool has_text;
} KeyEvent;

typedef struct {
    uint32_t key, shifted_key, alternate_key;
    bool add_alternates, has_mods, add_actions;
    char encoded_mods[4];
    KeyAction action;
} EncodingData;


static inline void
convert_glfw_mods(int mods, KeyEvent *ev) {
    ev->mods.alt = (mods & GLFW_MOD_ALT) > 0, ev->mods.ctrl = (mods & GLFW_MOD_CONTROL) > 0, ev->mods.shift = (mods & GLFW_MOD_SHIFT) > 0, ev->mods.super = (mods & GLFW_MOD_SUPER) > 0;
    ev->mods.value = ev->mods.shift ? SHIFT : 0;
    if (ev->mods.alt) ev->mods.value |= ALT;
    if (ev->mods.ctrl) ev->mods.value |= CTRL;
    if (ev->mods.super) ev->mods.value |= SUPER;
    snprintf(ev->mods.encoded, sizeof(ev->mods.encoded), "%u", ev->mods.value + 1);
}


static inline int
encode_csi_string(const char csi_trailer, const char *payload, char *output) {
    return snprintf(output, KEY_BUFFER_SIZE, "\x1b[%s%c", payload, csi_trailer);
}

static inline void
init_encoding_data(EncodingData *ans, const KeyEvent *ev) {
    ans->add_actions = ev->report_all_event_types && ev->action != PRESS;
    ans->has_mods = ev->mods.encoded[0] && ev->mods.encoded[0] != '1';
    ans->add_alternates = ev->report_alternate_key && (ev->shifted_key > 0 || ev->alternate_key > 0);
    if (ans->add_alternates) { ans->shifted_key = ev->shifted_key; ans->alternate_key = ev->alternate_key; }
    ans->action = ev->action;
    ans->key = ev->key;
    memcpy(ans->encoded_mods, ev->mods.encoded, sizeof(ans->encoded_mods));
}

static inline int
serialize(const EncodingData *data, char *output, const char csi_trailer) {
    int pos = 0;
#define P(fmt, ...) pos += snprintf(output + pos, KEY_BUFFER_SIZE - 2 - pos, fmt, __VA_ARGS__)
    P("\x1b%s", "[");
    if (data->key != 1 || data->add_alternates || data->has_mods || data->add_actions) P("%u", data->key);
    if (data->add_alternates) {
        P("%s", ":");
        if (data->shifted_key) P("%u", data->shifted_key);
        if (data->alternate_key) P(":%u", data->alternate_key);
    }
    if (data->has_mods || data->add_actions) {
        P(";%s", data->encoded_mods);
        if (data->add_actions) P(":%u", data->action + 1);
    }
#undef P
    output[pos++] = csi_trailer;
    output[pos] = 0;
    return pos;
}

static inline uint32_t
convert_kp_key_to_normal_key(uint32_t key_number) {
    switch(key_number) {
#define S(x) case GLFW_FKEY_KP_##x: key_number = GLFW_FKEY_##x; break;
        S(ENTER) S(HOME) S(END) S(INSERT) S(DELETE) S(PAGE_UP) S(PAGE_DOWN)
        S(UP) S(DOWN) S(LEFT) S(RIGHT)
#undef S
        case GLFW_FKEY_KP_0:
        case GLFW_FKEY_KP_9: key_number = '0' + (key_number - GLFW_FKEY_KP_0); break;
        case GLFW_FKEY_KP_DECIMAL: key_number = '.'; break;
        case GLFW_FKEY_KP_DIVIDE: key_number = '/'; break;
        case GLFW_FKEY_KP_MULTIPLY: key_number = '*'; break;
        case GLFW_FKEY_KP_SUBTRACT: key_number = '-'; break;
        case GLFW_FKEY_KP_ADD: key_number = '+'; break;
        case GLFW_FKEY_KP_EQUAL: key_number = '='; break;
    }
    return key_number;
}

static int
encode_function_key(const KeyEvent *ev, char *output) {
#define SIMPLE(val) return snprintf(output, KEY_BUFFER_SIZE, "%s", val);
    char csi_trailer = 'u';
    uint32_t key_number = ev->key;

    if (ev->cursor_key_mode && !ev->disambiguate && !ev->report_all_event_types) {
        switch(key_number) {
            case GLFW_FKEY_UP: SIMPLE("\x1bOA");
            case GLFW_FKEY_DOWN: SIMPLE("\x1bOB");
            case GLFW_FKEY_RIGHT: SIMPLE("\x1bOC");
            case GLFW_FKEY_LEFT: SIMPLE("\x1bOD");
            case GLFW_FKEY_END: SIMPLE("\x1bOF");
            case GLFW_FKEY_HOME: SIMPLE("\x1bOH");
            case GLFW_FKEY_F1: SIMPLE("\x1bOP");
            case GLFW_FKEY_F2: SIMPLE("\x1bOQ");
            case GLFW_FKEY_F3: SIMPLE("\x1bOR");
            case GLFW_FKEY_F4: SIMPLE("\x1bOS");
            default: break;
        }
    }
    if (!ev->mods.value) {
        switch(key_number) {
            case GLFW_FKEY_ENTER: SIMPLE("\r");
            case GLFW_FKEY_ESCAPE: {
                if (ev->disambiguate) { return encode_csi_string('u', "27", output); }
                SIMPLE("\x1b");
            }
            case GLFW_FKEY_BACKSPACE: SIMPLE("\x7f");
            case GLFW_FKEY_TAB: SIMPLE("\t");
            default: break;
        }
    }
    if (ev->mods.value == ALT) {
        switch(key_number) {
            case GLFW_FKEY_TAB: SIMPLE("\x1b\t");
            case GLFW_FKEY_ENTER: SIMPLE("\x1b\r");
            case GLFW_FKEY_BACKSPACE: SIMPLE("\x1b\x7f");
        }
    }
    if (ev->mods.value == SHIFT && key_number == GLFW_FKEY_TAB) { SIMPLE("\x1b[Z"); }
    if (ev->mods.value == CTRL && key_number == GLFW_FKEY_BACKSPACE) { SIMPLE("\x08"); }
#undef SIMPLE

#define S(number, trailer) key_number = number; csi_trailer = trailer; break
    switch(key_number) {
        /* start special numbers (auto generated by gen-key-constants.py do not edit) */
        case GLFW_FKEY_ESCAPE: S(27, 'u');
        case GLFW_FKEY_ENTER: S(13, 'u');
        case GLFW_FKEY_TAB: S(9, 'u');
        case GLFW_FKEY_BACKSPACE: S(127, 'u');
        case GLFW_FKEY_INSERT: S(2, '~');
        case GLFW_FKEY_DELETE: S(3, '~');
        case GLFW_FKEY_LEFT: S(1, 'D');
        case GLFW_FKEY_RIGHT: S(1, 'C');
        case GLFW_FKEY_UP: S(1, 'A');
        case GLFW_FKEY_DOWN: S(1, 'B');
        case GLFW_FKEY_PAGE_UP: S(5, '~');
        case GLFW_FKEY_PAGE_DOWN: S(6, '~');
        case GLFW_FKEY_HOME: S(1, 'H');
        case GLFW_FKEY_END: S(1, 'F');
        case GLFW_FKEY_F1: S(1, 'P');
        case GLFW_FKEY_F2: S(1, 'Q');
        case GLFW_FKEY_F3: S(1, 'R');
        case GLFW_FKEY_F4: S(1, 'S');
        case GLFW_FKEY_F5: S(15, '~');
        case GLFW_FKEY_F6: S(17, '~');
        case GLFW_FKEY_F7: S(18, '~');
        case GLFW_FKEY_F8: S(19, '~');
        case GLFW_FKEY_F9: S(20, '~');
        case GLFW_FKEY_F10: S(21, '~');
        case GLFW_FKEY_F11: S(23, '~');
        case GLFW_FKEY_F12: S(24, '~');
/* end special numbers */
        default: break;
    }
#undef S
    EncodingData ed = {0};
    init_encoding_data(&ed, ev);
    ed.key = key_number;
    ed.add_alternates = false;
    return serialize(&ed, output, csi_trailer);
}

static inline char
shifted_ascii_key(const uint32_t key) {
    switch(key) {
    /* start shifted key map (auto generated by gen-key-constants.py do not edit) */
         case '`': return '~';
         case '1': return '!';
         case '2': return '@';
         case '3': return '#';
         case '4': return '$';
         case '5': return '%';
         case '6': return '^';
         case '7': return '&';
         case '8': return '*';
         case '9': return '(';
         case '0': return ')';
         case '-': return '_';
         case '=': return '+';
         case '[': return '{';
         case ']': return '}';
         case '\\': return '|';
         case ';': return ':';
         case '\'': return '"';
         case ',': return '<';
         case '.': return '>';
         case '/': return '?';
         case 'a': return 'A';
         case 'b': return 'B';
         case 'c': return 'C';
         case 'd': return 'D';
         case 'e': return 'E';
         case 'f': return 'F';
         case 'g': return 'G';
         case 'h': return 'H';
         case 'i': return 'I';
         case 'j': return 'J';
         case 'k': return 'K';
         case 'l': return 'L';
         case 'm': return 'M';
         case 'n': return 'N';
         case 'o': return 'O';
         case 'p': return 'P';
         case 'q': return 'Q';
         case 'r': return 'R';
         case 's': return 'S';
         case 't': return 'T';
         case 'u': return 'U';
         case 'v': return 'V';
         case 'w': return 'W';
         case 'x': return 'X';
         case 'y': return 'Y';
         case 'z': return 'Z';
/* end shifted key map */
        default:
            return 0;
    }
}

static int
encode_printable_ascii_key_legacy(const KeyEvent *ev, char *output) {
    if (!ev->mods.value) return snprintf(output, KEY_BUFFER_SIZE, "%c", (char)ev->key);
    if (ev->disambiguate) return 0;

    char shifted_key = shifted_ascii_key(ev->key);
    shifted_key = (shifted_key && ev->mods.shift) ? shifted_key : (char)ev->key;
    if (ev->mods.value == SHIFT)
        return snprintf(output, KEY_BUFFER_SIZE, "%c", shifted_key);
    if ((ev->mods.value == ALT || ev->mods.value == (SHIFT | ALT)))
        return snprintf(output, KEY_BUFFER_SIZE, "\x1b%c", shifted_key);
    if (ev->mods.value == CTRL)
        return snprintf(output, KEY_BUFFER_SIZE, "%c", ev->key & 0x3f);
    if (ev->mods.value == (CTRL | ALT))
        return snprintf(output, KEY_BUFFER_SIZE, "\x1b%c", ev->key & 0x3f);
    return 0;
}

static inline bool
is_legacy_ascii_key(uint32_t key) {
    START_ALLOW_CASE_RANGE
    switch (key) {
        case 'a' ... 'z':
        case '0' ... '9':
        case '`':
        case '-':
        case '=':
        case '[':
        case ']':
        case '\\':
        case ';':
        case '\'':
        case ',':
        case '.':
        case '/':
            return true;
        default:
            return false;
    }
    END_ALLOW_CASE_RANGE
}

static int
encode_key(const KeyEvent *ev, char *output) {
    if (!ev->report_all_event_types && ev->action == RELEASE) return 0;
    if (GLFW_FKEY_FIRST <= ev->key && ev->key <= GLFW_FKEY_LAST) return encode_function_key(ev, output);
    EncodingData ed = {0};
    init_encoding_data(&ed, ev);
    bool simple_encoding_ok = !ed.add_actions && !ed.add_alternates;

    if (simple_encoding_ok) {
        if (!ed.has_mods) return encode_utf8(ev->key, output);
        if (!ev->disambiguate) {
            if (is_legacy_ascii_key(ev->key)) {
                int ret = encode_printable_ascii_key_legacy(ev, output);
                if (ret > 0) return ret;
            } else if (ev->key == ' ' && ev->mods.value == CTRL) {
                output[0] = 0;
                return 1;
            }
        }
    }

    return serialize(&ed, output, 'u');
}

static inline bool
is_ascii_control_char(char c) {
    return (0 <= c && c <= 31) || c == 127;
}

int
encode_glfw_key_event(const GLFWkeyevent *e, const bool cursor_key_mode, const unsigned key_encoding_flags, char *output) {
    KeyEvent ev = {
        .key = e->key, .shifted_key = e->shifted_key, .alternate_key = e->alternate_key,
        .text = e->text,
        .cursor_key_mode = cursor_key_mode,
        .disambiguate = key_encoding_flags & 1,
        .report_all_event_types = key_encoding_flags & 2,
        .report_alternate_key = key_encoding_flags & 4
    };
    ev.has_text = e->text && !is_ascii_control_char(e->text[0]);
    if (!ev.disambiguate && GLFW_FKEY_KP_0 <= ev.key && ev.key <= GLFW_FKEY_KP_DELETE) {
        ev.key = convert_kp_key_to_normal_key(ev.key);
    }
    switch (e->action) {
        case GLFW_PRESS: ev.action = PRESS; break;
        case GLFW_REPEAT: ev.action = REPEAT; break;
        case GLFW_RELEASE: ev.action = RELEASE; break;
    }
    if (ev.has_text && (ev.action == PRESS || ev.action == REPEAT)) return SEND_TEXT_TO_CHILD;
    convert_glfw_mods(e->mods, &ev);
    return encode_key(&ev, output);
}
