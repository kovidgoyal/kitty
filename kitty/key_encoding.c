/*
 * key_encoding.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "keys.h"
#include "charsets.h"

typedef enum { SHIFT=1, ALT=2, CTRL=4, SUPER=8, HYPER=16, META=32, CAPS_LOCK=64, NUM_LOCK=128} ModifierMasks;
typedef enum { PRESS = 0, REPEAT = 1, RELEASE = 2} KeyAction;
#define LOCK_MASK (CAPS_LOCK | NUM_LOCK)
typedef struct {
    uint32_t key, shifted_key, alternate_key;
    struct {
        bool shift, alt, ctrl, super, hyper, meta, numlock, capslock;
        unsigned value;
        char encoded[4];
    } mods;
    KeyAction action;
    bool cursor_key_mode, disambiguate, report_all_event_types, report_alternate_key, report_text, embed_text;
    const char *text;
    bool has_text;
} KeyEvent;

typedef struct {
    uint32_t key, shifted_key, alternate_key;
    bool add_alternates, has_mods, add_actions, add_text;
    char encoded_mods[4];
    const char *text;
    KeyAction action;
} EncodingData;

static void
convert_glfw_mods(int mods, KeyEvent *ev, const unsigned key_encoding_flags) {
    if (!key_encoding_flags) mods &= ~GLFW_LOCK_MASK;
    ev->mods.alt = (mods & GLFW_MOD_ALT) > 0, ev->mods.ctrl = (mods & GLFW_MOD_CONTROL) > 0, ev->mods.shift = (mods & GLFW_MOD_SHIFT) > 0, ev->mods.super = (mods & GLFW_MOD_SUPER) > 0, ev->mods.hyper = (mods & GLFW_MOD_HYPER) > 0, ev->mods.meta = (mods & GLFW_MOD_META) > 0;
    ev->mods.numlock = (mods & GLFW_MOD_NUM_LOCK) > 0, ev->mods.capslock = (mods & GLFW_MOD_CAPS_LOCK) > 0;
    ev->mods.value = ev->mods.shift ? SHIFT : 0;
    if (ev->mods.alt) ev->mods.value |= ALT;
    if (ev->mods.ctrl) ev->mods.value |= CTRL;
    if (ev->mods.super) ev->mods.value |= SUPER;
    if (ev->mods.hyper) ev->mods.value |= HYPER;
    if (ev->mods.meta) ev->mods.value |= META;
    if (ev->mods.capslock) ev->mods.value |= CAPS_LOCK;
    if (ev->mods.numlock) ev->mods.value |= NUM_LOCK;
    snprintf(ev->mods.encoded, sizeof(ev->mods.encoded), "%u", ev->mods.value + 1);
}


static void
init_encoding_data(EncodingData *ans, const KeyEvent *ev) {
    ans->add_actions = ev->report_all_event_types && ev->action != PRESS;
    ans->has_mods = ev->mods.encoded[0] && ( ev->mods.encoded[0] != '1' || ev->mods.encoded[1] );
    ans->add_alternates = ev->report_alternate_key && ((ev->shifted_key > 0 && ev->mods.shift) || ev->alternate_key > 0);
    if (ans->add_alternates) { if (ev->mods.shift) ans->shifted_key = ev->shifted_key; ans->alternate_key = ev->alternate_key; }
    ans->action = ev->action;
    ans->key = ev->key;
    ans->add_text = ev->embed_text && ev->text && ev->text[0];
    ans->text = ev->text;
    memcpy(ans->encoded_mods, ev->mods.encoded, sizeof(ans->encoded_mods));
}

static int
serialize(const EncodingData *data, char *output, const char csi_trailer) {
    int pos = 0;
    bool second_field_not_empty = data->has_mods || data->add_actions;
    bool third_field_not_empty = data->add_text;
#define P(fmt, ...) pos += snprintf(output + pos, KEY_BUFFER_SIZE - 2 <= pos ? 0 : KEY_BUFFER_SIZE - 2 - pos, fmt, __VA_ARGS__)
    P("\x1b%s", "[");
    if (data->key != 1 || data->add_alternates || second_field_not_empty || third_field_not_empty) P("%u", data->key);
    if (data->add_alternates) {
        P("%s", ":");
        if (data->shifted_key) P("%u", data->shifted_key);
        if (data->alternate_key) P(":%u", data->alternate_key);
    }
    if (second_field_not_empty || third_field_not_empty) {
        P("%s", ";");
        if (second_field_not_empty) P("%s", data->encoded_mods);
        if (data->add_actions) P(":%u", data->action + 1);
    }
    if (third_field_not_empty) {
        const char *p = data->text;
        uint32_t codep; UTF8State state = UTF8_ACCEPT;
        bool first = true;
        while(*p) {
            if (decode_utf8(&state, &codep, *p) == UTF8_ACCEPT) {
                if (first) { P(";%u", codep); first = false; }
                else P(":%u", codep);
            }
            p++;
        }
    }
#undef P
    output[pos++] = csi_trailer;
    output[pos] = 0;
    return pos;
}

static uint32_t
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
legacy_functional_key_encoding_with_modifiers(uint32_t key_number, const KeyEvent *ev, char *output) {
    const char *prefix = ev->mods.value & ALT ? "\x1b" : "";
    const char *main_bytes = "";
    switch (key_number) {
        case GLFW_FKEY_ENTER:
            main_bytes = "\x0d";
            break;
        case GLFW_FKEY_ESCAPE:
            main_bytes = "\x1b";
            break;
        case GLFW_FKEY_BACKSPACE:
            main_bytes = ev->mods.value & CTRL ? "\x08" : "\x7f";
            break;
        case GLFW_FKEY_TAB:
            if (ev->mods.value & SHIFT) {
                prefix = ev->mods.value & ALT ? "\x1b\x1b" : "\x1b";
                main_bytes = "[Z";
            } else {
                main_bytes = "\t";
            }
            break;
        default:
            return -1;
    }
    return snprintf(output, KEY_BUFFER_SIZE, "%s%s", prefix, main_bytes);
}

static int
encode_function_key(const KeyEvent *ev, char *output) {
#define SIMPLE(val) return snprintf(output, KEY_BUFFER_SIZE, "%s", val);
    char csi_trailer = 'u';
    uint32_t key_number = ev->key;
    bool legacy_mode = !ev->report_all_event_types && !ev->disambiguate && !ev->report_text;

    if (ev->cursor_key_mode && legacy_mode && !ev->mods.value) {
        switch(key_number) {
            case GLFW_FKEY_UP: SIMPLE("\x1bOA");
            case GLFW_FKEY_DOWN: SIMPLE("\x1bOB");
            case GLFW_FKEY_RIGHT: SIMPLE("\x1bOC");
            case GLFW_FKEY_LEFT: SIMPLE("\x1bOD");
            case GLFW_FKEY_KP_BEGIN: SIMPLE("\x1bOE");
            case GLFW_FKEY_END: SIMPLE("\x1bOF");
            case GLFW_FKEY_HOME: SIMPLE("\x1bOH");
            default: break;
        }
    }
    if (!ev->mods.value) {
        if (!ev->disambiguate && !ev->report_text && key_number == GLFW_FKEY_ESCAPE) SIMPLE("\x1b");
        if (legacy_mode) {
            switch(key_number) {
                case GLFW_FKEY_F1: SIMPLE("\x1bOP");
                case GLFW_FKEY_F2: SIMPLE("\x1bOQ");
                case GLFW_FKEY_F3: SIMPLE("\x1bOR");
                case GLFW_FKEY_F4: SIMPLE("\x1bOS");
                default: break;
            }
        }
        if (!ev->report_text) {
            switch(key_number) {
                case GLFW_FKEY_ENTER: if (ev->action == RELEASE) return -1; SIMPLE("\r");
                case GLFW_FKEY_BACKSPACE: if (ev->action == RELEASE) return -1; SIMPLE("\x7f");
                case GLFW_FKEY_TAB: if (ev->action == RELEASE) return -1; SIMPLE("\t");
                default: break;
            }
        }
    } else if (legacy_mode) {
        int num = legacy_functional_key_encoding_with_modifiers(key_number, ev, output);
        if (num > -1) return num;
    }
    if (!(ev->mods.value & ~LOCK_MASK) && !ev->report_text) {
        switch(key_number) {
            case GLFW_FKEY_ENTER: if (ev->action == RELEASE) return -1; SIMPLE("\r");
            case GLFW_FKEY_BACKSPACE: if (ev->action == RELEASE) return -1; SIMPLE("\x7f");
            case GLFW_FKEY_TAB: if (ev->action == RELEASE) return -1; SIMPLE("\t");
            default: break;
        }
    }
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
        case GLFW_FKEY_F3: S(13, '~');
        case GLFW_FKEY_F4: S(1, 'S');
        case GLFW_FKEY_F5: S(15, '~');
        case GLFW_FKEY_F6: S(17, '~');
        case GLFW_FKEY_F7: S(18, '~');
        case GLFW_FKEY_F8: S(19, '~');
        case GLFW_FKEY_F9: S(20, '~');
        case GLFW_FKEY_F10: S(21, '~');
        case GLFW_FKEY_F11: S(23, '~');
        case GLFW_FKEY_F12: S(24, '~');
        case GLFW_FKEY_KP_BEGIN: S(1, 'E');
/* end special numbers */
        case GLFW_FKEY_MENU:
            // use the same encoding as xterm for this key in legacy mode (F16)
            if (legacy_mode) { S(29, '~'); }
            break;
        default: break;
    }
