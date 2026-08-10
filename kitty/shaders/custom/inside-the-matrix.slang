#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Inside the Matrix https://www.shadertoy.com/view/4t3BWl
// runes code by FabriceNeyret2 / otaviogood (https://www.shadertoy.com/view/4ltyDM)
// Ported to Slang for kitty custom shader system

import kitty_custom_shader_types;

static const int   ITERATIONS        = 40;
static const float SPEED             = 0.5f;
static const float STRIP_CHARS_MIN   = 7.0f;
static const float STRIP_CHARS_MAX   = 40.0f;
static const float STRIP_CHAR_HEIGHT = 0.15f;
static const float STRIP_CHAR_WIDTH  = 0.10f;
static const float ZCELL_SIZE        = STRIP_CHAR_HEIGHT * STRIP_CHARS_MAX;
static const float XYCELL_SIZE       = 12.0f * STRIP_CHAR_WIDTH;
static const int   BLOCK_SIZE        = 10;
static const int   BLOCK_GAP         = 2;
static const float WALK_SPEED        = 0.5f * XYCELL_SIZE;
static const float BLOCKS_BEFORE_TURN = 3.0f;
static const float PI                = 3.14159265359f;

// ---- random ----

float hash(float v) {
    return frac(sin(v) * 43758.5453123f);
}

float hash(float2 v) {
    return hash(dot(v, float2(5.3983f, 5.4427f)));
}

float2 hash2(float2 v) {
    // GLSL: v * mat2(127.1, 311.7, 269.5, 183.3)  [column-major]
    // Slang float2x2 is row-major; transpose the GLSL column-major layout.
    v = mul(v, float2x2(127.1f, 269.5f,
                        311.7f, 183.3f));
    return frac(sin(v) * 43758.5453123f);
}

float4 hash4(float2 v) {
    // GLSL: v * mat4x2(127.1,311.7, 269.5,183.3, 113.5,271.9, 246.1,124.6)
    // mat4x2 = 4 cols × 2 rows; transpose into float2x4 (2 rows × 4 cols).
    float4 p = mul(v, float2x4(127.1f, 269.5f, 113.5f, 246.1f,
                               311.7f, 183.3f, 271.9f, 124.6f));
    return frac(sin(p) * 43758.5453123f);
}

float4 hash4(float3 v) {
    // GLSL: v * mat4x3(127.1,311.7,74.7, 269.5,183.3,246.1, 113.5,271.9,124.6, 271.9,269.5,311.7)
    // mat4x3 = 4 cols × 3 rows; transpose into float3x4 (3 rows × 4 cols).
    float4 p = mul(v, float3x4(127.1f, 269.5f, 113.5f, 271.9f,
                               311.7f, 183.3f, 271.9f, 269.5f,
                                74.7f, 246.1f, 124.6f, 311.7f));
    return frac(sin(p) * 43758.5453123f);
}

// ---- symbols ----

float rune_line(float2 p, float2 a, float2 b) {
    p -= a;
    b -= a;
    float h = clamp(dot(p, b) / dot(b, b), 0.0f, 1.0f);
    return length(p - b * h);
}

float rune(float2 U, float2 seed, float highlight) {
    float d = 1e5f;
    [ForceUnroll]
    for (int i = 0; i < 4; i++) {
        float4 pos = hash4(seed);
        seed += 1.0f;

        // each rune touches the edge of its box on all 4 sides
        // with [ForceUnroll] these become compile-time constant selects
        pos.y = (i == 0) ? 0.0f   : pos.y;
        pos.x = (i == 1) ? 0.999f : pos.x;
        pos.x = (i == 2) ? 0.0f   : pos.x;
        pos.y = (i == 3) ? 0.999f : pos.y;

        float4 snaps = float4(2.0f, 3.0f, 2.0f, 3.0f);
        pos = (floor(pos * snaps) + 0.5f) / snaps;

        if (any(pos.xy != pos.zw))
            d = min(d, rune_line(U, pos.xy, pos.zw + 0.001f));
    }
    return smoothstep(0.1f, 0.0f, d) + highlight * smoothstep(0.4f, 0.0f, d);
}

float random_char(float2 outer, float2 inner, float highlight) {
    float2 seed = float2(dot(outer, float2(269.5f, 183.3f)),
                         dot(outer, float2(113.5f, 271.9f)));
    return rune(inner, seed, highlight);
}

