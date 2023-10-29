/*
 * bytes-parser.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// TODO: Delete latin1_charset
// TODO: Delete C1 controls from control-codes.h

#include "vt-parser.h"
#include "screen.h"
#define NO_C1_CONTROLS 1
#include "control-codes.h"

#define EXTENDED_OSC_SENTINEL 0x1bu
#define PARSER_BUF_SZ (8u * 1024u)
#define PENDING_BUF_INCREMENT (16u * 1024u)

// Macros {{{
#define SAVE_INPUT_DATA const uint8_t *orig_input_data = self->input_data; size_t orig_input_sz = self->input_sz, orig_input_pos = self->input_pos

#define RESTORE_INPUT_DATA self->input_data = orig_input_data; self->input_sz = orig_input_sz; self->input_pos = orig_input_pos

#define SET_STATE(state) self->vte_state = state; self->parser_buf_pos = 0;

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

#define REPORT_ERROR(...) _report_error(self->dump_callback, __VA_ARGS__);

#define REPORT_COMMAND1(name) \
        Py_XDECREF(PyObject_CallFunction(self->dump_callback, "s", #name)); PyErr_Clear();

#define REPORT_COMMAND2(name, x) \
        Py_XDECREF(PyObject_CallFunction(self->dump_callback, "si", #name, (int)x)); PyErr_Clear();

#define REPORT_COMMAND3(name, x, y) \
        Py_XDECREF(PyObject_CallFunction(self->dump_callback, "sii", #name, (int)x, (int)y)); PyErr_Clear();

#define GET_MACRO(_1,_2,_3,NAME,...) NAME
#define REPORT_COMMAND(...) GET_MACRO(__VA_ARGS__, REPORT_COMMAND3, REPORT_COMMAND2, REPORT_COMMAND1, SENTINEL)(__VA_ARGS__)
#define REPORT_VA_COMMAND(...) Py_XDECREF(PyObject_CallFunction(dump_callback, __VA_ARGS__)); PyErr_Clear();

#define REPORT_DRAW(ch) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "sC", "draw", ch)); PyErr_Clear();

#define REPORT_PARAMS(name, params, num, region) _report_params(self->dump_callback, name, params, num_params, region)

#define FLUSH_DRAW \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "sO", "draw", Py_None)); PyErr_Clear();

#define REPORT_OSC(name, string) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "sO", #name, string)); PyErr_Clear();

#define REPORT_OSC2(name, code, string) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "siO", #name, code, string)); PyErr_Clear();

#define REPORT_HYPERLINK(id, url) \
    Py_XDECREF(PyObject_CallFunction(self->dump_callback, "szz", "set_active_hyperlink", id, url)); PyErr_Clear();

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

typedef enum VTEState {
    VTE_NORMAL, VTE_ESC, VTE_CSI, VTE_OSC, VTE_DCS, VTE_APC, VTE_PM
} VTEState;

typedef struct PS {
    id_type window_id;
    uint8_t parser_buf[PARSER_BUF_SZ];
    size_t parser_buf_pos;
    VTEState vte_state;
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
} PS;


#define dispatch_single_byte(dispatch, watch_for_pending) { \
    switch(self->vte_state) { \
        case VTE_ESC: \
            dispatch##_esc_mode_byte(self); \
            break; \
        case VTE_CSI: \
            if (accumulate_csi(self)) { dispatch##_csi(self); SET_STATE(0); watch_for_pending; } \
            break; \
        case VTE_OSC: \
            { \
                self->extended_osc_code = false; \
                if (accumulate_osc(self)) {  \
                    dispatch##_osc(self); \
                    if (self->extended_osc_code) { \
                        if (accumulate_osc(self)) { dispatch##_osc(self); SET_STATE(0); } \
                    } else { SET_STATE(0); } \
                } \
            } \
            break; \
        case VTE_APC: \
            if (accumulate_oth(self)) { dispatch##_apc(self); SET_STATE(0); } \
            break; \
        case VTE_PM: \
            if (accumulate_oth(self)) { dispatch##_pm(self); SET_STATE(0); } \
            break; \
        case VTE_DCS: \
            if (accumulate_dcs(self)) { dispatch##_dcs(self); SET_STATE(0); watch_for_pending; } \
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
        self->pending_mode.buf = PyMem_Realloc(self->pending_mode.buf, self->pending_mode.capacity);
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

static void
pending_escape_code(PS *self, char_type start_ch, char_type end_ch) {
    ensure_pending_space(self, 4 + self->parser_buf_pos);
    self->pending_mode.buf[self->pending_mode.used++] = ESC;
    self->pending_mode.buf[self->pending_mode.used++] = start_ch;
    memcpy(self->pending_mode.buf + self->pending_mode.used, self->parser_buf, self->parser_buf_pos);
    self->pending_mode.buf[self->pending_mode.used++] = ESC;
    self->pending_mode.buf[self->pending_mode.used++] = end_ch;
}

static void pending_pm(PS *self) { pending_escape_code(self, ESC_PM, ESC_ST); }
static void pending_apc(PS *self) { pending_escape_code(self, ESC_APC, ESC_ST); }


static void
queue_pending_bytes(PS *self) {
    for (; self->input_pos < self->input_sz; self->input_pos++) {
        dispatch_single_byte(pending, if (!screen->pending_mode.activated_at) goto end);
    }
end:
FLUSH_DRAW;
}

static void
parse_pending_bytes(PS *self) {
    SAVE_INPUT_DATA;
    self->input_data = self->pending_mode.buf; self->input_sz = self->pending_mode.used;
    for (self->input_pos = 0; self->input_pos < self->input_sz; self->input_pos++) {
        dispatch_single_byte(dispatch, ;);
    }
    RESTORE_INPUT_DATA;
}

static void
dump_partial_escape_code_to_pending(PS *self) {
    if (self->parser_buf_pos) {
        ensure_pending_space(self, self->parser_buf_pos + 1);
        self->pending_mode.buf[self->pending_mode.used++] = self->vte_state;
        memcpy(self->pending_mode.buf + self->pending_mode.used, self->parser_buf, self->parser_buf_pos);
        self->pending_mode.used += self->parser_buf_pos;
    }
}
// }}}

static void
parse_bytes_watching_for_pending(PS *self) {
    for (; self->input_pos < self->input_sz; self->input_pos++) {
        dispatch_single_byte(dispatch, if (screen->pending_mode.activated_at) goto end);
    }
end:
FLUSH_DRAW;
}

static void
do_parse_vte(PS *self) {
    enum STATE {START, PARSE_PENDING, PARSE_READ_BUF, QUEUE_PENDING};
    enum STATE state = START;
    size_t read_buf_pos = 0;
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
#ifdef DUMP_COMMANDS
void
parse_vte_dump(Parser *p) {
    do_parse_vte((PS*)p->state);
}
#else
void
parse_vte(Parser *p) {
    do_parse_vte((PS*)p->state);
}
#endif

#ifndef DUMP_COMMANDS
static PyObject*
new(PyTypeObject *type UNUSED, PyObject *args, PyObject UNUSED *kwds) {
    id_type window_id=0;
    if (!PyArg_ParseTuple(args, "|K", &window_id)) return NULL;
    return (PyObject*) alloc_parser(window_id);
}

static void
dealloc(Parser* self) {
    if (self->state) {
        PS *s = (PS*)self->state;
        PyMem_Free(s->pending_mode.buf); s->pending_mode.buf = NULL;
        PyMem_Free(self->state); self->state = NULL;
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

extern PyTypeObject Screen_Type;

static PyObject*
py_parse_vte(Parser *p, PyObject *args) {
    PS *self = (PS*)p->state;
    const uint8_t *data; Py_ssize_t sz;
    PyObject *dump_callback = NULL;
    if (!PyArg_ParseTuple(args, "O!y#|O", &Screen_Type, &self->screen, &data, &sz, &dump_callback)) return NULL;

    self->input_data = data; self->input_sz = sz; self->dump_callback = dump_callback;
    self->now = monotonic();
    if (dump_callback) parse_vte_dump(p); else parse_vte(p);
    self->input_data = NULL; self->input_sz = 0; self->dump_callback = NULL; self->screen = NULL;

    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"parse_vte", (PyCFunction)py_parse_vte, METH_VARARGS, ""},
    {NULL},
};

PyTypeObject Parser_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Parser",
    .tp_basicsize = sizeof(Parser),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "VT Escape code parser",
    .tp_methods = methods,
    .tp_new = new,
};

Parser*
alloc_parser(id_type window_id) {
    Parser *self = (Parser*)Parser_Type.tp_alloc(&Parser_Type, 1);
    if (self != NULL) {
        self->state = PyMem_Calloc(1, sizeof(PS));
        if (!self->state) { Py_CLEAR(self); PyErr_NoMemory(); return NULL; }
        PS *state = (PS*)self->state;
        state->window_id = window_id;
    }
    return self;
}

INIT_TYPE(Parser)
#endif
// }}}
