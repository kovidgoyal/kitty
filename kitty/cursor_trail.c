#include <float.h>
#include "state.h"

#define WD w->render_data
#define EDGE(axis, index) ct->cursor_edge_##axis[index]

inline static float
norm(float x, float y) {
    return sqrtf(x * x + y * y);
}

typedef struct ndc_coords { float xstart, ystart, dx, dy; } ndc_coords;

static void
update_cursor_trail_target(CursorTrail *ct, Window *w, ndc_coords g) {
    float left = FLT_MAX, right = FLT_MAX, top = FLT_MAX, bottom = FLT_MAX;
    switch (WD.screen->cursor_render_info.shape) {
        case CURSOR_BLOCK:
        case CURSOR_HOLLOW:
        case CURSOR_BEAM:
        case CURSOR_UNDERLINE:
            left = g.xstart + WD.screen->cursor_render_info.x * g.dx;
            bottom = g.ystart - (WD.screen->cursor_render_info.y + 1) * g.dy;
        default:
            break;
    }
    switch (WD.screen->cursor_render_info.shape) {
        case CURSOR_BLOCK:
        case CURSOR_HOLLOW:
            right = left + g.dx;
            top = bottom + g.dy;
            break;
        case CURSOR_BEAM:
            right = left + g.dx / WD.screen->cell_size.width * OPT(cursor_beam_thickness);
            top = bottom + g.dy;
            break;
        case CURSOR_UNDERLINE:
            right = left + g.dx;
            top = bottom + g.dy / WD.screen->cell_size.height * OPT(cursor_underline_thickness);
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
should_skip_cursor_trail_update(CursorTrail *ct, ndc_coords g, OSWindow *os_window) {
    if (os_window->live_resize.in_progress) {
        return true;
    }

    if (OPT(cursor_trail_start_threshold) > 0 && !ct->needs_render) {
        int dx = (int)round((ct->corner_x[0] - EDGE(x, 1)) / g.dx);
        int dy = (int)round((ct->corner_y[0] - EDGE(y, 0)) / g.dy);
        if (abs(dx) + abs(dy) <= OPT(cursor_trail_start_threshold)) {
            return true;
        }
    }
    return false;
}

static void
update_cursor_trail_corners(CursorTrail *ct, ndc_coords g, monotonic_t now, OSWindow *os_window) {
    // the trail corners move towards the cursor corner at a speed proportional to their distance from the cursor corner.
    // equivalent to exponential ease out animation.
    static const int corner_index[2][4] = {{1, 1, 0, 0}, {0, 1, 1, 0}};

    // the decay time for the trail to reach 1/1024 of its distance from the cursor corner
    float decay_fast = OPT(cursor_trail_decay_fast);
    float decay_slow = OPT(cursor_trail_decay_slow);

    if (should_skip_cursor_trail_update(ct, g, os_window)) {
        for (int i = 0; i < 4; ++i) {
            ct->corner_x[i] = EDGE(x, corner_index[0][i]);
            ct->corner_y[i] = EDGE(y, corner_index[1][i]);
        }
    }
    else if (ct->updated_at < now) {
        float cursor_center_x = (EDGE(x, 0) + EDGE(x, 1)) * 0.5f;
        float cursor_center_y = (EDGE(y, 0) + EDGE(y, 1)) * 0.5f;
        float cursor_diag_2 = norm(EDGE(x, 1) - EDGE(x, 0), EDGE(y, 1) - EDGE(y, 0)) * 0.5f;
        float dt = (float)monotonic_t_to_s_double(now - ct->updated_at);

        // dot product here is used to dynamically adjust the decay speed of
        // each corner. The closer the corner is to the cursor, the faster it
        // moves.
        float dx[4], dy[4];
        float dot[4];  // dot product of "direction vector" and "cursor center to corner vector"
        for (int i = 0; i < 4; ++i) {
            dx[i] = EDGE(x, corner_index[0][i]) - ct->corner_x[i];
            dy[i] = EDGE(y, corner_index[1][i]) - ct->corner_y[i];
            if (fabsf(dx[i]) < 1e-6 && fabsf(dy[i]) < 1e-6) {
                dx[i] = dy[i] = 0.0f;
                dot[i] = 0.0f;
                continue;
            }
            dot[i] = (dx[i] * (EDGE(x, corner_index[0][i]) - cursor_center_x) +
                      dy[i] * (EDGE(y, corner_index[1][i]) - cursor_center_y)) /
                     cursor_diag_2 / norm(dx[i], dy[i]);
        }
        float min_dot = FLT_MAX, max_dot = -FLT_MAX;
        for (int i = 0; i < 4; ++i) {
            min_dot = fminf(min_dot, dot[i]);
            max_dot = fmaxf(max_dot, dot[i]);
        }

        for (int i = 0; i < 4; ++i) {
            if ((dx[i] == 0 && dy[i] == 0) || min_dot == FLT_MAX) {
                continue;
            }

            float decay = (min_dot == max_dot)
                ? decay_slow
                : decay_slow + (decay_fast - decay_slow) * (dot[i] - min_dot) / (max_dot - min_dot);
            float step = 1.0f - exp2f(-10.0f * dt / decay);
            ct->corner_x[i] += dx[i] * step;
            ct->corner_y[i] += dy[i] * step;
        }
    }
}

static void
update_cursor_trail_opacity(CursorTrail *ct, Window *w, monotonic_t now) {
    const bool cursor_trail_always_visible = false;
    if (cursor_trail_always_visible) {
        ct->opacity = 1.0f;
    } else if (WD.screen->modes.mDECTCEM) {
        ct->opacity += (float)monotonic_t_to_s_double(now - ct->updated_at) / OPT(cursor_trail_decay_slow);
        ct->opacity = fminf(ct->opacity, 1.0f);
    } else {
        ct->opacity -= (float)monotonic_t_to_s_double(now - ct->updated_at) / OPT(cursor_trail_decay_slow);
        ct->opacity = fmaxf(ct->opacity, 0.0f);
    }
}

static void
update_cursor_trail_needs_render(CursorTrail *ct, Window *w, ndc_coords g) {
    static const int corner_index[2][4] = {{1, 1, 0, 0}, {0, 1, 1, 0}};
    ct->needs_render = false;

    // check if any corner is still far from the cursor corner, so it should be rendered
    const float dx_threshold = g.dx / WD.screen->cell_size.width * 0.5f;
    const float dy_threshold = g.dy / WD.screen->cell_size.height * 0.5f;
    for (int i = 0; i < 4; ++i) {
        float dx = fabsf(EDGE(x, corner_index[0][i]) - ct->corner_x[i]);
        float dy = fabsf(EDGE(y, corner_index[1][i]) - ct->corner_y[i]);
        if (dx_threshold <= dx || dy_threshold <= dy) {
            ct->needs_render = true;
            break;
        }
    }
}

bool
update_cursor_trail(CursorTrail *ct, Window *w, monotonic_t now, OSWindow *os_window) {
    ndc_coords g = {
        .xstart = gl_pos_x(w->render_data.geometry.left, os_window->viewport_width),
        .ystart = gl_pos_y(w->render_data.geometry.top, os_window->viewport_height),
        .dx     = gl_size (w->render_data.screen->cell_size.width, os_window->viewport_width),
        .dy     = gl_size (w->render_data.screen->cell_size.height, os_window->viewport_height),
    };
    if (!WD.screen->paused_rendering.expires_at && OPT(cursor_trail) <= now - WD.screen->cursor->position_changed_by_client_at) {
        update_cursor_trail_target(ct, w, g);
    }

    update_cursor_trail_corners(ct, g, now, os_window);
    update_cursor_trail_opacity(ct, w, now);

    bool needs_render_prev = ct->needs_render;
    update_cursor_trail_needs_render(ct, w, g);

    ct->updated_at = now;

    // returning true here will cause the cells to be drawn
    return ct->needs_render || needs_render_prev;
}

#undef WD
#undef EDGE
