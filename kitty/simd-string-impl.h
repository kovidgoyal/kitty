/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "simd-string.h"
#include <stdalign.h>

#ifndef KITTY_SIMD_LEVEL
#define KITTY_SIMD_LEVEL 128
#endif
#define CONCAT(A, B) A##B
#define CONCAT_EXPAND(A, B) CONCAT(A, B)
#define FUNC(name) CONCAT_EXPAND(name##_, KITTY_SIMD_LEVEL)

#ifdef KITTY_NO_SIMD
#define NOSIMD \
    { fatal("No SIMD implementations for this CPU"); }
bool
FUNC(utf8_decode_to_esc)(UTF8Decoder *d UNUSED, const uint8_t *src UNUSED, size_t src_sz UNUSED) NOSIMD const uint8_t *FUNC(find_either_of_two_bytes)(
    const uint8_t *haystack UNUSED, const size_t sz UNUSED, const uint8_t a UNUSED, const uint8_t b UNUSED) NOSIMD
    void FUNC(xor_data64)(const uint8_t key[64] UNUSED, uint8_t *data UNUSED, const size_t data_sz UNUSED) NOSIMD size_t
    FUNC(printable_ascii_run_length)(const uint32_t *chars UNUSED, const size_t sz UNUSED) NOSIMD
    void FUNC(blend_over_straight)(uint8_t *dst UNUSED, const uint8_t *src UNUSED, size_t num_pixels UNUSED) NOSIMD
    void FUNC(blend_over_opaque)(uint8_t *dst UNUSED, unsigned dst_bpp UNUSED, const uint8_t *src UNUSED, size_t num_pixels UNUSED) NOSIMD
    void FUNC(composite_alpha_mask)(uint32_t *dst UNUSED, const uint8_t *mask UNUSED, size_t num_pixels UNUSED, uint32_t color_rgb UNUSED) NOSIMD
#undef NOSIMD
#else

#include "charsets.h"

// Boilerplate {{{
START_IGNORE_DIAGNOSTIC("-Wfloat-conversion")
START_IGNORE_DIAGNOSTIC("-Wpedantic")
#if defined(__clang__) && __clang_major__ > 13
_Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#if defined(__aarch64__) || (defined(__arm64__) && defined(__APPLE__))
// On ARM64, include native NEON header directly instead of simde/arm/neon.h
// to avoid a GCC bug triggered by some versions of simde where
// simde_vcadd_rot270_f16 calls SIMDE_SHUFFLE_VECTOR_(16, 4, ...) with 4
// indices for a 4-byte (2-element) int16 vector, producing the error:
// "excess elements in vector initializer"
#include <arm_neon.h>
    typedef uint8x8_t simde_uint8x8_t;
typedef uint8x16_t simde_uint8x16_t;
#define simde_vshrn_n_u16 vshrn_n_u16
#define simde_vreinterpretq_u16_u8 vreinterpretq_u16_u8
#define simde_vget_lane_u64 vget_lane_u64
#define simde_vreinterpret_u64_u8 vreinterpret_u64_u8
#else
#include <simde/arm/neon.h>
#endif
#if defined(__clang__) && __clang_major__ > 13
_Pragma("clang diagnostic pop")
#endif
    END_IGNORE_DIAGNOSTIC END_IGNORE_DIAGNOSTIC


#ifndef _MM_SHUFFLE
#define _MM_SHUFFLE(z, y, x, w) (((z) << 6) | ((y) << 4) | ((x) << 2) | (w))
#endif
#define integer_t CONCAT_EXPAND(CONCAT_EXPAND(simde__m, KITTY_SIMD_LEVEL), i)
#define shift_right_by_bytes128 simde_mm_srli_si128
#define is_zero FUNC(is_zero)

#if KITTY_SIMD_LEVEL == 128
#define set1_epi8(x) simde_mm_set1_epi8((char)(x))
#define set1_epi32 simde_mm_set1_epi32
#define cmpgt_epi32 simde_mm_cmpgt_epi32
#define set_epi8 simde_mm_set_epi8
#define add_epi8 simde_mm_add_epi8
#define load_unaligned simde_mm_loadu_si128
#define load_aligned(x) simde_mm_load_si128((const integer_t *)(x))
#define store_unaligned simde_mm_storeu_si128
#define store_aligned(dest, vec) simde_mm_store_si128((integer_t *)dest, vec)
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define cmplt_epi8 simde_mm_cmplt_epi8
#define cmpgt_epi8 simde_mm_cmpgt_epi8
#define or_si simde_mm_or_si128
#define and_si simde_mm_and_si128
#define xor_si simde_mm_xor_si128
#define andnot_si simde_mm_andnot_si128
#define movemask_epi8 simde_mm_movemask_epi8
#define extract_lower_quarter_as_chars simde_mm_cvtepu8_epi32
#define blendv_epi8 simde_mm_blendv_epi8
#define shift_left_by_bits16 simde_mm_slli_epi16
#define shift_right_by_bits32 simde_mm_srli_epi32
#define shuffle_epi8 simde_mm_shuffle_epi8
#define numbered_bytes() set_epi8(15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
#define reverse_numbered_bytes() simde_mm_setr_epi8(15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
// output[i] = MAX(0, a[i] - b[1i])
#define subtract_saturate_epu8 simde_mm_subs_epu8
#define subtract_epi8 simde_mm_sub_epi8
#define create_zero_integer simde_mm_setzero_si128
#define create_all_ones_integer() simde_mm_set1_epi64x(-1)
#define zero_upper()
#define set1_epi16(x) simde_mm_set1_epi16((short)(x))
#define add_epi16 simde_mm_add_epi16
#define mullo_epi16 simde_mm_mullo_epi16
#define shift_right_by_bits16 simde_mm_srli_epi16
#define unpacklo_epi8 simde_mm_unpacklo_epi8
#define unpackhi_epi8 simde_mm_unpackhi_epi8
#define packus_epi16 simde_mm_packus_epi16
#define packus_epi32 simde_mm_packus_epi32
#define add_epi32 simde_mm_add_epi32
#define sub_epi32 simde_mm_sub_epi32
#define mullo_epi32 simde_mm_mullo_epi32
#define cmpeq_epi32 simde_mm_cmpeq_epi32
#define max_epu32 simde_mm_max_epu32
#define shuffle_epi32 simde_mm_shuffle_epi32
#define cvtepi32_ps simde_mm_cvtepi32_ps
#define cvtps_epi32 simde_mm_cvtps_epi32
#define div_ps simde_mm_div_ps
// set the same four 32-bit values in every 128-bit lane, a is the highest lane
#define set_epi32_in_lanes(a, b, c, d) simde_mm_set_epi32(a, b, c, d)
// replicate the alpha byte of each 4-byte pixel into all four of its bytes
#define alpha_broadcast_pattern() set_epi8(15, 15, 15, 15, 11, 11, 11, 11, 7, 7, 7, 7, 3, 3, 3, 3)
// widen the qth quarter (sizeof(integer_t)/4 bytes) of A into 32-bit lanes, q must be a literal
#define widen_quarter(A, q) simde_mm_cvtepu8_epi32(simde_mm_srli_si128(A, 4 * (q)))
// restore byte order after packus_epi32+packus_epi16 of four widened quarters
#define fixup_packed_dword_order(v) (v)

    static inline int FUNC(is_zero)(const integer_t a) {
    return simde_mm_testz_si128(a, a);
}

#define GA(LA) LA(1) LA(2) LA(3) LA(4) LA(5) LA(6) LA(7) LA(8) LA(9) LA(10) LA(11) LA(12) LA(13) LA(14) LA(15)
#define L(n) \
    case n: return simde_mm_srli_si128(A, n);
#define R(n) \
    case n: return simde_mm_slli_si128(A, n);
#define shift_left_by_bytes_macro(A, n) \
    {                                   \
        switch (n) {                    \
            default: return A; GA(L)    \
        }                               \
    }
#define shift_right_by_bytes_macro(A, n) \
    {                                    \
        switch (n) {                     \
            default: return A; GA(R)     \
        }                                \
    }

static inline integer_t
shift_right_by_bytes(const integer_t A, unsigned n) {
    shift_right_by_bytes_macro(A, n)
}
static inline integer_t
shift_left_by_bytes(const integer_t A, unsigned n){shift_left_by_bytes_macro(A, n)}

#define w(dir, word, num) \
    static inline integer_t shift_##dir##_by_##word(const integer_t A) { shift_##dir##_by_bytes_macro(A, num); }

w(right, one_byte, 1) w(right, two_bytes, 2) w(right, four_bytes, 4) w(right, eight_bytes, 8) w(right, sixteen_bytes, 16) w(left, one_byte, 1)
    w(left, two_bytes, 2) w(left, four_bytes, 4) w(left, eight_bytes, 8) w(left, sixteen_bytes, 16)
#undef w
#undef GA
#undef L
#undef R
#undef shift_right_by_bytes_macro
#undef shift_left_by_bytes_macro

#else

