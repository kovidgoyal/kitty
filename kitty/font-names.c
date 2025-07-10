/*
 * font-names.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"

static PyObject*
decode_name_record(PyObject *namerec) {
#define d(x) PyLong_AsUnsignedLong(PyTuple_GET_ITEM(namerec, x))
    unsigned long platform_id = d(0), encoding_id = d(1), language_id = d(2);
#undef d
    const char *encoding = "unicode_escape";
    if ((platform_id == 3 && encoding_id == 1) || platform_id == 0) encoding = "utf-16-be";
    else if (platform_id == 1 && encoding_id == 0 && language_id == 0) encoding = "mac-roman";
    PyObject *b = PyTuple_GET_ITEM(namerec, 3);
    return PyUnicode_Decode(PyBytes_AS_STRING(b), PyBytes_GET_SIZE(b), encoding, "replace");
}


static bool
namerec_matches(PyObject *namerec, unsigned platform_id, unsigned encoding_id, unsigned language_id) {
#define d(x) PyLong_AsUnsignedLong(PyTuple_GET_ITEM(namerec, x))
    return d(0) == platform_id && d(1) == encoding_id && d(2) == language_id;
#undef d
}

static PyObject*
find_matching_namerec(PyObject *namerecs, unsigned platform_id, unsigned encoding_id, unsigned language_id) {
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(namerecs); i++) {
        PyObject *namerec = PyList_GET_ITEM(namerecs, i);
        if (namerec_matches(namerec, platform_id, encoding_id, language_id)) return decode_name_record(namerec);
    }
    return NULL;
}


bool
add_font_name_record(PyObject *table, uint16_t platform_id, uint16_t encoding_id, uint16_t language_id, uint16_t name_id, const char *string, uint16_t string_len) {
    RAII_PyObject(key, PyLong_FromUnsignedLong((unsigned long)name_id));
    if (!key) return false;
    RAII_PyObject(list, PyDict_GetItem(table, key));
    if (list == NULL) {
        list = PyList_New(0);
        if (!list) return false;
        if (PyDict_SetItem(table, key, list) != 0) return false;
    } else Py_INCREF(list);
    RAII_PyObject(value, Py_BuildValue("(H H H y#)", platform_id, encoding_id, language_id, string, (Py_ssize_t)string_len));
    if (!value) return false;
    if (PyList_Append(list, value) != 0) return false;
    return true;
}

PyObject*
get_best_name_from_name_table(PyObject *table, PyObject *name_id) {
    PyObject *namerecs = PyDict_GetItem(table, name_id);
    if (namerecs == NULL) return PyUnicode_FromString("");
    if (PyList_GET_SIZE(namerecs) == 1) return decode_name_record(PyList_GET_ITEM(namerecs, 0));
#define d(...) { PyObject *ans = find_matching_namerec(namerecs, __VA_ARGS__); if (ans != NULL || PyErr_Occurred()) return ans; }
    d(3, 1, 1033);  // Microsoft/Windows/US English
    d(1, 0, 0);     // Mac/Roman/English
    d(0, 6, 0);     // Unicode/SMP/*
    d(0, 4, 0);     // Unicode/SMP/*
    d(0, 3, 0);     // Unicode/BMP/*
    d(0, 2, 0);     // Unicode/10646-BMP/*
    d(0, 1, 0);     // Unicode/1.1/*
#undef d
    return PyUnicode_FromString("");

}

static PyObject*
get_best_name(PyObject *table, unsigned long name_id) {
    RAII_PyObject(id, PyLong_FromUnsignedLong(name_id));
    return get_best_name_from_name_table(table, id);
}

// OpenType tables are big-endian for god knows what reason so need to byteswap
static uint16_t
byteswap(const uint16_t *p) {
    const uint8_t *b = (const uint8_t*)p;
    return (((uint16_t)b[0]) << 8) | b[1];
}

static uint32_t
byteswap32(const uint32_t *val) {
    const uint8_t *p = (const uint8_t*)val;
    return (((uint32_t)p[0]) << 24) | (((uint32_t)p[1]) << 16) | (((uint32_t)p[2]) << 8) | p[3];
}

static double
load_fixed(const uint32_t *p_) {
    uint32_t p = byteswap32(p_);
    static const double denom = 1 << 16;
    return ((int32_t)p) / denom;
}

#define next byteswap(p++)
#define next32 load_fixed(p32++)

PyObject*
read_name_font_table(const uint8_t *table, size_t table_len) {
    if (!table || table_len < 9 * sizeof(uint16_t)) return PyDict_New();
    uint16_t *p = (uint16_t*)table; p++;
    uint16_t num_of_name_records = next, storage_offset = next;
    const uint8_t *storage = table + storage_offset, *slimit = table + table_len;
    if (storage >= slimit) return PyDict_New();
    RAII_PyObject(ans, PyDict_New());
    for (; num_of_name_records > 0 && p + 6 <= (uint16_t*)slimit; num_of_name_records--) {
        uint16_t platform_id = next, encoding_id = next, language_id = next, name_id = next, length = next, offset = next;
        const uint8_t *s = storage + offset;
        if (s + length <= slimit && !add_font_name_record(
            ans, platform_id, encoding_id, language_id, name_id, (const char*)(s), length)) return NULL;
    }
    Py_INCREF(ans);
    return ans;

}

static bool is_digit(char x) { return '0' <= x && x <= '9'; }

static PyObject*
read_cv_feature_table(const uint8_t *table, const uint8_t *limit, PyObject *name_lookup_table) {
    RAII_PyObject(ans, PyDict_New()); if (!ans) return NULL;
    if (limit - table >= 12) {
        uint16_t *p = (uint16_t*)(table + 2);
        uint16_t name_id = next, tooltip_id = next, sample_id = next, num_params = next, first_value_id = next;
        if (name_id) {
            RAII_PyObject(name, get_best_name(name_lookup_table, name_id)); if (!name) return NULL;
            if (PyDict_SetItemString(ans, "name", name) != 0) return NULL;
        }
        if (tooltip_id) {
            RAII_PyObject(tooltip, get_best_name(name_lookup_table, tooltip_id)); if (!tooltip) return NULL;
            if (PyDict_SetItemString(ans, "tooltip", tooltip) != 0) return NULL;
        }
        if (sample_id) {
            RAII_PyObject(sample, get_best_name(name_lookup_table, sample_id)); if (!sample) return NULL;
            if (PyDict_SetItemString(ans, "sample", sample) != 0) return NULL;
        }
        if (num_params && first_value_id) {
            RAII_PyObject(params, PyTuple_New(num_params)); if (!params) return NULL;
            for (uint16_t i = 0; i < num_params; i++) {
                PyObject *pval = get_best_name(name_lookup_table, first_value_id + i); if (!pval) return NULL;
                PyTuple_SET_ITEM(params, i, pval);
            }
            if (PyDict_SetItemString(ans, "params", params) != 0) return NULL;
        }
    }
    Py_INCREF(ans); return ans;
}

static PyObject*
read_ss_feature_table(const uint8_t *table, const uint8_t *limit, PyObject *name_lookup_table) {
    RAII_PyObject(ans, PyDict_New()); if (!ans) return NULL;
    if (limit - table < 4) { Py_INCREF(ans); return ans; }
    uint16_t *p = (uint16_t*)(table + 2);
    uint16_t name_id = next;
    if (name_id) {
        RAII_PyObject(name, get_best_name(name_lookup_table, name_id)); if (!name) return NULL;
        if (PyDict_SetItemString(ans, "name", name) != 0) return NULL;
    }
    Py_INCREF(ans); return ans;
}

bool
read_features_from_font_table(const uint8_t *table, size_t table_len, PyObject *name_lookup_table, PyObject *output) {
    if (table_len < 20) return true;
    const uint16_t *p = (uint16_t*)table;
    const uint8_t *limit = table + table_len;
    uint16_t major_version = next, minor_version = next, script_list_offset = next, feature_list_offset = next;
    (void)major_version; (void)minor_version; (void)script_list_offset;
    const uint8_t *feature_list_table = table + feature_list_offset;
    char tag_buf[5] = {0};
    if (feature_list_table + 2 >= limit) return true;
    p = (uint16_t*)feature_list_table;
    uint16_t feature_count = next;
    const uint8_t *pos = (uint8_t*)p;
    for (uint16_t i = 0; i < feature_count && pos + 6 <= limit; pos += 6, i++) {
        memcpy(tag_buf, pos, 4);
        RAII_PyObject(tag, PyUnicode_FromString(tag_buf));
        if (!tag) return false;
        if (PyDict_Contains(output, tag) == 1) continue;
        if (PyDict_SetItem(output, tag, Py_None) != 0) return false;
        p = (uint16_t*)(pos + 4); uint16_t offset_to_feature_table = next;
        const uint8_t *feature_table = feature_list_table + offset_to_feature_table;
        if (feature_table + 2 > limit) continue;
        p = (uint16_t*)(feature_table); uint16_t offset_to_feature_params_table = next;
        if (tag_buf[0] == 'c' && tag_buf[1] == 'v' && is_digit(tag_buf[2]) && is_digit(tag_buf[3])) {
            if (offset_to_feature_params_table) {
                RAII_PyObject(cv, read_cv_feature_table(feature_table + offset_to_feature_params_table, limit, name_lookup_table));
                if (!cv) return false;
                if (PyDict_SetItem(output, tag, cv) != 0) return false;
            }
        } else if (tag_buf[0] == 's' && tag_buf[1] == 's' && '0' <= tag_buf[2] && tag_buf[2] <= '2' && is_digit(tag_buf[3])) {
            if (offset_to_feature_params_table) {
                RAII_PyObject(ss, read_ss_feature_table(feature_table + offset_to_feature_params_table, limit, name_lookup_table));
                if (!ss) return false;
                if (PyDict_SetItem(output, tag, ss) != 0) return false;
            }
        }
    }
    return true;
}

bool
read_STAT_font_table(const uint8_t *table, size_t table_len, PyObject *name_lookup_table, PyObject *output) {
    uint16_t elided_fallback_name_id = 0;
    RAII_PyObject(design_axes, PyTuple_New(0));
    RAII_PyObject(multi_axis_styles, PyTuple_New(0));
    if (!design_axes || !multi_axis_styles) return false;
    if (table_len < 20) goto ok;
    const uint16_t *p = (uint16_t*)table;
    uint16_t major_version = next, minor_version = next, size_of_design_axis_entry = next, count_of_design_axis_entries = next;
    const uint32_t *p32 = (uint32_t*)p;
    uint32_t offset_to_start_of_design_axes_entries = byteswap32(p32++);
    p = (uint16_t*)p32;
    uint16_t count_of_axis_value_entries = next;
    p32 = (uint32_t*)p;
    uint32_t offset_to_start_of_axis_value_entries = byteswap32(p32++);
    p = (uint16_t*)p32;
    elided_fallback_name_id = next;
    if (major_version == 1 && minor_version < 1) elided_fallback_name_id = 0;
    const uint8_t *table_limit = table + table_len;
    size_t count = 0;
    if (_PyTuple_Resize(&design_axes, count_of_design_axis_entries) == -1) return false;
    for (
        const uint8_t *pos = table + offset_to_start_of_design_axes_entries;
        pos + size_of_design_axis_entry <= table_limit && count < count_of_design_axis_entries;
        pos += size_of_design_axis_entry, count++
    ) {
        p = (uint16_t*)(pos + 4);
        uint16_t name_id = next, ordering = next;
        PyObject *rec = Py_BuildValue("{ss# sN sH sN}", "tag", (char*)pos, 4, "name", get_best_name(name_lookup_table, name_id), "ordering", ordering, "values", PyList_New(0));
        if (!rec) return false;
        PyTuple_SET_ITEM(design_axes, count, rec);
    }
    if (_PyTuple_Resize(&design_axes, count) == -1) return false;
    count = 0;
    const uint8_t *start_of_axis_values_offsets_array = table + offset_to_start_of_axis_value_entries;
    Py_ssize_t i = 0;
    if (_PyTuple_Resize(&multi_axis_styles, count_of_axis_value_entries) == -1) return false;
    for (
        const uint8_t *pos = start_of_axis_values_offsets_array;
        pos + 2 <= table_limit && count < count_of_axis_value_entries;
        pos += 2, count++
    ) {
        p = (uint16_t*)pos;
        uint16_t offset = next;
        const uint8_t *start_of_axis_values_table = start_of_axis_values_offsets_array + offset;
        if (start_of_axis_values_table + 12 > table_limit) continue;
        p = (uint16_t*)(start_of_axis_values_table);
        uint16_t format = next, axis_index = next, flags = next, value_name_id = next;
        p32 = (uint32_t*)p;
#define app(fmt, ...) { \
    RAII_PyObject(v, Py_BuildValue("{sH sH sN " fmt "}", \
                "format", format, "flags", flags, "name", get_best_name(name_lookup_table, value_name_id), __VA_ARGS__)); \
    if (!v) return false; \
    PyObject *l = PyDict_GetItemString(PyTuple_GET_ITEM(design_axes, axis_index), "values"); \
    if (l && PyList_Append(l, v) != 0) return false;  \
}
        switch(format) {
            case 1: if (p32 + 1 <= (uint32_t*)table_limit && axis_index < PyTuple_GET_SIZE(design_axes)) {
                const double value = next32; app("sd", "value", value);
            } break;
            case 2: if (p32 + 3 <= (uint32_t*)table_limit && axis_index < PyTuple_GET_SIZE(design_axes)) {
                const double value = next32, minimum = next32, maximum = next32;
                app("sd sd sd", "value", value, "minimum", minimum, "maximum", maximum);
            } break;
            case 3: if (p32 + 2 <= (uint32_t*)table_limit && axis_index < PyTuple_GET_SIZE(design_axes)) {
                const double value = next32, linked_value = next32;
                app("sd sd", "value", value, "linked_value", linked_value);
            } break;
            case 4: if ((uint8_t*)(p) + 6 * axis_index <= table_limit) {
                RAII_PyObject(values, PyTuple_New(axis_index));
                if (!values) return false;
                for (uint16_t n = 0; n < axis_index; n++, p += 3) {
                    uint16_t actual_axis_index = next;
                    p32 = (uint32_t*)p; double value = next32;
                    PyObject *e = Py_BuildValue("{sH sd}", "design_index", actual_axis_index, "value", value);
                    if (!e) return false;
                    PyTuple_SET_ITEM(values, n, e);
                }
                PyObject *e = Py_BuildValue("{sH sN sO}", "flags", flags,
                        "name", get_best_name(name_lookup_table, value_name_id), "values", values);
                if (!e) return false;
                PyTuple_SET_ITEM(multi_axis_styles, i++, e);
            } break;
        }
    }
    if (_PyTuple_Resize(&multi_axis_styles, i) == -1) return false;
ok:
    if (PyDict_SetItemString(output, "design_axes", design_axes) != 0) return false;
    if (PyDict_SetItemString(output, "multi_axis_styles", multi_axis_styles) != 0) return false;
    if (PyDict_SetItemString(output, "elided_fallback_name", elided_fallback_name_id ? get_best_name(name_lookup_table, elided_fallback_name_id) : PyUnicode_FromString("")) != 0) return false;
    return true;
}

bool
read_fvar_font_table(const uint8_t *table, size_t table_len, PyObject *name_lookup_table, PyObject *output) {
    RAII_PyObject(named_styles, PyTuple_New(0)); if (!named_styles) return false;
    RAII_PyObject(axes, PyTuple_New(0)); if (!axes) return false;

    if (!table || table_len < 14 * sizeof(uint16_t)) goto ok;

    const uint16_t *p = (uint16_t*)table;
    p += 2;
    const uint16_t offset_to_start_of_axis_array = next; next;
    const uint16_t num_of_axis_records = next, size_of_axis_record = next, num_of_name_records = next, size_of_name_record = next;
    const uint16_t size_of_coordinates = num_of_axis_records * sizeof(int32_t);
    if (size_of_name_record < size_of_coordinates + 4) {
        PyErr_Format(PyExc_ValueError, "size of name record: %u too small", size_of_name_record); return NULL;
    }
    const bool has_postscript_name = size_of_name_record >= 3 * sizeof(uint16_t) + size_of_coordinates;
    uint16_t i = 0;
    if (size_of_axis_record < 20) { PyErr_Format(PyExc_ValueError, "size of axis record: %u too small", size_of_axis_record); return NULL; }
    if (_PyTuple_Resize(&axes, num_of_axis_records) == -1) return NULL;
    for (
        const uint8_t *pos = table + offset_to_start_of_axis_array;
        pos + size_of_axis_record <= table + table_len && i < num_of_axis_records;
        i++, pos += size_of_axis_record
    ) {
        uint32_t *p32 = (uint32_t*)(pos + 4);
        const double minimum = next32, def = next32, maximum = next32;
        p = (uint16_t*)(pos + 16);
        int32_t flags = next, strid = next;
        PyObject *axis = Py_BuildValue("{sd sd sd sN sO sN}",
            "minimum", minimum, "maximum", maximum, "default", def, "tag", PyUnicode_FromStringAndSize((const char*)pos, 4),
            "hidden", (flags & 1) ? Py_True : Py_False, "strid", get_best_name(name_lookup_table, strid)
        ); if (!axis) return NULL;
        PyTuple_SET_ITEM(axes, i, axis);
    }
    if (_PyTuple_Resize(&axes, i) == -1) return NULL;
    char tag_buf[5] = {0};
    i = 0;
    if (_PyTuple_Resize(&named_styles, num_of_name_records) == -1) return NULL;
    for (
        const uint8_t *pos = table + offset_to_start_of_axis_array + num_of_axis_records * size_of_axis_record;
        pos + size_of_name_record <= table + table_len && i < num_of_name_records;
        i++, pos += size_of_name_record
    ) {
        p = (uint16_t*)pos;
        uint16_t name_id = next, psname_id = 0xffff; next;
        const uint32_t *p32 = (uint32_t*)p;
        RAII_PyObject(axis_values, PyDict_New());
        if (!axis_values) return NULL;
        for (uint16_t i = 0; i < num_of_axis_records; i++) {
            const uint8_t *t = table + offset_to_start_of_axis_array + i * size_of_axis_record;
            memcpy(tag_buf, t, 4);
            RAII_PyObject(pval, PyFloat_FromDouble(next32));
            if (!pval || PyDict_SetItemString(axis_values, tag_buf, pval) != 0) return NULL;
        }
        if (has_postscript_name) { p = (uint16_t*)p32; psname_id = next; }
        PyObject *ns = Py_BuildValue("{sO sN sN}",
            "axis_values", axis_values, "name", get_best_name(name_lookup_table, name_id),
            "psname", (psname_id != 0xffff && psname_id ? get_best_name(name_lookup_table, psname_id) : PyUnicode_FromString("")));
        if (!ns) return NULL;
        PyTuple_SET_ITEM(named_styles, i, ns);
    }
    if (_PyTuple_Resize(&named_styles, i) == -1) return NULL;
ok:
    if (PyDict_SetItemString(output, "variations_postscript_name_prefix", get_best_name(name_lookup_table, 25)) != 0) return false;
    if (PyDict_SetItemString(output, "axes", axes) != 0) return false;
    if (PyDict_SetItemString(output, "named_styles", named_styles) != 0) return false;
    return true;
}
#undef next32
#undef next
