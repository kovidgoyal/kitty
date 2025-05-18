/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifdef __APPLE__
// Needed for _CS_DARWIN_USER_CACHE_DIR
#define _DARWIN_C_SOURCE
#include <unistd.h>
#undef _DARWIN_C_SOURCE
#endif

#include "char-props.h"
#include "launcher/utils.h"
#include "line.h"
#include "charsets.h"
#include "base64.h"
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#include "cleanup.h"
#include "safe-wrappers.h"
#include "control-codes.h"
#include "wcswidth.h"
#include "modes.h"
#include <stddef.h>
#include <termios.h>
#include <fcntl.h>
#include <stdio.h>
#include <locale.h>

#ifdef WITH_PROFILER
#include <gperftools/profiler.h>
#endif

#include "monotonic.h"

#ifdef __APPLE__
#include <libproc.h>
#include <xlocale.h>

static PyObject*
user_cache_dir(PyObject *self UNUSED, PyObject *args UNUSED) {
    static char buf[1024];
    if (!confstr(_CS_DARWIN_USER_CACHE_DIR, buf, sizeof(buf) - 1)) return PyErr_SetFromErrno(PyExc_OSError);
    return PyUnicode_FromString(buf);
}

static PyObject*
process_group_map(PyObject *self UNUSED, PyObject *args UNUSED) {
    int num_of_processes = proc_listallpids(NULL, 0);
    size_t bufsize = sizeof(pid_t) * (num_of_processes + 1024);
    RAII_ALLOC(pid_t, buf, malloc(bufsize));
    if (!buf) return PyErr_NoMemory();
    num_of_processes = proc_listallpids(buf, (int)bufsize);
    PyObject *ans = PyTuple_New(num_of_processes);
    if (ans == NULL) { return PyErr_NoMemory(); }
    for (int i = 0; i < num_of_processes; i++) {
        long pid = buf[i], pgid = getpgid(buf[i]);
        PyObject *t = Py_BuildValue("ll", pid, pgid);
        if (t == NULL) { Py_DECREF(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, t);
    }
    return ans;
}
#endif

static PyObject*
pybase64_encode(PyObject UNUSED *self, PyObject *const *args, Py_ssize_t nargs) {
    int add_padding = 0;
    if (nargs < 1 || nargs > 2) { PyErr_SetString(PyExc_TypeError, "must supply one or two arguments"); return NULL; }
    RAII_PY_BUFFER(view);
    if (PyUnicode_Check(args[0])) view.buf = (void*)PyUnicode_AsUTF8AndSize(args[0], &view.len);
    else if (PyObject_GetBuffer(args[0], &view, PyBUF_SIMPLE) != 0) return NULL;
    if (nargs == 2) add_padding = PyObject_IsTrue(args[1]);
    size_t sz = required_buffer_size_for_base64_encode(view.len);
    PyObject *ans = PyBytes_FromStringAndSize(NULL, sz);
    if (!ans) return NULL;
    base64_encode8(view.buf, view.len, (unsigned char*)PyBytes_AS_STRING(ans), &sz, add_padding);
    if (_PyBytes_Resize(&ans, sz) != 0) return NULL;
    return ans;
}

static PyObject*
base64_encode_into(PyObject UNUSED *self, PyObject *args) {
    int add_padding = 0;
    RAII_PY_BUFFER(view); RAII_PY_BUFFER(output);
    if (!PyArg_ParseTuple(args, "s*w*|i", &view, &output, &add_padding)) return NULL;
    size_t sz = required_buffer_size_for_base64_encode(view.len);
    if (output.len < (ssize_t)sz) { PyErr_SetString(PyExc_TypeError, "output buffer too small"); return NULL; }
    base64_encode8(view.buf, view.len, output.buf, &sz, add_padding);
    return PyLong_FromSize_t(sz);
}

static PyObject*
pybase64_decode(PyObject UNUSED *self, PyObject *input_data) {
    RAII_PY_BUFFER(view);
    if (PyUnicode_Check(input_data)) view.buf = (void*)PyUnicode_AsUTF8AndSize(input_data, &view.len);
    else if (PyObject_GetBuffer(input_data, &view, PyBUF_SIMPLE) != 0) return NULL;
    size_t sz = required_buffer_size_for_base64_decode(view.len);
    PyObject *ans = PyBytes_FromStringAndSize(NULL, sz);
    if (!ans) return NULL;
    if (!base64_decode8(view.buf, view.len, (unsigned char*)PyBytes_AS_STRING(ans), &sz)) {
        Py_DECREF(ans);
        PyErr_SetString(PyExc_ValueError, "Invalid base64 input data");
        return NULL;
    }
    if (_PyBytes_Resize(&ans, sz) != 0) return NULL;
    return ans;
}

static PyObject*
base64_decode_into(PyObject UNUSED *self, PyObject *args) {
    RAII_PY_BUFFER(view); RAII_PY_BUFFER(output);
    if (!PyArg_ParseTuple(args, "s*w*", &view, &output)) return NULL;
    size_t sz = required_buffer_size_for_base64_decode(view.len);
    if (output.len < (ssize_t)sz) { PyErr_SetString(PyExc_TypeError, "output buffer too small"); return NULL; }
    if (!base64_decode8(view.buf, view.len, output.buf, &sz)) {
        PyErr_SetString(PyExc_ValueError, "Invalid base64 input data");
        return NULL;
    }
    return PyLong_FromSize_t(sz);
}

static PyObject*
split_into_graphemes(PyObject UNUSED *self, PyObject *src) {
    if (!PyUnicode_Check(src)) { PyErr_SetString(PyExc_TypeError, "must provide a unicode string"); return NULL; }
    int kind = PyUnicode_KIND(src); char *data = PyUnicode_DATA(src);
    RAII_PyObject(ans, PyList_New(0));
    if (!ans) return NULL;
    GraphemeSegmentationResult s; grapheme_segmentation_reset(&s);
    Py_ssize_t pos = 0;
    for (Py_ssize_t i = 0; i < PyUnicode_GET_LENGTH(src); i++) {
        char_type ch = PyUnicode_READ(kind, data, i);
        if (!(s = grapheme_segmentation_step(s, char_props_for(ch))).add_to_current_cell) {
            RAII_PyObject(u, PyUnicode_FromKindAndData(kind, data + kind * pos, i - pos));
            if (!u || PyList_Append(ans, u) != 0) return NULL;
            pos = i;
        }
    }
    if (pos < PyUnicode_GET_LENGTH(src)) {
        RAII_PyObject(u, PyUnicode_FromKindAndData(kind, data + kind * pos, PyUnicode_GET_LENGTH(src) - pos));
        if (!u || PyList_Append(ans, u) != 0) return NULL;
    }
    return Py_NewRef(ans);
}

typedef struct StreamingBase64Decoder {
    PyObject_HEAD
    struct base64_state state;
    bool add_trailing_bytes, needs_more_data;
} StreamingBase64Decoder;

static void
StreamingBase64Decoder_reset_(StreamingBase64Decoder *self) {
    base64_stream_decode_init(&self->state, 0);
    self->needs_more_data = false;
}

static int
StreamingBase64Decoder_init(PyObject *s, PyObject *args, PyObject *kwds UNUSED) {
    if (PyTuple_GET_SIZE(args)) { PyErr_SetString(PyExc_TypeError, "constructor takes no arguments"); return -1; }
    StreamingBase64Decoder *self = (StreamingBase64Decoder*)s;
	base64_stream_decode_init(&self->state, 0);
    return 0;
}

static PyObject*
StreamingBase64Decoder_decode(StreamingBase64Decoder *self, PyObject *a) {
    RAII_PY_BUFFER(data);
    if (PyObject_GetBuffer(a, &data, PyBUF_SIMPLE) != 0) return NULL;
    if (!data.buf || !data.len) return PyBytes_FromStringAndSize(NULL, 0);
    size_t sz = required_buffer_size_for_base64_decode(data.len);
    RAII_PyObject(ans, PyBytes_FromStringAndSize(NULL, sz));
    if (!ans) return NULL;
    int ret;
    Py_BEGIN_ALLOW_THREADS
    ret = base64_stream_decode(&self->state, data.buf, data.len, PyBytes_AS_STRING(ans), &sz);
    Py_END_ALLOW_THREADS;
    if (!ret) {
        StreamingBase64Decoder_reset_(self);
        PyErr_SetString(PyExc_ValueError, "Invalid base64 input data");
        return NULL;
    }
    if (self->state.eof) StreamingBase64Decoder_reset_(self);
    else self->needs_more_data = self->state.carry != 0 || self->state.bytes != 0;
    if (_PyBytes_Resize(&ans, sz) != 0) return NULL;
    return Py_NewRef(ans);
}

static PyObject*
StreamingBase64Decoder_decode_into(StreamingBase64Decoder *self, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 2) { PyErr_SetString(PyExc_TypeError, "constructor takes exactly two arguments"); return NULL; }
    RAII_PY_BUFFER(data);
    if (PyObject_GetBuffer(args[0], &data, PyBUF_WRITE) != 0) return NULL;
    if (!data.buf || !data.len) return PyLong_FromLong(0);
    RAII_PY_BUFFER(src);
    if (PyObject_GetBuffer(args[1], &src, PyBUF_SIMPLE) != 0) return NULL;
    if (!src.buf || !src.len) return PyLong_FromLong(0);
    size_t sz = required_buffer_size_for_base64_decode(src.len);
    if ((Py_ssize_t)sz > data.len) { PyErr_SetString(PyExc_BufferError, "output buffer too small"); return NULL; }
    int ret;
    Py_BEGIN_ALLOW_THREADS
    ret = base64_stream_decode(&self->state, src.buf, src.len, data.buf, &sz);
    Py_END_ALLOW_THREADS
    if (!ret) {
        StreamingBase64Decoder_reset_(self);
        PyErr_SetString(PyExc_ValueError, "Invalid base64 input data");
        return NULL;
    }
    if (self->state.eof) StreamingBase64Decoder_reset_(self); else self->needs_more_data = true;
    return PyLong_FromSize_t(sz);
}

