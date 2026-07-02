#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

module hsluv;

// Helper Functions
float divide(float num, float denom) {
    return num / (abs(denom) + 1e-15) * sign(denom);
}

float3 divide(float3 num, float3 denom) {
    return num / (abs(denom) + 1e-15) * sign(denom);
}

float3 hsluv_intersectLineLine(float3 line1x, float3 line1y, float3 line2x, float3 line2y) {
    return (line1y - line2y) / (line2x - line1x);
}

float3 hsluv_distanceFromPole(float3 pointx, float3 pointy) {
    return sqrt(pointx * pointx + pointy * pointy);
}

float3 hsluv_lengthOfRayUntilIntersect(float theta, float3 x, float3 y) {
    float3 len = divide(y, sin(theta) - x * cos(theta));
    len = lerp(len, (float3)1000.0, step(len, (float3)0.0));
    return len;
}

float hsluv_maxSafeChromaForL(float L) {
    // Transposed from GLSL column-major constructor to Slang row-major layout
    float3x3 m2 = float3x3(
         3.2409699419045214, -1.5373831775700935, -0.49861076029300328,
        -0.96924363628087983, 1.8759675015077207,  0.041555057407175613,
         0.055630079696993609,-0.20397695888897657, 1.0569715142428786
    );

    float sub0 = L + 16.0;
    float sub1 = sub0 * sub0 * sub0 * 0.000000641;
    float sub2 = lerp(L / 903.2962962962963, sub1, step(0.0088564516790356308, sub1));

    float3 top1   = (284517.0 * m2[0] - 94839.0  * m2[2]) * sub2;
    float3 bottom = (632260.0 * m2[2] - 126452.0 * m2[1]) * sub2;
    float3 top2   = (838422.0 * m2[2] + 769860.0 * m2[1] + 731718.0 * m2[0]) * L * sub2;

    float3 bounds0x = top1 / bottom;
    float3 bounds0y = top2 / bottom;

    float3 bounds1x =              top1 / (bottom + 126452.0);
    float3 bounds1y = (top2 - 769860.0 * L) / (bottom + 126452.0);

    float3 xs0 = hsluv_intersectLineLine(bounds0x, bounds0y, -1.0 / bounds0x, (float3)0.0);
    float3 xs1 = hsluv_intersectLineLine(bounds1x, bounds1y, -1.0 / bounds1x, (float3)0.0);

    float3 lengths0 = hsluv_distanceFromPole(xs0, bounds0y + xs0 * bounds0x);
    float3 lengths1 = hsluv_distanceFromPole(xs1, bounds1y + xs1 * bounds1x);

    return min(lengths0.x,
           min(lengths1.x,
           min(lengths0.y,
           min(lengths1.y,
           min(lengths0.z,
               lengths1.z)))));
}

float hsluv_maxChromaForLH(float L, float H) {
    float hrad = radians(H);

    // Transposed from GLSL column-major constructor to Slang row-major layout
    float3x3 m2 = float3x3(
         3.2409699419045214, -1.5373831775700935, -0.49861076029300328,
        -0.96924363628087983, 1.8759675015077207,  0.041555057407175613,
         0.055630079696993609,-0.20397695888897657, 1.0569715142428786
    );

    float sub1 = pow(L + 16.0, 3.0) / 1560896.0;
    float sub2 = lerp(L / 903.2962962962963, sub1, step(0.0088564516790356308, sub1));

    float3 top1   = (284517.0 * m2[0] - 94839.0  * m2[2]) * sub2;
    float3 bottom = (632260.0 * m2[2] - 126452.0 * m2[1]) * sub2;
    float3 top2   = (838422.0 * m2[2] + 769860.0 * m2[1] + 731718.0 * m2[0]) * L * sub2;

    float3 bound0x = top1 / bottom;
    float3 bound0y = top2 / bottom;

    float3 bound1x =              top1 / (bottom + 126452.0);
    float3 bound1y = (top2 - 769860.0 * L) / (bottom + 126452.0);

    float3 lengths0 = hsluv_lengthOfRayUntilIntersect(hrad, bound0x, bound0y);
    float3 lengths1 = hsluv_lengthOfRayUntilIntersect(hrad, bound1x, bound1y);

    return min(lengths0.x,
           min(lengths1.x,
           min(lengths0.y,
           min(lengths1.y,
           min(lengths0.z,
               lengths1.z)))));
}