// ---- digital rain ----

float3 rain(float3 ro3, float3 rd3, float time) {
    float4 result = float4(0.0f, 0.0f, 0.0f, 0.0f);

    float2 ro2 = ro3.xy;
    float2 rd2 = normalize(rd3.xy);

    bool prefer_dx = abs(rd2.x) > abs(rd2.y);
    float t3_to_t2 = prefer_dx ? rd3.x / rd2.x : rd3.y / rd2.y;

    int3 cell_side  = int3(step(0.0f, rd3));
    int3 cell_shift = int3(sign(rd3));

    float t2 = 0.0f;
    int2 next_cell = int2(floor(ro2 / XYCELL_SIZE));

    [ForceUnroll]
    for (int iter = 0; iter < ITERATIONS; iter++) {
        int2  cell = next_cell;
        float t2s  = t2;

        float2 side    = float2(next_cell + cell_side.xy) * XYCELL_SIZE;
        float2 t2_side = (side - ro2) / rd2;

        // branchless cell-side selection
        bool pick_x  = t2_side.x < t2_side.y;
        t2           = pick_x ? t2_side.x : t2_side.y;
        next_cell.x += pick_x ? cell_shift.x : 0;
        next_cell.y += pick_x ? 0 : cell_shift.y;

        // skip gap cells
        float2 cell_in_block = frac(float2(cell) / float(BLOCK_SIZE));
        float  gap           = float(BLOCK_GAP) / float(BLOCK_SIZE);
        if (cell_in_block.x < gap || cell_in_block.y < gap ||
            (cell_in_block.x < (gap + 0.1f) && cell_in_block.y < (gap + 0.1f)))
            continue;

        float t3s     = t2s / t3_to_t2;
        float pos_z   = ro3.z + rd3.z * t3s;
        float xh      = hash(float2(cell));
        float z_shift = xh * 11.0f - time * (0.5f + xh + xh * xh + pow(xh, 16.0f) * 3.0f);
        float czs     = floor(z_shift / STRIP_CHAR_HEIGHT);
        z_shift       = czs * STRIP_CHAR_HEIGHT;
        int zcell     = int(floor((pos_z - z_shift) / ZCELL_SIZE));

        [ForceUnroll]
        for (int j = 0; j < 2; j++) {
            float4 ch  = hash4(float3(int3(cell, zcell)));
            float4 ch2 = frac(ch * float4(127.1f, 311.7f, 271.9f, 124.6f));

            float chars_count   = ch.w * (STRIP_CHARS_MAX - STRIP_CHARS_MIN) + STRIP_CHARS_MIN;
            float target_length = chars_count * STRIP_CHAR_HEIGHT;
            float target_rad    = STRIP_CHAR_WIDTH * 0.5f;
            float target_z      = float(zcell) * ZCELL_SIZE + z_shift
                                 + ch.z * (ZCELL_SIZE - target_length);
            float2 target       = float2(cell) * XYCELL_SIZE + target_rad
                                 + ch.xy * (XYCELL_SIZE - target_rad * 2.0f);

            float2 sv   = target - ro2;
            float tmin  = dot(sv, rd2);
            if (tmin >= t2s && tmin <= t2) {
                float u = sv.x * rd2.y - sv.y * rd2.x;
                if (abs(u) < target_rad) {
                    u = (u / target_rad + 1.0f) * 0.5f;
                    float z = ro3.z + rd3.z * tmin / t3_to_t2;
                    float v = (z - target_z) / target_length;
                    if (v >= 0.0f && v < 1.0f) {
                        float c          = floor(v * chars_count);
                        float q          = frac(v * chars_count);
                        float2 char_hash = hash2(float2(c + czs, ch2.x));
                        if (char_hash.x >= 0.1f || c == 0.0f) {
                            float time_factor = floor(
                                c == 0.0f ? time
                                          : time * (ch2.z + ch2.w * ch2.w * 4.0f
                                                           * pow(char_hash.y, 4.0f)));
                            float a = random_char(float2(char_hash.x, time_factor),
                                                  float2(u, q),
                                                  max(1.0f, 3.0f - c * 0.5f) * 0.2f);
                            a *= clamp((chars_count - 0.5f - c) * 0.5f, 0.0f, 1.0f);
                            if (a > 0.0f) {
                                float attenuation = 1.0f + pow(0.06f * tmin / t3_to_t2, 2.0f);
                                float3 col = (c == 0.0f
                                    ? float3(0.67f, 1.0f, 0.82f)
                                    : float3(0.25f, 0.80f, 0.40f)) / attenuation;
                                float a1   = result.a;
                                result.a   = a1 + (1.0f - a1) * a;
                                result.xyz = (result.xyz * a1 + col * (1.0f - a1) * a) / result.a;
                                if (result.a > 0.98f)
                                    return result.xyz;
                            }
                        }
                    }
                }
            }
            zcell += cell_shift.z;
        }
    }
    return result.xyz * result.a;
}