static PyObject*
StreamingBase64Decoder_reset(StreamingBase64Decoder *self, PyObject *args UNUSED) {
    StreamingBase64Decoder_reset_(self);
    Py_RETURN_NONE;
}

static PyObject*
StreamingBase64Decoder_needs_more_data(StreamingBase64Decoder *self, PyObject *args UNUSED) {
    return Py_NewRef(self->needs_more_data ? Py_True : Py_False);
}

static PyTypeObject StreamingBase64Decoder_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "kitty.fast_data_types.StreamingBase64Decoder",
    .tp_basicsize = sizeof(StreamingBase64Decoder),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "StreamingBase64Decoder",
    .tp_methods = (PyMethodDef[]){
        {"decode", (PyCFunction)StreamingBase64Decoder_decode, METH_O, ""},
        {"decode_into", (PyCFunction)(void(*)(void))StreamingBase64Decoder_decode_into, METH_FASTCALL, ""},
        {"reset", (PyCFunction)StreamingBase64Decoder_reset, METH_NOARGS, ""},
        {"needs_more_data", (PyCFunction)StreamingBase64Decoder_needs_more_data, METH_NOARGS, ""},
        {NULL, NULL, 0, NULL},
    },
    .tp_new = PyType_GenericNew,
    .tp_init = StreamingBase64Decoder_init,
};

