/*
 * wcswidth.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "char-props.h"
#include "wcswidth.h"

void
initialize_wcs_state(WCSState *state) {
    zero_at_ptr(state);
}

int
wcswidth_step(WCSState *state, const char_type ch) {
    int ans = 0;
    switch (state->parser_state) {
        case IN_CSI: {
            state->prev_width = 0;
            if (0x40 <= ch && ch <= 0x7e) { state->parser_state = NORMAL; state->can_combine = false; }
        } break;
        case IN_ST_TERMINATED: {
            state->prev_width = 0;
            if (ch == '\a' || (ch == '\\' && state->prev_ch == 0x1b)) { state->parser_state = NORMAL; state->can_combine = false; }
        } break;

        case NORMAL: {
            CharProps cp = char_props_for(ch);
            state->seg = grapheme_segmentation_step(state->seg, cp);
            if (state->seg.add_to_current_cell && state->can_combine) {
                switch(ch) {
                    case 0xfe0f:
                        if (char_props_for(state->prev_ch).is_emoji_presentation_base && state->prev_width == 1) {
                            ans = 1; state->prev_width = 2;
                        } else state->prev_width = 0;
                        break;
                    case 0xfe0e:
                        if (char_props_for(state->prev_ch).is_emoji_presentation_base && state->prev_width == 2) {
                            ans = -1; state->prev_width = 1;
                        } else state->prev_width = 0;
                        break;
                }
                break;
            }
            int width = wcwidth_std(cp);
            switch (width) {
                case -1: case 0:
                    state->prev_width = 0;
                    if (ch == 0x1b) state->parser_state = IN_ESC;
                    break;
                case 2:
                    state->prev_width = 2; break;
                default:
                    state->prev_width = 1; break;
            }
            ans = state->prev_width;
            state->can_combine = true;
        } break;  // case NORMAL

        case IN_ESC:
            switch (ch) {
                case '[':
                    state->parser_state = IN_CSI; break;
                case 'P':
                case ']':
                case 'X':
                case '^':
                case '_':
                    state->parser_state = IN_ST_TERMINATED; break;
                case 'D':
                case 'E':
                case 'H':
                case 'M':
                case 'N':
                case 'O':
                case 'Z':
                case '6':
                case '7':
                case '8':
                case '9':
                case '=':
                case '>':
                case 'F':
                case 'c':
                case 'l':
                case 'm':
                case 'n':
                case 'o':
                case '|':
                case '}':
                case '~':
                    break;
                default:
                    zero_at_ptr(state);
                    return wcswidth_step(state, ch);
            } break;
    }
    state->prev_ch = ch;
    return ans;
}

size_t
wcswidth_string(const char_type *s) {
    WCSState state;
    initialize_wcs_state(&state);
    size_t ans = 0;
    while (*s) ans += wcswidth_step(&state, *(s++));
    return ans;
}

PyObject *
wcswidth_std(PyObject UNUSED *self, PyObject *str) {
    if (PyUnicode_READY(str) != 0) return NULL;
    int kind = PyUnicode_KIND(str);
    void *data = PyUnicode_DATA(str);
    Py_ssize_t len = PyUnicode_GET_LENGTH(str), i;
    WCSState state;
    initialize_wcs_state(&state);
    size_t ans = 0;
    for (i = 0; i < len; i++) {
        char_type ch = PyUnicode_READ(kind, data, i);
        ans += wcswidth_step(&state, ch);
    }
    return PyLong_FromSize_t(ans);
}
