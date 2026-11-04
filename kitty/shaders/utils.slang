#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

module utils;

// Return 0 if x < 1 otherwise 1
public __generic<T : __BuiltinFloatingPointType, int N = 1> vector<T, N>
zero_or_one(vector<T, N> x) {
    return step((vector<T, N>)1.0f, x);
}

// condition must be zero or one. When 1 thenval is returned otherwise elseval
public __generic<T : __BuiltinFloatingPointType, int N = 1> vector<T, N>
if_one_then(vector<T, N> condition, vector<T, N> thenval, vector<T, N> elseval) {
    return lerp(elseval, thenval, condition);
}

// a < b ? thenval : elseval
public __generic<T : __BuiltinFloatingPointType, int N = 1> vector<T, N>
if_less_than(vector<T, N> a, vector<T, N> b, vector<T, N> thenval, vector<T, N> elseval) {
    return lerp(thenval, elseval, step(b, a));
}

// Replaces vec4(rgb * a, a)
public float4
vec4_premul(float3 rgb, float a) {
    return float4(rgb * a, a);
}

// Overloaded variation replacing vec4(rgba.rgb * rgba.a, rgba.a)
public float4
vec4_premul(float4 rgba) {
    return float4(rgba.rgb * rgba.a, rgba.a);
}

// Reading texels and texture sizes of combined texture samplers. slangc
// (2026.14) generates broken MSL for Load(), operator[] and GetDimensions()
// of combined texture samplers: it passes the sampler in place of the
// arguments. Metal splits them into a texture and a sampler, which are $0
// and $1 in the MSL intrinsics below, the arguments follow them.
public __generic<T : ITexelElement> T
texel_fetch(Sampler2D<T> s, int2 pos) {
    __target_switch {
    case metal: __intrinsic_asm "$0.read(uint2($2))$z";
    default: return s[pos];
    }
}

public __generic<T : ITexelElement> T
texel_fetch(Sampler2DArray<T> s, int3 pos) {
    __target_switch {
    case metal: __intrinsic_asm "$0.read(uint2(($2).xy), uint(($2).z))$z";
    default: return s[pos];
    }
}

public __generic<T : ITexelElement> int2
texture_size(Sampler2D<T> s) {
    __target_switch {
    case metal: __intrinsic_asm "int2($0.get_width(), $0.get_height())";
    default:
        int w, h;
        s.GetDimensions(w, h);
        return int2(w, h);
    }
}

public __generic<T : ITexelElement> int3
texture_size(Sampler2DArray<T> s) {
    __target_switch {
    case metal: __intrinsic_asm "int3($0.get_width(), $0.get_height(), $0.get_array_size())";
    default:
        int w, h, l;
        s.GetDimensions(w, h, l);
        return int3(w, h, l);
    }
}