#if defined(SIMDE_ARCH_AMD64) || defined(SIMDE_ARCH_X86)
#define zero_upper _mm256_zeroupper
#else
#define zero_upper()
#endif
#define set1_epi8(x) simde_mm256_set1_epi8((char)(x))
#define set1_epi32 simde_mm256_set1_epi32
#define cmpgt_epi32 simde_mm256_cmpgt_epi32
#define set_epi8 simde_mm256_set_epi8
#define add_epi8 simde_mm256_add_epi8
#define load_unaligned simde_mm256_loadu_si256
#define load_aligned(x) simde_mm256_load_si256((const integer_t *)(x))
#define store_unaligned simde_mm256_storeu_si256
#define store_aligned(dest, vec) simde_mm256_store_si256((integer_t *)dest, vec)
#define cmpeq_epi8 simde_mm256_cmpeq_epi8
#define cmpgt_epi8 simde_mm256_cmpgt_epi8
#define cmplt_epi8(a, b) cmpgt_epi8(b, a)
#define or_si simde_mm256_or_si256
#define and_si simde_mm256_and_si256
#define xor_si simde_mm256_xor_si256
#define andnot_si simde_mm256_andnot_si256
#define movemask_epi8 simde_mm256_movemask_epi8
#define extract_lower_half_as_chars simde_mm256_cvtepu8_epi32
#define blendv_epi8 simde_mm256_blendv_epi8
#define subtract_saturate_epu8 simde_mm256_subs_epu8
#define subtract_epi8 simde_mm256_sub_epi8
#define shift_left_by_bits16 simde_mm256_slli_epi16
#define shift_right_by_bits32 simde_mm256_srli_epi32
#define create_zero_integer simde_mm256_setzero_si256
#define create_all_ones_integer() simde_mm256_set1_epi64x(-1)
#define set1_epi16(x) simde_mm256_set1_epi16((short)(x))
#define add_epi16 simde_mm256_add_epi16
#define mullo_epi16 simde_mm256_mullo_epi16
#define shift_right_by_bits16 simde_mm256_srli_epi16
#define unpacklo_epi8 simde_mm256_unpacklo_epi8
#define unpackhi_epi8 simde_mm256_unpackhi_epi8
#define packus_epi16 simde_mm256_packus_epi16
#define packus_epi32 simde_mm256_packus_epi32
#define add_epi32 simde_mm256_add_epi32
#define sub_epi32 simde_mm256_sub_epi32
#define mullo_epi32 simde_mm256_mullo_epi32
#define cmpeq_epi32 simde_mm256_cmpeq_epi32
#define max_epu32 simde_mm256_max_epu32
#define shuffle_epi32 simde_mm256_shuffle_epi32
#define cvtepi32_ps simde_mm256_cvtepi32_ps
#define cvtps_epi32 simde_mm256_cvtps_epi32
#define div_ps simde_mm256_div_ps
// set the same four 32-bit values in every 128-bit lane, a is the highest lane
#define set_epi32_in_lanes(a, b, c, d) simde_mm256_set_epi32(a, b, c, d, a, b, c, d)
// replicate the alpha byte of each 4-byte pixel into all four of its bytes (in-lane indices)
#define alpha_broadcast_pattern() set_epi8(15, 15, 15, 15, 11, 11, 11, 11, 7, 7, 7, 7, 3, 3, 3, 3, 15, 15, 15, 15, 11, 11, 11, 11, 7, 7, 7, 7, 3, 3, 3, 3)
// widen the qth quarter (sizeof(integer_t)/4 bytes) of A into 32-bit lanes, q must be a literal
#define widen_quarter(A, q) simde_mm256_cvtepu8_epi32(simde_mm_srli_si128(simde_mm256_extracti128_si256(A, (q) / 2), 8 * ((q) % 2)))
// restore byte order after the per 128-bit lane packus_epi32+packus_epi16 of four widened quarters
#define fixup_packed_dword_order(v) simde_mm256_permutevar8x32_epi32(v, simde_mm256_setr_epi32(0, 4, 1, 5, 2, 6, 3, 7))
#define numbered_bytes() set_epi8(31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
#define reverse_numbered_bytes() \
    simde_mm256_setr_epi8(31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)

    static inline int
    FUNC(is_zero)(const integer_t a) {
    return simde_mm256_testz_si256(a, a);
}

#define GA(LA) LA(1) LA(2) LA(3) LA(4) LA(5) LA(6) LA(7) LA(8) LA(9) LA(10) LA(11) LA(12) LA(13) LA(14) LA(15)
#define GB(LA) LA(17) LA(18) LA(19) LA(20) LA(21) LA(22) LA(23) LA(24) LA(25) LA(26) LA(27) LA(28) LA(29) LA(30) LA(31)
#define RA(n) \
    case n: return simde_mm256_alignr_epi8(A, simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), 16 - n);
#define RB(n) \
    case n: return simde_mm256_slli_si256(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), n - 16);

#define shift_right_by_bytes_macro(A, n)                                                          \
    {                                                                                             \
        switch (n) {                                                                              \
            default: return A; GA(RA)                                                             \
            case 16: return simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)); GB(RB) \
        }                                                                                         \
    }

#define LA(n) \
    case n: return simde_mm256_alignr_epi8(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), A, n);
#define LB(n) \
    case n: return simde_mm256_srli_si256(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), n - 16);
#define shift_left_by_bytes_macro(A, n)                                                           \
    {                                                                                             \
        switch (n) {                                                                              \
            default: return A; GA(LA)                                                             \
            case 16: return simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)); GB(LB) \
        }                                                                                         \
    }


static inline integer_t
shift_right_by_bytes(const integer_t A, unsigned n) {
    shift_right_by_bytes_macro(A, n)
}
static inline integer_t
shift_left_by_bytes(const integer_t A, unsigned n){shift_left_by_bytes_macro(A, n)}

#define w(dir, word, num) \
    static inline integer_t shift_##dir##_by_##word(const integer_t A) { shift_##dir##_by_bytes_macro(A, num); }

w(right, one_byte, 1) w(right, two_bytes, 2) w(right, four_bytes, 4) w(right, eight_bytes, 8) w(right, sixteen_bytes, 16) w(left, one_byte, 1)
    w(left, two_bytes, 2) w(left, four_bytes, 4) w(left, eight_bytes, 8) w(left, sixteen_bytes, 16)
#undef LA
#undef LB
#undef GA
#undef GB
#undef RA
#undef RB
#undef w
#undef shift_right_by_bytes_macro
#undef shift_left_by_bytes_macro

// only used with in-lane shuffle indices (0-15 within each 128-bit lane)
#define shuffle_epi8 simde_mm256_shuffle_epi8
#endif

// Byte shifts within each 128-bit lane. These are single instructions on x86
// and cheap NEON ext ops on ARM, unlike the cross-lane full-register shifts
// needed at the 256-bit level. Note that in this codebase shift_right means
// moving bytes to higher memory addresses, which corresponds to the intrinsics
// named "slli" and vice versa.
#if KITTY_SIMD_LEVEL == 128
// for 128-bit registers in-lane and full-register byte shifts are the same thing
#define shift_right_in_lane_by_one_byte shift_right_by_one_byte
#define shift_right_in_lane_by_two_bytes shift_right_by_two_bytes
#define shift_right_in_lane_by_four_bytes shift_right_by_four_bytes
#define shift_right_in_lane_by_eight_bytes shift_right_by_eight_bytes
#define shift_left_in_lane_by_one_byte shift_left_by_one_byte
#define shift_left_in_lane_by_two_bytes shift_left_by_two_bytes
#define shift_left_in_lane_by_four_bytes shift_left_by_four_bytes
#define shift_left_in_lane_by_eight_bytes shift_left_by_eight_bytes
#define numbered_bytes_in_lane numbered_bytes
#else
#define shift_right_in_lane_by_one_byte(A) simde_mm256_slli_si256(A, 1)
#define shift_right_in_lane_by_two_bytes(A) simde_mm256_slli_si256(A, 2)
#define shift_right_in_lane_by_four_bytes(A) simde_mm256_slli_si256(A, 4)
#define shift_right_in_lane_by_eight_bytes(A) simde_mm256_slli_si256(A, 8)
#define shift_left_in_lane_by_one_byte(A) simde_mm256_srli_si256(A, 1)
#define shift_left_in_lane_by_two_bytes(A) simde_mm256_srli_si256(A, 2)
#define shift_left_in_lane_by_four_bytes(A) simde_mm256_srli_si256(A, 4)
#define shift_left_in_lane_by_eight_bytes(A) simde_mm256_srli_si256(A, 8)
#define numbered_bytes_in_lane() set_epi8(15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
#endif

