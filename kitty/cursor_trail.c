#include "state.h"

inline static float
norm(float x, float y) {
    return sqrtf(x * x + y * y);
}

bool
update_cursor_trail(CursorTrail *ct, Window *w, monotonic_t now) {
#define WD w->render_data
    // the trail corners move towards the cursor corner at a speed proportional to their distance from the cursor corner.
    // equivalent to exponential ease out animation.
    static const int ci[4][2] = {{1, 0}, {1, 1}, {0, 1}, {0, 0}};
    float cursor_edge_x[2], cursor_edge_y[2];
    cursor_edge_x[0] = WD.xstart + WD.screen->cursor_render_info.x * WD.dx;
    cursor_edge_x[1] = cursor_edge_x[0] + WD.dx;
    cursor_edge_y[0] = WD.ystart - WD.screen->cursor_render_info.y * WD.dy;
    cursor_edge_y[1] = cursor_edge_y[0] - WD.dy;

    // todo - make these configurable
    // the decay time for the trail to reach 1/1024 of its distance from the cursor corner
    float decay_fast = 0.10f;
    float decay_slow = 0.40f;

    if (OPT(input_delay) < now - WD.screen->cursor->updated_at && ct->updated_at < now) {
        float cursor_center_x = (cursor_edge_x[0] + cursor_edge_x[1]) * 0.5f;
        float cursor_center_y = (cursor_edge_y[0] + cursor_edge_y[1]) * 0.5f;
        float cursor_diag_2 = norm(cursor_edge_x[1] - cursor_edge_x[0], cursor_edge_y[1] - cursor_edge_y[0]) * 0.5;
        float dt = monotonic_t_to_s_double(now - ct->updated_at);

        for (int i = 0; i < 4; ++i) {
            float dx = cursor_edge_x[ci[i][0]] - ct->corner_x[i];
            float dy = cursor_edge_y[ci[i][1]] - ct->corner_y[i];
            float dist = norm(dx, dy);
            if (dist == 0) {
                continue;
            }
            float dot = (dx * (cursor_edge_x[ci[i][0]] - cursor_center_x) +
                dy * (cursor_edge_y[ci[i][1]] - cursor_center_y)) /
                cursor_diag_2 / dist;

            float decay_seconds = decay_slow + (decay_fast - decay_slow) * (1.0f + dot) * 0.5f;
            float step = 1.0f - 1.0f / exp2f(10.0f * dt / decay_seconds);

            ct->corner_x[i] += dx * step;
            ct->corner_y[i] += dy * step;
        }
    }
    ct->updated_at = now;
    for (int i = 0; i < 4; ++i) {
        float dx = cursor_edge_x[ci[i][0]] - ct->corner_x[i];
        float dy = cursor_edge_y[ci[i][1]] - ct->corner_y[i];
        if (dx * dx + dy * dy >= 1e-6) {
            return true;
        }
    }
    return false;
}
