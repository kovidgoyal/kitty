#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Particles that fly off the cursor as it moves, in the style of the cursor
// effects in neovide. There are three styles, selected with MODE below:
//
//   railgun   - particles are fired sideways from the path of the cursor, in
//               a slowly turning direction, so they form a spiral.
//   torpedo   - particles are blown backwards from the path of the cursor,
//               like the wake of a torpedo.
//   pixiedust - glittering particles drift gently downwards from the path
//               of the cursor.
//
// Every style has a ready made pipeline, so to use it, add the following to
// kitty.conf:
//     cursor_trail 1
//     custom_shaders cursor-trail-railgun
// or cursor-trail-torpedo or cursor-trail-pixiedust.
//
// You can tune the options below without editing this file. Save a pipeline
// file such as shaders/my-particles.pipeline in your kitty config directory,
// containing, for example:
//     startgroup
//         animation_start cursor-trail-move
//         animation_stop 1300
//         animation_step 16
//         var int MODE 2
//         var float LIFETIME 1.1
//         var float4 PARTICLE_COLOR float4(1, 0.8, 0.2, 1)
//         shaders cursor-trail-default cursor-trail-particles
//     endgroup
// and then use custom_shaders my-particles in kitty.conf. Particles are drawn
// for a few recent cursor moves at a time, so they keep flying while you move
// the cursor again. The number in animation_stop is how many milliseconds
// after the last cursor move to keep drawing, it must be more than
// LIFETIME + EMIT_DURATION, otherwise particles will vanish early. Leave out
// cursor-trail-default to get only the particles without kitty's usual trail.

import kitty_custom_shader_types;

static const int RAILGUN = 0;
static const int TORPEDO = 1;
static const int PIXIEDUST = 2;

// Which style to use, 0 for railgun, 1 for torpedo and 2 for pixiedust.
static const int MODE = RAILGUN;
// The color of the particles. When the alpha is zero, the color of the cursor
// trail is used, see the cursor_trail_color option in kitty.conf.
static const float4 PARTICLE_COLOR = float4(0.0);
// How opaque the particles are, from 0 to 1.
static const float OPACITY = 1.0;
// Maximum number of particles for every cursor move. More looks richer but is
// slower. Values are limited to the range 1..64.
static const int MAX_PARTICLES = 48;
// How many particles to emit for every line height of distance the cursor
// moves, so short moves produce fewer particles than long jumps. At least a few particles are always
// emitted.
static const float PARTICLE_DENSITY = 3.0;
// How long particles live, in seconds. Individual particles live a little
// shorter, at random, so they do not all vanish at the same time.
static const float LIFETIME = 0.8;
// Particles are not emitted all at once, but in sequence as the cursor
// travels from its old position to its new one, taking this many seconds.
static const float EMIT_DURATION = 0.08;
// The radius of the particles, as a fraction of the size of the cursor.
static const float PARTICLE_SIZE = 0.12;
// The speed at which particles are launched, in cursor sizes per second.
static const float SPEED = 20.0;
// How fast particles slow down. Larger values make them stop sooner.
static const float DRAG = 2.5;
// How fast particles fall, in cursor sizes per second per second. Only used
// by pixiedust, as the other styles are too fast to be affected by gravity.
static const float GRAVITY = 8.0;
// How quickly the launch direction turns in the railgun style, in radians
// for every line height of distance the cursor moves.
static const float RAILGUN_PHASE = 1.5;
// How widely particles fan out in the torpedo style, in radians to either
// side of directly backwards.
static const float TORPEDO_SPREAD = 1.0;

static const float TAU = 6.28318530718;
// Noise constant from Dave Hoskins
static const float4 MOD4 = float4(0.1031, 0.1030, 0.0973, 0.1099);

static float4
hash43(float3 p) {
    float4 p4 = frac(float4(p.xyzx) * MOD4);
    p4 += dot(p4, p4.wzxy + 33.33);
    return frac((p4.xxyz + p4.yzzw) * p4.zywx);
}

static float2
rotate(float2 v, float angle) {
    float c = cos(angle), s = sin(angle);
    return float2(c * v.x - s * v.y, s * v.x + c * v.y);
}

// Distance travelled after time t by something launched at unit speed that
// slows down due to DRAG.
static float
drag_distance(float t) {
    return DRAG > 0.0 ? (1.0 - exp(-DRAG * t)) / DRAG : t;
}

// Seconds since move i, negative if there is no such move.
static float
move_age(KittyCustomShaderData d, int i) {
    return d.cursor_trail_history_age[i / 4][i % 4];
}