#define print_register_as_bytes(r)                          \
    {                                                       \
        printf("%s:\n", #r);                                \
        alignas(64) uint8_t data[sizeof(r)];                \
        store_unaligned((integer_t *)data, r);              \
        for (unsigned i = 0; i < sizeof(integer_t); i++) {  \
            uint8_t ch = data[i];                           \
            if (' ' <= ch && ch < 0x7f) printf("_%c ", ch); \
            else printf("%.2x ", ch);                       \
        }                                                   \
        printf("\n");                                       \
    }

#if 0
#define debug_register print_register_as_bytes
#define debug printf
#else
#define debug_register(...)
#define debug(...)
#endif

#if (defined(__arm64__) && defined(__APPLE__)) || defined(__aarch64__)
    // See https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/porting-x86-vector-bitmask-optimizations-to-arm-neon

    static inline uint64_t movemask_arm128(const simde__m128i vec) {
    simde_uint8x8_t res = simde_vshrn_n_u16(simde_vreinterpretq_u16_u8((simde_uint8x16_t)vec), 4);
    return simde_vget_lane_u64(simde_vreinterpret_u64_u8(res), 0);
}

#if KITTY_SIMD_LEVEL == 128

static inline int
bytes_to_first_match(const integer_t vec) {
    const uint64_t m = movemask_arm128(vec);
    return m ? (__builtin_ctzll(m) >> 2) : -1;
}

static inline int
bytes_to_first_match_ignoring_leading_n(const integer_t vec, uintptr_t num_ignored) {
    uint64_t m = movemask_arm128(vec);
    m >>= num_ignored << 2;
    return m ? (__builtin_ctzll(m) >> 2) : -1;
}

#else

static inline int
bytes_to_first_match(const integer_t vec) {
    if (is_zero(vec)) return -1;
    simde__m128i v = simde_mm256_extracti128_si256(vec, 0);
    if (!simde_mm_testz_si128(v, v)) return __builtin_ctzll(movemask_arm128(v)) >> 2;
    v = simde_mm256_extracti128_si256(vec, 1);
    return 16 + (__builtin_ctzll(movemask_arm128(v)) >> 2);
}

static inline int
bytes_to_first_match_ignoring_leading_n(const integer_t vec, uintptr_t num_ignored) {
    uint64_t m;
    int offset;
    if (num_ignored < 16) {
        m = ((uint64_t)movemask_arm128(simde_mm256_extracti128_si256(vec, 0))) >> (num_ignored << 2);
        if (m) return (__builtin_ctzll(m) >> 2);
        offset = 16 - num_ignored;
        num_ignored = 0;
    } else {
        num_ignored -= 16;
        offset = 0;
    }
    m = ((uint64_t)movemask_arm128(simde_mm256_extracti128_si256(vec, 1))) >> (num_ignored << 2);
    return m ? (offset + (__builtin_ctzll(m) >> 2)) : -1;
}
#endif

#else

        static inline int bytes_to_first_match(const integer_t vec) {
    return is_zero(vec) ? -1 : __builtin_ctz(movemask_epi8(vec));
}

static inline int
bytes_to_first_match_ignoring_leading_n(const integer_t vec, const uintptr_t num_ignored) {
    uint32_t mask = movemask_epi8(vec);
    mask >>= num_ignored;
    return mask ? __builtin_ctz(mask) : -1;
}


#endif


// }}}

static inline integer_t
zero_last_n_bytes(const integer_t vec, const char n) {
    integer_t mask = create_all_ones_integer();
    mask = shift_left_by_bytes(mask, n);
    return and_si(mask, vec);
}

#define KEY_SIZE 64
void
FUNC(xor_data64)(const uint8_t key[KEY_SIZE], uint8_t *data, const size_t data_sz) {
    // First process unaligned bytes at the start of data
    const uintptr_t unaligned_bytes = KEY_SIZE - ((uintptr_t)data & (KEY_SIZE - 1));
    if (data_sz <= unaligned_bytes) {
        for (unsigned i = 0; i < data_sz; i++) data[i] ^= key[i];
        return;
    }
    for (unsigned i = 0; i < unaligned_bytes; i++) data[i] ^= key[i];

    // Rotate the key by unaligned_bytes
    alignas(sizeof(integer_t)) char aligned_key[KEY_SIZE];
    memcpy(aligned_key, key + unaligned_bytes, KEY_SIZE - unaligned_bytes);
    memcpy(aligned_key + KEY_SIZE - unaligned_bytes, key, unaligned_bytes);

    const integer_t v1 = load_aligned(aligned_key), v2 = load_aligned(aligned_key + sizeof(integer_t));
#if KITTY_SIMD_LEVEL == 128
    const integer_t v3 = load_aligned(aligned_key + 2 * sizeof(integer_t)), v4 = load_aligned(aligned_key + 3 * sizeof(integer_t));
#endif
    // Process KEY_SIZE aligned chunks using SIMD
    integer_t d;
    uint8_t *p = data + unaligned_bytes, *limit = data + data_sz;
    const uintptr_t trailing_bytes = (uintptr_t)limit & (KEY_SIZE - 1);
    limit -= trailing_bytes;
    // p is aligned to first KEY_SIZE boundary >= data and limit is aligned to first KEY_SIZE boundary <= (data + data_sz)
#define do_one(which)                   \
    d = load_aligned(p);                \
    store_aligned(p, xor_si(which, d)); \
    p += sizeof(integer_t);
    while (p < limit) {
        do_one(v1);
        do_one(v2);
#if KITTY_SIMD_LEVEL == 128
        do_one(v3);
        do_one(v4);
#endif
    }
#undef do_one
    // Process remaining trailing_bytes
    for (unsigned i = 0; i < trailing_bytes; i++) limit[i] ^= aligned_key[i];
    zero_upper();
    return;
}
#undef KEY_SIZE

#define check_chunk()                      \
    if (n > -1) {                          \
        const uint8_t *ans = haystack + n; \
        zero_upper();                      \
        return ans < limit ? ans : NULL;   \
    }

#define find_match(haystack, sz, get_test_vec)                                                                                         \
    {                                                                                                                                  \
        const uint8_t *limit = haystack + sz;                                                                                          \
        integer_t chunk;                                                                                                               \
        int n;                                                                                                                         \
                                                                                                                                       \
        { /* first chunk which is possibly unaligned */                                                                                \
            const uintptr_t addr = (uintptr_t)haystack;                                                                                \
            const uintptr_t unaligned_bytes = addr & (sizeof(integer_t) - 1);                                                          \
            chunk = load_aligned(haystack - unaligned_bytes); /* this is an aligned load from the first aligned pos before haystack */ \
            n = bytes_to_first_match_ignoring_leading_n(get_test_vec(chunk), unaligned_bytes);                                         \
            check_chunk();                                                                                                             \
            haystack += sizeof(integer_t) - unaligned_bytes;                                                                           \
        }                                                                                                                              \
                                                                                                                                       \
        /* Iterate over aligned chunks */                                                                                              \
        for (; haystack < limit; haystack += sizeof(integer_t)) {                                                                      \
            chunk = load_aligned(haystack);                                                                                            \
            n = bytes_to_first_match(get_test_vec(chunk));                                                                             \
            check_chunk();                                                                                                             \
        }                                                                                                                              \
        zero_upper();                                                                                                                  \
        return NULL;                                                                                                                   \
    }

const uint8_t *
FUNC(find_either_of_two_bytes)(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    if (!sz) return NULL;
    const integer_t a_vec = set1_epi8(a), b_vec = set1_epi8(b);
#define get_test_from_chunk(chunk) (or_si(cmpeq_epi8(chunk, a_vec), cmpeq_epi8(chunk, b_vec)))
    find_match(haystack, sz, get_test_from_chunk);
#undef get_test_from_chunk
}

size_t
FUNC(printable_ascii_run_length)(const uint32_t *chars, const size_t sz) {
    // Length of the prefix of chars that contains only printable ASCII codepoints,
    // 32 <= ch <= 126. Signed comparisons are safe as codepoints are < 2^31.
    const integer_t lower = set1_epi32(32), upper = set1_epi32(126);
    const size_t lanes = sizeof(integer_t) / sizeof(uint32_t);
    size_t i = 0;
    for (; i + lanes <= sz; i += lanes) {
        const integer_t chunk = load_unaligned((const integer_t *)(chars + i));
        const integer_t non_printable = or_si(cmpgt_epi32(lower, chunk), cmpgt_epi32(chunk, upper));
        const int n = bytes_to_first_match(non_printable);
        if (n > -1) {
            zero_upper();
            return i + (size_t)n / sizeof(uint32_t);
        }
    }
    zero_upper();
    while (i < sz && (chars[i] - 32u) < 95u) i++;
    return i;
}

#undef check_chunk

#define output_increment sizeof(integer_t) / sizeof(uint32_t)

// The caller must ensure output has sufficient capacity
static inline void
FUNC(output_plain_ascii)(UTF8Decoder *d, integer_t vec, size_t src_sz) {
#if KITTY_SIMD_LEVEL == 128
    for (const uint32_t *p = d->output.storage + d->output.pos, *limit = p + src_sz; p < limit; p += output_increment) {
        const integer_t unpacked = extract_lower_quarter_as_chars(vec);
        store_unaligned((integer_t *)p, unpacked);
        vec = shift_right_by_bytes128(vec, output_increment);
    }
#else
    const uint32_t *p = d->output.storage + d->output.pos, *limit = p + src_sz;
    simde__m128i x = simde_mm256_extracti128_si256(vec, 0);
    integer_t unpacked = extract_lower_half_as_chars(x);
    store_unaligned((integer_t *)p, unpacked);
    p += output_increment;
    if (p < limit) {
        x = shift_right_by_bytes128(x, output_increment);
        unpacked = extract_lower_half_as_chars(x);
        store_unaligned((integer_t *)p, unpacked);
        p += output_increment;
        if (p < limit) {
            x = simde_mm256_extracti128_si256(vec, 1);
            unpacked = extract_lower_half_as_chars(x);
            store_unaligned((integer_t *)p, unpacked);
            p += output_increment;
            if (p < limit) {
                x = shift_right_by_bytes128(x, output_increment);
                unpacked = extract_lower_half_as_chars(x);
                store_unaligned((integer_t *)p, unpacked);
                p += output_increment;
            }
        }
    }
#endif
    d->output.pos += src_sz;
}

// The caller must ensure output has sufficient capacity.
// The outputN vectors must be compacted within each 128-bit lane, the number of
// codepoints in each lane is passed in separately and the lanes are joined by
// overlapping stores, relying on the output overwrite slack.
#if KITTY_SIMD_LEVEL == 128
static inline void
FUNC(output_unicode)(UTF8Decoder *d, integer_t output1, integer_t output2, integer_t output3, const unsigned num_codepoints) {
    for (const uint32_t *p = d->output.storage + d->output.pos, *limit = p + num_codepoints; p < limit; p += output_increment) {
        const integer_t unpacked1 = extract_lower_quarter_as_chars(output1);
        const integer_t unpacked2 = shift_right_by_one_byte(extract_lower_quarter_as_chars(output2));
        const integer_t unpacked3 = shift_right_by_two_bytes(extract_lower_quarter_as_chars(output3));
        const integer_t unpacked = or_si(or_si(unpacked1, unpacked2), unpacked3);
        store_unaligned((integer_t *)p, unpacked);
        output1 = shift_right_by_bytes128(output1, output_increment);
        output2 = shift_right_by_bytes128(output2, output_increment);
        output3 = shift_right_by_bytes128(output3, output_increment);
    }
    d->output.pos += num_codepoints;
}
#else
static inline void
FUNC(output_unicode)(
    UTF8Decoder *d, integer_t output1, integer_t output2, integer_t output3, const unsigned num_codepoints_lane0, const unsigned num_codepoints_lane1) {
    uint32_t *p = d->output.storage + d->output.pos;
    simde__m128i x1, x2, x3;
#define chunk()                                                                                        \
    {                                                                                                  \
        const integer_t unpacked1 = extract_lower_half_as_chars(x1);                                   \
        const integer_t unpacked2 = shift_right_in_lane_by_one_byte(extract_lower_half_as_chars(x2));  \
        const integer_t unpacked3 = shift_right_in_lane_by_two_bytes(extract_lower_half_as_chars(x3)); \
        store_unaligned((integer_t *)p, or_si(or_si(unpacked1, unpacked2), unpacked3));                \
        p += output_increment;                                                                         \
    }
#define extract(which)                                  \
    x1 = simde_mm256_extracti128_si256(output1, which); \
    x2 = simde_mm256_extracti128_si256(output2, which); \
    x3 = simde_mm256_extracti128_si256(output3, which);
#define shift()                                         \
    x1 = shift_right_by_bytes128(x1, output_increment); \
    x2 = shift_right_by_bytes128(x2, output_increment); \
    x3 = shift_right_by_bytes128(x3, output_increment);
    extract(0);
    chunk();
    if (num_codepoints_lane0 > output_increment) {
        shift();
        chunk();
    }
    p = d->output.storage + d->output.pos + num_codepoints_lane0;
    extract(1);
    chunk();
    if (num_codepoints_lane1 > output_increment) {
        shift();
        chunk();
    }
#undef chunk
#undef extract
#undef shift
    d->output.pos += num_codepoints_lane0 + num_codepoints_lane1;
}
#endif
#undef output_increment

#define do_one_byte                                                                   \
    const uint8_t ch = src[pos++];                                                    \
    switch (decode_utf8(&d->state.cur, &d->state.codep, ch)) {                        \
        case UTF8_ACCEPT: d->output.storage[d->output.pos++] = d->state.codep; break; \
        case UTF8_REJECT: {                                                           \
            const bool prev_was_accept = d->state.prev == UTF8_ACCEPT;                \
            zero_at_ptr(&d->state);                                                   \
            d->output.storage[d->output.pos++] = 0xfffd;                              \
            if (!prev_was_accept) {                                                   \
                pos--;                                                                \
                continue; /* so that prev is correct */                               \
            }                                                                         \
        } break;                                                                      \
    }                                                                                 \
    d->state.prev = d->state.cur;

static inline size_t
scalar_decode_to_accept(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (pos < src_sz && d->state.cur != UTF8_ACCEPT) { do_one_byte }
    return pos;
}

static inline size_t
scalar_decode_all(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (pos < src_sz) { do_one_byte }
    return pos;
}

#undef do_one_byte

// Fast decoding of blocks of valid UTF-8 {{{
// Uses the approach of simdutf (https://github.com/simdutf/simdutf): blocks are
// validated with the lookup tables of Keiser and Lemire, "Validating UTF-8 In
// Less Than One Instruction Per Byte" and converted twelve bytes at a time with
// the shuffles from utf8-decode-tables.h, see gen/utf8_decode_tables.py.

#include "utf8-decode-tables.h"

#if defined(__aarch64__) || (defined(__arm64__) && defined(__APPLE__))
// NEON has only 128 bit vectors and no movemask, so in both the 128 and 256
// bit builds blocks are four NEON vectors, tested with horizontal max and
// converted to bitmasks with pairwise adds. NEON table lookups give zero for
// out of range indices, so need no masking of indices, unlike simde's
// emulation of shuffle_epi8.
#define UTF8_BLOCK_NEON
#define utf8_vec_t uint8x16_t
#define utf8_load(p) vld1q_u8(p)
#define utf8_lookup16(...) vld1q_u8(((const uint8_t[16]){__VA_ARGS__}))
#define utf8_shuffle vqtbl1q_u8
// The bytes of cur preceded by the last n bytes of prev
#define utf8_prev(cur, prev, n) vextq_u8(prev, cur, 16 - (n))
#define utf8_high_nibbles(v) vshrq_n_u8(v, 4)
#define utf8_low_nibbles(v) vandq_u8(v, vdupq_n_u8(0x0f))
#define utf8_and vandq_u8
#define utf8_or vorrq_u8
#define utf8_xor veorq_u8
#define utf8_set1(x) vdupq_n_u8(x)
#define utf8_subs_epu8 vqsubq_u8
#define utf8_cmpeq vceqq_u8
#define utf8_zero() vdupq_n_u8(0)
#define utf8_any_set(v) (vmaxvq_u8(v) != 0)
#define utf8_any_high_bit(v) (vmaxvq_u8(v) >= 0x80)
#define utf8_is_zero(v) (vmaxvq_u8(v) == 0)
#define utf8_shuffle128(v, idx) ((simde__m128i)vqtbl1q_u8((uint8x16_t)(v), (uint8x16_t)(idx)))
#define UTF8_VECS_PER_BLOCK 4
#else
#define utf8_vec_t integer_t
#define utf8_load(p) load_unaligned((const integer_t *)(p))
#define utf8_shuffle shuffle_epi8
#define utf8_low_nibbles(v) and_si(v, set1_epi8(0x0f))
#define utf8_and and_si
#define utf8_or or_si
#define utf8_xor xor_si
#define utf8_set1 set1_epi8
#define utf8_subs_epu8 subtract_saturate_epu8
#define utf8_cmpeq cmpeq_epi8
#define utf8_zero create_zero_integer
// v must have bytes that are either 0 or 0xff
#define utf8_any_set(v) (movemask_epi8(v) != 0)
#define utf8_any_high_bit(v) (movemask_epi8(v) != 0)
#define utf8_is_zero is_zero
#define utf8_shuffle128 simde_mm_shuffle_epi8
#if KITTY_SIMD_LEVEL == 128
#define utf8_lookup16(...) simde_mm_loadu_si128((const simde__m128i *)(const uint8_t[16]){__VA_ARGS__})
// The bytes of cur preceded by the last n bytes of prev
#define utf8_prev(cur, prev, n) simde_mm_alignr_epi8(cur, prev, 16 - (n))
#define utf8_high_nibbles(v) simde_mm_and_si128(simde_mm_srli_epi16(v, 4), simde_mm_set1_epi8(0x0f))
#define UTF8_VECS_PER_BLOCK 4
#else
#define utf8_lookup16(...) simde_mm256_broadcastsi128_si256(simde_mm_loadu_si128((const simde__m128i *)(const uint8_t[16]){__VA_ARGS__}))
#define utf8_prev(cur, prev, n) simde_mm256_alignr_epi8(cur, simde_mm256_permute2x128_si256(prev, cur, 0x21), 16 - (n))
#define utf8_high_nibbles(v) simde_mm256_and_si256(simde_mm256_srli_epi16(v, 4), simde_mm256_set1_epi8(0x0f))
#define UTF8_VECS_PER_BLOCK 2
#endif
#endif

static inline utf8_vec_t
FUNC(utf8_errors)(const utf8_vec_t input, const utf8_vec_t prev_input) {
    // Returns a vector that is non-zero if input is not valid UTF-8, given that
    // prev_input are the bytes before it. Validates every byte using its
    // preceding three bytes.
    enum {
        TOO_SHORT = 1 << 0,  // 11______ 0_______ or 11______ 11______
        TOO_LONG = 1 << 1,   // 0_______ 10______
        OVERLONG_3 = 1 << 2, // 11100000 100_____
        TOO_LARGE = 1 << 3,  // 11110100 1001____ etc.
        SURROGATE = 1 << 4,  // 11101101 101_____
        OVERLONG_2 = 1 << 5, // 1100000_ 10______
        TOO_LARGE_1000 = 1 << 6,
        OVERLONG_4 = 1 << 6, // 11110000 1000____
        TWO_CONTS = 1 << 7,  // 10______ 10______
        CARRY = TOO_SHORT | TOO_LONG | TWO_CONTS,
    };
    const utf8_vec_t prev1 = utf8_prev(input, prev_input, 1);
    const utf8_vec_t byte_1_high = utf8_shuffle(
        utf8_lookup16(
            TOO_LONG,
            TOO_LONG,
            TOO_LONG,
            TOO_LONG,
            TOO_LONG,
            TOO_LONG,
            TOO_LONG,
            TOO_LONG,
            TWO_CONTS,
            TWO_CONTS,
            TWO_CONTS,
            TWO_CONTS,
            TOO_SHORT | OVERLONG_2,
            TOO_SHORT,
            TOO_SHORT | OVERLONG_3 | SURROGATE,
            TOO_SHORT | TOO_LARGE | TOO_LARGE_1000 | OVERLONG_4),
        utf8_high_nibbles(prev1));
    const utf8_vec_t byte_1_low = utf8_shuffle(
        utf8_lookup16(
            CARRY | OVERLONG_3 | OVERLONG_2 | OVERLONG_4,
            CARRY | OVERLONG_2,
            CARRY,
            CARRY,
            CARRY | TOO_LARGE,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000 | SURROGATE,
            CARRY | TOO_LARGE | TOO_LARGE_1000,
            CARRY | TOO_LARGE | TOO_LARGE_1000),
        utf8_low_nibbles(prev1));
    const utf8_vec_t byte_2_high = utf8_shuffle(
        utf8_lookup16(
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_LONG | OVERLONG_2 | TWO_CONTS | OVERLONG_3 | TOO_LARGE_1000 | OVERLONG_4,
            TOO_LONG | OVERLONG_2 | TWO_CONTS | OVERLONG_3 | TOO_LARGE,
            TOO_LONG | OVERLONG_2 | TWO_CONTS | SURROGATE | TOO_LARGE,
            TOO_LONG | OVERLONG_2 | TWO_CONTS | SURROGATE | TOO_LARGE,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT,
            TOO_SHORT),
        utf8_high_nibbles(input));
    const utf8_vec_t special_cases = utf8_and(utf8_and(byte_1_high, byte_1_low), byte_2_high);
    // The third and fourth bytes of three and four byte sequences must be
    // continuations, which special_cases flags as TWO_CONTS, so these cancel out
    const utf8_vec_t is_third_byte = utf8_subs_epu8(utf8_prev(input, prev_input, 2), utf8_set1(0xe0 - 0x80));
    const utf8_vec_t is_fourth_byte = utf8_subs_epu8(utf8_prev(input, prev_input, 3), utf8_set1(0xf0 - 0x80));
    const utf8_vec_t must_be_continuation = utf8_and(utf8_or(is_third_byte, is_fourth_byte), utf8_set1(0x80));
    return utf8_xor(must_be_continuation, special_cases);
}

static inline void
FUNC(store_u16_as_u32)(uint32_t *out, const simde__m128i v) {
    // Writes the eight 16 bit values in v as 32 bit values
#if KITTY_SIMD_LEVEL == 128
    simde_mm_storeu_si128((simde__m128i *)out, simde_mm_cvtepu16_epi32(v));
    simde_mm_storeu_si128((simde__m128i *)(out + 4), simde_mm_cvtepu16_epi32(simde_mm_srli_si128(v, 8)));
#else
    simde_mm256_storeu_si256((simde__m256i *)out, simde_mm256_cvtepu16_epi32(v));
#endif
}

static inline unsigned
FUNC(utf8_convert_twelve_bytes)(const uint8_t *input, const uint64_t end_of_code_point_mask, uint32_t **output) {
    // Converts the code points that end in the first twelve bytes of input (or
    // sixteen bytes for some fast paths), returning the number of bytes
    // consumed. Reads sixteen bytes from input and writes up to sixteen code
    // points to output, though fewer may be valid.
    const simde__m128i in = simde_mm_loadu_si128((const simde__m128i *)input);
    uint32_t *out = *output;
    const unsigned mask12 = end_of_code_point_mask & 0xfff;
    if (mask12 == 0xfff) { // twelve ASCII bytes
        FUNC(store_u16_as_u32)(out, simde_mm_cvtepu8_epi16(in));
        FUNC(store_u16_as_u32)(out + 8, simde_mm_cvtepu8_epi16(simde_mm_srli_si128(in, 8)));
        *output = out + 12;
        return 12;
    }
    if ((end_of_code_point_mask & 0xffff) == 0xaaaa) { // eight two byte sequences
        const simde__m128i perm = utf8_shuffle128(in, simde_mm_setr_epi8(1, 0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10, 13, 12, 15, 14));
        const simde__m128i composed = simde_mm_or_si128(
            simde_mm_and_si128(perm, simde_mm_set1_epi16(0x7f)), simde_mm_srli_epi16(simde_mm_and_si128(perm, simde_mm_set1_epi16(0x1f00)), 2));
        FUNC(store_u16_as_u32)(out, composed);
        *output = out + 8;
        return 16;
    }
    // Combines the bytes of three byte sequences shuffled into 32 bit lanes
#define compose_three_byte_lanes(perm)                                                                                                                         \
    simde_mm_or_si128(                                                                                                                                         \
        simde_mm_or_si128(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x7f)), simde_mm_srli_epi32(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x3f00)), 2)), \
        simde_mm_srli_epi32(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x0f0000)), 4))
    if (mask12 == 0x924) { // four three byte sequences, such as CJK text
        const simde__m128i perm = utf8_shuffle128(in, simde_mm_setr_epi8(2, 1, 0, -1, 5, 4, 3, -1, 8, 7, 6, -1, 11, 10, 9, -1));
        simde_mm_storeu_si128((simde__m128i *)out, compose_three_byte_lanes(perm));
        *output = out + 4;
        return 12;
    }
    const unsigned row = utf8_decode_index[mask12][0], consumed = utf8_decode_index[mask12][1];
    const simde__m128i perm = utf8_shuffle128(in, simde_mm_loadu_si128((const simde__m128i *)utf8_decode_shuffles[row]));
    if (row < UTF8_DECODE_FOUR_CODE_POINTS_START) { // six sequences of one or two bytes
        const simde__m128i composed = simde_mm_or_si128(
            simde_mm_and_si128(perm, simde_mm_set1_epi16(0x7f)), simde_mm_srli_epi16(simde_mm_and_si128(perm, simde_mm_set1_epi16(0x1f00)), 2));
        FUNC(store_u16_as_u32)(out, composed);
        *output = out + 6;
    } else if (row < UTF8_DECODE_THREE_CODE_POINTS_START) { // four sequences of one to three bytes
        simde_mm_storeu_si128((simde__m128i *)out, compose_three_byte_lanes(perm));
        *output = out + 4;
    } else if (row < UTF8_DECODE_NUM_SHUFFLES) { // three sequences of one to four bytes
        const simde__m128i middle = simde_mm_srli_epi32(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x3f00)), 2);
        simde__m128i middle_high = simde_mm_and_si128(perm, simde_mm_set1_epi32(0x3f0000));
        // remove the spurious high bit of the lead byte of three byte sequences
        middle_high = simde_mm_xor_si128(simde_mm_srli_epi32(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x400000)), 1), middle_high);
        const simde__m128i high = simde_mm_srli_epi32(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x07000000)), 6);
        const simde__m128i composed = simde_mm_or_si128(
            simde_mm_or_si128(simde_mm_and_si128(perm, simde_mm_set1_epi32(0x7f)), middle), simde_mm_or_si128(high, simde_mm_srli_epi32(middle_high, 4)));
        simde_mm_storeu_si128((simde__m128i *)out, composed);
        *output = out + 3;
    }
