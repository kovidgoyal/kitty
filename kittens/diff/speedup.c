/*
 * speedup.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static PyObject*
changed_center(PyObject *self UNUSED, PyObject *args) {
    unsigned int prefix_count = 0, suffix_count = 0;
    PyObject *lp, *rp;
    if (!PyArg_ParseTuple(args, "UU", &lp, &rp)) return NULL;
    const size_t left_len = PyUnicode_GET_LENGTH(lp), right_len = PyUnicode_GET_LENGTH(rp);

#define R(which, index) PyUnicode_READ(PyUnicode_KIND(which), PyUnicode_DATA(which), index)
    while(prefix_count < MIN(left_len, right_len)) {
        if (R(lp, prefix_count) != R(rp, prefix_count)) break;
        prefix_count++;
    }
    if (left_len && right_len && prefix_count < MIN(left_len, right_len)) {
        while(suffix_count < MIN(left_len - prefix_count, right_len - prefix_count)) {
            if(R(lp, left_len - 1 - suffix_count) != R(rp, right_len - 1 - suffix_count)) break;
            suffix_count++;
        }
    }
#undef R
    return Py_BuildValue("II", prefix_count, suffix_count);
}

typedef struct {
    unsigned int start_pos, end_pos, current_pos;
    PyObject *start_code, *end_code;
} Segment;

typedef struct {
    Segment sg;
    unsigned int num, pos;
} SegmentPointer;

static const Segment EMPTY_SEGMENT = { .current_pos = UINT_MAX };

static inline bool
convert_segment(PyObject *highlight, Segment *dest) {
    PyObject *val = NULL;
#define I
#define A(x, d, c) { \
    val = PyObject_GetAttrString(highlight, #x); \
    if (val == NULL) return false; \
    dest->d = c(val); Py_DECREF(val); \
}
    A(start, start_pos, PyLong_AsUnsignedLong);
    A(end, end_pos, PyLong_AsUnsignedLong);
    dest->current_pos = dest->start_pos;
    A(start_code, start_code, I);
    A(end_code, end_code, I);
    if (!PyUnicode_Check(dest->start_code)) { PyErr_SetString(PyExc_TypeError, "start_code is not a string"); return false; }
    if (!PyUnicode_Check(dest->end_code)) { PyErr_SetString(PyExc_TypeError, "end_code is not a string"); return false; }
#undef A
#undef I
    return true;
}

static inline bool
next_segment(SegmentPointer *s, PyObject *highlights) {
    if (s->pos < s->num) {
        if (!convert_segment(PyList_GET_ITEM(highlights, s->pos), &s->sg)) return false;
        s->pos++;
    } else s->sg.current_pos = UINT_MAX;
    return true;
}

static inline bool
insert_code(PyObject *code, Py_UCS4 *buf, size_t bufsz, unsigned int *buf_pos) {
    unsigned int csz = PyUnicode_GET_LENGTH(code);
    if (*buf_pos + csz >= bufsz) return false;
    for (unsigned int s = 0; s < csz; s++) buf[(*buf_pos)++] = PyUnicode_READ(PyUnicode_KIND(code), PyUnicode_DATA(code), s);
    return true;
}

static inline bool
add_line(Segment *bg_segment, Segment *fg_segment, Py_UCS4 *buf, size_t bufsz, unsigned int *buf_pos, PyObject *ans) {
    bool bg_is_active = bg_segment->current_pos == bg_segment->end_pos, fg_is_active = fg_segment->current_pos == fg_segment->end_pos;
    if (bg_is_active) { if(!insert_code(bg_segment->end_code, buf, bufsz, buf_pos)) return false; }
    if (fg_is_active) { if(!insert_code(fg_segment->end_code, buf, bufsz, buf_pos)) return false; }
    PyObject *wl = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, *buf_pos);
    if (!wl) return false;
    int ret = PyList_Append(ans, wl); Py_DECREF(wl); if (ret != 0) return false;
    *buf_pos = 0;
    if (bg_is_active) { if(!insert_code(bg_segment->start_code, buf, bufsz, buf_pos)) return false; }
    if (fg_is_active) { if(!insert_code(fg_segment->start_code, buf, bufsz, buf_pos)) return false; }
    return true;
}

static PyObject*
split_with_highlights(PyObject *self UNUSED, PyObject *args) {
    PyObject *line, *truncate_points_py, *fg_highlights, *bg_highlight;
    if (!PyArg_ParseTuple(args, "UO!O!O", &line, &PyList_Type, &truncate_points_py, &PyList_Type, &fg_highlights, &bg_highlight)) return NULL;
    PyObject *ans = PyList_New(0);
    if (!ans) return NULL;
    static unsigned int truncate_points[256];
    unsigned int num_truncate_pts = PyList_GET_SIZE(truncate_points_py), truncate_pos = 0, truncate_point;
    for (unsigned int i = 0; i < MIN(num_truncate_pts, arraysz(truncate_points)); i++) {
        truncate_points[i] = PyLong_AsUnsignedLong(PyList_GET_ITEM(truncate_points_py, i));
    }
    SegmentPointer fg_segment = { .sg = EMPTY_SEGMENT, .num = PyList_GET_SIZE(fg_highlights)}, bg_segment = { .sg = EMPTY_SEGMENT };
    if (bg_highlight != Py_None) { if (!convert_segment(bg_highlight, &bg_segment.sg)) { Py_CLEAR(ans); return NULL; }; bg_segment.num = 1; }
#define CHECK_CALL(func, ...) if (!func(__VA_ARGS__)) { Py_CLEAR(ans); if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "line too long"); return NULL; }
    CHECK_CALL(next_segment, &fg_segment, fg_highlights);

#define NEXT_TRUNCATE_POINT truncate_point = (truncate_pos < num_truncate_pts) ? truncate_points[truncate_pos++] : UINT_MAX
    NEXT_TRUNCATE_POINT;

#define INSERT_CODE(x) { CHECK_CALL(insert_code, x, buf, arraysz(buf), &buf_pos); }

#define ADD_LINE CHECK_CALL(add_line, &bg_segment.sg, &fg_segment.sg, buf, arraysz(buf), &buf_pos, ans);

#define ADD_CHAR(x) { \
    buf[buf_pos++] = x; \
    if (buf_pos >= arraysz(buf)) { Py_CLEAR(ans); PyErr_SetString(PyExc_ValueError, "line too long"); return NULL; } \
}
#define CHECK_SEGMENT(sgp, is_fg) { \
    if (i == sgp.sg.current_pos) { \
        INSERT_CODE(sgp.sg.current_pos == sgp.sg.start_pos ? sgp.sg.start_code : sgp.sg.end_code); \
        if (sgp.sg.current_pos == sgp.sg.start_pos) sgp.sg.current_pos = sgp.sg.end_pos; \
        else { \
            if (is_fg) { \
                CHECK_CALL(next_segment, &fg_segment, fg_highlights); \
                if (sgp.sg.current_pos == i) { \
                    INSERT_CODE(sgp.sg.start_code); \
                    sgp.sg.current_pos = sgp.sg.end_pos; \
                } \
            } else sgp.sg.current_pos = UINT_MAX; \
        } \
    }\
}

    const unsigned int line_sz = PyUnicode_GET_LENGTH(line);
    static Py_UCS4 buf[4096];
    unsigned int i = 0, buf_pos = 0;
    for (; i < line_sz; i++) {
        if (i == truncate_point) { ADD_LINE; NEXT_TRUNCATE_POINT; }
        CHECK_SEGMENT(bg_segment, false);
        CHECK_SEGMENT(fg_segment, true)
        ADD_CHAR(PyUnicode_READ(PyUnicode_KIND(line), PyUnicode_DATA(line), i));
    }
    if (buf_pos) ADD_LINE;
    return ans;
#undef INSERT_CODE
#undef CHECK_SEGMENT
#undef CHECK_CALL
#undef ADD_CHAR
#undef ADD_LINE
#undef NEXT_TRUNCATE_POINT
}

static PyMethodDef module_methods[] = {
    {"changed_center", (PyCFunction)changed_center, METH_VARARGS, ""},
    {"split_with_highlights", (PyCFunction)split_with_highlights, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "diff_speedup",   /* name of module */
   .m_doc = NULL,
   .m_size = -1,
   .m_methods = module_methods
};

EXPORTED PyMODINIT_FUNC
PyInit_diff_speedup(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;
    return m;
}
