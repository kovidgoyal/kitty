#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

module utils;

// Return 0 if x < 1 otherwise 1
public __generic<T : __BuiltinFloatingPointType, int N = 1>
vector<T, N> zero_or_one(vector<T, N> x) {
    return step((vector<T, N>)1.0f, x);
}

// condition must be zero or one. When 1 thenval is returned otherwise elseval
public __generic<T : __BuiltinFloatingPointType, int N = 1>
vector<T, N> if_one_then(vector<T, N> condition, vector<T, N> thenval, vector<T, N> elseval) {
    return lerp(elseval, thenval, condition);
}

// a < b ? thenval : elseval
public __generic<T : __BuiltinFloatingPointType, int N = 1>
vector<T, N> if_less_than(vector<T, N> a, vector<T, N> b, vector<T, N> thenval, vector<T, N> elseval) {
    return lerp(thenval, elseval, step(b, a));
}

// Replaces vec4(rgb * a, a)
public float4 vec4_premul(float3 rgb, float a) {
    return float4(rgb * a, a);
}

// Overloaded variation replacing vec4(rgba.rgb * rgba.a, rgba.a)
public float4 vec4_premul(float4 rgba) {
    return float4(rgba.rgb * rgba.a, rgba.a);
}