#undef S
    EncodingData ed = {0};
    init_encoding_data(&ed, ev);
    ed.key = key_number;
    ed.add_alternates = false;
    return serialize(&ed, output, csi_trailer);
}

static char
ctrled_key(const char key) { // {{{
    switch(key) {
        /* start ctrl mapping (auto generated by gen-key-constants.py do not edit) */
        case ' ': return 0;
        case '/': return 31;
        case '0': return 48;
        case '1': return 49;
        case '2': return 0;
        case '3': return 27;
        case '4': return 28;
        case '5': return 29;
        case '6': return 30;
        case '7': return 31;
        case '8': return 127;
        case '9': return 57;
        case '?': return 127;
        case '@': return 0;
        case '[': return 27;
        case '\\': return 28;
        case ']': return 29;
        case '^': return 30;
        case '_': return 31;
        case 'a': return 1;
        case 'b': return 2;
        case 'c': return 3;
        case 'd': return 4;
        case 'e': return 5;
        case 'f': return 6;
        case 'g': return 7;
        case 'h': return 8;
        case 'i': return 9;
        case 'j': return 10;
        case 'k': return 11;
        case 'l': return 12;
        case 'm': return 13;
        case 'n': return 14;
        case 'o': return 15;
        case 'p': return 16;
        case 'q': return 17;
        case 'r': return 18;
        case 's': return 19;
        case 't': return 20;
        case 'u': return 21;
        case 'v': return 22;
        case 'w': return 23;
        case 'x': return 24;
        case 'y': return 25;
        case 'z': return 26;
        case '~': return 30;
/* end ctrl mapping */
        default:
            return key;
    }
} // }}}

