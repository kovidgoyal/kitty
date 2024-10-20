#include <float.h>
#include "state.h"

inline static float
norm(float x, float y) {
    return sqrtf(x * x + y * y);
}

static void
update_cursor_trail_target(CursorTrail *ct, Window *w) {
#define EDGE(axis, index) ct->cursor_edge_##axis[index]
#define WD w->render_data
    float left = FLT_MAX, right = FLT_MAX, top = FLT_MAX, bottom = FLT_MAX;
    switch (WD.screen->cursor_render_info.shape) {
        case CURSOR_BLOCK:
        case CURSOR_HOLLOW:
        case CURSOR_BEAM:
        case CURSOR_UNDERLINE:
            left = WD.xstart + WD.screen->cursor_render_info.x * WD.dx;
            bottom = WD.ystart - (WD.screen->cursor_render_info.y + 1) * WD.dy;
        default:
            break;
    }
    switch (WD.screen->cursor_render_info.shape) {
        case CURSOR_BLOCK:
        case CURSOR_HOLLOW:
            right = left + WD.dx;
            top = bottom + WD.dy;
            break;
        case CURSOR_BEAM:
            right = left + WD.dx / WD.screen->cell_size.width * OPT(cursor_beam_thickness);
            top = bottom + WD.dy;
            break;
        case CURSOR_UNDERLINE:
            right = left + WD.dx;
            top = bottom + WD.dy / WD.screen->cell_size.height * OPT(cursor_underline_thickness);
            break;
        default:
            break;
    }
    if (left != FLT_MAX) {
        EDGE(x, 0) = left;
        EDGE(x, 1) = right;
        EDGE(y, 0) = top;
        EDGE(y, 1) = bottom;
    }
}

static bool
update_cursor_trail_corners(CursorTrail *ct, Window *w, monotonic_t now, OSWindow *os_window) {
    // the trail corners move towards the cursor corner at a speed proportional to their distance from the cursor corner.
    // equivalent to exponential ease out animation.
    static const int ci[4][2] = {{1, 0}, {1, 1}, {0, 1}, {0, 0}};
    const float dx_threshold = WD.dx / WD.screen->cell_size.width;
    const float dy_threshold = WD.dy / WD.screen->cell_size.height;

    // the decay time for the trail to reach 1/1024 of its distance from the cursor corner
    float decay_fast = OPT(cursor_trail_decay_fast);
    float decay_slow = OPT(cursor_trail_decay_slow);

    if (os_window->live_resize.in_progress) {
        for (int i = 0; i < 4; ++i) {
            ct->corner_x[i] = EDGE(x, ci[i][0]);
            ct->corner_y[i] = EDGE(y, ci[i][1]);
        }
    }
    else if (ct->updated_at < now) {
        float cursor_center_x = (EDGE(x, 0) + EDGE(x, 1)) * 0.5f;
        float cursor_center_y = (EDGE(y, 0) + EDGE(y, 1)) * 0.5f;
        float cursor_diag_2 = norm(EDGE(x, 1) - EDGE(x, 0), EDGE(y, 1) - EDGE(y, 0)) * 0.5f;
        float dt = (float)monotonic_t_to_s_double(now - ct->updated_at);

        for (int i = 0; i < 4; ++i) {
            float dx = EDGE(x, ci[i][0]) - ct->corner_x[i];
            float dy = EDGE(y, ci[i][1]) - ct->corner_y[i];
            if (fabsf(dx) < dx_threshold && fabsf(dy) < dy_threshold) {
                ct->corner_x[i] = EDGE(x, ci[i][0]);
                ct->corner_y[i] = EDGE(y, ci[i][1]);
                continue;
            }

            // Corner that is closer to the cursor moves faster.
            // It creates dynamic effect that looks like the trail is being pulled towards the cursor.
            float dot = (dx * (EDGE(x, ci[i][0]) - cursor_center_x) +
                dy * (EDGE(y, ci[i][1]) - cursor_center_y)) /
                cursor_diag_2 / norm(dx, dy);

            float decay_seconds = decay_slow + (decay_fast - decay_slow) * (1.0f + dot) * 0.5f;
            float step = 1.0f - 1.0f / exp2f(10.0f * dt / decay_seconds);

            ct->corner_x[i] += dx * step;
            ct->corner_y[i] += dy * step;
        }
    }

    ct->updated_at = now;
    for (int i = 0; i < 4; ++i) {
        float dx = fabsf(EDGE(x, ci[i][0]) - ct->corner_x[i]);
        float dy = fabsf(EDGE(y, ci[i][1]) - ct->corner_y[i]);
        if (dx_threshold <= dx || dy_threshold <= dy) {
            return true;
        }
    }
    return false;
}

bool
update_cursor_trail(CursorTrail *ct, Window *w, monotonic_t now, OSWindow *os_window) {
    if (!WD.screen->paused_rendering.expires_at && OPT(cursor_trail) < now - WD.screen->cursor->position_changed_by_client_at) {
        update_cursor_trail_target(ct, w);
    }

    bool needs_render_prev = ct->needs_render;
    ct->needs_render = false;

    if (update_cursor_trail_corners(ct, w, now, os_window)) {
        ct->needs_render = true;
    }

    // returning true here will cause the cells to be drawn
    return ct->needs_render || needs_render_prev;
}

#undef WD
#undef EDGE