// ---- camera helpers ----
// For M*v in GLSL with column-major constructor, Slang needs the same values
// re-read as row-major (i.e. transposed GLSL column-major == correct Slang row-major).

float2 rotate2D(float2 v, float angle) {
    float s = sin(angle), c = cos(angle);
    // GLSL: mat2(c,-s, s,c)*v  →  rows: (c,s),(-s,c)
    return mul(float2x2(c, s, -s, c), v);
}

float3 rotateX(float3 v, float angle) {
    float s = sin(angle), c = cos(angle);
    // GLSL: mat3(1,0,0, 0,c,-s, 0,s,c)*v  →  rows: (1,0,0),(0,c,s),(0,-s,c)
    return mul(float3x3(1.0f, 0.0f, 0.0f,
                        0.0f,    c,    s,
                        0.0f,   -s,    c), v);
}

float3 rotateY(float3 v, float angle) {
    float s = sin(angle), c = cos(angle);
    // GLSL: mat3(c,0,-s, 0,1,0, s,0,c)*v  →  rows: (c,0,s),(0,1,0),(-s,0,c)
    return mul(float3x3(   c, 0.0f,    s,
                        0.0f, 1.0f, 0.0f,
                          -s, 0.0f,    c), v);
}

float3 rotateZ(float3 v, float angle) {
    float s = sin(angle), c = cos(angle);
    // GLSL: mat3(c,-s,0, s,c,0, 0,0,1)*v  →  rows: (c,s,0),(-s,c,0),(0,0,1)
    return mul(float3x3(   c,    s, 0.0f,
                          -s,    c, 0.0f,
                        0.0f, 0.0f, 1.0f), v);
}

float smoothstep1(float x) { return smoothstep(0.0f, 1.0f, x); }