// Center and size of a cursor rectangle given in UV edges, in pixels.
static float4
rect_center_and_size(float4 edges, float2 pixelDims) {
    float2 lb = float2(edges.x, edges.w) * pixelDims;
    float2 rt = float2(edges.y, edges.z) * pixelDims;
    return float4((lb + rt) * 0.5, abs(rt - lb));
}

// The opacity of the particles from one cursor move at the pixel px.
static float
move_particles(float2 px, float2 from, float2 to, float scale, float lines, float age, float seed) {
    float2 path = to - from;
    float pathLen = length(path);
    float2 dir = pathLen > 0.0 ? path / pathLen : float2(1.0, 0.0);
    float2 perp = float2(-dir.y, dir.x);
    float speed = SPEED * scale;
    float radius = max(PARTICLE_SIZE * scale, 0.75);

    int count = clamp(int(ceil(lines * PARTICLE_DENSITY)), min(4, MAX_PARTICLES), clamp(MAX_PARTICLES, 1, 64));
    float coverage = 0.0;
    for (int i = 0; i < count; i++) {
        float4 r = hash43(float3(float(i), seed, 17.0));
        float4 r2 = hash43(float3(seed, float(i), 59.0));
        // Where along the path the particle starts, 0 is the old cursor position
        float u = (float(i) + r.x) / float(count);
        float t = age - u * EMIT_DURATION;
        float life = LIFETIME * lerp(0.6, 1.0, r.y);
        if (t < 0.0 || t >= life) continue;

        float2 start = lerp(from, to, u) + (r2.xy - 0.5) * scale * 0.5;
        float2 velocity;
        float2 fall = float2(0.0);
        float brightness = 1.0;
        if (MODE == TORPEDO) {
            velocity = rotate(-dir, (r.z * 2.0 - 1.0) * TORPEDO_SPREAD) * lerp(0.4, 1.0, r.w);
        } else if (MODE == PIXIEDUST) {
            velocity = rotate(float2(0.4, 0.0), r.z * TAU) * lerp(0.2, 1.0, r.w);
            fall = float2(0.0, -0.5 * GRAVITY * scale * t * t);
            // Glitter
            brightness = 0.55 + 0.45 * sin(t * 40.0 + r2.z * TAU);
        } else {
            velocity = rotate(perp, u * lines * RAILGUN_PHASE) * lerp(0.7, 1.0, r.w);
        }
        float2 pos = start + velocity * speed * drag_distance(t) + fall;
        float fade = 1.0 - t / life;
        // Particles shrink as they fade
        float rad = radius * lerp(0.5, 1.0, fade);
        // Antialiased disc
        float a = saturate(rad + 0.5 - length(px - pos)) * fade * brightness;
        coverage = max(coverage, a);
    }
    return coverage;
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;
    float2 px = t.pos * pixelDims;
    // Upper bound on how far a particle can get from the path of its cursor move
    float reachPerScale = SPEED * drag_distance(LIFETIME) + 0.5 * (MODE == PIXIEDUST ? GRAVITY * LIFETIME * LIFETIME : 0.0) + PARTICLE_SIZE + 0.5;

    float coverage = 0.0;
    for (int i = 0; i < 8; i++) {
        float age = move_age(d, i);
        // Moves are most recent first, so all remaining ones are unused or older still
        if (age < 0.0 || age >= LIFETIME + EMIT_DURATION) break;
        float4 from = rect_center_and_size(d.cursor_trail_history_from[i], pixelDims);
        float4 to = rect_center_and_size(d.cursor_trail_history_to[i], pixelDims);
        // The width of a beam cursor and the height of an underline cursor
        // are tiny, so use the larger of the two dimensions for scale.
        float scale = max(max(to.z, to.w), 1.0);
        float reach = reachPerScale * scale + 1.0;
        if (any(px < min(from.xy, to.xy) - reach) || any(px > max(from.xy, to.xy) + reach)) continue;
        float lines = length(to.xy - from.xy) / scale;
        // The seed only needs to be stable over the lifetime of the move, so derive it from the end points of the move
        float seed = frac(dot(to.xy - from.xy, float2(0.1371, 0.2113)) + dot(to.xy, float2(0.0173, 0.0291))) * 1000.0;
        coverage = max(coverage, move_particles(px, from.xy, to.xy, scale, lines, age, seed));
    }
    coverage *= OPACITY;
    if (coverage <= 0.0) return color;
    float3 pcol = PARTICLE_COLOR.a > 0.0 ? PARTICLE_COLOR.rgb : d.cursor_trail_color.rgb;
    return float4(lerp(color.rgb, pcol, saturate(coverage)), color.a);
}
