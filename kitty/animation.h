/*
 * animation.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stddef.h>

typedef struct easing_curve_parameters {
    size_t count;
    const double *params, *positions;
} easing_curve_parameters;

typedef double(*easing_curve)(easing_curve_parameters, double);

typedef struct Animation {
    struct {
        easing_curve_parameters params;
        easing_curve curve;
    } first_half, second_half;
} Animation;

double linear_easing_curve(easing_curve_parameters, double);
double cubic_bezier_easing_curve(easing_curve_parameters, double);
double apply_easing_curve(const Animation *a, double t /* must be between 0 and 1*/);
