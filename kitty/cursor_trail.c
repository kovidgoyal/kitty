#include <float.h>
#include "state.h"

#define WD w->render_data
#define EDGE(axis, index) ct->cursor_edge_##axis[index]

inline static float
norm(float x, float y) {
    return sqrtf(x * x + y * y);
}

typedef struct ndc_coords {
    float xstart, ystart, dx, dy;
} ndc_coords;

static void
update_cursor_trail_target(CursorTrail *ct, Window *w, ndc_coords g) {
    float left = FLT_MAX, right = FLT_MAX, top = FLT_MAX, bottom = FLT_MAX;
    switch (WD.screen->cursor_render_info.shape) {
        case CURSOR_BLOCK:
        case CURSOR_HOLLOW:
        case CURSOR_BEAM:
        case CURSOR_UNDERLINE: left = g.xstart + WD.screen->cursor_render_info.x * g.dx; bottom = g.ystart - (WD.screen->cursor_render_info.y + 1) * g.dy;
        default: break;
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
        default: break;
    }
    if (left != FLT_MAX) {
        if (EDGE(x, 0) != left || EDGE(x, 1) != right || EDGE(y, 0) != top || EDGE(y, 1) != bottom) {
            ct->target_updated = true;
            if (ct->prev_edge_valid) {
                ct->prev_cursor_edge_x[0] = EDGE(x, 0);
                ct->prev_cursor_edge_x[1] = EDGE(x, 1);
                ct->prev_cursor_edge_y[0] = EDGE(y, 0);
                ct->prev_cursor_edge_y[1] = EDGE(y, 1);
            }
        }
        ct->prev_edge_valid = true;
        EDGE(x, 0) = left;
        EDGE(x, 1) = right;
        EDGE(y, 0) = top;
        EDGE(y, 1) = bottom;
    }
}

static bool
should_skip_cursor_trail_update(CursorTrail *ct, ndc_coords g, OSWindow *os_window, Window *w) {
    if (os_window->live_resize.in_progress) { return true; }

    if (!WD.screen->modes.mDECTCEM && ct->opacity <= 0.0f) { return true; }

    if ((OPT(cursor_trail_start_threshold_x) > 0 || OPT(cursor_trail_start_threshold_y) > 0) && !ct->needs_render) {
        int dx = (int)round((ct->corner_x[0] - EDGE(x, 1)) / g.dx);
        int dy = (int)round((ct->corner_y[0] - EDGE(y, 0)) / g.dy);
        if (abs(dx) <= OPT(cursor_trail_start_threshold_x) && abs(dy) <= OPT(cursor_trail_start_threshold_y)) { return true; }
    }
    return false;
}

static uint32_t
next_particle_random(CursorTrail *ct) {
    if (!ct->particle_rng_inc) {
        ct->particle_rng_state = 0x853C49E6748FEA9Bull;
        ct->particle_rng_inc = (0xDA3E39CB94B95BDBull << 1u) | 1u;
    }
    uint64_t old_state = ct->particle_rng_state;
    ct->particle_rng_state = old_state * 6364136223846793005ull + ct->particle_rng_inc;
    uint32_t rot = (uint32_t)(old_state >> 59u);
    uint32_t xsh = (uint32_t)(((old_state >> 18u) ^ old_state) >> 27u);
    return (xsh >> rot) | (xsh << ((-rot) & 31u));
}

static float
next_particle_float(CursorTrail *ct) {
    return (float)ldexp((double)next_particle_random(ct), -32);
}

static void
update_cursor_particles(CursorTrail *ct, Window *w, monotonic_t now, OSWindow *os_window, bool had_prev_edge) {
    const float particle_lifetime = OPT(cursor_trail_particle_lifetime);
    if (particle_lifetime <= 0.f) {
        ct->num_particles = 0;
        ct->particle_count_remainder = 0.f;
        return;
    }
    const float dt = ct->updated_at ? (float)monotonic_t_to_s_double(now - ct->updated_at) : 0.f;
    size_t i = 0;
    while (i < ct->num_particles) {
        CursorParticle *p = ct->particles + i;
        p->lifetime -= dt;
        if (p->lifetime <= 0.f) {
            *p = ct->particles[--ct->num_particles];
            continue;
        }
        p->x += p->speed_x * dt;
        p->y += p->speed_y * dt;
        const float angle = dt * p->rotation_speed;
        const float s = sinf(angle), c = cosf(angle);
        const float speed_x = p->speed_x;
        p->speed_x = speed_x * c - p->speed_y * s;
        p->speed_y = speed_x * s + p->speed_y * c;
        i++;
    }

    if (!ct->target_updated || !had_prev_edge) return;
    const float viewport_width = os_window->viewport_width, viewport_height = os_window->viewport_height;
    const float current_x = (EDGE(x, 0) + EDGE(x, 1) + 2.f) * viewport_width * 0.25f;
    const float current_y = (2.f - EDGE(y, 0) - EDGE(y, 1)) * viewport_height * 0.25f;
    const float previous_x = (ct->prev_cursor_edge_x[0] + ct->prev_cursor_edge_x[1] + 2.f) * viewport_width * 0.25f;
    const float previous_y = (2.f - ct->prev_cursor_edge_y[0] - ct->prev_cursor_edge_y[1]) * viewport_height * 0.25f;
    const float travel_x = current_x - previous_x, travel_y = current_y - previous_y;
    const float cursor_height = WD.screen->cell_size.height;
    const float particle_count_float =
        hypotf(travel_x, travel_y) / cursor_height * OPT(cursor_trail_particle_density) + ct->particle_count_remainder;
    const size_t particle_count = (size_t)particle_count_float;
    ct->particle_count_remainder = particle_count_float - particle_count;

    for (i = 0; i < particle_count && ct->num_particles < arraysz(ct->particles); i++) {
        const float t = (float)(i + 1u) / particle_count;
        float dir_x = next_particle_float(ct) * 2.f - 1.f;
        float dir_y = next_particle_float(ct) * 2.f - 1.f;
        const float dir_length = hypotf(dir_x, dir_y);
        if (dir_length > 0.f) {
            dir_x /= dir_length;
            dir_y /= dir_length;
        }
        CursorParticle *p = ct->particles + ct->num_particles++;
        const float along_path = next_particle_float(ct);
        p->x = previous_x + travel_x * along_path;
        p->y = previous_y + travel_y * along_path + cursor_height * 0.5f;
        p->speed_x = dir_x * 0.5f * 3.f * OPT(cursor_trail_particle_speed);
        p->speed_y = (0.4f + fabsf(dir_y)) * 3.f * OPT(cursor_trail_particle_speed);
        p->rotation_speed = (next_particle_float(ct) - 0.5f) * 1.57079632679f * OPT(cursor_trail_particle_curl);
        p->lifetime = t * particle_lifetime;
        p->color = WD.screen->last_rendered.cursor_bg;
    }
}

