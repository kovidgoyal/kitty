#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Fireworks with Rockets — port of https://www.shadertoy.com/view/4dBGRw
// Ported to Slang for kitty custom shader system

import kitty_custom_shader_types;

static const int NUM_PARTICLES = 128;
static const float BLACK_BLEND_THRESHOLD = 0.4f;
static const float CYCLE_TIME = 6.0f;
static const float PARTICLE_PHASE = 2.0f;

// Pseudo-random in [-1, 1]
float
rand_val(float val, float seed) {
    return cos(val * sin(val * seed) * seed);
}

float
distance2(float2 a, float2 b) {
    float2 d = a - b;
    return dot(d, d);
}

// Diagonal red-and-white barber-pole pattern — branchless
float3
barberpole(float2 pos, float2 rocketpos) {
    float d = fmod(((pos.x - rocketpos.x) + (pos.y - rocketpos.y)) * 20.0f, 2.0f);
    return lerp(float3(1.0f), float3(1.0f, 0.0f, 0.0f), step(1.0f, d));
}

// Draw a single rocket at rocketpos in the supplied coordinate space — branchless
float3
rocket(float2 pos, float2 rocketpos) {
    float3 col = float3(0.0f);
    float absx = abs(rocketpos.x - pos.x);
    float absy = abs(rocketpos.y - pos.y);

    // Wooden stick
    float stick = step(absx, 0.01f) * step(absy, 0.22f);
    col = lerp(col, float3(1.0f, 0.5f, 0.5f), stick);

    // Barber-pole body
    float pole = step(absx, 0.05f) * step(absy, 0.15f);
    col = lerp(col, barberpole(pos, rocketpos), pole);

    // Pointed nose cone
    float pointw = (rocketpos.y - pos.y - 0.25f) * -0.7f;
    float has_point = step(0.1f, rocketpos.y - pos.y);
    float f_point = smoothstep(pointw - 0.001f, pointw + 0.001f, absx);
    col = lerp(col, lerp(float3(1.0f, 0.0f, 0.0f), col, f_point), has_point);

    // Ambient shadow gradient
    float shadow = -0.5f + smoothstep(-0.05f, 0.05f, rocketpos.x - pos.x);
    col *= 0.7f + shadow;

    return col;
}

// Draw the exploding particle burst.
// Particle direction for iteration i is the unit vector at angle i radians,
// precomputed as (cos(i), sin(i)) — equivalent to iteratively applying the
// original 1-radian rotation matrix but eliminates inter-iteration data dependency.
float3
drawParticles(float2 pos, float3 particolor, float time, float2 cpos, float gravity, float seed, float timelength) {
    float3 col = float3(0.0f);

    [ForceUnroll]
    for (int i = 0; i < NUM_PARTICLES; i++) {
        float fi = float(i + 1); // 1-indexed to match original
        float d = rand_val(fi, seed);
        float fade = (fi / float(NUM_PARTICLES)) * time;
        float2 pp = float2(cos(float(i)), sin(float(i))); // unit direction at angle i
        float2 particpos = cpos + time * pp * d;
        col = lerp(particolor / fade, col, smoothstep(0.0f, 0.0001f, distance2(particpos, pos)));
    }
    col *= smoothstep(0.0f, 1.0f, (timelength - time) / timelength);
    return col;
}

// Returns rocket or particles depending on which phase of the cycle we are in
float3
drawFireworks(float time, float2 uv, float3 particolor, float seed) {
    float3 col = float3(0.0f);
    if (time <= 0.0f) return col;

    float tmod = fmod(time, CYCLE_TIME);
    float cycle_id = ceil(time / CYCLE_TIME);

    if (tmod > PARTICLE_PHASE) {
        float2 cpos = float2(rand_val(cycle_id, seed), -0.5f);
        col = drawParticles(uv, particolor, tmod - PARTICLE_PHASE, cpos, 0.5f, cycle_id, seed);
    } else {
        float rx = 3.0f * rand_val(cycle_id, seed);
        float ry = 3.0f * (-0.5f + (PARTICLE_PHASE - tmod));
        col = rocket(uv * 3.0f, float2(rx, ry));
    }
    return col;
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;
    float aspect = pixelDims.x / pixelDims.y;

    // Map to [-aspect, aspect] × [-1, 1] with y=1 at top (matching the original)
    float2 uv = 1.0f - 2.0f * t.pos;
    uv.x *= aspect;
    uv.y = -uv.y;

    float3 col = float3(0.1f, 0.1f, 0.2f);
    col += 0.1f * uv.y; // subtle sky gradient

    float time = d.timestamp;
    col += drawFireworks(time, uv, float3(1.0f, 0.1f, 0.1f), 1.0f);
    col += drawFireworks(time - 2.0f, uv, float3(0.0f, 1.0f, 0.5f), 2.0f);
    col += drawFireworks(time - 4.0f, uv, float3(1.0f, 1.0f, 0.1f), 3.0f);

    float4 terminalColor = t.backbuffer.Sample(t.pos);
    float alpha = step(length(terminalColor.rgb), BLACK_BLEND_THRESHOLD);
    float3 blended = lerp(terminalColor.rgb, col * 0.3f, alpha);

    return float4(blended, terminalColor.a);
}