#undef compose_three_byte_lanes
    return consumed;
}

static inline uint64_t
FUNC(utf8_continuation_mask)(const utf8_vec_t v[UTF8_VECS_PER_BLOCK]) {
    // Returns a bitmask of the continuation bytes in the 64 bytes of v
#ifdef UTF8_BLOCK_NEON
    // Continuation bytes are less than -64 as signed bytes. AND with the
    // weight of each bit and three rounds of pairwise adds give the bitmask.
    static const uint8_t weights[16] = {1, 2, 4, 8, 16, 32, 64, 128, 1, 2, 4, 8, 16, 32, 64, 128};
    const uint8x16_t w = vld1q_u8(weights);
    const int8x16_t max_continuation = vdupq_n_s8(-65 + 1);
#define m(i) vandq_u8(vcltq_s8(vreinterpretq_s8_u8(v[i]), max_continuation), w)
    const uint8x16_t s = vpaddq_u8(vpaddq_u8(m(0), m(1)), vpaddq_u8(m(2), m(3)));
#undef m
    return vgetq_lane_u64(vreinterpretq_u64_u8(vpaddq_u8(s, s)), 0);
#else
    const integer_t max_continuation = set1_epi8(-65 + 1);
    uint64_t ans = 0;
    for (unsigned i = 0; i < UTF8_VECS_PER_BLOCK; i++) ans |= (uint64_t)(uint32_t)movemask_epi8(cmplt_epi8(v[i], max_continuation)) << (i * sizeof(integer_t));
    return ans;
#endif
}

