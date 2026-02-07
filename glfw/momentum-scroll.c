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
    double friction,  // Deceleration inverse factor (0-1, higher = longer coast)
           min_velocity, // Minimum velocity before stopping
           max_velocity, // Maximum velocity to prevent runaway scrolling
           velocity_scale; // Scale factor for initial velocity
    monotonic_t timer_interval;  // animation speed

    GLFWid timer_id, window_id;
    ScrollSamples samples;
    ScrollerState state;
    double scale;
    struct { double x, y; } velocity;
    int keyboard_modifiers;
    struct {
        monotonic_t start, duration;
        struct { double x, y; } displacement;
    } physical_event;
} MomentumScroller;

#define DEFAULTS { .friction = 0.96, .min_velocity = 0.5, .max_velocity = 100, .timer_interval = 10, }
static const MomentumScroller defaults = DEFAULTS;
static MomentumScroller s = DEFAULTS;
#undef DEFAULTS

GLFWAPI void
glfwConfigureMomentumScroller(double friction, double min_velocity, double max_velocity, unsigned timer_interval_ms) {
    s.timer_interval = timer_interval_ms ? ms_to_monotonic_t(timer_interval_ms) : defaults.timer_interval;
    s.friction = friction < 0 ? defaults.friction : MAX(0, MIN(friction, 1));
#define S(w) s.w = w >= 0 ? w : defaults.w
    S(min_velocity); S(max_velocity);
#undef S
}

static void
cancel_existing_scroll(bool reset_velocity) {
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
    if (reset_velocity) { s.velocity.x = 0; s.velocity.y = 0; }
}

static void
add_sample(double dx, double dy, monotonic_t now) {
    deque_push_back(&s.samples, (ScrollSample){dx, dy, now}, NULL);
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
set_velocity_from_samples(monotonic_t now) {
    s.timer_interval = ms_to_monotonic_t(8);
    trim_old_samples(now);
    ScrollSample ss;
    switch (deque_size(&s.samples)) {
        case 0:
            return;
        case 1:
            deque_pop_front(&s.samples, &ss);
            add_velocity(ss.dx, ss.dy);
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
    double dy = total_dy / total_weight, dx = total_dx / total_weight;
    add_velocity(dx, dy);
    if (false) timed_debug_print("momentum scroll: event velocity: %.1f final velocity: %.1f\n", dy, s.velocity.y);
}

static void
send_momentum_event(bool is_start) {
    _GLFWwindow *w = _glfwWindowForId(s.window_id);
    if (!w || w != _glfwFocusedWindow()) {
        cancel_existing_scroll(true);
        return;
    }
    s.velocity.x *= s.friction; s.velocity.y *= s.friction;
    if (fabs(s.velocity.x) < s.min_velocity) s.velocity.x = 0;
    if (fabs(s.velocity.y) < s.min_velocity) s.velocity.y = 0;

    GLFWMomentumType m = is_start ? GLFW_MOMENTUM_PHASE_BEGAN : GLFW_MOMENTUM_PHASE_ACTIVE;
    if (s.velocity.x == 0 && s.velocity.y == 0 && !is_start) {
        m = GLFW_MOMENTUM_PHASE_ENDED;
        if (s.timer_id) glfwRemoveTimer(s.timer_id);
        s.timer_id = 0;
        s.state = NONE;
    }
    GLFWScrollEvent e = {
        .offset_type=GLFW_SCROLL_OFFEST_HIGHRES, .momentum_type=m, .unscaled.x=s.velocity.x, .unscaled.y=s.velocity.y,
        .x_offset=s.scale * s.velocity.x, .y_offset=s.scale * s.velocity.y, .keyboard_modifiers=s.keyboard_modifiers
    };
    _glfwInputScroll(w, &e);
}

static void
momentum_timer_fired(unsigned long long timer_id UNUSED, void *data UNUSED) {
    send_momentum_event(false);
}

static void
start_momentum_scroll(monotonic_t now) {
    set_velocity_from_samples(now);
    send_momentum_event(true);
    s.timer_id = glfwAddTimer(s.timer_interval, true, momentum_timer_fired, NULL, NULL);
}

static bool
is_suitable_for_momentum(void) {
    return (
        MAX(fabs(s.physical_event.displacement.x), fabs(s.physical_event.displacement.y)) > 10 &&
        s.physical_event.duration > ms_to_monotonic_t(2)
    );
}

void
glfw_handle_scroll_event_for_momentum(
    _GLFWwindow *w, const GLFWScrollEvent *ev, bool stopped, bool is_finger_based
) {
    const bool is_synthetic_momentum_start_event = stopped && momentum_scroll_gesture_detection_timeout_ms;
    if (!w) { cancel_existing_scroll(true); return; }
    if (!is_finger_based || ev->offset_type != GLFW_SCROLL_OFFEST_HIGHRES || s.friction < 0 || s.friction >= 1) {
        _glfwInputScroll(w, ev);
        return;
    }
    monotonic_t now = monotonic();
    if (is_synthetic_momentum_start_event) now -= ms_to_monotonic_t(momentum_scroll_gesture_detection_timeout_ms);
    if (s.state == PHYSICAL_EVENT_IN_PROGRESS) {
        s.physical_event.displacement.x += ev->unscaled.x;
        s.physical_event.displacement.y += ev->unscaled.y;
        if (stopped) {
            s.physical_event.duration = now - s.physical_event.start;
            s.physical_event.start = 0;
        }
    } else {
        memset(&s.physical_event, 0, sizeof(s.physical_event));
        s.physical_event.start = now;
    }
    if (ev->unscaled.y > 0) s.scale = ev->y_offset / ev->unscaled.y;
    else if (ev->unscaled.x > 0) s.scale = ev->x_offset / ev->unscaled.x;
    if (s.window_id && s.window_id != w->id) cancel_existing_scroll(true);
    if (s.state != PHYSICAL_EVENT_IN_PROGRESS) cancel_existing_scroll(false);
    if (!is_synthetic_momentum_start_event) {
        // Check for change in direction
        double ldx, ldy; last_sample_delta(&ldx, &ldy);
        if (ldx * ev->x_offset < 0 || ldy * ev->y_offset < 0) cancel_existing_scroll(true);
    }
    s.window_id = w->id;
    s.keyboard_modifiers = ev->keyboard_modifiers;
    if (ev->offset_type == GLFW_SCROLL_OFFEST_HIGHRES) {
        if (!is_synthetic_momentum_start_event) add_sample(ev->unscaled.x, ev->unscaled.y, now);
        if (stopped) s.state = is_suitable_for_momentum() ? MOMENTUM_IN_PROGRESS : NONE;
        else s.state = PHYSICAL_EVENT_IN_PROGRESS;
    } else {
        s.state = stopped ? NONE : PHYSICAL_EVENT_IN_PROGRESS;
    }
    if (s.state == MOMENTUM_IN_PROGRESS) start_momentum_scroll(now);
    else _glfwInputScroll(w, ev);
}