static int
StreamingBase64Encoder_init(PyObject *s, PyObject *args, PyObject *kwds UNUSED) {
    StreamingBase64Decoder *self = (StreamingBase64Decoder*)s;
    self->add_trailing_bytes = true;
    switch (PyTuple_GET_SIZE(args)) {
        case 0: break;
        case 1: self->add_trailing_bytes = PyObject_IsTrue(PyTuple_GET_ITEM(args, 0)); break;
        default: PyErr_SetString(PyExc_TypeError, "constructor takes no more than one argument"); return -1;
    }
	base64_stream_encode_init(&self->state, 0);
    return 0;
}

static PyObject*
StreamingBase64Encoder_encode(StreamingBase64Decoder *self, PyObject *a) {
    RAII_PY_BUFFER(data);
    if (PyObject_GetBuffer(a, &data, PyBUF_SIMPLE) != 0) return NULL;
    if (!data.buf || !data.len) return PyBytes_FromStringAndSize(NULL, 0);
    size_t sz = required_buffer_size_for_base64_encode(data.len);
    RAII_PyObject(ans, PyBytes_FromStringAndSize(NULL, sz));
    if (!ans) return NULL;
    Py_BEGIN_ALLOW_THREADS
    base64_stream_encode(&self->state, data.buf, data.len, PyBytes_AS_STRING(ans), &sz);
    Py_END_ALLOW_THREADS
    if (_PyBytes_Resize(&ans, sz) != 0) return NULL;
    return Py_NewRef(ans);
}

static PyObject*
StreamingBase64Encoder_encode_into(StreamingBase64Decoder *self, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 2) { PyErr_SetString(PyExc_TypeError, "constructor takes exactly two arguments"); return NULL; }
    RAII_PY_BUFFER(data);
    if (PyObject_GetBuffer(args[0], &data, PyBUF_WRITE) != 0) return NULL;
    if (!data.buf || !data.len) return PyLong_FromLong(0);
    RAII_PY_BUFFER(src);
    if (PyObject_GetBuffer(args[1], &src, PyBUF_SIMPLE) != 0) return NULL;
    if (!src.buf || !src.len) return PyLong_FromLong(0);
    size_t sz = required_buffer_size_for_base64_encode(src.len);
    if ((Py_ssize_t)sz > data.len) { PyErr_SetString(PyExc_BufferError, "output buffer too small"); return NULL; }
    Py_BEGIN_ALLOW_THREADS
    base64_stream_encode(&self->state, src.buf, src.len, data.buf, &sz);
    Py_END_ALLOW_THREADS
    return PyLong_FromSize_t(sz);
}

static PyObject*
StreamingBase64Encoder_reset(StreamingBase64Decoder *self, PyObject *args UNUSED) {
    char trailer[4];
    size_t sz;
    base64_stream_encode_final(&self->state, trailer, &sz);
    base64_stream_encode_init(&self->state, 0);
    if (!self->add_trailing_bytes) { while(sz && trailer[sz-1] == '=') sz--; }
    return PyBytes_FromStringAndSize(trailer, sz);
}

static PyTypeObject StreamingBase64Encoder_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "kitty.fast_data_types.StreamingBase64Encoder",
    .tp_basicsize = sizeof(StreamingBase64Decoder),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "StreamingBase64Encoder",
    .tp_methods = (PyMethodDef[]){
        {"encode", (PyCFunction)StreamingBase64Encoder_encode, METH_O, ""},
        {"encode_into", (PyCFunction)(void(*)(void))StreamingBase64Encoder_encode_into, METH_FASTCALL, ""},
        {"reset", (PyCFunction)StreamingBase64Encoder_reset, METH_NOARGS, ""},
        {NULL, NULL, 0, NULL},
    },
    .tp_new = PyType_GenericNew,
    .tp_init = StreamingBase64Encoder_init,
};


static PyObject*
pyset_iutf8(PyObject UNUSED *self, PyObject *args) {
    int fd, on;
    if (!PyArg_ParseTuple(args, "ip", &fd, &on)) return NULL;
    if (!set_iutf8(fd, on & 1)) return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}

#ifdef WITH_PROFILER
static PyObject*
start_profiler(PyObject UNUSED *self, PyObject *args) {
    char *path;
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;
    ProfilerStart(path);
    Py_RETURN_NONE;
}

