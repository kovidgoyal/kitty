#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

module linear2srgb;

// Scalar sRGB to Linear conversion
public float srgb2linear(float x) {
    float lower = x / 12.92;
    float upper = pow((x + 0.055f) / 1.055f, 2.4f);

    // GLSL mix() is replaced by Slang's lerp()
    return lerp(lower, upper, step(0.04045f, x));
}

// Scalar Linear to sRGB conversion
public float linear2srgb(float x) {
    float lower = 12.92 * x;
    float upper = 1.055 * pow(x, 1.0f / 2.4f) - 0.055f;

    return lerp(lower, upper, step(0.0031308f, x));
}

// Vector Linear to sRGB conversion
public float3 linear2srgb(float3 x) {
    float3 lower = 12.92 * x;
    float3 upper = 1.055 * pow(x, float3(1.0f / 2.4f)) - 0.055f;

    return lerp(lower, upper, step(float3(0.0031308f), x));
}

// Vector sRGB to Linear conversion
public float3 srgb2linear(float3 c) {
    // You can call the scalar version per-component,
    // or pass the whole vector if you overload it for float3.
    return float3(srgb2linear(c.r), srgb2linear(c.g), srgb2linear(c.b));
}