// ---- entry point ----

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float2 uv   = t.pos;
    float  time = fmod(d.timestamp, 300.0f) * SPEED;

    const float turn_rad      = 0.25f / BLOCKS_BEFORE_TURN;
    const float turn_abs_time = (PI * 0.5f * turn_rad) * 1.5f;
    const float turn_time     = turn_abs_time / (1.0f - 2.0f * turn_rad + turn_abs_time);

    float level1_size = float(BLOCK_SIZE) * BLOCKS_BEFORE_TURN * XYCELL_SIZE;
    float gap_size    = float(BLOCK_GAP) * XYCELL_SIZE;

    float3 ro = float3(gap_size * 0.5f, gap_size * 0.5f, 0.0f);
    float3 rd = float3(uv.x, 2.0f, uv.y);

    float tq = frac(time / (level1_size * 4.0f * 4.0f) * WALK_SPEED);
    float t8 = frac(tq * 4.0f);
    float t1 = frac(t8 * 8.0f);

    float2 prev, dir;
    if      (tq < 0.25f) { prev = float2(0.0f, 0.0f); dir = float2(0.0f,  1.0f); }
    else if (tq < 0.50f) { prev = float2(0.0f, 1.0f); dir = float2(1.0f,  0.0f); }
    else if (tq < 0.75f) { prev = float2(1.0f, 1.0f); dir = float2(0.0f, -1.0f); }
    else                 { prev = float2(1.0f, 0.0f); dir = float2(-1.0f, 0.0f); }

    float angle = floor(tq * 4.0f);
    prev *= 4.0f;

    const float first_turn_look_angle   = 0.4f;
    const float second_turn_drift_angle = 0.5f;
    const float fifth_turn_drift_angle  = 0.25f;

    float2 dirL = rotate2D(dir, -PI * 0.5f);
    float2 dirR = -dirL;
    float2 turn;
    float  turn_sign      = 0.0f;
    float  up_down        = 0.0f;
    float  rotate_on_turns = 1.0f;
    float  roll_on_turns   = 1.0f;
    float  add_angel       = 0.0f;

    if (t8 < 0.125f) {
        turn = dirL; turn_sign = -1.0f;
        angle -= first_turn_look_angle * (
            max(0.0f, t1 - (1.0f - turn_time * 2.0f)) / turn_time
          - max(0.0f, t1 - (1.0f - turn_time))        / turn_time * 2.5f);
        roll_on_turns = 0.0f;
    } else if (t8 < 0.250f) {
        prev += dir; turn = dir; dir = dirL;
        angle -= 1.0f; turn_sign = 1.0f;
        add_angel += first_turn_look_angle * 0.5f
                   + (-first_turn_look_angle * 0.5f + 1.0f + second_turn_drift_angle) * t1;
        rotate_on_turns = 0.0f; roll_on_turns = 0.0f;
    } else if (t8 < 0.375f) {
        prev += dir + dirL; turn = dirR; turn_sign = 1.0f;
        add_angel += second_turn_drift_angle * sqrt(1.0f - t1);
    } else if (t8 < 0.500f) {
        prev += dir + dir + dirL; turn = dirR; dir = dirR;
        angle += 1.0f; turn_sign = 0.0f;
        up_down = sin(t1 * PI) * 0.37f;
    } else if (t8 < 0.625f) {
        prev += dir + dir; turn = dir; dir = dirR;
        angle += 1.0f; turn_sign = -1.0f;
        up_down = sin(-min(1.0f, t1 / (1.0f - turn_time)) * PI) * 0.37f;
    } else if (t8 < 0.750f) {
        prev += dir + dir + dirR; turn = dirL; turn_sign = -1.0f;
        add_angel -= (fifth_turn_drift_angle + 1.0f) * smoothstep1(t1);
        rotate_on_turns = 0.0f; roll_on_turns = 0.0f;
    } else if (t8 < 0.875f) {
        prev += dir + dir + dir + dirR; turn = dir; dir = dirL;
        angle -= 1.0f; turn_sign = 1.0f;
        add_angel -= fifth_turn_drift_angle
                   - smoothstep1(t1) * (fifth_turn_drift_angle * 2.0f + 1.0f);
        rotate_on_turns = 0.0f; roll_on_turns = 0.0f;
    } else {
        prev += dir + dir + dir; turn = dirR; turn_sign = 1.0f;
        angle += fifth_turn_drift_angle * (
            1.5f * min(1.0f, (1.0f - t1) / turn_time)
          - 0.5f * smoothstep1(1.0f - min(1.0f, t1 / (1.0f - turn_time))));
    }

    if (d.mouse_button_pressed.x != 0) {
        float2 mouse = 2.0f * d.mouse_pos.xy - 1.0f;
        up_down = -0.7f * mouse.y;
        angle += mouse.x;
        rotate_on_turns = 1.0f;
        roll_on_turns = 0.0f;
    } else {
        angle += add_angel;
    }

    rd = rotateX(rd, up_down);

    float2 p;
    if (turn_sign == 0.0f) {
        p = prev + dir * (turn_rad + t1);
    } else if (t1 > (1.0f - turn_time)) {
        float  tr  = (t1 - (1.0f - turn_time)) / turn_time;
        float2 ctr = prev + dir * (1.0f - turn_rad) + turn * turn_rad;
        p   = ctr + turn_rad * rotate2D(dir, (tr - 1.0f) * turn_sign * PI * 0.5f);
        angle += tr * turn_sign * rotate_on_turns;
        rd = rotateY(rd, sin(tr * turn_sign * PI) * 0.2f * roll_on_turns);
    } else {
        t1 /= (1.0f - turn_time);
        p = prev + dir * (turn_rad + (1.0f - turn_rad * 2.0f) * t1);
    }

    rd = rotateZ(rd, angle * PI * 0.5f);
    ro.xy += level1_size * p;
    rd = normalize(rd);
    ro += rd * 0.2f;

    float3 col = rain(ro, rd, time) * 0.25f;

    float4 terminalColor = t.backbuffer.Sample(t.pos);
    float  mask          = 1.2f - step(0.5f, dot(terminalColor.rgb, float3(1.0f, 1.0f, 1.0f)));
    float3 blended       = lerp(terminalColor.rgb * 1.2f, col, mask);

    return float4(blended, terminalColor.a);
}