static int
encode_printable_ascii_key_legacy(const KeyEvent *ev, char *output) {
    unsigned mods = ev->mods.value;
    if (!mods) return snprintf(output, KEY_BUFFER_SIZE, "%c", (char)ev->key);

    char key = ev->key;
    if (mods & SHIFT) {
        const char shifted = ev->shifted_key;
        if (shifted && shifted != key && (!(mods & CTRL) || key < 'a' || key > 'z')) {
            key = shifted;
            mods &= ~SHIFT;
        }
    }

    if (ev->mods.value == SHIFT)
        return snprintf(output, KEY_BUFFER_SIZE, "%c", key);
    if (mods == ALT)
        return snprintf(output, KEY_BUFFER_SIZE, "\x1b%c", key);
    if (mods == CTRL)
        return snprintf(output, KEY_BUFFER_SIZE, "%c", ctrled_key(key));
    if (mods == (CTRL | ALT))
        return snprintf(output, KEY_BUFFER_SIZE, "\x1b%c", ctrled_key(key));
    if (key == ' ') {
        if (mods == (CTRL | SHIFT)) return snprintf(output, KEY_BUFFER_SIZE, "%c", ctrled_key(key));
        if (mods == (ALT  | SHIFT)) return snprintf(output, KEY_BUFFER_SIZE, "\x1b%c", key);
    }
    return 0;
}

