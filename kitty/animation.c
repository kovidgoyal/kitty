/*
 * animation.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "animation.h"
#include <stdbool.h>
#include "data-types.h"

static double
unit_value(double x) { return MAX(0., MIN(x, 1.)); }

double
linear_easing_curve(easing_curve_parameters p, double val) {
    for (size_t i = p.count - 1; i-- > 0;) if (p.positions[i] <= val) return p.params[i];
    return p.params[0];
}

double
cubic_bezier_easing_curve(easing_curve_parameters p, double t) {
    const double u = 1. - t, uu = u * u, uuu = uu * u, tt = t * t, ttt = tt * t;
    // p0 is start, p3 is end. p1, p2 are control points
    return uuu * p.params[0] + 3 * uu * t * p.params[1] + 3 * u * tt * p.params[2] + ttt * p.params[3];
}

double
apply_easing_curve(const Animation *a, double val) {
    if (a->first_half.curve) {
        if (a->second_half.curve) {
            if (val <= 0.5) return unit_value(a->first_half.curve(a->first_half.params, 2 * val));
            return unit_value(a->second_half.curve(a->second_half.params, 2 * (val - 0.5)));
        } else return unit_value(a->first_half.curve(a->first_half.params, val));
    } else return (val <= 0.5) ? 1. : 0.;
}

