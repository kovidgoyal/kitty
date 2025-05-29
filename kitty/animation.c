/*
 * animation.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#define ANIMATION_INTERNAL_API

typedef struct LinearParameters {
    size_t count;
    double buf[];
} LinearParameters;

typedef struct StepsParameters {
    size_t num_of_buckets;
    double jump_size, start_value;
} StepsParameters;

static const double bezier_epsilon = 1e-7;
static const unsigned max_newton_iterations = 4;
static const unsigned max_bisection_iterations = 16;

typedef struct BezierParameters {
    double ax, bx, cx, ay, by, cy, start_gradient, end_gradient, spline_samples[11];
} BezierParameters;

typedef double(*easing_curve)(void*, double, monotonic_t);

typedef struct animation_function {
    void *params;
    easing_curve curve;
    double y_at_start, y_size;
} animation_function;


typedef struct Animation {
    animation_function *functions;
    size_t count, capacity;
} Animation;


#include "animation.h"
#include "state.h"

Animation*
alloc_animation(void) {
    return calloc(1, sizeof(Animation));
}

bool
animation_is_valid(const Animation* a) { return a != NULL && a->count > 0; }

Animation*
free_animation(Animation *a) {
    if (a) {
        for (size_t i = 0; i < a->count; i++) free(a->functions[i].params);
        free(a->functions);
        free(a);
    }
    return NULL;
}


static double
unit_value(double x) { return MAX(0., MIN(x, 1.)); }

static double
linear_easing_curve(void *p_, double val, monotonic_t duration UNUSED) {
    LinearParameters *p = p_;
    double start_pos = 0, stop_pos = 1, start_val = 0, stop_val = 1;
    double *x = p->buf, *y = p->buf + p->count;
    for (size_t i = 0; i < p->count; i++) {
        if (x[i] >= val) {
            stop_pos = x[i];
            stop_val = y[i];
            if (i > 0) {
                start_val = y[i-1];
                start_pos = x[i-1];
            }
            break;
        }
    }
    if (stop_pos > start_pos) {
        double frac = (val - start_pos) / (stop_pos - start_pos);
        return start_val + frac * (stop_val - start_val);
    }
    return stop_val;
}

// Cubic Bezier {{{
static double
sample_curve_x(const BezierParameters *p, double t) {
    // `ax t^3 + bx t^2 + cx t' expanded using Horner's rule.
    return ((p->ax * t + p->bx) * t + p->cx) * t;
}

static double
sample_curve_y(const BezierParameters *p, double t) {
    return ((p->ay * t + p->by) * t + p->cy) * t;
}

static double
sample_derivative_x(const BezierParameters *p, double t) {
    return (3.0 * p->ax * t + 2.0 * p->bx) * t + p->cx;
}

static double
solve_curve_x(const BezierParameters *p, double x, double epsilon) {
    // Given an x value, find a parametric value it came from.
    double t0 = 0.0, t1 = 0.0, t2 = x, x2 = 0.0, d2 = 0.0;

    // Linear interpolation of spline curve for initial guess.
    static const size_t num_samples = arraysz(p->spline_samples);
    double delta = 1.0 / (num_samples - 1);
    for (size_t i = 1; i < num_samples; i++) {
        if (x <= p->spline_samples[i]) {
            t1 = delta * i;
            t0 = t1 - delta;
            t2 = t0 + (t1 - t0) * (x - p->spline_samples[i - 1]) / (p->spline_samples[i] - p->spline_samples[i - 1]);
            break;
        }
    }

    // Perform a few iterations of Newton's method -- normally very fast.
    // See https://en.wikipedia.org/wiki/Newton%27s_method.
    double newton_epsilon = MIN(bezier_epsilon, epsilon);
    for (unsigned i = 0; i < max_newton_iterations; i++) {
        x2 = sample_curve_x(p, t2) - x;
        if (fabs(x2) < newton_epsilon) return t2;
        d2 = sample_derivative_x(p, t2);
        if (fabs(d2) < bezier_epsilon) break;
        t2 = t2 - x2 / d2;
    }
    if (fabs(x2) < epsilon) return t2;

    t0 = 0.0, t1 = 0.0, t2 = x, x2 = 0.0;
    // Fall back to the bisection method for reliability.
    unsigned iteration = 0;
    while (t0 < t1 && iteration++ < max_bisection_iterations) {
        x2 = sample_curve_x(p, t2);
        if (fabs(x2 - x) < epsilon) return t2;
        if (x > x2) t0 = t2;
        else t1 = t2;
        t2 = (t1 + t0) * .5;
    }

    // Failure.
    return t2;
}

static double
solve_unit_bezier(const BezierParameters *p, double x, double epsilon) {
    if (x < 0.0) return 0.0 + p->start_gradient * x;
    if (x > 1.0) return 1.0 + p->end_gradient * (x - 1.0);
    return sample_curve_y(p, solve_curve_x(p, x, epsilon));
}

static double
cubic_bezier_easing_curve(void *p_, double t, monotonic_t duration) {
    BezierParameters *p = p_;
    // The longer the animation, the more precision we need
    double epsilon = 1.0 / monotonic_t_to_ms(duration);
    return fabs(solve_unit_bezier(p, t, epsilon));
}
// }}}

static double
step_easing_curve(void *p_, double t, monotonic_t duration UNUSED) {
    StepsParameters *p = p_;
    size_t val_bucket = (size_t)(t * p->num_of_buckets);
    return p->start_value + val_bucket * p->jump_size;
}

static double
identity_easing_curve(void *p_ UNUSED, double t, monotonic_t duration UNUSED) { return t; }

double
apply_easing_curve(const Animation *a, double val, monotonic_t duration) {
    val = unit_value(val);
    if (!a->count) return val;
    size_t idx = MIN((size_t)(val * a->count), a->count - 1);
    animation_function *f = a->functions + idx;
    double interval_size = 1. / a->count, interval_start = idx * interval_size;
    double scaled_val = (val - interval_start) / interval_size;
    double ans = f->curve(f->params, scaled_val, duration);
    return f->y_at_start + unit_value(ans) * f->y_size;
}

static animation_function*
init_function(Animation *a, double y_at_start, double y_at_end, easing_curve curve) {
    ensure_space_for(a, functions, animation_function, a->count + 1, capacity, 4, false);
    animation_function *f = a->functions + a->count++;
    zero_at_ptr(f);
    f->y_at_start = y_at_start; f->y_size = y_at_end - y_at_start; f->curve = curve;
    return f;
}

static bool
is_bezier_linear(double p1x, double p1y, double p2x, double p2y) {
    // Is linear if all four points are on the same line. P0 and P4 are fixed at (0, 0) and (1, 1) for us.
    return p1x == p1y && p2x == p2y;
}

void
add_cubic_bezier_animation(Animation *a, double y_at_start, double y_at_end, double p1x, double p1y, double p2x, double p2y) {
    p1x = unit_value(p1x); p2x = unit_value(p2x);
    if (is_bezier_linear(p1x, p1y, p2x, p2y)) {
        init_function(a, y_at_start, y_at_end, identity_easing_curve);
        return;
    }
    BezierParameters *p = calloc(1, sizeof(BezierParameters));
    if (!p) fatal("Out of memory");
    // Calculate the polynomial coefficients, implicit first and last control points are (0,0) and (1,1).
    p->cx = 3.0 * p1x;
    p->bx = 3.0 * (p2x - p1x) - p->cx;
    p->ax = 1.0 - p->cx - p->bx;

    p->cy = 3.0 * p1y;
    p->by = 3.0 * (p2y - p1y) - p->cy;
    p->ay = 1.0 - p->cy - p->by;

    // Calculate gradients used for values outside the unit interval
    if (p1x > 0) p->start_gradient = p1y / p1x;
    else if (p1y == 0 && p2x > 0) p->start_gradient = p2y / p2x;
    else if (p1y == 0 && p2y == 0) p->start_gradient = 1;
    else p->start_gradient = 0;

    if (p2x < 1) p->end_gradient = (p2y - 1) / (p2x - 1);
    else if (p2y == 1 && p1x < 1) p->end_gradient = (p1y - 1) / (p1x - 1);
    else if (p2y == 1 && p1y == 1) p->end_gradient = 1;
    else p->end_gradient = 0;

    size_t num_samples = arraysz(p->spline_samples);
    double delta = 1. / num_samples;
    for (size_t i = 0; i < num_samples; i++) p->spline_samples[i] = sample_curve_x(p, i * delta);
    animation_function *f = init_function(a, y_at_start, y_at_end, cubic_bezier_easing_curve);
    f->params = p;
}

void
add_linear_animation(Animation *a, double y_at_start, double y_at_end, size_t count, const double *x, const double *y) {
    const size_t sz = count * sizeof(double);
    LinearParameters *p = calloc(1, sizeof(LinearParameters) + 2 * sz);
    if (!p) fatal("Out of memory");
    p->count = count;
    double *px = p->buf, *py = px + count;
    memcpy(px, x, sz); memcpy(py, y, sz);
    animation_function *f = init_function(a, y_at_start, y_at_end, linear_easing_curve);
    f->params = p;
}

void
add_steps_animation(Animation *a, double y_at_start, double y_at_end, size_t count, EasingStep step) {
    double jump_size = 1. / count, start_value = 0.;
    size_t num_of_buckets = count;
    switch (step) {
        case EASING_STEP_START: start_value = jump_size; break;
        case EASING_STEP_END: break;
        case EASING_STEP_NONE:
            jump_size = 1. / (num_of_buckets - 1);
            break;
        case EASING_STEP_BOTH:
            num_of_buckets++;
            jump_size = 1. / num_of_buckets;
            start_value = jump_size;
            break;
    }
    StepsParameters *p = malloc(sizeof(StepsParameters));
    if (!p) fatal("Out of memory");
    p->num_of_buckets = num_of_buckets; p->jump_size = jump_size; p->start_value = start_value;
    animation_function *f = init_function(a, y_at_start, y_at_end, step_easing_curve);
    f->params = p;
}

static PyObject*
test_cursor_blink_easing_function(PyObject *self UNUSED, PyObject *args) {
    Animation *a = OPT(animation.cursor);
    if (!animation_is_valid(a)) {
        PyErr_SetString(PyExc_RuntimeError, "must set a cursor blink animation on the global options object first");
        return NULL;
    }
    double t, duration_s = 0.5; int only_single = 1;
    if (!PyArg_ParseTuple(args, "d|pd", &t, &only_single, &duration_s)) return NULL;
    monotonic_t duration = s_double_to_monotonic_t(duration_s);
    if (only_single) {
        animation_function f = a->functions[0];
        return PyFloat_FromDouble(f.curve(f.params, t, duration));
    }
    return PyFloat_FromDouble(apply_easing_curve(a, t, duration));
}

static PyMethodDef module_methods[] = {
    METHODB(test_cursor_blink_easing_function, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool init_animations(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
