/*
 * animation.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stddef.h>
#include <stdbool.h>

typedef enum { EASING_STEP_START, EASING_STEP_END, EASING_STEP_NONE, EASING_STEP_BOTH } EasingStep;
#ifndef ANIMATION_INTERNAL_API
typedef struct {int x;} *Animation;
#endif
Animation* alloc_animation(void);
double apply_easing_curve(const Animation *a, double t /* must be between 0 and 1*/);
bool animation_is_valid(const Animation *a);
void add_cubic_bezier_animation(Animation *a, double y_at_start, double y_at_end, double start, double p1, double p2, double end);
void add_linear_animation(Animation *a, double y_at_start, double y_at_end, size_t count, const double *params, const double *positions);
void add_steps_animation(Animation *a, double y_at_start, double y_at_end, size_t count, EasingStep step);
Animation* free_animation(Animation *a);
