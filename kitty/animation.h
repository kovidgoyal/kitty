/*
 * animation.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stddef.h>
#include <stdbool.h>
#include "monotonic.h"

typedef enum { EASING_STEP_START, EASING_STEP_END, EASING_STEP_NONE, EASING_STEP_BOTH } EasingStep;
#ifndef ANIMATION_INTERNAL_API
typedef struct {int x;} *Animation;
#endif
#define EASE_IN_OUT 0.42, 0, 0.58, 1
#define ANIMATION_SAMPLE_WAIT (50 * MONOTONIC_T_1e6)
Animation* alloc_animation(void);
double apply_easing_curve(const Animation *a, double t /* must be between 0 and 1*/, monotonic_t duration);
bool animation_is_valid(const Animation *a);
void add_cubic_bezier_animation(Animation *a, double y_at_start, double y_at_end, double p1_x, double p1_y, double p2_x, double p2_y);
void add_linear_animation(Animation *a, double y_at_start, double y_at_end, size_t count, const double *x, const double *y);
void add_steps_animation(Animation *a, double y_at_start, double y_at_end, size_t count, EasingStep step);
Animation* free_animation(Animation *a);