static void
update_cursor_trail_corners(CursorTrail *ct, ndc_coords g, monotonic_t now, OSWindow *os_window, Window *w) {
    // the trail corners move towards the cursor corner at a speed proportional to their distance from the cursor corner.
    // equivalent to exponential ease out animation.
    static const int corner_index[2][4] = {{1, 1, 0, 0}, {0, 1, 1, 0}};

    // the decay time for the trail to reach 1/1024 of its distance from the cursor corner
    float decay_fast = OPT(cursor_trail_decay_fast);
    float decay_slow = OPT(cursor_trail_decay_slow);

    if (should_skip_cursor_trail_update(ct, g, os_window, w)) {
        ct->target_updated = false;
        for (int i = 0; i < 4; ++i) {
            ct->corner_x[i] = EDGE(x, corner_index[0][i]);
            ct->corner_y[i] = EDGE(y, corner_index[1][i]);
        }
    } else if (ct->updated_at < now) {
        float cursor_center_x = (EDGE(x, 0) + EDGE(x, 1)) * 0.5f;
        float cursor_center_y = (EDGE(y, 0) + EDGE(y, 1)) * 0.5f;
        float cursor_diag_2 = norm(EDGE(x, 1) - EDGE(x, 0), EDGE(y, 1) - EDGE(y, 0)) * 0.5f;
        float dt = (float)monotonic_t_to_s_double(now - ct->updated_at);

        // dot product here is used to dynamically adjust the decay speed of
        // each corner. The closer the corner is to the cursor, the faster it
        // moves.
        float dx[4], dy[4];
        float dot[4]; // dot product of "direction vector" and "cursor center to corner vector"
        for (int i = 0; i < 4; ++i) {
            dx[i] = EDGE(x, corner_index[0][i]) - ct->corner_x[i];
            dy[i] = EDGE(y, corner_index[1][i]) - ct->corner_y[i];
            if (fabsf(dx[i]) < 1e-6 && fabsf(dy[i]) < 1e-6) {
                dx[i] = dy[i] = 0.0f;
                dot[i] = 0.0f;
                continue;
            }
            dot[i] = (dx[i] * (EDGE(x, corner_index[0][i]) - cursor_center_x) + dy[i] * (EDGE(y, corner_index[1][i]) - cursor_center_y)) / cursor_diag_2 /
                     norm(dx[i], dy[i]);
        }
        float min_dot = FLT_MAX, max_dot = -FLT_MAX;
        for (int i = 0; i < 4; ++i) {
            min_dot = fminf(min_dot, dot[i]);
            max_dot = fmaxf(max_dot, dot[i]);
        }

        for (int i = 0; i < 4; ++i) {
            if ((dx[i] == 0 && dy[i] == 0) || min_dot == FLT_MAX) { continue; }

            float decay = (min_dot == max_dot) ? decay_slow : decay_slow + (decay_fast - decay_slow) * (dot[i] - min_dot) / (max_dot - min_dot);
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
    ct->target_updated = false;
    ndc_coords g = {
        .xstart = gl_pos_x(w->render_data.geometry.left, os_window->viewport_width),
        .ystart = gl_pos_y(w->render_data.geometry.top, os_window->viewport_height),
        .dx = gl_size(w->render_data.screen->cell_size.width, os_window->viewport_width),
        .dy = gl_size(w->render_data.screen->cell_size.height, os_window->viewport_height),
    };
    bool had_prev_edge = ct->prev_edge_valid;
    if (!WD.screen->paused_rendering.expires_at && OPT(cursor_trail) <= now - WD.screen->cursor->position_changed_by_client_at) {
        update_cursor_trail_target(ct, w, g);
    }
    if (ct->target_updated && had_prev_edge) ct->cursor_changed_at = now;

    const bool particles_were_rendering = ct->num_particles > 0;
    if (OPT(cursor_trail_particles)) update_cursor_particles(ct, w, now, os_window, had_prev_edge);
    else {
        ct->num_particles = 0;
        ct->particle_count_remainder = 0.f;
    }
    update_cursor_trail_corners(ct, g, now, os_window, w);
    update_cursor_trail_opacity(ct, w, now);

    bool needs_render_prev = ct->needs_render;
    update_cursor_trail_needs_render(ct, w, g);

    ct->updated_at = now;

    // returning true here will cause the cells to be drawn
    return ct->needs_render || needs_render_prev || ct->num_particles > 0 || particles_were_rendering;
}

#undef WD
#undef EDGE
