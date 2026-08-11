#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Pond ripple effect — concentric expanding rings centered on pointer-left-button-press.
// animation_progress (0 → 1) drives the wavefront expansion over the pipeline duration.
// 3D lighting via analytic surface normals and Blinn-Phong specular highlights.

import kitty_custom_shader_types;

// Maximum wavefront radius at animation_progress=1 (aspect-corrected UV units).
static const float WAVE_SPEED = 0.45;
// Spatial frequency of the rings (cycles per aspect-corrected UV unit).
static const float WAVE_FREQUENCY = 14.0;
// Starting half-width of the Gaussian envelope (expands as animation_progress increases).
static const float WAVE_WIDTH = 0.055;
// Peak radial UV displacement at the wavecrest.
static const float AMPLITUDE = 0.010;
// Scale applied to the wave gradient when constructing the surface normal.
static const float NORMAL_SCALE = 8.0;
// Blinn-Phong shininess exponent — higher values give a sharper, more mirror-like glint.
static const float SHININESS = 64.0;
// Peak specular contribution at the wave crest facing the light.
static const float SPECULAR_STRENGTH = 0.40;
// Subtle diffuse shading that rounds each ring into a 3D ridge.
static const float DIFFUSE_STRENGTH = 0.10;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;
    float aspect = pixelDims.x / pixelDims.y;

    // d.mouse_pos.zw is the UV position of the last left-button press (y=0 at bottom).
    float2 center = d.mouse_pos.zw;

    // Aspect-corrected vector from the click center to this pixel.
    float2 delta = (t.pos - center) * float2(aspect, 1.0);
    float dist = length(delta);
    float2 dir = delta / max(dist, 1e-5);

    // Wavefront radius advances linearly with animation_progress.
    float front = WAVE_SPEED * t.animation_progress;

    // Signed distance from the wavefront (negative = wave has passed, positive = not yet reached).
    float behind = dist - front;

    // Gaussian spatial envelope centered at the wavefront; grows in width over time.
    float sigma = WAVE_WIDTH * (1.0 + t.animation_progress);
    float env = exp(-behind * behind / (2.0 * sigma * sigma));

    // Causality: suppress any energy ahead of the wavefront.
    env *= 1.0 - smoothstep(-0.01, 0.02, behind);

    // Temporal amplitude decay as the wave expands outward.
    float decay = pow(1.0 - t.animation_progress, 0.7);

    float k = WAVE_FREQUENCY * 6.28318530718;
    float wave = sin(behind * k);

    // Analytic derivative of wave height h = wave * env * decay w.r.t. dist.
    // d(wave)/d(behind) = k*cos(k*behind); d(env)/d(behind) = -behind/sigma^2 * env.
    float dh_ddist = (k * cos(behind * k) - wave * behind / (sigma * sigma)) * env * decay;

    // Surface gradient in aspect-corrected UV space; dir is the unit radial vector.
    float2 grad = dh_ddist * dir;

    // Surface normal: xy from negated gradient (slope), z pointing out of the screen.
    float3 N = normalize(float3(-grad * AMPLITUDE * NORMAL_SCALE, 1.0));

    // Directional light from upper-right in screen space (y points up in UV, z out of screen).
    float3 L = normalize(float3(0.5, 0.7, 1.0));
    // Viewer looks straight into the screen.
    float3 V = float3(0.0, 0.0, 1.0);
    // Blinn-Phong half-vector.
    float3 H = normalize(L + V);

    float diffuse = max(dot(N, L), 0.0);
    float specular = pow(max(dot(N, H), 0.0), SHININESS);

    // Radial UV displacement: push pixels away from center at crests, pull inward at troughs.
    float2 warpedUV = clamp(t.pos + dir * (wave * env * decay * AMPLITUDE), float2(0.0), float2(1.0));

    // Sample the terminal backbuffer at the displaced position.
    float4 result = t.backbuffer.Sample(warpedUV);

    // 3D lighting: diffuse rounds each ring into a ridge, specular gives directional glints.
    float lighting = 1.0 + diffuse * DIFFUSE_STRENGTH * env * decay + specular * SPECULAR_STRENGTH * env * decay;
    result.rgb *= lighting;

    return result;
}