static bool
is_legacy_ascii_key(uint32_t key) {
    START_ALLOW_CASE_RANGE
    switch (key) {
        case 'a' ... 'z':
        case '0' ... '9':
        case '!':
        case '@':
        case '#':
        case '$':
        case '%':
        case '^':
        case '&':
        case '*':
        case '(':
        case ')':
        case '`':
        case '~':
        case '-':
        case '_':
        case '=':
        case '+':
        case '[':
        case '{':
        case ']':
        case '}':
        case '\\':
        case '|':
        case ';':
        case ':':
        case '\'':
        case '"':
        case ',':
        case '<':
        case '.':
        case '>':
        case '/':
        case '?':
        case ' ':
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
    bool simple_encoding_ok = !ed.add_actions && !ed.add_alternates && !ed.add_text;

    if (simple_encoding_ok) {
        if (!ed.has_mods) {
            if (ev->report_text) return serialize(&ed, output, 'u');
            return encode_utf8(ev->key, output);
        }
        if (!ev->disambiguate && !ev->report_text) {
            if (is_legacy_ascii_key(ev->key) || (ev->shifted_key && is_legacy_ascii_key(ev->shifted_key))) {
                int ret = encode_printable_ascii_key_legacy(ev, output);
                if (ret > 0) return ret;
            }
            unsigned mods = ev->mods.value;
            if ((mods == CTRL || mods == ALT || mods == (CTRL | ALT)) && ev->alternate_key && !is_legacy_ascii_key(ev->key) && is_legacy_ascii_key(ev->alternate_key)) {
                KeyEvent alternate = *ev;
                alternate.key = ev->alternate_key;
                alternate.alternate_key = 0;
                alternate.shifted_key = 0;
                int ret = encode_printable_ascii_key_legacy(&alternate, output);
                if (ret > 0) return ret;
            }
        }
    }

    return serialize(&ed, output, 'u');
}

static bool
startswith_ascii_control_char(const char *p) {
    if (!p || !*p) return true;
    uint32_t codep; UTF8State state = UTF8_ACCEPT;
    while(*p) {
        if (decode_utf8(&state, &codep, *p) == UTF8_ACCEPT) {
            return codep < 32 || codep == 127;
        }
        state = UTF8_ACCEPT;
        p++;
    }
    return false;
}

int
encode_glfw_key_event(const GLFWkeyevent *e, const bool cursor_key_mode, const unsigned key_encoding_flags, char *output) {
    KeyEvent ev = {
        .key = e->key, .shifted_key = e->shifted_key, .alternate_key = e->alternate_key,
        .text = e->text,
        .cursor_key_mode = cursor_key_mode,
        .disambiguate = key_encoding_flags & 1,
        .report_all_event_types = key_encoding_flags & 2,
        .report_alternate_key = key_encoding_flags & 4,
        .report_text = key_encoding_flags & 8,
        .embed_text = key_encoding_flags & 16
    };
    if (!ev.report_text && is_modifier_key(e->key)) return 0;
    ev.has_text = e->text && !startswith_ascii_control_char(e->text);
    if (!ev.key && !ev.has_text) return 0;
    bool send_text_standalone = !ev.report_text;
    if (!ev.disambiguate && !ev.report_text && GLFW_FKEY_KP_0 <= ev.key && ev.key <= GLFW_FKEY_KP_BEGIN) {
        ev.key = convert_kp_key_to_normal_key(ev.key);
    }
    switch (e->action) {
        case GLFW_PRESS: ev.action = PRESS; break;
        case GLFW_REPEAT: ev.action = REPEAT; break;
        case GLFW_RELEASE: ev.action = RELEASE; break;
    }
    if (send_text_standalone && ev.has_text && (ev.action == PRESS || ev.action == REPEAT)) return SEND_TEXT_TO_CHILD;
    convert_glfw_mods(e->mods, &ev, key_encoding_flags);
    return encode_key(&ev, output);
}
