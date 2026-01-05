/*
 * momentum-scroll.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "internal.h"
#include <math.h>

typedef struct ScrollSample {
    double dx, dy;
    monotonic_t timestamp;
} ScrollSample;

#define DEQUE_DATA_TYPE ScrollSample
#define DEQUE_NAME ScrollSamples
#include "../kitty/fixed_size_deque.h"

typedef enum ScrollerState { NONE, PHYSICAL_EVENT_IN_PROGRESS, MOMENTUM_IN_PROGRESS } ScrollerState;

typedef struct MomentumScroller {
    double friction,  // Deceleration factor (0-1, lower = longer coast)
           min_velocity, // Minimum velocity before stopping
           max_velocity, // Maximum velocity to prevent runaway scrolling
           velocity_scale; // Scale factor for initial velocity
    unsigned timer_interval_ms;

    GLFWid timer_id, window_id;
    ScrollSamples samples;
    ScrollerState state;
    struct { double x, y; } velocity;
    int keyboard_modifiers;
} MomentumScroller;

static MomentumScroller s = {
    .friction = 0.04,
    .min_velocity = 0.5,
    .max_velocity = 100,
    .velocity_scale = 0.9,
    .timer_interval_ms = 10,
};

static void
cancel_existing_scroll(void) {
    if (s.timer_id) {
        glfwRemoveTimer(s.timer_id);
        s.timer_id = 0;
    }
    if (s.state == MOMENTUM_IN_PROGRESS) {
        _GLFWwindow *w = _glfwWindowForId(s.window_id);
        if (w) _glfwInputScroll(
            w, &(GLFWScrollEvent){.momentum_type=GLFW_MOMENTUM_PHASE_CANCELED, .keyboard_modifiers=s.keyboard_modifiers});
    }
    s.window_id = 0;
    s.keyboard_modifiers = 0;
    deque_clear(&s.samples);
    s.state = NONE;
}

static void
add_sample(double dx, double dy) {
    deque_push_back(&s.samples, (ScrollSample){dx, dy, monotonic()}, NULL);
}

static void
last_sample_delta(double *dx, double *dy) {
    const ScrollSample *ss;
    if ((ss = deque_peek_back(&s.samples))) { *dx = ss->dx; *dy = ss->dy; }
    else { *dx = 0; *dy = 0; }
}

static void
trim_old_samples(monotonic_t now) {
    const ScrollSample *ss;
    while ((ss = deque_peek_front(&s.samples)) && (now - ss->timestamp) > ms_to_monotonic_t(150))
        deque_pop_front(&s.samples, NULL);
}

static void
add_velocity(double x, double y) {
    if (x == 0 || x * s.velocity.x >= 0) s.velocity.x += x;
    else s.velocity.x = x;
    if (y == 0 || y * s.velocity.y >= 0) s.velocity.y += y;
    else s.velocity.y = y;
    s.velocity.x = MAX(-s.max_velocity, MIN(s.velocity.x, s.max_velocity));
    s.velocity.y = MAX(-s.max_velocity, MIN(s.velocity.y, s.max_velocity));
}

static void
set_velocity_from_samples(void) {
    trim_old_samples(monotonic());
    ScrollSample ss;
    switch (deque_size(&s.samples)) {
        case 0:
            return;
        case 1:
            deque_pop_front(&s.samples, &ss);
            add_velocity(s.velocity_scale * ss.dx, s.velocity_scale * ss.dy);
            return;
    }

    // Use weighted average - more recent samples have higher weight
    double total_dx = 0.0, total_dy = 0.0, total_weight = 0.0;
    monotonic_t first_time = deque_peek_front(&s.samples)->timestamp;
    monotonic_t last_time = deque_peek_back(&s.samples)->timestamp;
    double time_span = MAX(1, last_time - first_time);
    for (size_t i = 0; i < deque_size(&s.samples); i++) {
        const ScrollSample *ss = deque_at(&s.samples, i);
        double weight = 1.0 + (ss->timestamp - first_time) / time_span;
        total_dx += ss->dx * weight; total_dy += ss->dy * weight;
        total_weight += weight;
    }
    deque_clear(&s.samples);
    if (total_weight <= 0) return;
    add_velocity((total_dx / total_weight) * s.velocity_scale, (total_dy / total_weight) * s.velocity_scale);
}

static void
send_momentum_event(bool is_start) {
    double friction = 1.0 - MAX(0, MIN(s.friction, 1.));
    s.velocity.x *= friction; s.velocity.y *= friction;
    if (fabs(s.velocity.x) < s.min_velocity) s.velocity.x = 0;
    if (fabs(s.velocity.y) < s.min_velocity) s.velocity.y = 0;
    _GLFWwindow *w = _glfwWindowForId(s.window_id);
    if (!w || w != _glfwFocusedWindow()) {
        cancel_existing_scroll();
        return;
    }
    GLFWMomentumType m = is_start ? GLFW_MOMENTUM_PHASE_BEGAN : GLFW_MOMENTUM_PHASE_ACTIVE;
    if (s.velocity.x == 0 && s.velocity.y == 0 && !is_start) {
        m = GLFW_MOMENTUM_PHASE_ENDED;
        if (s.timer_id) glfwRemoveTimer(s.timer_id);
        s.timer_id = 0;
    }
    GLFWScrollEvent e = {
        .offset_type=GLFW_SCROLL_OFFEST_HIGHRES, .momentum_type=m, .x_offset=s.velocity.x, .y_offset=s.velocity.y,
        .keyboard_modifiers=s.keyboard_modifiers
    };
    _glfwInputScroll(w, &e);
}

static void
momentum_timer_fired(unsigned long long timer_id UNUSED, void *data UNUSED) {
    send_momentum_event(false);
}

static void
start_momentum_scroll(void) {
    set_velocity_from_samples();
    send_momentum_event(true);
    s.timer_id = glfwAddTimer(ms_to_monotonic_t(s.timer_interval_ms), true, momentum_timer_fired, NULL, NULL);
}

void
glfw_handle_scroll_event_for_momentum(
    _GLFWwindow *w, const GLFWScrollEvent *ev, bool stopped, bool is_finger_based
) {
    if (!w || (w->id != s.window_id && s.window_id) || s.state != PHYSICAL_EVENT_IN_PROGRESS) cancel_existing_scroll();
    if (!w) return;
    // Check for change in direction
    double ldx, ldy; last_sample_delta(&ldx, &ldy);
    if (ldx * ev->x_offset < 0 || ldy * ev->y_offset < 0) {
        s.velocity.x = 0; s.velocity.y = 0;
        cancel_existing_scroll();
    }
    s.window_id = w->id;
    s.keyboard_modifiers = ev->keyboard_modifiers;
    if (is_finger_based) {
        add_sample(ev->x_offset, ev->y_offset);
        s.state = stopped ? MOMENTUM_IN_PROGRESS : PHYSICAL_EVENT_IN_PROGRESS;
    } else {
        s.state = stopped ? NONE : PHYSICAL_EVENT_IN_PROGRESS;
    }
    if (s.state == MOMENTUM_IN_PROGRESS) start_momentum_scroll();
    else _glfwInputScroll(w, ev);
}