static inline size_t
FUNC(utf8_decode_valid_blocks)(UTF8Decoder *d, const uint8_t *src, const size_t src_sz) {
    // Decodes 64 byte blocks of src while they are valid UTF-8 and contain no
    // ESC, returning the number of bytes consumed, which always ends at a code
    // point boundary. src must start at a code point boundary. The caller must
    // ensure the output has capacity for src_sz plus 64 code points. Blocks are
    // validated with zero preceding bytes, which is correct at a code point
    // boundary, and only the code points that end within the block before its
    // last twelve bytes are converted, the rest are part of the next block.
    // Converting reads up to 16 bytes from the start of the last conversion,
    // so blocks are only used when they are followed by 16 more bytes.
    if (src_sz < 64 + 16) return 0;
    const uint8_t *p = src, *const last_block_start = src + src_sz - (64 + 16);
    uint32_t *out = d->output.storage + d->output.pos;
    const utf8_vec_t esc_vec = utf8_set1(0x1b), zero = utf8_zero();
    while (p <= last_block_start) {
        utf8_vec_t v[UTF8_VECS_PER_BLOCK];
        utf8_vec_t any_esc = zero, all_bits = zero;
        for (unsigned i = 0; i < UTF8_VECS_PER_BLOCK; i++) {
            v[i] = utf8_load(p + i * sizeof(utf8_vec_t));
            any_esc = utf8_or(any_esc, utf8_cmpeq(v[i], esc_vec));
            all_bits = utf8_or(all_bits, v[i]);
        }
        if (utf8_any_set(any_esc)) break;
        if (!utf8_any_high_bit(all_bits)) { // all ASCII
            for (unsigned i = 0; i < 64; i += 16)
                FUNC(store_u16_as_u32)(out + i, simde_mm_cvtepu8_epi16(simde_mm_loadu_si128((const simde__m128i *)(p + i)))),
                    FUNC(store_u16_as_u32)(out + i + 8, simde_mm_cvtepu8_epi16(simde_mm_loadu_si128((const simde__m128i *)(p + i + 8))));
            out += 64;
            p += 64;
            continue;
        }
        utf8_vec_t errors = FUNC(utf8_errors)(v[0], zero);
        for (unsigned i = 1; i < UTF8_VECS_PER_BLOCK; i++) errors = utf8_or(errors, FUNC(utf8_errors)(v[i], v[i - 1]));
        if (!utf8_is_zero(errors)) break;
        const uint64_t continuation_mask = FUNC(utf8_continuation_mask)(v);
        // A byte is the last byte of a code point if the next byte is not a continuation
        uint64_t end_of_code_point_mask = ~continuation_mask >> 1;
        const uint8_t *const block_end = p + 64 - 12;
        while (p < block_end) {
            const unsigned consumed = FUNC(utf8_convert_twelve_bytes)(p, end_of_code_point_mask, &out);
            p += consumed;
            end_of_code_point_mask >>= consumed;
        }
    }
    d->output.pos = out - d->output.storage;
    return p - src;
}
#undef UTF8_BLOCK_NEON
#undef utf8_vec_t
#undef utf8_load
#undef utf8_lookup16
#undef utf8_shuffle
#undef utf8_prev
#undef utf8_high_nibbles
#undef utf8_low_nibbles
#undef utf8_and
#undef utf8_or
#undef utf8_xor
#undef utf8_set1
#undef utf8_subs_epu8
#undef utf8_cmpeq
#undef utf8_zero
#undef utf8_any_set
#undef utf8_is_zero
#undef utf8_any_high_bit
#undef utf8_shuffle128
#undef UTF8_VECS_PER_BLOCK
// }}}

