/*
 * kittens.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

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
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_kittens(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
