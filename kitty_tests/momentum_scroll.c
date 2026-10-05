// License: GPLv3 Copyright: 2026, kitty contributors

#include "../glfw/internal.h"
#include <assert.h>
#include <math.h>

static _GLFWwindow window = {.id = 1};
static monotonic_t now;
monotonic_t monotonic_start_time;
static GLFWScrollEvent momentum;
static unsigned starts;

monotonic_t
monotonic_(void) {
    return now;
}
_GLFWwindow *
_glfwWindowForId(GLFWid id) {
    return id == window.id ? &window : NULL;
}
_GLFWwindow *
_glfwFocusedWindow(void) {
    return &window;
}
void
_glfwPlatformGetWindowContentScale(_GLFWwindow *w, float *xscale, float *yscale) {
    assert(w == &window);
    *xscale = *yscale = 1;
}
void
_glfwInputScroll(_GLFWwindow *w, const GLFWScrollEvent *ev) {
    assert(w == &window);
    if (ev->momentum_type == GLFW_MOMENTUM_PHASE_BEGAN) {
        momentum = *ev;
        starts++;
    }
}
unsigned long long
glfwAddTimer(monotonic_t interval UNUSED, bool repeats UNUSED, GLFWuserdatafun callback UNUSED, void *data UNUSED, GLFWuserdatafun cleanup UNUSED) {
    return 1;
}
void
glfwRemoveTimer(unsigned long long id UNUSED) {}

static void
gesture(bool horizontal, double delta, double scale) {
    glfw_cancel_momentum_scroll();
    starts = 0;
    GLFWScrollEvent ev = {.offset_type = GLFW_SCROLL_OFFEST_HIGHRES};
    if (horizontal) {
        ev.unscaled.x = delta;
        ev.x_offset = delta * scale;
    } else {
        ev.unscaled.y = delta;
        ev.y_offset = delta * scale;
    }
    for (unsigned i = 0; i < 5; i++) {
        now = ms_to_monotonic_t(10 * i);
        glfw_handle_scroll_event_for_momentum(&window, &ev, false, true);
    }
    ev.unscaled.x = ev.unscaled.y = ev.x_offset = ev.y_offset = 0;
    now = ms_to_monotonic_t(50 + momentum_scroll_gesture_detection_timeout_ms);
    glfw_handle_scroll_event_for_momentum(&window, &ev, true, true);
    assert(starts == 1);
    double unscaled = horizontal ? momentum.unscaled.x : momentum.unscaled.y;
    double scaled = horizontal ? momentum.x_offset : momentum.y_offset;
    assert(unscaled * delta > 0);
    assert(fabs(scaled - scale * unscaled) < 1e-6);
}

int
main(void) {
    gesture(false, -20, 2);
    gesture(false, 20, 3);
    gesture(true, -20, 4);
    gesture(true, 20, 5);
    glfw_cancel_momentum_scroll();
    return 0;
}