bool
FUNC(utf8_decode_to_esc)(UTF8Decoder *d, const uint8_t *src_data, size_t src_len) {
    // Based on the algorithm described in: https://woboq.com/blog/utf-8-processing-using-simd.html
#ifdef compare_with_scalar
    UTF8Decoder debugdec = {0};
    memcpy(&debugdec.state, &d->state, sizeof(debugdec.state));
    bool scalar_sentinel_found = utf8_decode_to_esc_scalar(&debugdec, src_data, src_len);
#endif
    d->output.pos = 0;
    d->num_consumed = 0;
    if (d->state.cur != UTF8_ACCEPT) {
        // Finish the trailing sequence only
        d->num_consumed = scalar_decode_to_accept(d, src_data, src_len);
        src_data += d->num_consumed;
        src_len -= d->num_consumed;
    }
    utf8_decoder_ensure_capacity(d, src_len + 64);
    {
        const size_t consumed = FUNC(utf8_decode_valid_blocks)(d, src_data, src_len);
        d->num_consumed += consumed;
        src_data += consumed;
        src_len -= consumed;
    }
    const integer_t esc_vec = set1_epi8(0x1b);
    const integer_t zero = create_zero_integer(), one = set1_epi8(1), two = set1_epi8(2), three = set1_epi8(3), four = set1_epi8(4),
                    numbered = numbered_bytes(), numbered_in_lane = numbered_bytes_in_lane();
    const uint8_t *limit = src_data + src_len, *p = src_data, *start_of_current_chunk = src_data;
    bool sentinel_found = false;
    unsigned chunk_src_sz = 0;
    unsigned num_of_trailing_bytes = 0;

    bool prev_chunk_was_all_ascii = true; // avoid paying for the fast path attempt in runs of non-ASCII chunks

    while (p < limit && !sentinel_found) {
        // Fast path: process pairs of full chunks that contain only ASCII and no ESC
        if (prev_chunk_was_all_ascii) {
            while ((size_t)(limit - p) >= 2 * sizeof(integer_t)) {
                const integer_t v1 = load_unaligned((integer_t *)p), v2 = load_unaligned((integer_t *)(p + sizeof(integer_t)));
                const integer_t esc_or_non_ascii = or_si(or_si(cmpeq_epi8(v1, esc_vec), cmpeq_epi8(v2, esc_vec)), or_si(v1, v2));
                if (movemask_epi8(esc_or_non_ascii)) break;
                FUNC(output_plain_ascii)(d, v1, sizeof(integer_t));
                FUNC(output_plain_ascii)(d, v2, sizeof(integer_t));
                d->num_consumed += 2 * sizeof(integer_t);
                p += 2 * sizeof(integer_t);
            }
            if (p >= limit) break;
        }
        chunk_src_sz = MIN((size_t)(limit - p), sizeof(integer_t));
        integer_t vec = load_unaligned((integer_t *)p);
        start_of_current_chunk = p;
        p += chunk_src_sz;

        // bit set for every non-ASCII byte and every ESC byte in the chunk
        uint32_t ascii_mask = movemask_epi8(vec);
        uint32_t esc_mask = movemask_epi8(cmpeq_epi8(vec, esc_vec));
        if (chunk_src_sz < sizeof(integer_t)) {
            // exclude the garbage bytes read from beyond limit
            const uint32_t chunk_mask = (1u << chunk_src_sz) - 1;
            ascii_mask &= chunk_mask;
            esc_mask &= chunk_mask;
        }
        if (esc_mask) {
            sentinel_found = true;
            chunk_src_sz = __builtin_ctz(esc_mask);
            ascii_mask &= (1u << chunk_src_sz) - 1;
            d->num_consumed += chunk_src_sz + 1; // esc is also consumed
            if (!chunk_src_sz) continue;
        } else d->num_consumed += chunk_src_sz;

        num_of_trailing_bytes = 0;
        bool check_for_trailing_bytes = !sentinel_found;

        debug_register(vec);

#define abort_with_invalid_utf8()                                                           \
    {                                                                                       \
        scalar_decode_all(d, start_of_current_chunk, chunk_src_sz + num_of_trailing_bytes); \
        d->num_consumed += num_of_trailing_bytes;                                           \
        break;                                                                              \
    }

#define handle_trailing_bytes()                                                     \
    if (num_of_trailing_bytes) {                                                    \
        if (p >= limit) {                                                           \
            scalar_decode_all(d, p - num_of_trailing_bytes, num_of_trailing_bytes); \
            d->num_consumed += num_of_trailing_bytes;                               \
            break;                                                                  \
        }                                                                           \
        p -= num_of_trailing_bytes;                                                 \
    }

    start_classification:
        if (!ascii_mask) { // no bytes with high bit (0x80) set, so just plain ASCII
            FUNC(output_plain_ascii)(d, vec, chunk_src_sz);
            prev_chunk_was_all_ascii = true;
            handle_trailing_bytes();
            continue;
        }
        prev_chunk_was_all_ascii = false;
        // zero the bytes not part of the chunk as they would corrupt classification
        if (chunk_src_sz < sizeof(integer_t)) vec = zero_last_n_bytes(vec, sizeof(integer_t) - chunk_src_sz);
        // Classify the bytes by whether they may be the start of a 2-byte, 3-byte, or 4-byte sequence.
        // This is only an initial, potential classification.
        // 0xC0 and 0xC1 are initially classified as potential starter bytes of 2-byte sequences.
        // And 0xF5..0xFF are initially classified as potential starter bytes of 4-byte sequences.
        // They will be marked as actually invalid later in the chunk_is_invalid checks.
        integer_t state = set1_epi8(0x80);
        const integer_t vec_signed = add_epi8(vec, state); // needed because cmplt_epi8 works only on signed chars
        // state now has 0x80 on all bytes
        const integer_t bytes_indicating_start_of_two_byte_sequence = cmplt_epi8(set1_epi8(0xc0 - 1 - 0x80), vec_signed);
        state = blendv_epi8(state, set1_epi8(0xc2), bytes_indicating_start_of_two_byte_sequence);
        // state now has 0xc2 on all bytes that start a 2 or more byte sequence and 0x80 on the rest
        const integer_t bytes_indicating_start_of_three_byte_sequence = cmplt_epi8(set1_epi8(0xe0 - 1 - 0x80), vec_signed);
        state = blendv_epi8(state, set1_epi8(0xe3), bytes_indicating_start_of_three_byte_sequence);
        const integer_t bytes_indicating_start_of_four_byte_sequence = cmplt_epi8(set1_epi8(0xf0 - 1 - 0x80), vec_signed);
        state = blendv_epi8(state, set1_epi8(0xf4), bytes_indicating_start_of_four_byte_sequence);
        // state now has 0xc2 on all bytes that start a 2 byte sequence, 0xe3 on start of 3-byte, 0xf4 on 4-byte start and 0x80 on rest
        debug_register(state);
        const integer_t mask = and_si(state, set1_epi8(0xf8)); // keep upper 5 bits of state
        debug_register(mask);
        const integer_t count = and_si(state, set1_epi8(0x7)); // keep lower 3 bits of state
        debug_register(count);
        // count contains the number of bytes in the sequence for the start byte of every sequence and zero elsewhere
        // shift 02 bytes by 1 and subtract 1
        const integer_t count_subs1 = subtract_saturate_epu8(count, one);
        integer_t counts = add_epi8(count, shift_right_by_one_byte(count_subs1));
        // shift 03 and 04 bytes by 2 and subtract 2
        counts = add_epi8(counts, shift_right_by_two_bytes(subtract_saturate_epu8(counts, two)));
        // counts now contains the number of bytes remaining in each utf-8 sequence of 2 or more bytes
        debug_register(counts);
        // check for an incomplete trailing utf8 sequence
        if (check_for_trailing_bytes && !is_zero(cmplt_epi8(one, and_si(counts, cmpeq_epi8(numbered, set1_epi8(chunk_src_sz - 1)))))) {
            // The value of counts at the last byte is > 1 indicating we have a trailing incomplete sequence
            check_for_trailing_bytes = false;
            if (start_of_current_chunk[chunk_src_sz - 1] >= 0xc0) num_of_trailing_bytes = 1; // 2-, 3- and 4-byte characters with only 1 byte left
            else if (chunk_src_sz > 1 && start_of_current_chunk[chunk_src_sz - 2] >= 0xe0)
                num_of_trailing_bytes = 2; // 3- and 4-byte characters with only 1 byte left
            else if (chunk_src_sz > 2 && start_of_current_chunk[chunk_src_sz - 3] >= 0xf0)
                num_of_trailing_bytes = 3; // 4-byte characters with only 3 bytes left
            // num_of_trailing_bytes can be zero, when overlapping sequences near the end
            // of the chunk make counts[last] > 1 without an actual incomplete trailing
            // sequence. Reclassification then detects the overlap as invalid.
            if (num_of_trailing_bytes) {
                chunk_src_sz -= num_of_trailing_bytes;
                d->num_consumed -= num_of_trailing_bytes;
                if (!chunk_src_sz) { abort_with_invalid_utf8(); }
                ascii_mask &= (1u << chunk_src_sz) - 1;
                vec = zero_last_n_bytes(vec, sizeof(integer_t) - chunk_src_sz);
            }
            goto start_classification;
        }

        // The next section performs detailed validation of the chunk's byte sequences.
        // It accumulates validation errors into a chunk_is_invalid vector.
        // When chunk_is_invalid has any non-zero byte, then the chunk contains invalid UTF-8.
        // chunk_is_invalid is a vector, and not a bitmask or boolean,
        // because the or_si SIMD operation is empirically faster than movemask_epi8 with |= or ||=.
        integer_t chunk_is_invalid;

        // Only bytes within the ASCII range should have counts[i] == 0, and vice versa.
        // Detect any mismatch between the two conditions for each chunk byte.
        // If there is any mismatch, then the chunk has invalid UTF-8, so set all bytes in chunk_is_invalid to 0xFF;
        // otherwise the chunk might be valid, so set all bytes in chunk_is_invalid to 0x00.
        // Without this, "\x80" would incorrectly be decoded as a "\x00".
        // This also validates that continuation bytes' positions do not have ASCII bytes (< 0x80).
        // Without this, "\xe0\xa0\x7f\x01" would incorrectly be decoded as "\x00\x01".
        // In that example, 0x7F has an ascii_mask bit of 0 (i.e., it is within 0x00..0x7F),
        // but it has a counts value of 1, not 0 (i.e., it is the last remaining byte of a multi-byte sequence).
        // Therefore there is a count mismatch, indicating that the chunk is ill-formed UTF-8.
        // (If the following "\x01" were absent, and the "\x7f" were the last byte of the chunk,
        // then the `check_for_trailing_bytes` validation above detects the error as a trailing incomplete sequence.)
        const uint32_t ascii_sequence_count_mismatches = ascii_mask ^ (uint32_t)movemask_epi8(cmpgt_epi8(counts, zero));
        chunk_is_invalid = set1_epi8(ascii_sequence_count_mismatches ? 0xff : 0x00);

        // Validate 2-byte sequence starter bytes: 0xC0..0xC1 are invalid (overlong encodings for U+0000..U+007F).
        // Without this, "\xc0\x80" would incorrectly be decoded as a "\x00".
        chunk_is_invalid = or_si(chunk_is_invalid, and_si(bytes_indicating_start_of_two_byte_sequence, cmplt_epi8(vec, set1_epi8(0xc2))));

        // Validate 4-byte sequence starter bytes: 0xF5..0xFF are invalid (out of Unicode codespace).
        // Without this, "\xff\x80\x80\x80" would incorrectly be decoded as an ill-formed "\U003C0000".
        chunk_is_invalid = or_si(chunk_is_invalid, and_si(bytes_indicating_start_of_four_byte_sequence, cmpgt_epi8(vec, set1_epi8(0xf4))));

        // Validate that all continuation bytes' positions do not have non-ASCII starter bytes (>=0xC0).
        // If counts[i] > count[i], the chunk byte at i is in the middle of a previous sequence but also classified as a starter byte.
        // Without this, "\xf0\x90\xc2\x80" would have overlapping sequences, and it would be incorrectly decoded elsewhere as an empty string.
        chunk_is_invalid = or_si(chunk_is_invalid, andnot_si(cmplt_epi8(vec, set1_epi8(0xc0)), cmpgt_epi8(counts, count)));

        // The second byte checks below all need the previous byte at each position.
        // Compute the shifted vector once, comparing it for equality with a starter
        // byte gives the same result as shifting the comparison result, since the
        // zero byte shifted in at position 0 cannot equal any starter byte.
        const integer_t prev_bytes = shift_right_by_one_byte(vec);

        // Validate second bytes of E0-starting 3-byte sequences.
        // 0xE0 must be followed by 0xA0..0xBF (not 0x80..0x9F) to avoid overlong encodings.
        // Without this, "\xe0\x80\x80" would incorrectly be decoded as a "\x00".
        const integer_t e0_first_follower_bytes = cmpeq_epi8(prev_bytes, set1_epi8(0xe0));
        chunk_is_invalid = or_si(chunk_is_invalid, and_si(e0_first_follower_bytes, cmplt_epi8(and_si(e0_first_follower_bytes, vec), set1_epi8(0xa0))));

        // Validate second bytes of ED-starting 3-byte sequences.
        // 0xED must be followed by 0x80..0x9F (not 0xA0..0xBF) to avoid UTF-16 surrogates.
        // Without this, "\xed\xa0\x80" would incorrectly be decoded as an isolated surrogate "\uD800".
        const integer_t ed_first_follower_bytes = cmpeq_epi8(prev_bytes, set1_epi8(0xed));
        chunk_is_invalid = or_si(chunk_is_invalid, and_si(ed_first_follower_bytes, cmpgt_epi8(and_si(ed_first_follower_bytes, vec), set1_epi8(0x9f))));

        // Validate second bytes of F0-starting 4-byte sequences.
        // F0 must be followed by 0x90..0xBF (not 0x80..0x8F) to avoid overlong encodings.
        // Without this, "\xf0\x80\x80\x80" would incorrectly be decoded as a "\x0000".
        const integer_t f0_first_follower_bytes = cmpeq_epi8(prev_bytes, set1_epi8(0xf0));
        chunk_is_invalid = or_si(chunk_is_invalid, and_si(f0_first_follower_bytes, cmplt_epi8(and_si(f0_first_follower_bytes, vec), set1_epi8(0x90))));

        // Validate second bytes of F4-starting 4-byte sequences.
        // F4 must be followed by 0x80..0x8F (not 0x90..0xBF) to stay within the Unicode codespace.
        // Without this, "\xf4\x90\x80\x80" would incorrectly be decoded as an ill-formed "\U00110000".
        const integer_t f4_first_follower_bytes = cmpeq_epi8(prev_bytes, set1_epi8(0xf4));
        chunk_is_invalid = or_si(chunk_is_invalid, and_si(f4_first_follower_bytes, cmpgt_epi8(and_si(f4_first_follower_bytes, vec), set1_epi8(0x8f))));

        // Check for any accumulated validation errors and, if found,
        // fall back to slow scalar decoding of this chunk,
        // which handles replacement of invalid sequences with U+FFFD
        if (!is_zero(chunk_is_invalid)) { abort_with_invalid_utf8(); }

        // Process the bytes storing the three resulting bytes that make up the unicode codepoint
        // mask all control bits so that we have only useful bits left
        vec = andnot_si(mask, vec);
        debug_register(vec);

        // Now calculate the three output vectors

        // The lowest byte is made up of 6 bits from locations with counts == 1 and the lowest two bits from locations with count == 2
        // In addition, the ASCII bytes are copied unchanged from vec
        const integer_t vec_non_ascii = andnot_si(cmpeq_epi8(counts, zero), vec);
        debug_register(vec_non_ascii);
        integer_t output1 = blendv_epi8(
            vec,
            or_si(
                // there are no count == 1 locations without a count == 2 location to its left so we dont need to AND with count2_locations
                vec,
                and_si(shift_left_by_bits16(shift_right_by_one_byte(vec_non_ascii), 6), set1_epi8(0xc0))),
            cmpeq_epi8(counts, one));
        debug_register(output1);

        // The next byte is made up of 4 bits (5, 4, 3, 2) from locations with count == 2 and the first 4 bits from locations with count == 3
        const integer_t count2_locations = cmpeq_epi8(counts, two), count3_locations = cmpeq_epi8(counts, three);
        integer_t output2 = and_si(vec, count2_locations);
        output2 = shift_right_by_bits32(output2, 2); // selects the bits 5, 4, 3, 2
        // select the first 4 bits from locs with count == 3 by shifting count 3 locations right by one byte and left by 4 bits
        output2 = or_si(output2, and_si(set1_epi8(0xf0), shift_left_by_bits16(shift_right_by_one_byte(and_si(count3_locations, vec_non_ascii)), 4)));
        output2 = and_si(output2, count2_locations); // keep only the count2 bytes
        output2 = shift_right_by_one_byte(output2);
        debug_register(output2);

        // The last byte is made up of bits 5 and 6 from count == 3 and 3 bits from count == 4
        integer_t output3 = and_si(three, shift_right_by_bits32(vec, 4)); // bits 5 and 6 from count == 3
        const integer_t count4_locations = cmpeq_epi8(counts, four);
        // 3 bits from count == 4 locations, placed at count == 3 locations shifted left by 2 bits
        output3 = or_si(output3, and_si(set1_epi8(0xfc), shift_left_by_bits16(shift_right_by_one_byte(and_si(count4_locations, vec_non_ascii)), 2)));
        output3 = and_si(output3, count3_locations); // keep only count3 bytes
        output3 = shift_right_by_two_bytes(output3);
        debug_register(output3);

        // Shuffle bytes to remove continuation bytes. The compaction is done
        // independently within each 128-bit lane, which needs only cheap in-lane
        // shifts and an in-lane shuffle. The lanes are then joined by output_unicode
        // using the number of codepoints in each lane. Note that sequences spanning
        // a lane boundary are fine: their assembled codepoint lives at the position
        // of the last byte of the sequence, all that matters here is how far
        // leftwards within its lane that position must move.
        const integer_t discarded_locations = cmpgt_epi8(counts, one); // bytes that are not ASCII and not the last byte of a sequence
        // number of discarded bytes at or before each position, within its lane,
        // computed via prefix sum of ones at discarded locations
        integer_t shifts = and_si(one, discarded_locations);
        shifts = add_epi8(shifts, shift_right_in_lane_by_one_byte(shifts));
        shifts = add_epi8(shifts, shift_right_in_lane_by_two_bytes(shifts));
        shifts = add_epi8(shifts, shift_right_in_lane_by_four_bytes(shifts));
        shifts = add_epi8(shifts, shift_right_in_lane_by_eight_bytes(shifts));
        // zero the shifts for discarded continuation bytes
        shifts = andnot_si(discarded_locations, shifts);
        // now we need to convert shifts into a mask for the shuffle. The mask has each byte of the
        // form 0000xxxx the lower four bits indicating the source location within the lane for the byte.
        // First we move the numbers in shifts to discard the unwanted UTF-8 sequence bytes.
        // Every full lane keeps at least four bytes so the numbers are bounded by 12 and we
        // need at most 4 moves. The numbers are monotonic from left to right within a lane and
        // change value only at the end of a UTF-8 sequence. We move them leftwards, accumulating the
        // moves bit-by-bit.
#define move(shifts, amt, which_bit) \
    blendv_epi8(shifts, shift_left_in_lane_by_##amt(shifts), shift_left_in_lane_by_##amt(shift_left_by_bits16(shifts, 8 - which_bit)))
        shifts = move(shifts, one_byte, 1);
        shifts = move(shifts, two_bytes, 2);
        shifts = move(shifts, four_bytes, 3);
        shifts = move(shifts, eight_bytes, 4);
#undef move
        // convert the shifts into a suitable mask for the in-lane shuffle by adding the byte number within the lane to each byte
        shifts = add_epi8(shifts, numbered_in_lane);
        debug_register(shifts);

        output1 = shuffle_epi8(output1, shifts);
        output2 = shuffle_epi8(output2, shifts);
        output3 = shuffle_epi8(output3, shifts);
        debug_register(output1);
        debug_register(output2);
        debug_register(output3);

        uint32_t kept_mask = ~(uint32_t)movemask_epi8(discarded_locations);
        if (chunk_src_sz < 32) kept_mask &= (1u << chunk_src_sz) - 1; // also clears the always zero high bits for the 128-bit case
#if KITTY_SIMD_LEVEL == 128
        const unsigned num_codepoints = __builtin_popcount(kept_mask);
        debug("num_codepoints: %u\n", num_codepoints);
        FUNC(output_unicode)(d, output1, output2, output3, num_codepoints);
#else
        const unsigned num_codepoints_lane0 = __builtin_popcount(kept_mask & 0xffff), num_codepoints_lane1 = __builtin_popcount(kept_mask >> 16);
        debug("num_codepoints: %u\n", num_codepoints_lane0 + num_codepoints_lane1);
        FUNC(output_unicode)(d, output1, output2, output3, num_codepoints_lane0, num_codepoints_lane1);
#endif
        handle_trailing_bytes();
    }
    if (sentinel_found && d->state.cur != UTF8_ACCEPT) {
        // an incomplete UTF-8 sequence was cut off by the sentinel, matching
        // the scalar implementation, emit a replacement char for it
        utf8_decoder_ensure_capacity(d, 1);
        d->output.storage[d->output.pos++] = 0xfffd;
        zero_at_ptr(&d->state);
    }
#ifdef compare_with_scalar
    if (debugdec.output.pos != d->output.pos || debugdec.num_consumed != d->num_consumed ||
        memcmp(d->output.storage, debugdec.output.storage, d->output.pos * sizeof(d->output.storage[0])) != 0 || sentinel_found != scalar_sentinel_found ||
        debugdec.state.cur != d->state.cur) {
        fprintf(
            stderr,
            "vector decode output differs from scalar: input_sz=%zu consumed=(%u %u) output_sz=(%u %u) sentinel=(%d %d) state_changed: %d output_different: "
            "%d\n",
            src_len,
            debugdec.num_consumed,
            d->num_consumed,
            debugdec.output.pos,
            d->output.pos,
            scalar_sentinel_found,
            sentinel_found,
            debugdec.state.cur != d->state.cur,
            memcmp(d->output.storage, debugdec.output.storage, MIN(d->output.pos, debugdec.output.pos) * sizeof(d->output.storage[0])));
        fprintf(stderr, "\"");
        for (unsigned i = 0; i < src_len; i++) {
            if (32 <= src_data[i] && src_data[i] < 0x7f && src_data[i] != '"') fprintf(stderr, "%c", src_data[i]);
            else fprintf(stderr, "\\x%x", src_data[i]);
        }
        fprintf(stderr, "\"\n");
    }
    utf8_decoder_free(&debugdec);
#endif
    zero_upper();
    return sentinel_found;
#undef abort_with_invalid_utf8
#undef handle_trailing_bytes
}

// Pixel compositing {{{

static inline integer_t
FUNC(load_bytes_as_dwords)(const uint8_t *p) {
#if KITTY_SIMD_LEVEL == 128
    uint32_t v;
    memcpy(&v, p, sizeof(v));
    return simde_mm_cvtepu8_epi32(simde_mm_cvtsi32_si128((int32_t)v));
#else
    return simde_mm256_cvtepu8_epi32(simde_mm_loadl_epi64((const simde__m128i *)p));
#endif
}

void
FUNC(composite_alpha_mask)(uint32_t *dst, const uint8_t *mask, const size_t num_pixels, const uint32_t color_rgb) {
    const uint32_t col = (color_rgb << 8) & 0xffffff00;
    const integer_t col_vec = set1_epi32((int32_t)col), low_byte = set1_epi32(0xff);
    const size_t px_per_iter = sizeof(integer_t) / 4;
    size_t i = 0;
    for (; i + px_per_iter <= num_pixels; i += px_per_iter) {
        const integer_t m = FUNC(load_bytes_as_dwords)(mask + i);
        const integer_t d = load_unaligned((const integer_t *)(dst + i));
        store_unaligned((integer_t *)(dst + i), or_si(col_vec, max_epu32(m, and_si(d, low_byte))));
    }
    for (; i < num_pixels; i++) {
        const uint32_t dst_alpha = dst[i] & 0xff, mask_alpha = mask[i];
        dst[i] = col | MAX(mask_alpha, dst_alpha);
    }
    zero_upper();
}

static inline integer_t
FUNC(div255_epu16)(const integer_t x) {
    // rounding division of 16-bit lanes by 255, exact for values <= 65407, matches div255_round()
    const integer_t y = add_epi16(x, set1_epi16(128));
    return shift_right_by_bits16(add_epi16(y, shift_right_by_bits16(y, 8)), 8);
}

// Blend the 4-byte RGBA pixels in over onto the pixels in under, with under considered fully
// opaque: out_c = round((over_c * alpha + under_c * (255 - alpha)) / 255) for each of the first
// three channels, with the alpha bytes set to 255
static inline integer_t
FUNC(blend_opaque_pixels)(const integer_t under, const integer_t over) {
    const integer_t zero = create_zero_integer();
    const integer_t alpha = shuffle_epi8(over, alpha_broadcast_pattern());
    const integer_t inv_alpha = xor_si(alpha, create_all_ones_integer()); // 255 - alpha in every byte
    const integer_t lo = FUNC(div255_epu16)(
        add_epi16(mullo_epi16(unpacklo_epi8(over, zero), unpacklo_epi8(alpha, zero)), mullo_epi16(unpacklo_epi8(under, zero), unpacklo_epi8(inv_alpha, zero))));
    const integer_t hi = FUNC(div255_epu16)(
        add_epi16(mullo_epi16(unpackhi_epi8(over, zero), unpackhi_epi8(alpha, zero)), mullo_epi16(unpackhi_epi8(under, zero), unpackhi_epi8(inv_alpha, zero))));
    // the per 128-bit lane unpacks and pack are symmetric so byte order is preserved
    return or_si(packus_epi16(lo, hi), set1_epi32((int32_t)0xff000000));
}

#if KITTY_SIMD_LEVEL == 128
#define blend_opaque_pixels_128bit FUNC(blend_opaque_pixels)
#else
// 128-bit version of blend_opaque_pixels for the 3 bytes per pixel destination case, whose
// expand/compact shuffles cannot cross 128-bit lane boundaries
static inline simde__m128i
blend_opaque_pixels_128bit(const simde__m128i under, const simde__m128i over) {
    const simde__m128i zero = simde_mm_setzero_si128(), c128 = simde_mm_set1_epi16(128);
    const simde__m128i alpha = simde_mm_shuffle_epi8(over, simde_mm_set_epi8(15, 15, 15, 15, 11, 11, 11, 11, 7, 7, 7, 7, 3, 3, 3, 3));
    const simde__m128i inv_alpha = simde_mm_xor_si128(alpha, simde_mm_set1_epi64x(-1));
    simde__m128i t, y;
    t = simde_mm_add_epi16(
        simde_mm_mullo_epi16(simde_mm_unpacklo_epi8(over, zero), simde_mm_unpacklo_epi8(alpha, zero)),
        simde_mm_mullo_epi16(simde_mm_unpacklo_epi8(under, zero), simde_mm_unpacklo_epi8(inv_alpha, zero)));
    y = simde_mm_add_epi16(t, c128);
    const simde__m128i lo = simde_mm_srli_epi16(simde_mm_add_epi16(y, simde_mm_srli_epi16(y, 8)), 8);
    t = simde_mm_add_epi16(
        simde_mm_mullo_epi16(simde_mm_unpackhi_epi8(over, zero), simde_mm_unpackhi_epi8(alpha, zero)),
        simde_mm_mullo_epi16(simde_mm_unpackhi_epi8(under, zero), simde_mm_unpackhi_epi8(inv_alpha, zero)));
    y = simde_mm_add_epi16(t, c128);
    const simde__m128i hi = simde_mm_srli_epi16(simde_mm_add_epi16(y, simde_mm_srli_epi16(y, 8)), 8);
    return simde_mm_or_si128(simde_mm_packus_epi16(lo, hi), simde_mm_set1_epi32((int32_t)0xff000000));
}
#endif

void
FUNC(blend_over_opaque)(uint8_t *dst, const unsigned dst_bpp, const uint8_t *src, const size_t num_pixels) {
    size_t i = 0;
    if (dst_bpp == 4) {
        const size_t px_per_iter = sizeof(integer_t) / 4;
        for (; i + px_per_iter <= num_pixels; i += px_per_iter) {
            const integer_t s = load_unaligned((const integer_t *)(src + 4 * i)), d = load_unaligned((const integer_t *)(dst + 4 * i));
            store_unaligned((integer_t *)(dst + 4 * i), FUNC(blend_opaque_pixels)(d, s));
        }
    } else {
        // Expand each group of four 3-byte pixels to 4-byte pixels with a byte shuffle, blend, and
        // compact back with another shuffle, using 128-bit registers at every level since the
        // shuffles cannot cross 128-bit lane boundaries. The 16-byte destination loads cover 4
        // bytes beyond the four pixels being processed, which stay inside dst as long as at least
        // six pixels remain. Only the 12 blended bytes are stored, both to leave the extra bytes
        // untouched and because a 16-byte store would overlap the next iteration's load, stalling
        // on failed store to load forwarding.
        const simde__m128i expand = simde_mm_set_epi8(-1, 11, 10, 9, -1, 8, 7, 6, -1, 5, 4, 3, -1, 2, 1, 0);
        const simde__m128i compact = simde_mm_set_epi8(-1, -1, -1, -1, 14, 13, 12, 10, 9, 8, 6, 5, 4, 2, 1, 0);
        for (; i + 6 <= num_pixels; i += 4) {
            const simde__m128i s = simde_mm_loadu_si128((const simde__m128i *)(src + 4 * i));
            const simde__m128i d = simde_mm_loadu_si128((const simde__m128i *)(dst + 3 * i));
            const simde__m128i blended = simde_mm_shuffle_epi8(blend_opaque_pixels_128bit(simde_mm_shuffle_epi8(d, expand), s), compact);
            simde_mm_storel_epi64((simde__m128i *)(dst + 3 * i), blended);
            const uint32_t last = (uint32_t)simde_mm_extract_epi32(blended, 2);
            memcpy(dst + 3 * i + 8, &last, sizeof(last));
        }
    }
    for (; i < num_pixels; i++) blend_pixel_over_opaque(dst + dst_bpp * i, src + 4 * i, dst_bpp);
    zero_upper();
}

// Straight alpha over blend of pixels unpacked into 32-bit lanes, four consecutive lanes per
// pixel. Matches the arithmetic of blend_pixel_over_straight() bit for bit: exact integer
// numerator and denominator, IEEE single precision division, round to nearest.
static inline integer_t
FUNC(blend_straight_dwords)(const integer_t d, const integer_t s) {
    const integer_t c255 = set1_epi32(255);
    const integer_t alpha = shuffle_epi32(s, _MM_SHUFFLE(3, 3, 3, 3)), dst_alpha = shuffle_epi32(d, _MM_SHUFFLE(3, 3, 3, 3));
    const integer_t inv_alpha = sub_epi32(c255, alpha);
    const integer_t denom = add_epi32(mullo_epi32(alpha, c255), mullo_epi32(dst_alpha, inv_alpha));
    const integer_t num = add_epi32(mullo_epi32(mullo_epi32(s, alpha), c255), mullo_epi32(mullo_epi32(d, dst_alpha), inv_alpha));
    integer_t r = cvtps_epi32(div_ps(cvtepi32_ps(num), cvtepi32_ps(denom)));
    const integer_t y = add_epi32(denom, set1_epi32(128)); // out alpha = round(denom / 255)
    const integer_t out_alpha = shift_right_by_bits32(add_epi32(y, shift_right_by_bits32(y, 8)), 8);
    r = blendv_epi8(r, out_alpha, set_epi32_in_lanes(-1, 0, 0, 0));
    // both src and dst fully transparent => leave dst unchanged (this also discards the NaN from the 0/0 above)
    return blendv_epi8(r, d, cmpeq_epi32(denom, create_zero_integer()));
}

void
FUNC(blend_over_straight)(uint8_t *dst, const uint8_t *src, const size_t num_pixels) {
    const size_t px_per_iter = sizeof(integer_t) / 4;
    size_t i = 0;
    for (; i + px_per_iter <= num_pixels; i += px_per_iter) {
        const integer_t s = load_unaligned((const integer_t *)(src + 4 * i)), d = load_unaligned((const integer_t *)(dst + 4 * i));
        const integer_t r0 = FUNC(blend_straight_dwords)(widen_quarter(d, 0), widen_quarter(s, 0));
        const integer_t r1 = FUNC(blend_straight_dwords)(widen_quarter(d, 1), widen_quarter(s, 1));
        const integer_t r2 = FUNC(blend_straight_dwords)(widen_quarter(d, 2), widen_quarter(s, 2));
        const integer_t r3 = FUNC(blend_straight_dwords)(widen_quarter(d, 3), widen_quarter(s, 3));
        store_unaligned((integer_t *)(dst + 4 * i), fixup_packed_dword_order(packus_epi16(packus_epi32(r0, r1), packus_epi32(r2, r3))));
    }
    for (; i < num_pixels; i++) blend_pixel_over_straight(dst + 4 * i, src + 4 * i);
    zero_upper();
}

#undef blend_opaque_pixels_128bit
// }}}

#undef FUNC
#undef integer_t
#undef set1_epi8
#undef set1_epi32
#undef cmpgt_epi32
#undef set_epi8
#undef load_unaligned
#undef load_aligned
#undef store_unaligned
#undef store_aligned
#undef cmpeq_epi8
#undef cmplt_epi8
#undef cmpgt_epi8
#undef or_si
#undef and_si
#undef xor_si
#undef andnot_si
#undef movemask_epi8
#undef CONCAT
#undef CONCAT_EXPAND
#undef KITTY_SIMD_LEVEL
#undef shift_right_by_one_byte
#undef shift_right_by_two_bytes
#undef shift_right_by_four_bytes
#undef shift_right_by_eight_bytes
#undef shift_right_by_sixteen_bytes
#undef shift_left_by_one_byte
#undef shift_left_by_two_bytes
#undef shift_left_by_four_bytes
#undef shift_left_by_eight_bytes
#undef shift_left_by_sixteen_bytes
#undef shift_right_in_lane_by_one_byte
#undef shift_right_in_lane_by_two_bytes
#undef shift_right_in_lane_by_four_bytes
#undef shift_right_in_lane_by_eight_bytes
#undef shift_left_in_lane_by_one_byte
#undef shift_left_in_lane_by_two_bytes
#undef shift_left_in_lane_by_four_bytes
#undef shift_left_in_lane_by_eight_bytes
#undef numbered_bytes_in_lane
#undef shift_left_by_bits16
#undef shift_right_by_bits32
#undef shift_right_by_bytes128
#undef extract_lower_quarter_as_chars
#undef extract_lower_half_as_chars
#undef blendv_epi8
#undef add_epi8
#undef subtract_saturate_epu8
#undef subtract_epi8
#undef create_zero_integer
#undef create_all_ones_integer
#undef shuffle_epi8
#undef numbered_bytes
#undef reverse_numbered_bytes
#undef is_zero
#undef zero_upper
#undef print_register_as_bytes
#undef set1_epi16
#undef add_epi16
#undef mullo_epi16
#undef shift_right_by_bits16
#undef unpacklo_epi8
#undef unpackhi_epi8
#undef packus_epi16
#undef packus_epi32
#undef add_epi32
#undef sub_epi32
#undef mullo_epi32
#undef cmpeq_epi32
#undef max_epu32
#undef shuffle_epi32
#undef cvtepi32_ps
#undef cvtps_epi32
#undef div_ps
#undef set_epi32_in_lanes
#undef alpha_broadcast_pattern
#undef widen_quarter
#undef fixup_packed_dword_order
#endif // KITTY_NO_SIMD