static PyObject*
stop_profiler(PyObject UNUSED *self, PyObject *args UNUSED) {
    ProfilerStop();
    Py_RETURN_NONE;
}
#endif

static bool
put_tty_in_raw_mode(int fd, const struct termios* termios_p, bool read_with_timeout, int optional_actions) {
    struct termios raw_termios = *termios_p;
    cfmakeraw(&raw_termios);
    if (read_with_timeout) {
        raw_termios.c_cc[VMIN] = 0; raw_termios.c_cc[VTIME] = 1;
    } else {
        raw_termios.c_cc[VMIN] = 1; raw_termios.c_cc[VTIME] = 0;
    }
    if (tcsetattr(fd, optional_actions, &raw_termios) != 0) { PyErr_SetFromErrno(PyExc_OSError); return false; }
    return true;
}

static PyObject*
open_tty(PyObject *self UNUSED, PyObject *args) {
    int read_with_timeout = 0, optional_actions = TCSAFLUSH;
    if (!PyArg_ParseTuple(args, "|pi", &read_with_timeout, &optional_actions)) return NULL;
    int flags = O_RDWR | O_CLOEXEC | O_NOCTTY;
    if (!read_with_timeout) flags |= O_NONBLOCK;
    static char ctty[L_ctermid+1];
    int fd = safe_open(ctermid(ctty), flags, 0);
    if (fd == -1) { PyErr_Format(PyExc_OSError, "Failed to open controlling terminal: %s (identified with ctermid()) with error: %s", ctty, strerror(errno)); return NULL; }
    struct termios *termios_p = calloc(1, sizeof(struct termios));
    if (!termios_p) return PyErr_NoMemory();
    if (tcgetattr(fd, termios_p) != 0) { free(termios_p); PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    if (!put_tty_in_raw_mode(fd, termios_p, read_with_timeout != 0, optional_actions)) { free(termios_p); return NULL; }
    return Py_BuildValue("iN", fd, PyLong_FromVoidPtr(termios_p));
}

#define TTY_ARGS \
    PyObject *tp; int fd; int optional_actions = TCSAFLUSH; \
    if (!PyArg_ParseTuple(args, "iO!|i", &fd, &PyLong_Type, &tp, &optional_actions)) return NULL; \
    struct termios *termios_p = PyLong_AsVoidPtr(tp);

static PyObject*
normal_tty(PyObject *self UNUSED, PyObject *args) {
    TTY_ARGS
    if (tcsetattr(fd, optional_actions, termios_p) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    Py_RETURN_NONE;
}

static PyObject*
raw_tty(PyObject *self UNUSED, PyObject *args) {
    TTY_ARGS
    if (!put_tty_in_raw_mode(fd, termios_p, false, optional_actions)) return NULL;
    Py_RETURN_NONE;
}


static PyObject*
close_tty(PyObject *self UNUSED, PyObject *args) {
    TTY_ARGS
    tcsetattr(fd, optional_actions, termios_p);  // deliberately ignore failure
    free(termios_p);
    safe_close(fd, __FILE__, __LINE__);
    Py_RETURN_NONE;
}

#undef TTY_ARGS

static PyObject*
py_shm_open(PyObject UNUSED *self, PyObject *args) {
    char *name;
    int flags, mode = 0600;
    if (!PyArg_ParseTuple(args, "si|i", &name, &flags, &mode)) return NULL;
    long fd = safe_shm_open(name, flags, mode);
    if (fd < 0) return PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError, PyTuple_GET_ITEM(args, 0));
    return PyLong_FromLong(fd);
}

static PyObject*
py_shm_unlink(PyObject UNUSED *self, PyObject *args) {
    char *name;
    if (!PyArg_ParseTuple(args, "s", &name)) return NULL;
    if (shm_unlink(name) != 0) return PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError, PyTuple_GET_ITEM(args, 0));
    Py_RETURN_NONE;
}

static PyObject*
wcwidth_wrap(PyObject UNUSED *self, PyObject *chr) {
    return PyLong_FromLong(wcwidth_std(char_props_for(PyLong_AsLong(chr))));
}

static PyObject*
locale_is_valid(PyObject *self UNUSED, PyObject *args) {
    char *name;
    if (!PyArg_ParseTuple(args, "s", &name)) return NULL;
    locale_t test_locale = newlocale(LC_ALL_MASK, name, NULL);
    if (!test_locale) { Py_RETURN_FALSE; }
    freelocale(test_locale);
    Py_RETURN_TRUE;
}

#include "docs_ref_map_generated.h"

static PyObject*
get_docs_ref_map(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyBytes_FromStringAndSize(docs_ref_map, sizeof(docs_ref_map));
}

static PyObject*
wrapped_kittens(PyObject *self UNUSED, PyObject *args UNUSED) {
    static const char *wrapped_kitten_names = WRAPPED_KITTENS;
    PyObject *ans = PyUnicode_FromString(wrapped_kitten_names);
    if (ans == NULL) return NULL;
    PyObject *s = PyUnicode_Split(ans, NULL, -1);
    Py_DECREF(ans);
    return s;
}

