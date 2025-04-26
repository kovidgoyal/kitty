/*
 * shlex.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <sys/types.h>
#include <stdbool.h>
#include <stdlib.h>

typedef enum { NORMAL, WORD, STRING_WITHOUT_ESCAPES, STRING_WITH_ESCAPES, ANSI_C_QUOTED } ShlexEnum;

typedef struct {
    const char *src;
    bool support_ansi_c_quoting, allow_empty;
    char *buf;
    size_t src_sz, src_pos, word_start, buf_pos;
    ShlexEnum state;
    const char *err;
} ShlexState;


static bool
alloc_shlex_state(ShlexState *s, const char *src, size_t src_sz, bool support_ansi_c_quoting) {
    *s = (ShlexState){
        // for NULL termination and some safety we add 16 bytes
        .src=src, .src_sz=src_sz, .support_ansi_c_quoting=support_ansi_c_quoting, .buf=malloc(16 + src_sz)
    };
    return s->buf != NULL;
}

static void
dealloc_shlex_state(ShlexState *s) {
    free(s->buf); s->buf = NULL;
    *s = (ShlexState){0};
}
#define WHITESPACE ' ': case '\n': case '\t': case '\r'
#define STRING_WITH_ESCAPES_DELIM '"'
#define STRING_WITHOUT_ESCAPES_DELIM '\''
#define ESCAPE_CHAR '\\'

static void
start_word(ShlexState *self) {
    self->word_start = self->src_pos - 1;
    self->buf_pos = 0;
}

static void
write_ch(ShlexState *self, char ch) {
    self->buf[self->buf_pos++] = ch;
}

static unsigned
encode_utf8(unsigned long ch, char* dest) {
    if (ch < 0x80) { // only lower 7 bits can be 1
        dest[0] = (char)ch;  // 0xxxxxxx
        return 1;
    }
    if (ch < 0x800) { // only lower 11 bits can be 1
        dest[0] = (ch>>6) | 0xC0; // 110xxxxx
        dest[1] = (ch & 0x3F) | 0x80;  // 10xxxxxx
        return 2;
    }
    if (ch < 0x10000) { // only lower 16 bits can be 1
        dest[0] = (ch>>12) | 0xE0; // 1110xxxx
        dest[1] = ((ch>>6) & 0x3F) | 0x80;  // 10xxxxxx
        dest[2] = (ch & 0x3F) | 0x80;       // 10xxxxxx
        return 3;
    }
    if (ch < 0x110000) { // only lower 21 bits can be 1
        dest[0] = (ch>>18) | 0xF0; // 11110xxx
        dest[1] = ((ch>>12) & 0x3F) | 0x80; // 10xxxxxx
        dest[2] = ((ch>>6) & 0x3F) | 0x80;  // 10xxxxxx
        dest[3] = (ch & 0x3F) | 0x80; // 10xxxxxx
        return 4;
    }
    return 0;
}

static void
write_unich(ShlexState *self, unsigned long ch) {
    self->buf_pos += encode_utf8(ch, self->buf + self->buf_pos);
}


static size_t
get_word(ShlexState *self) {
    size_t ans = self->buf_pos; self->buf_pos = 0;
    self->buf[ans] = 0;
    self->allow_empty = false;
    return ans;
}

static char
read_ch(ShlexState *self) {
    return self->src[self->src_pos++];
}

static bool
write_escape_ch(ShlexState *self) {
    if (self->src_pos < self->src_sz) {
        char nch = read_ch(self);
        write_ch(self, nch);
        return true;
    }
    return false;
}

static bool
write_control_ch(ShlexState *self) {
    if (self->src_pos >= self->src_sz) {
        self->err = "Trailing \\c escape at end of input data";
        return false;
    }
    char ch = read_ch(self);
    write_ch(self, ch & 0x1f);
    return true;
}

static void
read_valid_digits(ShlexState *self, int max, char *output, bool(*is_valid)(char ch)) {
    for (int i = 0; i < max && self->src_pos < self->src_sz; i++, output++) {
        char ch = read_ch(self);
        if (!is_valid(ch)) { self->src_pos--; break; }
        *output = ch;
    }
}

static bool
is_octal_digit(char ch) { return '0' <= ch && ch <= '7'; }

static bool
is_hex_digit(char ch) { return ('0' <= ch && ch <= '9') || ('a' <= ch && ch <= 'f') || ('A' <= ch && ch <= 'F'); }

static void
write_octal_ch(ShlexState *self, char ch) {
    char chars[4] = {ch, 0, 0, 0};
    read_valid_digits(self, 2, chars + 1, is_octal_digit);
    write_unich(self, strtol(chars, NULL, 8));
}

static bool
write_unicode_ch(ShlexState *self, int max) {
    char chars[16] = {0};
    read_valid_digits(self, max, chars, is_hex_digit);
    if (!chars[0]) { self->err = "Trailing unicode escape at end of input data"; return false; }
    write_unich(self, strtol(chars, NULL, 16));
    return true;
}

static bool
write_ansi_escape_ch(ShlexState *self) {
    if (self->src_pos >= self->src_sz) { self->err = "Trailing backslash at end of input data"; return false; }
    char ch = read_ch(self);
    switch(ch) {
        case 'a': write_ch(self, '\a'); return true;
        case 'b': write_ch(self, '\b'); return true;
        case 'e': case 'E': write_ch(self, 0x1b); return true;
        case 'f': write_ch(self, '\f'); return true;
        case 'n': write_ch(self, '\n'); return true;
        case 'r': write_ch(self, '\r'); return true;
        case 't': write_ch(self, '\t'); return true;
        case 'v': write_ch(self, '\v'); return true;
        case '\\': write_ch(self, '\\'); return true;
        case '\'': write_ch(self, '\''); return true;
        case '\"': write_ch(self, '\"'); return true;
        case '\?': write_ch(self, '\?'); return true;

        case 'c': return write_control_ch(self);
        case 'x': return write_unicode_ch(self, 2);
        case 'u': return write_unicode_ch(self, 4);
        case 'U': return write_unicode_ch(self, 8);
        case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': write_octal_ch(self, ch); return true;
        default:
            write_ch(self, ch); return true;
    }
}

static void
set_state(ShlexState *self, ShlexEnum s) {
    self->state = s;
}

static ssize_t
next_word(ShlexState *self) {
#define write_escaped_or_fail() if (!write_escape_ch(self)) { self->err = "Trailing backslash at end of input data"; return -1; }
    char prev_word_ch = 0;
    while (self->src_pos < self->src_sz) {
        char ch = read_ch(self);
        switch(self->state) {
            case NORMAL:
                switch(ch) {
                    case WHITESPACE: break;
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, STRING_WITH_ESCAPES); start_word(self); break;
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, STRING_WITHOUT_ESCAPES); start_word(self); break;
                    case ESCAPE_CHAR: start_word(self); write_escaped_or_fail(); set_state(self, WORD); break;
                    default: set_state(self, WORD); start_word(self); write_ch(self, ch); prev_word_ch = ch; break;
                }
                break;
            case WORD:
                switch(ch) {
                    case WHITESPACE: set_state(self, NORMAL); if (self->buf_pos || self->allow_empty) return get_word(self); break;
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, STRING_WITH_ESCAPES); break;
                    case STRING_WITHOUT_ESCAPES_DELIM:
                        if (self->support_ansi_c_quoting && prev_word_ch == '$') { self->buf_pos--; set_state(self, ANSI_C_QUOTED); }
                        else set_state(self, STRING_WITHOUT_ESCAPES);
                        break;
                    case ESCAPE_CHAR: write_escaped_or_fail(); break;
                    default: write_ch(self, ch); prev_word_ch = ch; break;
                } break;
            case STRING_WITHOUT_ESCAPES:
                switch(ch) {
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, WORD); self->allow_empty = true; break;
                    default: write_ch(self, ch); break;
                } break;
            case STRING_WITH_ESCAPES:
                switch(ch) {
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, WORD); self->allow_empty = true; break;
                    case ESCAPE_CHAR: write_escaped_or_fail(); break;
                    default: write_ch(self, ch); break;
                } break;
            case ANSI_C_QUOTED:
                switch(ch) {
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, WORD); self->allow_empty = true; break;
                    case ESCAPE_CHAR: if (!write_ansi_escape_ch(self)) return -1; break;
                    default: write_ch(self, ch); break;
                } break;
        }
    }
    switch (self->state) {
        case WORD:
            self->state = NORMAL;
            if (self->buf_pos || self->allow_empty) return get_word(self);
            break;
        case STRING_WITH_ESCAPES: case STRING_WITHOUT_ESCAPES: case ANSI_C_QUOTED:
            self->err = "Unterminated string at the end of input";
            self->state = NORMAL;
            return -1;
        case NORMAL:
            break;
    }
    return -2;
#undef write_escaped_or_fail
}


