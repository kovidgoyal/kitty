/*
 * kittens.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "monotonic.h"

#define CMD_BUF_SZ 2048


static bool
append_buf(char buf[CMD_BUF_SZ], size_t *pos, PyObject *ans) {
    if (*pos) {
        PyObject *bytes = PyBytes_FromStringAndSize(buf, *pos);
        if (!bytes) { PyErr_NoMemory(); return false; }
        int ret = PyList_Append(ans, bytes);
        Py_CLEAR(bytes);
        if (ret != 0) return false;
        *pos = 0;
    }
    return true;
}

static bool
add_char(char buf[CMD_BUF_SZ], size_t *pos, char ch, PyObject *ans) {
    if (*pos >= CMD_BUF_SZ) {
        if (!append_buf(buf, pos, ans)) return false;
    }
    buf[*pos] = ch;
    *pos += 1;
    return true;
}

static bool
read_response(int fd, monotonic_t timeout, PyObject *ans) {
    static char buf[CMD_BUF_SZ];
    size_t pos = 0;
    enum ReadState {START, STARTING_ESC, P, AT, K, I, T, T2, Y, HYPHEN, C, M, BODY, TRAILING_ESC};
    enum ReadState state = START;
    char ch;
    monotonic_t end_time = monotonic() + timeout;
    while(monotonic() <= end_time) {
        ssize_t len = read(fd, &ch, 1);
        if (len == 0) continue;
        if (len < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            PyErr_SetFromErrno(PyExc_OSError);
            return false;
        }
        end_time = monotonic() + timeout;
        switch(state) {
            case START:
                if (ch == 0x1b) state = STARTING_ESC;
                if (ch == 0x03) { PyErr_SetString(PyExc_KeyboardInterrupt, "User pressed Ctrl+C"); return false; }
                break;
#define CASE(curr, q, next) case curr: state = ch == q ? next : START; break;
            CASE(STARTING_ESC, 'P', P);
            CASE(P, '@', AT);
            CASE(AT, 'k', K);
            CASE(K, 'i', I);
            CASE(I, 't', T);
            CASE(T, 't', T2);
            CASE(T2, 'y', Y);
            CASE(Y, '-', HYPHEN);
            CASE(HYPHEN, 'c', C);
            CASE(C, 'm', M);
            CASE(M, 'd', BODY);
            case BODY:
                if (ch == 0x1b) { state = TRAILING_ESC; }
                else {
                    if (!add_char(buf, &pos, ch, ans)) return false;
                }
                break;
            case TRAILING_ESC:
                if (ch == '\\') return append_buf(buf, &pos, ans);
                if (!add_char(buf, &pos, 0x1b, ans)) return false;
                if (!add_char(buf, &pos, ch, ans)) return false;
                state = BODY;
                break;
        }
    }
    PyErr_SetString(PyExc_TimeoutError,
            "Timed out while waiting to read command response."
            " Make sure you are running this command from within the kitty terminal."
            " If you want to run commands from outside, then you have to setup a"
            " socket with the --listen-on command line flag.");
    return false;
}

static PyObject*
read_command_response(PyObject *self UNUSED, PyObject *args) {
    double timeout;
    int fd;
    PyObject *ans;
    if (!PyArg_ParseTuple(args, "idO!", &fd, &timeout, &PyList_Type, &ans)) return NULL;
    if (!read_response(fd, s_double_to_monotonic_t(timeout), ans)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
parse_input_from_terminal(PyObject *self UNUSED, PyObject *args) {
    enum State { NORMAL, ESC, CSI, ST, ESC_ST };
    enum State state = NORMAL;
    PyObject *uo, *text_callback, *dcs_callback, *csi_callback, *osc_callback, *pm_callback, *apc_callback, *callback;
    int inbp = 0;
    if (!PyArg_ParseTuple(args, "OOOOOOUp", &text_callback, &dcs_callback, &csi_callback, &osc_callback, &pm_callback, &apc_callback, &uo, &inbp)) return NULL;
    Py_ssize_t sz = PyUnicode_GET_LENGTH(uo), pos = 0, start = 0, count = 0, consumed = 0;
    callback = text_callback;
    int kind = PyUnicode_KIND(uo);
    void *data = PyUnicode_DATA(uo);
    bool in_bracketed_paste_mode = inbp != 0;
#define CALL(cb, s_, num_) {\
    PyObject *fcb = cb; \
    Py_ssize_t s = s_, num = num_; \
    if (in_bracketed_paste_mode && fcb != text_callback) { \
        fcb = text_callback; num += 2; s -= 2; \
    } \
    if (num > 0) { \
        PyObject *ret = PyObject_CallFunction(fcb, "N", PyUnicode_Substring(uo, s, s + num));  \
        if (ret == NULL) return NULL; \
        Py_DECREF(ret); \
    } \
    consumed = s_ + num_; \
    count = 0; \
}
    START_ALLOW_CASE_RANGE;
    while (pos < sz) {
        Py_UCS4 ch = PyUnicode_READ(kind, data, pos);
        switch(state) {
            case NORMAL:
                if (ch == 0x1b) {
                    state = ESC;
                    CALL(text_callback, start, count);
                    start = pos;
                } else count++;
                break;
            case ESC:
                start = pos;
                count = 0;
                switch(ch) {
                    case 'P':
                        state = ST; callback = dcs_callback; break;
                    case '[':
                        state = CSI; callback = csi_callback; break;
                    case ']':
                        state = ST; callback = osc_callback; break;
                    case '^':
                        state = ST; callback = pm_callback; break;
                    case '_':
                        state = ST; callback = apc_callback; break;
                    default:
                        state = NORMAL; break;
                }
                break;
            case CSI:
                count++;
                switch (ch) {
                    case 'a' ... 'z':
                    case 'A' ... 'Z':
                    case '@':
                    case '`':
                    case '{':
                    case '|':
                    case '}':
                    case '~':
#define IBP(w)  ch == '~' && PyUnicode_READ(kind, data, start + 1) == '2' && PyUnicode_READ(kind, data, start + 2) == '0' && PyUnicode_READ(kind, data, start + 3) == w
                        if (IBP('1')) in_bracketed_paste_mode = false;
                        CALL(callback, start + 1, count);
                        if (IBP('0')) in_bracketed_paste_mode = true;
#undef IBP
                        state = NORMAL;
                        start = pos + 1;
                        break;
                }
                break;
            case ESC_ST:
                if (ch == '\\') {
                    CALL(callback, start + 1, count);
                    state = NORMAL; start = pos + 1;
                    consumed += 2;
                } else count += 2;
                break;
            case ST:
                if (ch == 0x1b) { state = ESC_ST; }
                else count++;
                break;
        }
        pos++;
    }
    if (state == NORMAL && count > 0) CALL(text_callback, start, count);
    return PyUnicode_Substring(uo, consumed, sz);
    END_ALLOW_CASE_RANGE;
#undef CALL
}

static PyMethodDef module_methods[] = {
    METHODB(parse_input_from_terminal, METH_VARARGS),
    METHODB(read_command_response, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_kittens(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