static PyObject*
expand_ansi_c_escapes(PyObject *self UNUSED, PyObject *src) {
    enum { NORMAL, PREV_ESC, HEX_DIGIT, OCT_DIGIT, CONTROL_CHAR } state = NORMAL;
    if (PyUnicode_READY(src) != 0) return NULL;
    int max_num_hex_digits = 0, hex_digit_idx = 0;
    char hex_digits[16];
    Py_ssize_t idx = 0, dest_idx = 0;
    PyObject *dest = PyUnicode_New(PyUnicode_GET_LENGTH(src)*2, 1114111);
    if (dest == NULL) return NULL;
    const int kind = PyUnicode_KIND(src), dest_kind = PyUnicode_KIND(dest);
    const void *data = PyUnicode_DATA(src), *dest_data = PyUnicode_DATA(dest);
#define w(ch) { PyUnicode_WRITE(dest_kind, dest_data, dest_idx, ch); dest_idx++; }
#define write_digits(base) { hex_digits[hex_digit_idx] = 0; if (hex_digit_idx > 0) w(strtol(hex_digits, NULL, base)); hex_digit_idx = 0; state = NORMAL; }
#define add_digit(base) { hex_digits[hex_digit_idx++] = ch; if (idx >= PyUnicode_GET_LENGTH(src)) write_digits(base); }
    START_ALLOW_CASE_RANGE
    while (idx < PyUnicode_GET_LENGTH(src)) {
        Py_UCS4 ch = PyUnicode_READ(kind, data, idx); idx++;
        switch(state) {
            case NORMAL: {
                if (ch == '\\' && idx < PyUnicode_GET_LENGTH(src)) {
                    state = PREV_ESC;
                    continue;
                }
                w(ch);
            } break;
            case CONTROL_CHAR: w(ch & 0x1f); state = NORMAL; break;
            case HEX_DIGIT: {
                if (hex_digit_idx < max_num_hex_digits && (('0' <= ch && ch <= '9') || ('a' <= ch && ch <= 'f') || ('A' <= ch && ch <= 'F'))) add_digit(16)
                else { write_digits(16); idx--; }
            }; break;
            case OCT_DIGIT: {
                if ('0' <= ch && ch <= '7' && hex_digit_idx < max_num_hex_digits) add_digit(16)
                else { write_digits(8); idx--; }
            }; break;
            case PREV_ESC: {
                state = NORMAL;
                switch(ch) {
                    default: w('\\'); w(ch); break;
                    case 'a': w(7); break;
                    case 'b': w(8); break;
                    case 'c': if (idx < PyUnicode_GET_LENGTH(src)) {state = CONTROL_CHAR;} else {w('\\'); w(ch);}; break;
                    case 'e': case 'E': w(27); break;
                    case 'f': w(12); break;
                    case 'n': w(10); break;
                    case 'r': w(13); break;
                    case 't': w(9); break;
                    case 'v': w(11); break;
                    case 'x': max_num_hex_digits = 2; hex_digit_idx = 0; state = HEX_DIGIT; break;
                    case 'u': max_num_hex_digits = 4; hex_digit_idx = 0; state = HEX_DIGIT; break;
                    case 'U': max_num_hex_digits = 8; hex_digit_idx = 0; state = HEX_DIGIT; break;
                    case '0' ... '7': max_num_hex_digits = 3; hex_digits[0] = ch; hex_digit_idx = 1; state = OCT_DIGIT; break;
                    case '\\': w('\\'); break;
                    case '?': w('?'); break;
                    case '"': w('"'); break;
                    case '\'': w('\''); break;
                }
            } break;
        }
    }
#undef add_digit
#undef write_digits
#undef w
    END_ALLOW_CASE_RANGE
    PyObject *ans = PyUnicode_FromKindAndData(dest_kind, dest_data, dest_idx);
    Py_DECREF(dest);
    return ans;
}

