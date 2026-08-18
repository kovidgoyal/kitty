/*
 * animation-parse.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include "animation.h"

// Populate an Animation from a Python EasingFunction NamedTuple
// (kitty.options.utils.EasingFunction). y_at_start/y_at_end are the output
// values at t=0 and t=1 respectively.
static void
add_easing_function(Animation *a, PyObject *e, double y_at_start, double y_at_end) {
#define G(name) RAII_PyObject(name, PyObject_GetAttrString(e, #name))
#define D(container, idx) PyFloat_AsDouble(PyTuple_GET_ITEM(container, idx))
#define EQ(x, val) (PyUnicode_CompareWithASCIIString((x), val) == 0)
    G(type);
    if (EQ(type, "cubic-bezier")) {
        G(cubic_bezier_points);
        add_cubic_bezier_animation(
            a, y_at_start, y_at_end, D(cubic_bezier_points, 0), D(cubic_bezier_points, 1), D(cubic_bezier_points, 2), D(cubic_bezier_points, 3));
    } else if (EQ(type, "linear")) {
        G(linear_x);
        G(linear_y);
        size_t count = PyTuple_GET_SIZE(linear_x);
        RAII_ALLOC(double, x, malloc(2 * sizeof(double) * count));
        if (x) {
            double *y = x + count;
            for (size_t i = 0; i < count; i++) {
                x[i] = D(linear_x, i);
                y[i] = D(linear_y, i);
            }
            add_linear_animation(a, y_at_start, y_at_end, count, x, y);
        }
    } else if (EQ(type, "steps")) {
        G(num_steps);
        G(jump_type);
        EasingStep jt = EASING_STEP_END;
        if (EQ(jump_type, "start")) jt = EASING_STEP_START;
        else if (EQ(jump_type, "none")) jt = EASING_STEP_NONE;
        else if (EQ(jump_type, "both")) jt = EASING_STEP_BOTH;
        add_steps_animation(a, y_at_start, y_at_end, PyLong_AsSize_t(num_steps), jt);
    }
#undef EQ
#undef D
#undef G
}
