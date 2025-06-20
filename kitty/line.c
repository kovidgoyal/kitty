/*
 * line.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "state.h"
#include "unicode-data.h"
#include "lineops.h"
#include "charsets.h"
#include "control-codes.h"

extern PyTypeObject Cursor_Type;
static_assert(sizeof(char_type) == sizeof(Py_UCS4), "Need to perform conversion to Py_UCS4");

static void
dealloc(Line* self) {
    if (self->needs_free) {
        PyMem_Free(self->cpu_cells);
        PyMem_Free(self->gpu_cells);
    }
    tc_decref(self->text_cache);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static unsigned
nonnegative_integer_as_utf32(unsigned num, ANSIBuf *output) {
    unsigned num_digits = 0;
    if (!num) num_digits = 1;
    else {
        unsigned temp = num;
        while (temp > 0) {
            temp /= 10;
            num_digits++;
        }
    }
    ensure_space_for(output, buf, output->buf[0], output->len + num_digits, capacity, 2048, false);
    if (!num) output->buf[output->len++] = '0';
    else {
        char_type *result = output->buf + output->len;
        unsigned i = num_digits - 1;
        do {
            uint32_t digit = num % 10;
            result[i--] = '0' + digit;
            num /= 10;
            output->len++;
        } while (num > 0);
    }
    return num_digits;
}

static void
ensure_space_in_ansi_output_buf(ANSILineState *s, size_t extra) {
    ensure_space_for(s->output_buf, buf, s->output_buf->buf[0], s->output_buf->len + extra, capacity, 2048, false);
}

static unsigned
write_multicell_ansi_prefix(ANSILineState *s, const CPUCell *mcd) {
    ensure_space_in_ansi_output_buf(s, 128);
    s->current_multicell_state = mcd;
    s->escape_code_written = true;
    unsigned pos = s->output_buf->len;
#define w(x) s->output_buf->buf[s->output_buf->len++] = x
    w(0x1b); w(']');
    for (unsigned i = 0; i < sizeof(xstr(TEXT_SIZE_CODE)) - 1; i++) w(xstr(TEXT_SIZE_CODE)[i]);
    w(';');
    if (!mcd->natural_width) {
        w('w'); w('='); nonnegative_integer_as_utf32(mcd->width, s->output_buf); w(':');
    }
    if (mcd->scale > 1) {
        w('s'); w('='); nonnegative_integer_as_utf32(mcd->scale, s->output_buf); w(':');
    }
    if (mcd->subscale_n) {
        w('n'); w('='); nonnegative_integer_as_utf32(mcd->subscale_n, s->output_buf); w(':');
    }
    if (mcd->subscale_d) {
        w('d'); w('='); nonnegative_integer_as_utf32(mcd->subscale_d, s->output_buf); w(':');
    }
    if (mcd->valign) {
        w('v'); w('='); nonnegative_integer_as_utf32(mcd->valign, s->output_buf); w(':');
    }
    if (mcd->halign) {
        w('h'); w('='); nonnegative_integer_as_utf32(mcd->halign, s->output_buf); w(':');
    }
    if (s->output_buf->buf[s->output_buf->len - 1] == ':') s->output_buf->len--;
    w(';');
#undef w
    return s->output_buf->len - pos;
}

static void
close_multicell(ANSILineState *s) {
    if (s->current_multicell_state) {
        ensure_space_in_ansi_output_buf(s, 1);
        s->output_buf->buf[s->output_buf->len++] = '\a';
        s->current_multicell_state = NULL;
    }
}

static void
start_multicell_if_needed(ANSILineState *s, const CPUCell *c) {
    if (!c->natural_width || c->scale > 1 || c->subscale_n || c->subscale_d || c->valign || c->halign) write_multicell_ansi_prefix(s, c);
}

static bool
multicell_is_continuation_of_previous(const CPUCell *prev, const CPUCell *curr) {
    if (prev->scale != curr->scale || prev->subscale_n != curr->subscale_n || prev->subscale_d != curr->subscale_d || prev->valign != curr->valign || prev->halign != curr->halign) return false;
    if (prev->natural_width) return curr->natural_width;
    return prev->width == curr->width && !curr->natural_width;
}

static index_type
text_in_cell_ansi(ANSILineState *s, const CPUCell *c, TextCache *tc, bool skip_multiline_non_zero_lines) {
    index_type num_cells_to_skip_for_tab = 0;
    if (c->is_multicell) {
        if (c->x || (skip_multiline_non_zero_lines && c->y)) return num_cells_to_skip_for_tab;
        if (s->current_multicell_state) {
            if (!multicell_is_continuation_of_previous(s->current_multicell_state, c)) {
                close_multicell(s);
                start_multicell_if_needed(s, c);
            }
        } else start_multicell_if_needed(s, c);
    } else close_multicell(s);

    size_t pos = s->output_buf->len;
    if (c->ch_is_idx) {
        tc_chars_at_index_ansi(tc, c->ch_or_idx, s->output_buf);
    } else {
        ensure_space_in_ansi_output_buf(s, 2);
        s->output_buf->buf[s->output_buf->len++] = c->ch_or_idx;
    }
    if (s->output_buf->len > pos) {
        switch (s->output_buf->buf[pos]) {
            case 0: s->output_buf->buf[pos] = ' '; break;
            case '\t': {
                index_type n = s->output_buf->len - pos;
                if (n > 1) {
                    num_cells_to_skip_for_tab = s->output_buf->buf[s->output_buf->len - n + 1];
                    s->output_buf->len -= n - 1;
                }
            } break;
        }
    }
    return num_cells_to_skip_for_tab;
}


unsigned int
line_length(Line *self) {
    index_type last = self->xnum - 1;
    for (index_type i = 0; i < self->xnum; i++) {
        if (!cell_is_char(self->cpu_cells + last - i, BLANK_CHAR)) return self->xnum - i;
    }
    return 0;
}

// URL detection {{{

static bool
is_hostname_char(char_type ch) {
    return ch == '[' || ch == ']' || is_url_char(ch);
}

static bool
is_hostname_lc(const ListOfChars *lc) {
    for (size_t i = 0; i < lc->count; i++) if (!is_hostname_char(lc->chars[i])) return false;
    return true;
}

static bool
is_url_lc(const ListOfChars *lc) {
    for (size_t i = 0; i < lc->count; i++) if (!is_url_char(lc->chars[i])) return false;
    return true;
}

index_type
next_char_pos(const Line *self, index_type x, index_type num) {
    const CPUCell *ans = self->cpu_cells + x, *limit = self->cpu_cells + self->xnum;
    while (num-- && ans < limit) ans += ans->is_multicell ? mcd_x_limit(ans) - ans->x : 1;
    return ans - self->cpu_cells;
}

index_type
prev_char_pos(const Line *self, index_type x, index_type num) {
    const CPUCell *ans = self->cpu_cells + x, *limit = self->cpu_cells - 1;
    if (ans->is_multicell) ans -= ans->x;
    while (num-- && --ans > limit) if (ans->is_multicell) ans -= ans->x;
    return ans > limit ? (index_type)(ans - self->cpu_cells) : self->xnum;
}


static index_type
find_colon_slash(Line *self, index_type x, index_type limit, ListOfChars *lc, index_type scale) {
    // Find :// at or before x
    index_type pos = MIN(x, self->xnum - 1);
    enum URL_PARSER_STATES {ANY, FIRST_SLASH, SECOND_SLASH};
    enum URL_PARSER_STATES state = ANY;
    limit = MAX(2u, limit);
    if (pos < limit) return 0;
    const CPUCell *c = self->cpu_cells + pos;
    index_type n;
#define next_char_is(num, ch) ((n = next_char_pos(self, pos, num)) < self->xnum && cell_is_char(self->cpu_cells + n, ch) && cell_scale(self->cpu_cells + n) == scale)
    if (cell_is_char(c, ':')) {
        if (next_char_is(1, '/') && next_char_is(2, '/')) state = SECOND_SLASH;
    } else if (cell_is_char(c, '/')) {
        if (next_char_is(1, '/')) state = FIRST_SLASH;
    }
#undef next_char_is

    do {
        text_in_cell(c, self->text_cache, lc);
        if (!is_hostname_lc(lc)) return false;
        switch(state) {
            case ANY:
                if (cell_is_char(c, '/')) state = FIRST_SLASH;
                break;
            case FIRST_SLASH:
                state = cell_is_char(c, '/') ? SECOND_SLASH : ANY;
                break;
            case SECOND_SLASH:
                if (cell_is_char(c, ':')) return pos;
                state = cell_is_char(c, '/') ? SECOND_SLASH : ANY;
                break;
        }
        pos = prev_char_pos(self, pos, 1);
        if (pos >= self->xnum) break;
        c = self->cpu_cells + pos;
        if (cell_scale(c) != scale) break;
    } while(pos >= limit);
    return 0;
}

static bool
prefix_matches(Line *self, index_type at, const char_type* prefix, index_type prefix_len, index_type scale) {
    if (prefix_len > at) return false;
    while (prefix_len--) {
        at = prev_char_pos(self, at, 1);
        if (at >= self->xnum || cell_scale(self->cpu_cells + at) != scale || !cell_is_char(self->cpu_cells + at, prefix[prefix_len])) return false;
    }
    return true;
}

static bool
has_url_prefix_at(Line *self, const index_type at, index_type *ans, index_type scale) {
    for (size_t i = 0; i < OPT(url_prefixes.num); i++) {
        index_type prefix_len = OPT(url_prefixes.values[i].len);
        if (at < prefix_len) continue;
        if (prefix_matches(self, at, OPT(url_prefixes.values[i].string), prefix_len, scale)) {
            *ans = prev_char_pos(self, at, prefix_len);
            if (*ans < self->xnum) return true;
        }
    }
    return false;
}

#define MIN_URL_LEN 5

static bool
has_url_beyond_colon_slash(Line *self, const index_type x, ListOfChars *lc, const index_type scale) {
    unsigned num_of_slashes = 0;
    index_type pos = x, num_chars = 0;
    while ((pos = next_char_pos(self, pos, 1)) < self->xnum && num_chars++ < MIN_URL_LEN + 2) {
        const CPUCell *c = self->cpu_cells + pos;
        if (cell_scale(c) != scale) return false;
        text_in_cell(c, self->text_cache, lc);
        if (num_of_slashes < 3) {
            if (!is_hostname_lc(lc)) return false;
            if (lc->count == 1 && lc->chars[0] == '/') num_of_slashes++;
        } else {
            for (size_t n = 0; n < lc->count; n++) if (!is_url_char(lc->chars[n])) return false;
        }
    }
    return true;
}

index_type
line_url_start_at(Line *self, index_type x, ListOfChars *lc) {
    // Find the starting cell for a URL that contains the position x. A URL is defined as
    // known-prefix://url-chars. If no URL is found self->xnum is returned.
    if (self->cpu_cells[x].is_multicell && self->cpu_cells[x].x) x = x > self->cpu_cells[x].x ? x - self->cpu_cells[x].x : 0;
    if (x >= self->xnum || self->xnum <= MIN_URL_LEN + 3) return self->xnum;
    index_type ds_pos = 0, t, scale = cell_scale(self->cpu_cells + x);
    // First look for :// ahead of x
    ds_pos = find_colon_slash(self, x + OPT(url_prefixes).max_prefix_len + 3, x < 2 ? 0 : x - 2, lc, scale);
    if (ds_pos != 0 && has_url_beyond_colon_slash(self, ds_pos, lc, scale)) {
        if (has_url_prefix_at(self, ds_pos, &t, scale) && t <= x) return t;
    }
    ds_pos = find_colon_slash(self, x, 0, lc, scale);
    if (ds_pos == 0 || self->xnum < ds_pos + MIN_URL_LEN + 3 || !has_url_beyond_colon_slash(self, ds_pos, lc, scale)) return self->xnum;
    if (has_url_prefix_at(self, ds_pos, &t, scale)) return t;
    return self->xnum;
}

static bool
is_pos_ok_for_url(Line *self, index_type x, bool in_hostname, index_type last_hostname_char_pos, ListOfChars *lc) {
    if (x >= self->xnum) return false;
    text_in_cell(self->cpu_cells + x, self->text_cache, lc);
    if (in_hostname && x <= last_hostname_char_pos) return is_hostname_lc(lc);
    return is_url_lc(lc);
}

index_type
line_url_end_at(Line *self, index_type x, bool check_short, char_type sentinel, bool next_line_starts_with_url_chars, bool in_hostname, index_type last_hostname_char_pos, ListOfChars *lc) {
    index_type ans = x;
#define is_not_ok(n) ((sentinel && cell_is_char(self->cpu_cells + n, sentinel)) || !is_pos_ok_for_url(self, n, in_hostname, last_hostname_char_pos, lc))
    if (x >= self->xnum || (check_short && self->xnum <= MIN_URL_LEN + 3) || is_not_ok(x)) return 0;
    index_type n = ans;
    while ((n = next_char_pos(self, ans, 1)) < self->xnum) {
        if (is_not_ok(n)) break;
        ans = n;
    }
#undef is_not_ok
    if (next_char_pos(self, ans, 1) < self->xnum || !next_line_starts_with_url_chars) {
        while (ans > x && !self->cpu_cells[ans].ch_is_idx && can_strip_from_end_of_url(self->cpu_cells[ans].ch_or_idx)) {
            n = prev_char_pos(self, ans, 1);
            if (n >= self->xnum || n < x) break;
            ans = n;
        }
    }
    return ans;
}

bool
line_startswith_url_chars(Line *self, bool in_hostname, ListOfChars *lc) {
    text_in_cell(self->cpu_cells, self->text_cache, lc);
    if (in_hostname) return is_hostname_lc(lc);
    return is_url_lc(lc);
}

index_type
find_char(Line *self, index_type start, char_type ch) {
    do {
        if (cell_is_char(self->cpu_cells + start, ch)) return start;
    } while ((start = next_char_pos(self, start, 1)) < self->xnum);
    return self->xnum;
}

char_type
get_url_sentinel(Line *line, index_type url_start) {
    char_type before = 0, sentinel;
    if (url_start > 0 && url_start < line->xnum) {
        index_type n = prev_char_pos(line, url_start, 1);
        if (n < line->xnum) before = cell_first_char(line->cpu_cells + n, line->text_cache);
    }
    switch(before) {
        case '"':
        case '\'':
        case '*':
            sentinel = before; break;
        case '(':
            sentinel = ')'; break;
        case '[':
            sentinel = ']'; break;
        case '{':
            sentinel = '}'; break;
        case '<':
            sentinel = '>'; break;
        default:
            sentinel = 0; break;
    }
    return sentinel;
}



static PyObject*
url_start_at(Line *self, PyObject *x) {
#define url_start_at_doc "url_start_at(x) -> Return the start cell number for a URL containing x or self->xnum if not found"
    RAII_ListOfChars(lc);
    return PyLong_FromUnsignedLong((unsigned long)line_url_start_at(self, PyLong_AsUnsignedLong(x), &lc));
}

static PyObject*
url_end_at(Line *self, PyObject *args) {
#define url_end_at_doc "url_end_at(x) -> Return the end cell number for a URL containing x or 0 if not found"
    unsigned int x, sentinel = 0;
    int next_line_starts_with_url_chars = 0;
    if (!PyArg_ParseTuple(args, "I|Ip", &x, &sentinel, &next_line_starts_with_url_chars)) return NULL;
    RAII_ListOfChars(lc);
    return PyLong_FromUnsignedLong((unsigned long)line_url_end_at(self, x, true, sentinel, next_line_starts_with_url_chars, false, self->xnum, &lc));
}

// }}}

static PyObject*
text_at(Line* self, Py_ssize_t xval) {
#define text_at_doc "[x] -> Return the text in the specified cell"
    if ((unsigned)xval >= self->xnum) { PyErr_SetString(PyExc_IndexError, "Column number out of bounds"); return NULL; }
    const CPUCell *cell = self->cpu_cells + xval;
    if (cell->ch_is_idx) {
        RAII_ListOfChars(lc);
        tc_chars_at_index(self->text_cache, cell->ch_or_idx, &lc);
        if (cell->is_multicell) {
            if (cell->x || cell->y || !lc.count) return PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, lc.chars, 0);
            return PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, lc.chars + 1, lc.count - 1);
        }
        return PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, lc.chars, lc.count);
    }
    Py_UCS4 ch = cell->ch_or_idx;
    return PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, &ch, 1);
}

size_t
cell_as_unicode_for_fallback(const ListOfChars *lc, Py_UCS4 *buf, size_t sz) {
    size_t n = 1;
    buf[0] = lc->chars[0] ? lc->chars[0] : ' ';
    if (buf[0] != '\t') {
        for (unsigned i = 1; i < lc->count && n < sz; i++) {
            if (lc->chars[i] != VS15 && lc->chars[i] != VS16) buf[n++] = lc->chars[i];
        }
    } else buf[0] = ' ';
    return n;
}

size_t
cell_as_utf8_for_fallback(const ListOfChars *lc, char *buf, size_t sz) {
    char_type ch = lc->chars[0] ? lc->chars[0] : ' ';
    bool include_cc = true;
    if (ch == '\t') { ch = ' '; include_cc = false; }
    size_t n = encode_utf8(ch, buf);
    if (include_cc) {
        for (unsigned i = 1; i < lc->count && sz > n + 4; i++) {
            char_type ch = lc->chars[i];
            if (ch != VS15 && ch != VS16) n += encode_utf8(ch, buf + n);
        }
    }
    buf[n] = 0;
    return n;
}

bool
unicode_in_range(const Line *self, const index_type start, const index_type limit, const bool include_cc, const bool add_trailing_newline, const bool skip_zero_cells, bool skip_multiline_non_zero_lines, ANSIBuf *buf) {
    static const size_t initial_cap = 4096;
    ListOfChars lc;
    if (!buf->buf) {
        buf->buf = malloc(initial_cap * sizeof(buf->buf[0]));
        if (!buf->buf) return false;
        buf->capacity = initial_cap;
    }
    for (index_type i = start; i < limit; i++) {
        lc.chars = buf->buf + buf->len; lc.capacity = buf->capacity - buf->len;
        while (!text_in_cell_without_alloc(self->cpu_cells + i, self->text_cache, &lc)) {
            size_t ns = MAX(initial_cap, 2 * buf->capacity);
            char_type *np = realloc(buf->buf, ns);
            if (!np) return false;
            buf->capacity = ns; buf->buf = np;
            lc.chars = buf->buf + buf->len; lc.capacity = buf->capacity - buf->len;
        }
        if (self->cpu_cells[i].is_multicell && (self->cpu_cells[i].x || (skip_multiline_non_zero_lines && self->cpu_cells[i].y))) continue;
        if (!lc.chars[0]) {
            if (skip_zero_cells) continue;
            lc.chars[0] = ' ';
        }
        if (lc.chars[0] == '\t') {
            buf->len++;
            unsigned num_cells_to_skip_for_tab = lc.count > 1 ? lc.chars[1] : 0;
            while (num_cells_to_skip_for_tab && i + 1 < limit && cell_is_char(self->cpu_cells+i+1, ' ')) {
                i++;
                num_cells_to_skip_for_tab--;
            }
        } else buf->len += include_cc ? lc.count : 1;
    }
    if (add_trailing_newline && !self->cpu_cells[self->xnum-1].next_char_was_wrapped && buf->len < buf->capacity) buf->buf[buf->len++] = '\n';
    return true;
}

PyObject *
line_as_unicode(Line* self, bool skip_zero_cells, ANSIBuf *buf) {
    size_t before = buf->len;
    if (!unicode_in_range(self, 0, xlimit_for_line(self), true, false, skip_zero_cells, true, buf)) return PyErr_NoMemory();
    PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf->buf + before, buf->len - before);
    buf->len = before;
    return ans;
}

static PyObject*
sprite_at(Line* self, PyObject *x) {
#define sprite_at_doc "[x] -> Return the sprite in the specified cell"
    unsigned long xval = PyLong_AsUnsignedLong(x);
    if (xval >= self->xnum) { PyErr_SetString(PyExc_IndexError, "Column number out of bounds"); return NULL; }
    GPUCell *c = self->gpu_cells + xval;
    return Py_BuildValue("I", (unsigned int)c->sprite_idx);
}

static void
write_sgr(const char *val, ANSIBuf *output) {
#define W(c) output->buf[output->len++] = c
    W(0x1b); W('[');
    for (size_t i = 0; val[i] != 0 && i < 122; i++) W(val[i]);
    W('m');
#undef W
}

static void
write_hyperlink(hyperlink_id_type hid, ANSIBuf *output) {
#define W(c) output->buf[output->len++] = c
    const char *key = hid ? get_hyperlink_for_id(output->hyperlink_pool, hid, false) : NULL;
    if (!key) hid = 0;
    output->active_hyperlink_id = hid;
    W(0x1b); W(']'); W('8');
    if (!hid) {
        W(';'); W(';');
    } else {
        const char* partition = strstr(key, ":");
        W(';');
        if (partition != key) {
            W('i'); W('d'); W('=');
            while (key != partition) W(*(key++));
        }
        W(';');
        while(*(++partition))  W(*partition);
    }
    W(0x1b); W('\\');
#undef W
}

static void
write_mark(const char *mark, ANSIBuf *output) {
#define W(c) output->buf[output->len++] = c
    W(0x1b); W(']'); W('1'); W('3'); W('3'); W(';');
    for (size_t i = 0; mark[i] != 0 && i < 32; i++) W(mark[i]);
    W(0x1b); W('\\');
#undef W

}

static void
write_sgr_to_ansi_buf(ANSILineState *s, const char *val) {
    close_multicell(s);
    ensure_space_in_ansi_output_buf(s, 128);
    s->escape_code_written = true;
    write_sgr(val, s->output_buf);
}

static void
write_ch_to_ansi_buf(ANSILineState *s, char_type ch) {
    close_multicell(s);
    ensure_space_in_ansi_output_buf(s, 1);
    s->output_buf->buf[s->output_buf->len++] = ch;
}

static void
write_hyperlink_to_ansi_buf(ANSILineState *s, hyperlink_id_type hid) {
    close_multicell(s);
    ensure_space_in_ansi_output_buf(s, 2256);
    s->escape_code_written = true;
    write_hyperlink(hid, s->output_buf);
}

static void
write_mark_to_ansi_buf(ANSILineState *s, const char *m) {
    close_multicell(s);
    ensure_space_in_ansi_output_buf(s, 64);
    s->escape_code_written = true;
    write_mark(m, s->output_buf);
}

bool
line_as_ansi(Line *self, ANSILineState *s, index_type start_at, index_type stop_before, char_type prefix_char, bool skip_multiline_non_zero_lines) {
    s->limit = MIN(stop_before, xlimit_for_line(self));
    s->current_multicell_state = NULL;
    s->escape_code_written = false;
    if (prefix_char) write_ch_to_ansi_buf(s, prefix_char);

    if (start_at == 0) {
        switch (self->attrs.prompt_kind) {
            case UNKNOWN_PROMPT_KIND:
                break;
            case PROMPT_START: write_mark_to_ansi_buf(s, "A"); break;
            case SECONDARY_PROMPT: write_mark_to_ansi_buf(s, "A;k=s"); break;
            case OUTPUT_START: write_mark_to_ansi_buf(s, "C"); break;
        }
    }
    if (s->limit <= start_at) return s->escape_code_written;

    static const GPUCell blank_cell = { 0 };
    GPUCell *cell;
    if (s->prev_gpu_cell == NULL) s->prev_gpu_cell = &blank_cell;
    const CellAttrs mask_for_sgr = {.val=SGR_MASK};

#define CMP_ATTRS (cell->attrs.val & mask_for_sgr.val) != (s->prev_gpu_cell->attrs.val & mask_for_sgr.val)
#define CMP(x) (cell->x != s->prev_gpu_cell->x)

    for (s->pos=start_at; s->pos < s->limit; s->pos++) {
        if (s->output_buf->hyperlink_pool) {
            hyperlink_id_type hid = self->cpu_cells[s->pos].hyperlink_id;
            if (hid != s->output_buf->active_hyperlink_id) write_hyperlink_to_ansi_buf(s, hid);
        }
        cell = &self->gpu_cells[s->pos];
        if (CMP_ATTRS || CMP(fg) || CMP(bg) || CMP(decoration_fg)) {
            const char *sgr = cell_as_sgr(cell, s->prev_gpu_cell);
            if (*sgr) write_sgr_to_ansi_buf(s, sgr);
        }

        index_type num_cells_to_skip_for_tab = text_in_cell_ansi(
            s, self->cpu_cells + s->pos, self->text_cache, skip_multiline_non_zero_lines);
        s->prev_gpu_cell = cell;
        const CPUCell *next = self->cpu_cells + s->pos + 1;
        while (num_cells_to_skip_for_tab && s->pos + 1 < s->limit && cell_is_char(next, ' ')) {
            num_cells_to_skip_for_tab--; s->pos++; next++;
        }
    }
    close_multicell(s);
    return s->escape_code_written;
#undef CMP_ATTRS
#undef CMP
}

static PyObject*
as_ansi(Line* self, PyObject *a UNUSED) {
#define as_ansi_doc "Return the line's contents with ANSI (SGR) escape codes for formatting"
    ANSIBuf output = {0}; ANSILineState s = {.output_buf=&output};
    line_as_ansi(self, &s, 0, self->xnum, 0, true);
    PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, output.buf, output.len);
    free(output.buf);
    return ans;
}

static PyObject*
last_char_has_wrapped_flag(Line* self, PyObject *a UNUSED) {
#define last_char_has_wrapped_flag_doc "Return True if the last cell of this line has the wrapped flags set"
    if (self->cpu_cells[self->xnum - 1].next_char_was_wrapped) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
set_wrapped_flag(Line* self, PyObject *is_wrapped) {
    self->cpu_cells[self->xnum-1].next_char_was_wrapped = PyObject_IsTrue(is_wrapped);
    Py_RETURN_NONE;
}

static PyObject*
__repr__(Line* self) {
    RAII_ANSIBuf(buf);
    RAII_PyObject(s, line_as_unicode(self, false, &buf));
    if (s != NULL) return PyObject_Repr(s);
    return NULL;
}

static PyObject*
__str__(Line* self) {
    RAII_ANSIBuf(buf);
    return line_as_unicode(self, false, &buf);
}


static PyObject*
width(Line *self, PyObject *val) {
#define width_doc "width(x) -> the width of the character at x"
    unsigned long x = PyLong_AsUnsignedLong(val);
    if (x >= self->xnum) { PyErr_SetString(PyExc_ValueError, "Out of bounds"); return NULL; }
    const CPUCell *c = self->cpu_cells + x;
    if (!cell_has_text(c)) return 0;
    unsigned long ans = 1;
    if (c->is_multicell) ans = c->x || c->y ? 0 : c->width;
    return PyLong_FromUnsignedLong(ans);
}

static PyObject*
add_combining_char(Line* self, PyObject *args) {
#define add_combining_char_doc "add_combining_char(x, ch) -> Add the specified character as a combining char to the specified cell."
    int new_char;
    unsigned int x;
    if (!PyArg_ParseTuple(args, "IC", &x, &new_char)) return NULL;
    if (x >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Column index out of bounds");
        return NULL;
    }
    CPUCell *cell = self->cpu_cells + x;
    if (cell->is_multicell) { PyErr_SetString(PyExc_IndexError, "cannot set combining char in a multicell"); return NULL; }
    RAII_ListOfChars(lc);
    text_in_cell(cell, self->text_cache, &lc);
    ensure_space_for_chars(&lc, lc.count + 1);
    lc.chars[lc.count++] = new_char;
    cell->ch_or_idx = tc_get_or_insert_chars(self->text_cache, &lc);
    cell->ch_is_idx = true;
    Py_RETURN_NONE;
}


static PyObject*
set_text(Line* self, PyObject *args) {
#define set_text_doc "set_text(src, offset, sz, cursor) -> Set the characters and attributes from the specified text and cursor"
    PyObject *src;
    Py_ssize_t offset, sz, limit;
    Cursor *cursor;
    int kind;
    void *buf;

    if (!PyArg_ParseTuple(args, "UnnO!", &src, &offset, &sz, &Cursor_Type, &cursor)) return NULL;
    if (PyUnicode_READY(src) != 0) {
        PyErr_NoMemory();
        return NULL;
    }
    kind = PyUnicode_KIND(src);
    buf = PyUnicode_DATA(src);
    limit = offset + sz;
    if (PyUnicode_GET_LENGTH(src) < limit) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds offset/sz");
        return NULL;
    }
    CellAttrs attrs = cursor_to_attrs(cursor);
    color_type fg = (cursor->fg & COL_MASK), bg = cursor->bg & COL_MASK;
    color_type dfg = cursor->decoration_fg & COL_MASK;

    for (index_type i = cursor->x; offset < limit && i < self->xnum; i++, offset++) {
        self->cpu_cells[i] = (CPUCell){0};
        self->cpu_cells[i].ch_or_idx = PyUnicode_READ(kind, buf, offset);
        self->gpu_cells[i].attrs = attrs;
        self->gpu_cells[i].fg = fg;
        self->gpu_cells[i].bg = bg;
        self->gpu_cells[i].decoration_fg = dfg;
    }

    Py_RETURN_NONE;
}

static PyObject*
cursor_from(Line* self, PyObject *args) {
#define cursor_from_doc "cursor_from(x, y=0) -> Create a cursor object based on the formatting attributes at the specified x position. The y value of the cursor is set as specified."
    unsigned int x, y = 0;
    Cursor* ans;
    if (!PyArg_ParseTuple(args, "I|I", &x, &y)) return NULL;
    if (x >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds x");
        return NULL;
    }
    ans = alloc_cursor();
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    ans->x = x; ans->y = y;
    attrs_to_cursor(self->gpu_cells[x].attrs, ans);
    ans->fg = self->gpu_cells[x].fg; ans->bg = self->gpu_cells[x].bg;
    ans->decoration_fg = self->gpu_cells[x].decoration_fg & COL_MASK;

    return (PyObject*)ans;
}

void
line_clear_text(Line *self, unsigned int at, unsigned int num, char_type ch) {
    const CPUCell cc = {.ch_or_idx=ch};
    if (at + num > self->xnum) num = self->xnum > at ? self->xnum - at : 0;
    memset_array(self->cpu_cells + at, cc, num);
}

static PyObject*
clear_text(Line* self, PyObject *args) {
#define clear_text_doc "clear_text(at, num, ch=BLANK_CHAR) -> Clear characters in the specified range, preserving formatting."
    unsigned int at, num;
    int ch = BLANK_CHAR;
    if (!PyArg_ParseTuple(args, "II|C", &at, &num, &ch)) return NULL;
    line_clear_text(self, at, num, ch);
    Py_RETURN_NONE;
}

void
line_apply_cursor(Line *self, const Cursor *cursor, unsigned int at, unsigned int num, bool clear_char) {
    GPUCell gc = cursor_as_gpu_cell(cursor);
    if (clear_char) {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
        if (at + num > self->xnum) { num = at < self->xnum ? self->xnum - at : 0; }
        memset(self->cpu_cells + at, 0, num * sizeof(CPUCell));
        memset_array(self->gpu_cells + at, gc, num);
    } else {
        for (index_type i = at; i < self->xnum && i < at + num; i++) {
            gc.attrs.mark = self->gpu_cells[i].attrs.mark;
            gc.sprite_idx = self->gpu_cells[i].sprite_idx;
            memcpy(self->gpu_cells + i, &gc, sizeof(gc));
        }
    }
}

static PyObject*
apply_cursor(Line* self, PyObject *args) {
#define apply_cursor_doc "apply_cursor(cursor, at=0, num=1, clear_char=False) -> Apply the formatting attributes from cursor to the specified characters in this line."
    Cursor* cursor;
    unsigned int at=0, num=1;
    int clear_char = 0;
    if (!PyArg_ParseTuple(args, "O!|IIp", &Cursor_Type, &cursor, &at, &num, &clear_char)) return NULL;
    line_apply_cursor(self, cursor, at, num, clear_char & 1);
    Py_RETURN_NONE;
}

static color_type
resolve_color(const ColorProfile *cp, color_type val, color_type defval) {
    switch(val & 0xff) {
        case 1:
            return cp->color_table[(val >> 8) & 0xff];
        case 2:
            return val >> 8;
        default:
            return defval;
    }
}

bool
colors_for_cell(Line *self, const ColorProfile *cp, index_type *x, color_type *fg, color_type *bg, bool *reversed) {
    if (*x >= self->xnum) return false;
    while (self->cpu_cells[*x].is_multicell && self->cpu_cells[*x].x && *x) (*x)--;
    *fg = resolve_color(cp, self->gpu_cells[*x].fg, *fg);
    *bg = resolve_color(cp, self->gpu_cells[*x].bg, *bg);
    if (self->gpu_cells[*x].attrs.reverse) {
        color_type t = *fg;
        *fg = *bg;
        *bg = t;
        *reversed = true;
    }
    return true;
}

char_type
line_get_char(Line *self, index_type at) {
    if (self->cpu_cells[at].ch_is_idx) {
        RAII_ListOfChars(lc);
        text_in_cell(self->cpu_cells + at, self->text_cache, &lc);
        if (self->cpu_cells[at].is_multicell && (self->cpu_cells[at].x || self->cpu_cells[at].y)) return 0;
        return lc.chars[0];
    } else return self->cpu_cells[at].ch_or_idx;
}


static void
line_set_char(Line *self, unsigned int at, uint32_t ch, Cursor *cursor, hyperlink_id_type hyperlink_id) {
    GPUCell *g = self->gpu_cells + at;
    if (cursor != NULL) {
        g->attrs = cursor_to_attrs(cursor);
        g->fg = cursor->fg & COL_MASK;
        g->bg = cursor->bg & COL_MASK;
        g->decoration_fg = cursor->decoration_fg & COL_MASK;
    }
    CPUCell *c = self->cpu_cells + at;
    *c = (CPUCell){0};
    cell_set_char(c, ch);
    c->hyperlink_id = hyperlink_id;
    if (OPT(underline_hyperlinks) == UNDERLINE_ALWAYS && hyperlink_id) {
        g->decoration_fg = ((OPT(url_color) & COL_MASK) << 8) | 2;
        g->attrs.decoration = OPT(url_style);
    }
}

static PyObject*
set_char(Line *self, PyObject *args) {
#define set_char_doc "set_char(at, ch, width=1, cursor=None, hyperlink_id=0) -> Set the character at the specified cell. If cursor is not None, also set attributes from that cursor."
    unsigned int at, width=1;
    int ch;
    Cursor *cursor = NULL;
    unsigned int hyperlink_id = 0;

    if (!PyArg_ParseTuple(args, "IC|IO!I", &at, &ch, &width, &Cursor_Type, &cursor, &hyperlink_id)) return NULL;
    if (at >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    if (width != 1) {
        PyErr_SetString(PyExc_NotImplementedError, "TODO: Implement setting wide char"); return NULL;
    }
    line_set_char(self, at, ch, cursor, hyperlink_id);
    Py_RETURN_NONE;
}

static PyObject*
set_attribute(Line *self, PyObject *args) {
#define set_attribute_doc "set_attribute(which, val) -> Set the attribute on all cells in the line."
    unsigned int val;
    char *which;
    if (!PyArg_ParseTuple(args, "sI", &which, &val)) return NULL;
    if (!set_named_attribute_on_line(self->gpu_cells, which, val, self->xnum)) {
        PyErr_SetString(PyExc_KeyError, "Unknown cell attribute"); return NULL;
    }
    Py_RETURN_NONE;
}

static int
color_as_sgr(char *buf, size_t sz, unsigned long val, unsigned simple_code, unsigned aix_code, unsigned complex_code) {
    switch(val & 0xff) {
        case 1:
            val >>= 8;
            if (val < 16 && simple_code) {
                return snprintf(buf, sz, "%lu;", (val < 8) ? simple_code + val : aix_code + (val - 8));
            }
            return snprintf(buf, sz, "%u:5:%lu;", complex_code, val);
        case 2:
            return snprintf(buf, sz, "%u:2:%lu:%lu:%lu;", complex_code, (val >> 24) & 0xff, (val >> 16) & 0xff, (val >> 8) & 0xff);
        default:
            return snprintf(buf, sz, "%u;", complex_code + 1);  // reset
    }
}

static const char*
decoration_as_sgr(uint8_t decoration) {
    switch(decoration) {
        case 1: return "4;";
        case 2: return "4:2;";
        case 3: return "4:3;";
        case 4: return "4:4";
        case 5: return "4:5";
        default: return "24;";
    }
}


const char*
cell_as_sgr(const GPUCell *cell, const GPUCell *prev) {
    static char buf[128];
#define SZ sizeof(buf) - (p - buf) - 2
#define P(s) { size_t len = strlen(s); if (SZ > len) { memcpy(p, s, len); p += len; } }
    char *p = buf;
#define CA cell->attrs
#define PA prev->attrs
    bool intensity_differs = CA.bold != PA.bold || CA.dim != PA.dim;
    if (intensity_differs) {
        if (CA.bold && CA.dim) { if (!PA.bold) P("1;"); if (!PA.dim) P("2;"); }
        else {
            P("22;"); if (CA.bold) P("1;"); if (CA.dim) P("2;");
        }
    }
    if (CA.italic != PA.italic) P(CA.italic ? "3;" : "23;");
    if (CA.reverse != PA.reverse) P(CA.reverse ? "7;" : "27;");
    if (CA.strike != PA.strike) P(CA.strike ? "9;" : "29;");
    if (cell->fg != prev->fg) p += color_as_sgr(p, SZ, cell->fg, 30, 90, 38);
    if (cell->bg != prev->bg) p += color_as_sgr(p, SZ, cell->bg, 40, 100, 48);
    if (cell->decoration_fg != prev->decoration_fg) p += color_as_sgr(p, SZ, cell->decoration_fg, 0, 0, DECORATION_FG_CODE);
    if (CA.decoration != PA.decoration) P(decoration_as_sgr(CA.decoration));
#undef PA
#undef CA
#undef P
#undef SZ
    if (p > buf) *(p - 1) = 0;  // remove trailing semi-colon
    *p = 0;  // ensure string is null-terminated
    return buf;
}


static Py_ssize_t
__len__(PyObject *self) {
    return (Py_ssize_t)(((Line*)self)->xnum);
}

static int
__eq__(Line *a, Line *b) {
    return a->xnum == b->xnum && memcmp(a->cpu_cells, b->cpu_cells, sizeof(CPUCell) * a->xnum) == 0 && memcmp(a->gpu_cells, b->gpu_cells, sizeof(GPUCell) * a->xnum) == 0;
}

bool
line_has_mark(Line *line, uint16_t mark) {
    for (index_type x = 0; x < line->xnum; x++) {
        const uint16_t m = line->gpu_cells[x].attrs.mark;
        if (m && (!mark || mark == m)) return true;
    }
    return false;
}

static void
report_marker_error(PyObject *marker) {
    if (!PyObject_HasAttrString(marker, "error_reported")) {
        PyErr_Print();
        if (PyObject_SetAttrString(marker, "error_reported", Py_True) != 0) PyErr_Clear();
    } else PyErr_Clear();
}

static void
apply_mark(Line *line, const uint16_t mark, index_type *cell_pos, unsigned int *match_pos) {
#define MARK { line->gpu_cells[x].attrs.mark = mark; }
    index_type x = *cell_pos;
    MARK;
    (*match_pos)++;
    RAII_ListOfChars(lc); text_in_cell(line->cpu_cells + x, line->text_cache, &lc);
    if (lc.chars[0]) {
        if (lc.chars[0] == '\t') {
            unsigned num_cells_to_skip_for_tab = lc.count > 1 ? lc.chars[1] : 0;
            while (num_cells_to_skip_for_tab && x + 1 < line->xnum && cell_is_char(line->cpu_cells+x+1, ' ')) {
                x++;
                num_cells_to_skip_for_tab--;
                MARK;
            }
        } else if (line->cpu_cells[x].is_multicell) {
            *match_pos += lc.count - 1;
            index_type x_limit = MIN(line->xnum, mcd_x_limit(line->cpu_cells + x));
            for (; x < x_limit; x++) { MARK; }
            x--;
        } else {
            *match_pos += lc.count - 1;
        }
    }
    *cell_pos = x + 1;
#undef MARK
}

static void
apply_marker(PyObject *marker, Line *line, const PyObject *text) {
    unsigned int l=0, r=0, col=0, match_pos=0;
    PyObject *pl = PyLong_FromVoidPtr(&l), *pr = PyLong_FromVoidPtr(&r), *pcol = PyLong_FromVoidPtr(&col);
    if (!pl || !pr || !pcol) { PyErr_Clear(); return; }
    PyObject *iter = PyObject_CallFunctionObjArgs(marker, text, pl, pr, pcol, NULL);
    Py_DECREF(pl); Py_DECREF(pr); Py_DECREF(pcol);

    if (iter == NULL) { report_marker_error(marker); return; }
    PyObject *match;
    index_type x = 0;
    while ((match = PyIter_Next(iter)) && x < line->xnum) {
        Py_DECREF(match);
        while (match_pos < l && x < line->xnum) {
            apply_mark(line, 0, &x, &match_pos);
        }
        uint16_t am = (col & MARK_MASK);
        while(x < line->xnum && match_pos <= r) {
            apply_mark(line, am, &x, &match_pos);
        }

    }
    Py_DECREF(iter);
    while(x < line->xnum) line->gpu_cells[x++].attrs.mark = 0;
    if (PyErr_Occurred()) report_marker_error(marker);
}

void
mark_text_in_line(PyObject *marker, Line *line, ANSIBuf *buf) {
    if (!marker) {
        for (index_type i = 0; i < line->xnum; i++)  line->gpu_cells[i].attrs.mark = 0;
        return;
    }
    PyObject *text = line_as_unicode(line, false, buf);
    if (PyUnicode_GET_LENGTH(text) > 0) {
        apply_marker(marker, line, text);
    } else {
        for (index_type i = 0; i < line->xnum; i++)  line->gpu_cells[i].attrs.mark = 0;
    }
    Py_DECREF(text);
}

PyObject*
as_text_generic(PyObject *args, void *container, get_line_func get_line, index_type lines, ANSIBuf *ansibuf, bool add_trailing_newline) {
#define APPEND(x) { PyObject* retval = PyObject_CallFunctionObjArgs(callback, x, NULL); if (!retval) return NULL; Py_DECREF(retval); }
#define APPEND_AND_DECREF(x) { if (x == NULL) { if (PyErr_Occurred()) return NULL; Py_RETURN_NONE; } PyObject* retval = PyObject_CallFunctionObjArgs(callback, x, NULL); Py_CLEAR(x); if (!retval) return NULL; Py_DECREF(retval); }
    PyObject *callback;
    int as_ansi = 0, insert_wrap_markers = 0;
    if (!PyArg_ParseTuple(args, "O|pp", &callback, &as_ansi, &insert_wrap_markers)) return NULL;
    PyObject *t = NULL;
    RAII_PyObject(nl, PyUnicode_FromString("\n"));
    RAII_PyObject(cr, PyUnicode_FromString("\r"));
    RAII_PyObject(sgr_reset, PyUnicode_FromString("\x1b[m"));
    if (nl == NULL || cr == NULL || sgr_reset == NULL) return NULL;
    ANSILineState s = {.output_buf=ansibuf};
    ansibuf->active_hyperlink_id = 0;
    bool need_newline = false;
    for (index_type y = 0; y < lines; y++) {
        Line *line = get_line(container, y);
        if (!line) { if (PyErr_Occurred()) return NULL; break; }
        if (need_newline) APPEND(nl);
        ansibuf->len = 0;
        if (as_ansi) {
            // less has a bug where it resets colors when it sees a \r, so work
            // around it by resetting SGR at the start of every line. This is
            // pretty sad performance wise, but I guess it will remain as it
            // makes writing pagers easier.
            // see https://github.com/kovidgoyal/kitty/issues/2381
            s.prev_gpu_cell = NULL;
            line_as_ansi(line, &s, 0, line->xnum, 0, true);
            t = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, ansibuf->buf, ansibuf->len);
            if (t && ansibuf->len > 0) APPEND(sgr_reset);
        } else {
            t = line_as_unicode(line, false, ansibuf);
        }
        APPEND_AND_DECREF(t);
        if (insert_wrap_markers) APPEND(cr);
        need_newline = !line->cpu_cells[line->xnum-1].next_char_was_wrapped;
    }
    if (need_newline && add_trailing_newline) APPEND(nl);
    if (ansibuf->active_hyperlink_id) {
        ansibuf->active_hyperlink_id = 0;
        t = PyUnicode_FromString("\x1b]8;;\x1b\\");
        APPEND_AND_DECREF(t);
    }
    Py_RETURN_NONE;
#undef APPEND
#undef APPEND_AND_DECREF
}

// Boilerplate {{{
static PyObject*
copy_char(Line* self, PyObject *args);
#define copy_char_doc "copy_char(src, to, dest) -> Copy the character at src to the character dest in the line `to`"

#define hyperlink_ids_doc "hyperlink_ids() -> Tuple of hyper link ids at every cell"
static PyObject*
hyperlink_ids(Line *self, PyObject *args UNUSED) {
    PyObject *ans = PyTuple_New(self->xnum);
    for (index_type x = 0; x < self->xnum; x++) {
        PyTuple_SET_ITEM(ans, x, PyLong_FromUnsignedLong(self->cpu_cells[x].hyperlink_id));
    }
    return ans;
}

static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);


static PySequenceMethods sequence_methods = {
    .sq_length = __len__,
    .sq_item = (ssizeargfunc)text_at
};

static PyMethodDef methods[] = {
    METHOD(add_combining_char, METH_VARARGS)
    METHOD(set_text, METH_VARARGS)
    METHOD(cursor_from, METH_VARARGS)
    METHOD(apply_cursor, METH_VARARGS)
    METHOD(clear_text, METH_VARARGS)
    METHOD(copy_char, METH_VARARGS)
    METHOD(set_char, METH_VARARGS)
    METHOD(set_attribute, METH_VARARGS)
    METHOD(as_ansi, METH_NOARGS)
    METHOD(last_char_has_wrapped_flag, METH_NOARGS)
    METHODB(set_wrapped_flag, METH_O),
    METHOD(hyperlink_ids, METH_NOARGS)
    METHOD(width, METH_O)
    METHOD(url_start_at, METH_O)
    METHOD(url_end_at, METH_VARARGS)
    METHOD(sprite_at, METH_O)

    {NULL}  /* Sentinel */
};

PyTypeObject Line_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Line",
    .tp_basicsize = sizeof(Line),
    .tp_dealloc = (destructor)dealloc,
    .tp_repr = (reprfunc)__repr__,
    .tp_str = (reprfunc)__str__,
    .tp_as_sequence = &sequence_methods,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_richcompare = richcmp,
    .tp_doc = "Lines",
    .tp_methods = methods,
};

Line *alloc_line(TextCache *tc) {
    Line *ans = (Line*)Line_Type.tp_alloc(&Line_Type, 0);
    if (ans) ans->text_cache = tc_incref(tc);
    return ans;
}

RICHCMP(Line)
INIT_TYPE(Line)
// }}}

static PyObject*
copy_char(Line* self, PyObject *args) {
    unsigned int src, dest;
    Line *to;
    if (!PyArg_ParseTuple(args, "IO!I", &src, &Line_Type, &to, &dest)) return NULL;
    if (src >= self->xnum || dest >= to->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    COPY_CELL(self, src, to, dest);
    Py_RETURN_NONE;
}