START_ALLOW_CASE_RANGE
static PyObject*
c0_replace_bytes(const char *input_data, Py_ssize_t input_sz) {
    RAII_PyObject(ans, PyBytes_FromStringAndSize(NULL, input_sz * 3));
    if (!ans) return NULL;
    char *output = PyBytes_AS_STRING(ans);
    char buf[4];
    Py_ssize_t j = 0;
    for (Py_ssize_t i = 0; i < input_sz; i++) {
        const char x = input_data[i];
        switch (x) {
            case C0_EXCEPT_NL_SPACE_TAB: {
                const uint32_t ch = 0x2400 + x;
                const unsigned sz = encode_utf8(ch, buf);
                for (unsigned c = 0; c < sz; c++, j++) output[j] = buf[c];
            } break;
            default:
                output[j++] = x; break;
        }
    }
    if (_PyBytes_Resize(&ans, j) != 0) return NULL;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
c0_replace_unicode(PyObject *input) {
    RAII_PyObject(ans, PyUnicode_New(PyUnicode_GET_LENGTH(input), 1114111));
    if (!ans) return NULL;
    void *input_data = PyUnicode_DATA(input);
    int input_kind = PyUnicode_KIND(input);
    void *output_data = PyUnicode_DATA(ans);
    int output_kind = PyUnicode_KIND(ans);
    Py_UCS4 maxchar = 0;
    bool changed = false;
    for (Py_ssize_t i = 0; i < PyUnicode_GET_LENGTH(input); i++) {
        Py_UCS4 ch = PyUnicode_READ(input_kind, input_data, i);
        switch(ch) { case C0_EXCEPT_NL_SPACE_TAB: ch += 0x2400; changed = true; }
        if (ch > maxchar) maxchar = ch;
        PyUnicode_WRITE(output_kind, output_data, i, ch);
    }
    if (!changed) { Py_INCREF(input); return input; }
    if (maxchar > 65535) { Py_INCREF(ans); return ans; }
    RAII_PyObject(ans2, PyUnicode_New(PyUnicode_GET_LENGTH(ans), maxchar));
    if (!ans2) return NULL;
    if (PyUnicode_CopyCharacters(ans2, 0, ans, 0, PyUnicode_GET_LENGTH(ans)) == -1) return NULL;
    Py_INCREF(ans2); return ans2;
}
END_ALLOW_CASE_RANGE

static PyObject*
replace_c0_codes_except_nl_space_tab(PyObject *self UNUSED, PyObject *obj) {
    if (PyUnicode_Check(obj)) {
        return c0_replace_unicode(obj);
    } else if (PyBytes_Check(obj)) {
        return c0_replace_bytes(PyBytes_AS_STRING(obj), PyBytes_GET_SIZE(obj));
    } else if (PyMemoryView_Check(obj)) {
        Py_buffer *buf = PyMemoryView_GET_BUFFER(obj);
        return c0_replace_bytes(buf->buf, buf->len);
    } else if (PyByteArray_Check(obj)) {
        return c0_replace_bytes(PyByteArray_AS_STRING(obj), PyByteArray_GET_SIZE(obj));
    } else {
        PyErr_SetString(PyExc_TypeError, "Input must be bytes, memoryview, bytearray or unicode");
        return NULL;
    }
}


static PyObject*
find_in_memoryview(PyObject *self UNUSED, PyObject *args) {
    unsigned char q;
    RAII_PY_BUFFER(view);
    if (!PyArg_ParseTuple(args, "y*b", &view, &q)) return NULL;
    const char *buf = view.buf, *p = memchr(buf, q, view.len);
    Py_ssize_t ans = -1;
    if (p) ans = p - buf;
    return PyLong_FromSsize_t(ans);
}

#include "terminfo.h"

static PyObject*
py_terminfo_data(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyBytes_FromStringAndSize((const char*)terminfo_data, arraysz(terminfo_data));
}

static PyObject*
py_monotonic(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyFloat_FromDouble(monotonic_t_to_s_double(monotonic()));
}

static PyObject*
py_timed_debug_print(PyObject *self UNUSED, PyObject *args) {
    const char *payload; Py_ssize_t sz;
    if (!PyArg_ParseTuple(args, "s#", &payload, &sz)) return NULL;
    const char *fmt = "%.*s";
    if (sz && payload[sz-1] == '\n') { fmt = "%.*s\n"; sz--; }
    timed_debug_print(fmt, sz, payload);
    Py_RETURN_NONE;
}

static PyObject*
py_run_atexit_cleanup_functions(PyObject *self UNUSED, PyObject *args UNUSED) {
    run_at_exit_cleanup_functions();
    Py_RETURN_NONE;
}

static PyObject*
py_char_props_for(PyObject *self UNUSED, PyObject *ch) {
    if (!PyUnicode_Check(ch) || PyUnicode_GET_LENGTH(ch) != 1) { PyErr_SetString(PyExc_TypeError, "must supply a single character"); return NULL; }
    char_type c = PyUnicode_READ_CHAR(ch, 0);
    CharProps cp = char_props_for(c);
#define B(x) #x, cp.x ? Py_True : Py_False
    return Py_BuildValue("{si sO sB sB ss sO sO}",
        "width", wcwidth_std(cp), B(is_extended_pictographic), "grapheme_break", cp.grapheme_break,
        "indic_conjunct_break", cp.indic_conjunct_break, "category", char_category(cp), B(is_emoji), B(is_emoji_presentation_base)
    );
#undef B
}

static PyObject*
expanduser(PyObject *self UNUSED, PyObject *path) {
    if (!PyUnicode_Check(path)) { PyErr_SetString(PyExc_TypeError, "path must a string"); return NULL; }
    char buf[PATH_MAX + 1];
    expand_tilde(PyUnicode_AsUTF8(path), buf, arraysz(buf));
    return PyUnicode_FromString(buf);
}

static PyObject*
abspath(PyObject *self UNUSED, PyObject *path) {
    if (!PyUnicode_Check(path)) { PyErr_SetString(PyExc_TypeError, "path must a string"); return NULL; }
    char buf[PATH_MAX + 1];
    lexical_absolute_path(PyUnicode_AsUTF8(path), buf, arraysz(buf));
    return PyUnicode_FromString(buf);
}

static PyObject*
read_file(PyObject *self UNUSED, PyObject *path) {
    if (!PyUnicode_Check(path)) { PyErr_SetString(PyExc_TypeError, "path must a string"); return NULL; }
    size_t sz;
    char *result = read_full_file(PyUnicode_AsUTF8(path), &sz);
    if (!result) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    PyObject *ans = PyBytes_FromStringAndSize(result, sz);
    free(result);
    return ans;
}

static PyObject*
py_makedirs(PyObject *self UNUSED, PyObject *args) {
    int mode = 0755; const char *p;
    if (!PyArg_ParseTuple(args, "s|i", &p, &mode)) return NULL;
    if (!makedirs(p, mode)) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    Py_RETURN_NONE;
}

static PyObject*
py_get_config_dir(PyObject *self UNUSED, PyObject *args UNUSED) {
    char buf[PATH_MAX];
    if (get_config_dir(buf, PATH_MAX)) return PyUnicode_FromString(buf);
    return PyUnicode_FromString("");
}

#include "launcher/cli-parser.h"

static PyMethodDef module_methods[] = {
    METHODB(replace_c0_codes_except_nl_space_tab, METH_O),
    METHODB(read_file, METH_O),
    {"parse_cli_from_spec", parse_cli_from_python_spec, METH_VARARGS, ""},
    {"wcwidth", (PyCFunction)wcwidth_wrap, METH_O, ""},
    {"expanduser", (PyCFunction)expanduser, METH_O, ""},
    {"abspath", (PyCFunction)abspath, METH_O, ""},
    {"expand_ansi_c_escapes", (PyCFunction)expand_ansi_c_escapes, METH_O, ""},
    {"get_docs_ref_map", (PyCFunction)get_docs_ref_map, METH_NOARGS, ""},
    {"get_config_dir", (PyCFunction)py_get_config_dir, METH_NOARGS, ""},
    {"wcswidth", (PyCFunction)wcswidth_std, METH_O, ""},
    {"open_tty", open_tty, METH_VARARGS, ""},
    {"makedirs", py_makedirs, METH_VARARGS, ""},
    {"normal_tty", normal_tty, METH_VARARGS, ""},
    {"raw_tty", raw_tty, METH_VARARGS, ""},
    {"close_tty", close_tty, METH_VARARGS, ""},
    {"set_iutf8_fd", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
    {"base64_encode", (PyCFunction)(void (*) (void))(pybase64_encode), METH_FASTCALL, ""},
    {"base64_encode_into", (PyCFunction)base64_encode_into, METH_VARARGS, ""},
    {"base64_decode", (PyCFunction)(void (*) (void))(pybase64_decode), METH_O, ""},
    {"base64_decode_into", (PyCFunction)base64_decode_into, METH_VARARGS, ""},
    {"char_props_for", py_char_props_for, METH_O, ""},
    {"split_into_graphemes", (PyCFunction)split_into_graphemes, METH_O, ""},
    {"thread_write", (PyCFunction)cm_thread_write, METH_VARARGS, ""},
    {"locale_is_valid", (PyCFunction)locale_is_valid, METH_VARARGS, ""},
    {"shm_open", (PyCFunction)py_shm_open, METH_VARARGS, ""},
    {"shm_unlink", (PyCFunction)py_shm_unlink, METH_VARARGS, ""},
    {"wrapped_kitten_names", (PyCFunction)wrapped_kittens, METH_NOARGS, ""},
    {"terminfo_data", (PyCFunction)py_terminfo_data, METH_NOARGS, ""},
    {"monotonic", (PyCFunction)py_monotonic, METH_NOARGS, ""},
    {"timed_debug_print", (PyCFunction)py_timed_debug_print, METH_VARARGS, ""},
    {"find_in_memoryview", (PyCFunction)find_in_memoryview, METH_VARARGS, ""},
    {"run_at_exit_cleanup_functions", (PyCFunction)py_run_atexit_cleanup_functions, METH_NOARGS, ""},
#ifdef __APPLE__
    METHODB(user_cache_dir, METH_NOARGS),
    METHODB(process_group_map, METH_NOARGS),
#endif
#ifdef WITH_PROFILER
    {"start_profiler", (PyCFunction)start_profiler, METH_VARARGS, ""},
    {"stop_profiler", (PyCFunction)stop_profiler, METH_NOARGS, ""},
#endif
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static void
free_fast_data_types_module(void *m UNUSED) {
    run_at_exit_cleanup_functions();
}

static struct PyModuleDef module = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "fast_data_types",   /* name of module */
    .m_doc = NULL,
    .m_size = -1,
    .m_methods = module_methods,
    .m_free = free_fast_data_types_module,
};


extern int init_LineBuf(PyObject *);
extern int init_HistoryBuf(PyObject *);
extern int init_Cursor(PyObject *);
extern int init_Shlex(PyObject *);
extern int init_Parser(PyObject *);
extern int init_DiskCache(PyObject *);
extern bool init_child_monitor(PyObject *);
extern int init_Line(PyObject *);
extern int init_ColorProfile(PyObject *);
extern int init_Screen(PyObject *);
extern bool init_animations(PyObject*);
extern bool init_fontconfig_library(PyObject*);
extern bool init_crypto_library(PyObject*);
extern bool init_desktop(PyObject*);
extern bool init_fonts(PyObject*);
extern bool init_glfw(PyObject *m);
extern bool init_child(PyObject *m);
extern bool init_state(PyObject *module);
extern bool init_keys(PyObject *module);
extern bool init_graphics(PyObject *module);
extern bool init_shaders(PyObject *module);
extern bool init_mouse(PyObject *module);
extern bool init_kittens(PyObject *module);
extern bool init_logging(PyObject *module);
extern bool init_png_reader(PyObject *module);
extern bool init_utmp(PyObject *module);
extern bool init_loop_utils(PyObject *module);
extern bool init_systemd_module(PyObject *module);
#ifdef __APPLE__
extern int init_CoreText(PyObject *);
extern bool init_cocoa(PyObject *module);
extern bool init_macos_process_info(PyObject *module);
#else
extern bool init_freetype_library(PyObject*);
extern bool init_freetype_render_ui_text(PyObject*);
#endif

static unsigned
shift_to_first_set_bit(CellAttrs x) {
    unsigned num_of_bits = 8 * sizeof(x.val);
    unsigned ans = 0;
    while (num_of_bits--) {
        if (x.val & 1) return ans;
        x.val >>= 1;
        ans++;
    }
    return ans;
}


EXPORTED PyMODINIT_FUNC
PyInit_fast_data_types(void) {
    PyObject *m;
    m = PyModule_Create(&module);
    if (m == NULL) return NULL;
    init_monotonic();

    if (!init_logging(m)) return NULL;
    if (!init_LineBuf(m)) return NULL;
    if (!init_HistoryBuf(m)) return NULL;
    if (!init_Line(m)) return NULL;
    if (!init_Cursor(m)) return NULL;
    if (!init_Shlex(m)) return NULL;
    if (!init_Parser(m)) return NULL;
    if (!init_DiskCache(m)) return NULL;
    if (!init_child_monitor(m)) return NULL;
    if (!init_ColorProfile(m)) return NULL;
    if (!init_Screen(m)) return NULL;
    if (!init_glfw(m)) return NULL;
    if (!init_child(m)) return NULL;
    if (!init_state(m)) return NULL;
    if (!init_keys(m)) return NULL;
    if (!init_graphics(m)) return NULL;
    if (!init_shaders(m)) return NULL;
    if (!init_mouse(m)) return NULL;
    if (!init_kittens(m)) return NULL;
    if (!init_png_reader(m)) return NULL;
#ifdef __APPLE__
    if (!init_macos_process_info(m)) return NULL;
    if (!init_CoreText(m)) return NULL;
    if (!init_cocoa(m)) return NULL;
#else
    if (!init_freetype_library(m)) return NULL;
    if (!init_fontconfig_library(m)) return NULL;
    if (!init_desktop(m)) return NULL;
    if (!init_freetype_render_ui_text(m)) return NULL;
#endif
    if (!init_fonts(m)) return NULL;
    if (!init_utmp(m)) return NULL;
    if (!init_loop_utils(m)) return NULL;
    if (!init_crypto_library(m)) return NULL;
    if (!init_systemd_module(m)) return NULL;
    if (!init_animations(m)) return NULL;

    CellAttrs a;
#define s(name, attr) { a.val = 0; a.attr = 1; PyModule_AddIntConstant(m, #name, shift_to_first_set_bit(a)); }
    s(BOLD, bold); s(ITALIC, italic); s(REVERSE, reverse); s(MARK, mark);
    s(STRIKETHROUGH, strike); s(DIM, dim); s(DECORATION, decoration);
#undef s
    PyModule_AddIntConstant(m, "MARK_MASK", MARK_MASK);
    PyModule_AddIntConstant(m, "DECORATION_MASK", DECORATION_MASK);
    PyModule_AddStringMacro(m, ERROR_PREFIX);
#ifdef KITTY_VCS_REV
    PyModule_AddStringMacro(m, KITTY_VCS_REV);
#endif
    PyModule_AddIntMacro(m, CURSOR_BLOCK);
    PyModule_AddIntMacro(m, CURSOR_BEAM);
    PyModule_AddIntMacro(m, CURSOR_UNDERLINE);
    PyModule_AddIntMacro(m, CURSOR_HOLLOW);
    PyModule_AddIntMacro(m, NO_CURSOR_SHAPE);
    PyModule_AddIntMacro(m, DECAWM);
    PyModule_AddIntMacro(m, DECCOLM);
    PyModule_AddIntMacro(m, DECOM);
    PyModule_AddIntMacro(m, IRM);
    PyModule_AddIntMacro(m, FILE_TRANSFER_CODE);
    PyModule_AddIntMacro(m, ESC_CSI);
    PyModule_AddIntMacro(m, ESC_OSC);
    PyModule_AddIntMacro(m, ESC_APC);
    PyModule_AddIntMacro(m, ESC_DCS);
    PyModule_AddIntMacro(m, ESC_PM);
    PyModule_AddIntMacro(m, TEXT_SIZE_CODE);
#ifdef __APPLE__
    // Apple says its SHM_NAME_MAX but SHM_NAME_MAX is not actually declared in typical CrApple style.
    // This value is based on experimentation and from qsharedmemory.cpp in Qt
    PyModule_AddIntConstant(m, "SHM_NAME_MAX", 30);
#else
    // FreeBSD's man page says this is 1023. Linux says its PATH_MAX.
    PyModule_AddIntConstant(m, "SHM_NAME_MAX", MIN(1023, PATH_MAX));
#endif

    if (PyType_Ready(&StreamingBase64Decoder_Type) < 0) return NULL;
    if (PyModule_AddObject(m, "StreamingBase64Decoder", (PyObject *) &StreamingBase64Decoder_Type) < 0) return NULL;
    if (PyType_Ready(&StreamingBase64Encoder_Type) < 0) return NULL;
    if (PyModule_AddObject(m, "StreamingBase64Encoder", (PyObject *) &StreamingBase64Encoder_Type) < 0) return NULL;

    return m;
}