float3 hsluv_fromLinear(float3 c) {
    return lerp(c * 12.92, 1.055 * pow(max(c, (float3)0), (float3)(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

float3 hsluv_toLinear(float3 c) {
    return lerp(c / 12.92, pow(max((c + 0.055) / (1.0 + 0.055), (float3)0), (float3)2.4), step(0.04045, c));
}

float hsluv_yToL(float Y) {
    return lerp(Y * 903.2962962962963, 116.0 * pow(max(Y, 0), 1.0 / 3.0) - 16.0, step(0.0088564516790356308, Y));
}

float hsluv_lToY(float L) {
    return lerp(L / 903.2962962962963, pow((max(L, 0) + 16.0) / 116.0, 3.0), step(8.0, L));
}

float3 xyzToRgb(float3 tuple) {
    // Transposed layout from GLSL column-major matrix construction
    const float3x3 m = float3x3(
        3.2409699419045214,  -0.96924363628087983,  0.055630079696993609,
       -1.5373831775700935,   1.8759675015077207,  -0.20397695888897657,
       -0.49861076029300328,  0.041555057407175613, 1.0569715142428786
    );
    // GLSL `tuple * m` is transformed to Slang/HLSL `mul(m, tuple)`
    return hsluv_fromLinear(mul(m, tuple));
}

float3 rgbToXyz(float3 tuple) {
    // Transposed layout from GLSL column-major matrix construction
    const float3x3 m = float3x3(
        0.41239079926595948,  0.21263900587151036,  0.019330818715591851,
        0.35758433938387796,  0.71516867876775593,  0.11919477979462599,
        0.18048078840183429,  0.072192315360733715, 0.95053215224966058
    );
    // GLSL `tuple * m` is transformed to Slang/HLSL `mul(m, tuple)`
    return mul(m, hsluv_toLinear(tuple));
}

float3 xyzToLuv(float3 tuple) {
    float X = tuple.x;
    float Y = tuple.y;
    float Z = tuple.z;

    float L = hsluv_yToL(Y);
    float div = 1.0 / max(dot(tuple, float3(1, 15, 3)), 1e-15);

    return float3(
        1.0,
        (52.0 * (X * div) - 2.57179),
        (117.0 * (Y * div) - 6.08816)
    ) * L;
}

float3 luvToXyz(float3 tuple) {
    float L = tuple.x;

    float U = divide(tuple.y, 13.0 * L) + 0.19783000664283681;
    float V = divide(tuple.z, 13.0 * L) + 0.468319994938791;

    float Y = hsluv_lToY(L);
    float X = 2.25 * U * Y / V;
    float Z = (3.0 / V - 5.0) * Y - (X / 3.0);

    return float3(X, Y, Z);
}

float3 luvToLch(float3 tuple) {
    float L = tuple.x;
    float U = tuple.y;
    float V = tuple.z;

    float C = length(tuple.yz);
    float H = degrees(atan2(V, U)); // Slang standard library uses atan2(y, x)
    H += 360.0 * step(H, 0.0);

    return float3(L, C, H);
}

float3 lchToLuv(float3 tuple) {
    float hrad = radians(tuple.z);
    return float3(
        tuple.x,
        cos(hrad) * tuple.y,
        sin(hrad) * tuple.y
    );
}

float3 hsluvToLch(float3 tuple) {
    tuple.y *= hsluv_maxChromaForLH(tuple.z, tuple.x) * 0.01;
    return tuple.zyx;
}

float3 lchToHsluv(float3 tuple) {
    tuple.y = divide(tuple.y, hsluv_maxChromaForLH(tuple.x, tuple.z) * 0.01);
    return tuple.zyx;
}

float3 lchToRgb(float3 tuple) {
    return xyzToRgb(luvToXyz(lchToLuv(tuple)));
}

float3 rgbToLch(float3 tuple) {
    return luvToLch(xyzToLuv(rgbToXyz(tuple)));
}

public float3 hsluvToRgb(float3 tuple) {
    return lchToRgb(hsluvToLch(tuple));
}

public float3 rgbToHsluv(float3 tuple) {
    return lchToHsluv(rgbToLch(tuple));
}

float3 luvToRgb(float3 tuple) {
    return xyzToRgb(luvToXyz(tuple));
}

