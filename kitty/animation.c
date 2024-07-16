/*
 * animation.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#define ANIMATION_INTERNAL_API

typedef struct easing_curve_parameters {
    size_t count;
    double extra0, extra1, extra2, extra3;
    const double *params, *positions;
} easing_curve_parameters;

typedef double(*easing_curve)(easing_curve_parameters*, double);

typedef struct animation_function {
    easing_curve_parameters params;
    easing_curve curve;
    double y_at_start, y_size;
} animation_function;


typedef struct Animation {
    animation_function *functions;
    size_t count, capacity;
} Animation;


#include "animation.h"

Animation*
alloc_animation(void) {
    return calloc(1, sizeof(Animation));
}

bool
animation_is_valid(const Animation* a) { return a != NULL && a->count > 0; }

Animation*
free_animation(Animation *a) {
    if (a) {
        for (size_t i = 0; i < a->count; i++) free((void*)a->functions[i].params.params);
        free(a->functions);
        free(a);
    }
    return NULL;
}

static double
unit_value(double x) { return MAX(0., MIN(x, 1.)); }

static double
linear_easing_curve(easing_curve_parameters *p, double val) {
    double start_pos = 0, stop_pos = 1, start_val = 0, stop_val = 1;
    for (size_t i = 0; i < p->count; i++) {
        if (p->positions[i] >= val) {
            stop_pos = p->positions[i];
            stop_val = p->params[i];
            if (i > 0) {
                start_val = p->params[i-1];
                start_pos = p->positions[i-1];
            }
            break;
        }
    }
    double frac = (val - start_pos) / (stop_pos - start_pos);
    return start_val + frac * (stop_val - start_val);
}

static double
cubic_bezier_easing_curve(easing_curve_parameters *p, double t) {
    const double u = 1. - t, uu = u * u, uuu = uu * u, tt = t * t, ttt = tt * t;
    // p0 is start, p3 is end. p1, p2 are control points
    return uuu * p->extra0 + 3 * uu * t * p->extra1 + 3 * u * tt * p->extra2 + ttt * p->extra3;
}

static double
step_easing_curve(easing_curve_parameters *p, double t) {
    double num_of_buckets = p->extra0, start_value = p->extra2, jump_size = p->extra1;
    size_t val_bucket = (size_t)(t * num_of_buckets);
    return start_value + val_bucket * jump_size;
}

double
apply_easing_curve(const Animation *a, double val) {
    val = unit_value(val);
    if (!a->count) return val;
    size_t idx = MIN((size_t)(val * a->count), a->count - 1);
    animation_function *f = a->functions + idx;
    double ans = f->curve(&f->params, val);
    return f->y_at_start + unit_value(ans) * f->y_size;
}

static animation_function*
init_function(Animation *a, double y_at_start, double y_at_end, easing_curve curve, size_t count) {
    ensure_space_for(a, functions, animation_function, a->count + 1, capacity, 4, false);
    animation_function *f = a->functions + a->count++;
    zero_at_ptr(f);
    f->y_at_start = y_at_start; f->y_size = y_at_end - y_at_start; f->curve = curve;
    if (count) {
        double *p = calloc(count*2, sizeof(double));
        if (!p) fatal("Out of memory");
        f->params.params = p;
        f->params.positions = p + count;
        f->params.count = 0;
    }
    return f;
}

void
add_cubic_bezier_animation(Animation *a, double y_at_start, double y_at_end, double start, double p1, double p2, double end) {
    animation_function *f = init_function(a, y_at_start, y_at_end, cubic_bezier_easing_curve, 4);
    f->params.extra0 = start; f->params.extra1 = p1; f->params.extra2 = p2; f->params.extra3 = end;
}

void
add_linear_animation(Animation *a, double y_at_start, double y_at_end, size_t count, const double *params, const double *positions) {
    animation_function *f = init_function(a, y_at_start, y_at_end, linear_easing_curve, count);
    const size_t sz = count * sizeof(double);
    memcpy((void*)f->params.params, params, sz); memcpy((void*)f->params.positions, positions, sz);
}

void
add_steps_animation(Animation *a, double y_at_start, double y_at_end, size_t count, EasingStep step) {
    animation_function *f = init_function(a, y_at_start, y_at_end, step_easing_curve, 0);
    double jump_size = 1. / count, start_value = 0.;
    size_t num_of_buckets = count;
    switch (step) {
        case EASING_STEP_START:
            start_value = jump_size;
            num_of_buckets--;
            break;
        case EASING_STEP_END: break;
        case EASING_STEP_NONE:
            num_of_buckets--;
            break;
        case EASING_STEP_BOTH:
            num_of_buckets++;
            jump_size = 1. / num_of_buckets;
            start_value = jump_size;
            break;
    }
    f->params.extra0 = num_of_buckets; f->params.extra1 = jump_size; f->params.extra2 = start_value;
}
