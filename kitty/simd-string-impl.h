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
#define CONCAT_EXPAND(A, B) CONCAT(A,B)
#define FUNC(name) CONCAT_EXPAND(name##_, KITTY_SIMD_LEVEL)

#ifdef KITTY_NO_SIMD
#define NOSIMD { fatal("No SIMD implementations for this CPU"); }
bool FUNC(utf8_decode_to_esc)(UTF8Decoder *d UNUSED, const uint8_t *src UNUSED, size_t src_sz UNUSED) NOSIMD
const uint8_t* FUNC(find_either_of_two_bytes)(const uint8_t *haystack UNUSED, const size_t sz UNUSED, const uint8_t a UNUSED, const uint8_t b UNUSED) NOSIMD
void FUNC(xor_data64)(const uint8_t key[64] UNUSED, uint8_t* data UNUSED, const size_t data_sz UNUSED) NOSIMD
#undef NOSIMD
#else

#include "charsets.h"

// Boilerplate {{{
START_IGNORE_DIAGNOSTIC("-Wfloat-conversion")
START_IGNORE_DIAGNOSTIC("-Wpedantic")
#if  defined(__clang__) && __clang_major__ > 13
_Pragma("clang diagnostic push")
_Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#include <simde/arm/neon.h>
#if  defined(__clang__) && __clang_major__ > 13
_Pragma("clang diagnostic pop")
#endif
END_IGNORE_DIAGNOSTIC
END_IGNORE_DIAGNOSTIC


#ifndef _MM_SHUFFLE
#define _MM_SHUFFLE(z, y, x, w) (((z) << 6) | ((y) << 4) | ((x) << 2) | (w))
#endif
#define integer_t CONCAT_EXPAND(CONCAT_EXPAND(simde__m, KITTY_SIMD_LEVEL), i)
#define shift_right_by_bytes128 simde_mm_srli_si128
#define is_zero FUNC(is_zero)

#if KITTY_SIMD_LEVEL == 128
#define set1_epi8(x) simde_mm_set1_epi8((char)(x))
#define set_epi8 simde_mm_set_epi8
#define add_epi8 simde_mm_add_epi8
#define load_unaligned simde_mm_loadu_si128
#define load_aligned(x) simde_mm_load_si128((const integer_t*)(x))
#define store_unaligned simde_mm_storeu_si128
#define store_aligned(dest, vec) simde_mm_store_si128((integer_t*)dest, vec)
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
#define numbered_bytes() set_epi8(15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
#define reverse_numbered_bytes() simde_mm_setr_epi8(15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
// output[i] = MAX(0, a[i] - b[1i])
#define subtract_saturate_epu8 simde_mm_subs_epu8
#define subtract_epi8 simde_mm_sub_epi8
#define create_zero_integer simde_mm_setzero_si128
#define create_all_ones_integer() simde_mm_set1_epi64x(-1)
#define sum_bytes sum_bytes_128
#define zero_upper()

static inline int
FUNC(is_zero)(const integer_t a) { return simde_mm_testz_si128(a, a); }

#define GA(LA) LA(1) LA(2) LA(3) LA(4) LA(5) LA(6) LA(7) LA(8) LA(9) LA(10) LA(11) LA(12) LA(13) LA(14) LA(15)
#define L(n) case n: return simde_mm_srli_si128(A, n);
#define R(n) case n: return simde_mm_slli_si128(A, n);
#define shift_left_by_bytes_macro(A, n) { switch(n) { default: return A; GA(L) } }
#define shift_right_by_bytes_macro(A, n) { switch(n) { default: return A; GA(R) } }

static inline integer_t shift_right_by_bytes(const integer_t A, unsigned n) { shift_right_by_bytes_macro(A, n) }
static inline integer_t shift_left_by_bytes(const integer_t A, unsigned n) { shift_left_by_bytes_macro(A, n) }

#define w(dir, word, num) static inline integer_t shift_##dir##_by_##word(const integer_t A) { shift_##dir##_by_bytes_macro(A, num); }

w(right, one_byte, 1)
w(right, two_bytes, 2)
w(right, four_bytes, 4)
w(right, eight_bytes, 8)
w(right, sixteen_bytes, 16)
w(left, one_byte, 1)
w(left, two_bytes, 2)
w(left, four_bytes, 4)
w(left, eight_bytes, 8)
w(left, sixteen_bytes, 16)
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
#define set_epi8 simde_mm256_set_epi8
#define add_epi8 simde_mm256_add_epi8
#define load_unaligned simde_mm256_loadu_si256
#define load_aligned(x) simde_mm256_load_si256((const integer_t*)(x))
#define store_unaligned simde_mm256_storeu_si256
#define store_aligned(dest, vec) simde_mm256_store_si256((integer_t*)dest, vec)
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
#define numbered_bytes() set_epi8(31,30,29,28,27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
#define reverse_numbered_bytes() simde_mm256_setr_epi8(31,30,29,28,27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)

static inline int
FUNC(is_zero)(const integer_t a) { return simde_mm256_testz_si256(a, a); }

#define GA(LA) LA(1) LA(2) LA(3) LA(4) LA(5) LA(6) LA(7) LA(8) LA(9) LA(10) LA(11) LA(12) LA(13) LA(14) LA(15)
#define GB(LA) LA(17) LA(18) LA(19) LA(20) LA(21) LA(22) LA(23) LA(24) LA(25) LA(26) LA(27) LA(28) LA(29) LA(30) LA(31)
#define RA(n) case n: return simde_mm256_alignr_epi8(A, simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), 16 - n);
#define RB(n)  case n: return simde_mm256_slli_si256(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), n - 16); \

#define shift_right_by_bytes_macro(A, n) { \
    switch(n) { \
        default: return A; \
        GA(RA) \
        case 16: return simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)); \
        GB(RB) \
    } \
}

#define LA(n) case n: return simde_mm256_alignr_epi8(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), A, n);
#define LB(n) case n: return simde_mm256_srli_si256(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), n - 16);
#define shift_left_by_bytes_macro(A, n) { \
    switch(n) { \
        default: return A; \
        GA(LA) \
        case 16: return simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)); \
        GB(LB) \
    } \
}


static inline integer_t shift_right_by_bytes(const integer_t A, unsigned n) { shift_right_by_bytes_macro(A, n) }
static inline integer_t shift_left_by_bytes(const integer_t A, unsigned n) { shift_left_by_bytes_macro(A, n) }

#define w(dir, word, num) static inline integer_t shift_##dir##_by_##word(const integer_t A) { shift_##dir##_by_bytes_macro(A, num); }

w(right, one_byte, 1)
w(right, two_bytes, 2)
w(right, four_bytes, 4)
w(right, eight_bytes, 8)
w(right, sixteen_bytes, 16)
w(left, one_byte, 1)
w(left, two_bytes, 2)
w(left, four_bytes, 4)
w(left, eight_bytes, 8)
w(left, sixteen_bytes, 16)
#undef LA
#undef LB
#undef GA
#undef GB
#undef RA
#undef RB
#undef w
#undef shift_right_by_bytes_macro
#undef shift_left_by_bytes_macro

static inline integer_t shuffle_impl256(const integer_t value, const integer_t shuffle) {
#define K0 simde_mm256_setr_epi8( \
        0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, \
        -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16)

#define K1 simde_mm256_setr_epi8( \
        -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, \
        0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70)

    return or_si(
            simde_mm256_shuffle_epi8(value, add_epi8(shuffle, K0)),
            simde_mm256_shuffle_epi8(simde_mm256_permute4x64_epi64(value, 0x4E), simde_mm256_add_epi8(shuffle, K1))
    );
#undef K0
#undef K1
}

#define shuffle_epi8 shuffle_impl256
#define sum_bytes(x) (sum_bytes_128(simde_mm256_extracti128_si256(x, 0)) + sum_bytes_128(simde_mm256_extracti128_si256(x, 1)))
#endif

#define print_register_as_bytes(r) { \
    printf("%s:\n", #r); \
    alignas(64) uint8_t data[sizeof(r)]; \
    store_unaligned((integer_t*)data, r); \
    for (unsigned i = 0; i < sizeof(integer_t); i++) { \
        uint8_t ch = data[i]; \
        if (' ' <= ch && ch < 0x7f) printf("_%c ", ch); else printf("%.2x ", ch); \
    } \
    printf("\n"); \
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

static inline uint64_t
movemask_arm128(const simde__m128i vec) {
    simde_uint8x8_t res = simde_vshrn_n_u16(simde_vreinterpretq_u16_u8((simde_uint8x16_t)vec), 4);
    return simde_vget_lane_u64(simde_vreinterpret_u64_u8(res), 0);
}

#if KITTY_SIMD_LEVEL == 128

static inline int
bytes_to_first_match(const integer_t vec) { const uint64_t m = movemask_arm128(vec); return m ? (__builtin_ctzll(m) >> 2) : -1; }

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

static inline int
bytes_to_first_match(const integer_t vec) {
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
FUNC(xor_data64)(const uint8_t key[KEY_SIZE], uint8_t* data, const size_t data_sz) {
    // First process unaligned bytes at the start of data
    const uintptr_t unaligned_bytes = KEY_SIZE - ((uintptr_t)data & (KEY_SIZE - 1));
    if (data_sz <= unaligned_bytes) { for (unsigned i = 0; i < data_sz; i++) data[i] ^= key[i]; return; }
    for (unsigned i = 0; i < unaligned_bytes; i++) data[i] ^= key[i];

    // Rotate the key by unaligned_bytes
    alignas(sizeof(integer_t)) char aligned_key[KEY_SIZE];
    memcpy(aligned_key, key + unaligned_bytes, KEY_SIZE - unaligned_bytes);
    memcpy(aligned_key + KEY_SIZE - unaligned_bytes, key, unaligned_bytes);

    const integer_t v1 = load_aligned(aligned_key), v2 = load_aligned(aligned_key + sizeof(integer_t));
#if KITTY_SIMD_LEVEL == 128
    const integer_t v3 = load_aligned(aligned_key + 2*sizeof(integer_t)), v4 = load_aligned(aligned_key + 3 * sizeof(integer_t));
#endif
    // Process KEY_SIZE aligned chunks using SIMD
    integer_t d;
    uint8_t *p = data + unaligned_bytes, *limit = data + data_sz;
    const uintptr_t trailing_bytes = (uintptr_t)limit & (KEY_SIZE - 1);
    limit -= trailing_bytes;
    // p is aligned to first KEY_SIZE boundary >= data and limit is aligned to first KEY_SIZE boundary <= (data + data_sz)
#define do_one(which) d = load_aligned(p); store_aligned(p, xor_si(which, d)); p += sizeof(integer_t);
    while (p < limit) {
        do_one(v1); do_one(v2);
#if KITTY_SIMD_LEVEL == 128
        do_one(v3); do_one(v4);
#endif
    }
#undef do_one
    // Process remaining trailing_bytes
    for (unsigned i = 0; i < trailing_bytes; i++) limit[i] ^= aligned_key[i];
    zero_upper(); return;
}
#undef KEY_SIZE

#define check_chunk() if (n > -1) { \
    const uint8_t *ans = haystack + n; \
    zero_upper(); \
    return ans < limit ? ans : NULL; \
}

#define find_match(haystack, sz, get_test_vec) { \
    const uint8_t* limit = haystack + sz; \
    integer_t chunk; int n; \
\
    { /* first chunk which is possibly unaligned */  \
        const uintptr_t addr = (uintptr_t)haystack; \
        const uintptr_t unaligned_bytes = addr & (sizeof(integer_t) - 1); \
        chunk = load_aligned(haystack - unaligned_bytes); /* this is an aligned load from the first aligned pos before haystack */ \
        n = bytes_to_first_match_ignoring_leading_n(get_test_vec(chunk), unaligned_bytes); \
        check_chunk(); \
        haystack += sizeof(integer_t) - unaligned_bytes; \
    } \
\
    /* Iterate over aligned chunks */ \
    for (; haystack < limit; haystack += sizeof(integer_t)) { \
        chunk = load_aligned(haystack); \
        n = bytes_to_first_match(get_test_vec(chunk)); \
        check_chunk(); \
    } \
    zero_upper(); \
    return NULL;\
}

const uint8_t*
FUNC(find_either_of_two_bytes)(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    if (!sz) return NULL;
    const integer_t a_vec = set1_epi8(a), b_vec = set1_epi8(b);
#define get_test_from_chunk(chunk) (or_si(cmpeq_epi8(chunk, a_vec), cmpeq_epi8(chunk, b_vec)))
    find_match(haystack, sz, get_test_from_chunk);
#undef get_test_from_chunk
}

#undef check_chunk

#define output_increment sizeof(integer_t)/sizeof(uint32_t)

static inline void
FUNC(output_plain_ascii)(UTF8Decoder *d, integer_t vec, size_t src_sz) {
    utf8_decoder_ensure_capacity(d, src_sz);
#if KITTY_SIMD_LEVEL == 128
    for (const uint32_t *p = d->output.storage + d->output.pos, *limit = p + src_sz; p < limit; p += output_increment) {
        const integer_t unpacked = extract_lower_quarter_as_chars(vec);
        store_unaligned((integer_t*)p, unpacked);
        vec = shift_right_by_bytes128(vec, output_increment);
    }
#else
    const uint32_t *p = d->output.storage + d->output.pos, *limit = p + src_sz;
    simde__m128i x = simde_mm256_extracti128_si256(vec, 0);
    integer_t unpacked = extract_lower_half_as_chars(x);
    store_unaligned((integer_t*)p, unpacked); p += output_increment;
    if (p < limit) {
        x = shift_right_by_bytes128(x, output_increment);
        unpacked = extract_lower_half_as_chars(x);
        store_unaligned((integer_t*)p, unpacked); p += output_increment;
        if (p < limit) {
            x = simde_mm256_extracti128_si256(vec, 1);
            unpacked = extract_lower_half_as_chars(x);
            store_unaligned((integer_t*)p, unpacked); p += output_increment;
            if (p < limit) {
                x = shift_right_by_bytes128(x, output_increment);
                unpacked = extract_lower_half_as_chars(x);
                store_unaligned((integer_t*)p, unpacked); p += output_increment;
            }
        }
    }
#endif
    d->output.pos += src_sz;
}

static inline void
FUNC(output_unicode)(UTF8Decoder *d, integer_t output1, integer_t output2, integer_t output3, const size_t num_codepoints) {
    utf8_decoder_ensure_capacity(d, 64);
#if KITTY_SIMD_LEVEL == 128
    for (const uint32_t *p = d->output.storage + d->output.pos, *limit = p + num_codepoints; p < limit; p += output_increment) {
        const integer_t unpacked1 = extract_lower_quarter_as_chars(output1);
        const integer_t unpacked2 = shift_right_by_one_byte(extract_lower_quarter_as_chars(output2));
        const integer_t unpacked3 = shift_right_by_two_bytes(extract_lower_quarter_as_chars(output3));
        const integer_t unpacked = or_si(or_si(unpacked1, unpacked2), unpacked3);
        store_unaligned((integer_t*)p, unpacked);
        output1 = shift_right_by_bytes128(output1, output_increment);
        output2 = shift_right_by_bytes128(output2, output_increment);
        output3 = shift_right_by_bytes128(output3, output_increment);
    }
#else
    uint32_t *p = d->output.storage + d->output.pos;
    const uint32_t *limit = p + num_codepoints;
    simde__m128i x1, x2, x3;
#define chunk() { \
        const integer_t unpacked1 = extract_lower_half_as_chars(x1); \
        const integer_t unpacked2 = shift_right_by_one_byte(extract_lower_half_as_chars(x2)); \
        const integer_t unpacked3 = shift_right_by_two_bytes(extract_lower_half_as_chars(x3)); \
        store_unaligned((integer_t*)p, or_si(or_si(unpacked1, unpacked2), unpacked3)); \
        p += output_increment; \
}
#define extract(which) x1 = simde_mm256_extracti128_si256(output1, which); x2 = simde_mm256_extracti128_si256(output2, which); x3 = simde_mm256_extracti128_si256(output3, which);
#define shift() x1 = shift_right_by_bytes128(x1, output_increment); x2 = shift_right_by_bytes128(x2, output_increment); x3 = shift_right_by_bytes128(x3, output_increment);
    extract(0); chunk();
    if (p < limit) {
        shift(); chunk();
        if (p < limit) {
            extract(1); chunk();
            if (p < limit) {
                shift(); chunk();
            }
        }
    }
#undef chunk
#undef extract
#undef shift
#endif
    d->output.pos += num_codepoints;
}
#undef output_increment

static inline unsigned
sum_bytes_128(simde__m128i v) {
    // Use _mm_sad_epu8 to perform a sum of absolute differences against zero
    // This sums up all 8-bit integers in the 128-bit vector and packs the result into a 64-bit integer
    simde__m128i sum = simde_mm_sad_epu8(v, simde_mm_setzero_si128());

    // At this point, the sum of the first half is in the lower 64 bits, and the sum of the second half is in the upper 64 bits.
    // Extract the lower and upper 64-bit sums and add them together.
    const unsigned lower_sum = simde_mm_cvtsi128_si32(sum); // Extracts the lower 32 bits
    const unsigned upper_sum = simde_mm_cvtsi128_si32(simde_mm_srli_si128(sum, 8)); // Extracts the upper 32 bits

    return lower_sum + upper_sum; // Final sum of all bytes
}

#define do_one_byte \
    const uint8_t ch = src[pos++]; \
    switch (decode_utf8(&d->state.cur, &d->state.codep, ch)) { \
        case UTF8_ACCEPT: \
            d->output.storage[d->output.pos++] = d->state.codep; \
            break; \
        case UTF8_REJECT: { \
                const bool prev_was_accept = d->state.prev == UTF8_ACCEPT; \
                zero_at_ptr(&d->state); \
                d->output.storage[d->output.pos++] = 0xfffd; \
                if (!prev_was_accept) { \
                    pos--; \
                    continue; /* so that prev is correct */ \
                } \
        } break; \
    } \
    d->state.prev = d->state.cur;

static inline size_t
scalar_decode_to_accept(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (pos < src_sz && d->state.cur != UTF8_ACCEPT) {
        do_one_byte
    }
    return pos;
}

static inline size_t
scalar_decode_all(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (pos < src_sz) {
        do_one_byte
    }
    return pos;
}

#undef do_one_byte

bool
FUNC(utf8_decode_to_esc)(UTF8Decoder *d, const uint8_t *src_data, size_t src_len) {
    // Based on the algorithm described in: https://woboq.com/blog/utf-8-processing-using-simd.html
#ifdef compare_with_scalar
    UTF8Decoder debugdec ={0};
    memcpy(&debugdec.state, &d->state, sizeof(debugdec.state));
    bool scalar_sentinel_found = utf8_decode_to_esc_scalar(&debugdec, src_data, src_len);
#endif
    d->output.pos = 0; d->num_consumed = 0;
    if (d->state.cur != UTF8_ACCEPT) {
        // Finish the trailing sequence only
        d->num_consumed = scalar_decode_to_accept(d, src_data, src_len);
        src_data += d->num_consumed; src_len -= d->num_consumed;
    }
    const integer_t esc_vec = set1_epi8(0x1b);
    const integer_t zero = create_zero_integer(), one = set1_epi8(1), two = set1_epi8(2), three = set1_epi8(3), numbered = numbered_bytes();
    const uint8_t *limit = src_data + src_len, *p = src_data, *start_of_current_chunk = src_data;
    bool sentinel_found = false;
    unsigned chunk_src_sz = 0;
    unsigned num_of_trailing_bytes = 0;

    while (p < limit && !sentinel_found) {
        chunk_src_sz = MIN((size_t)(limit - p), sizeof(integer_t));
        integer_t vec = load_unaligned((integer_t*)p);
        start_of_current_chunk = p;
        p += chunk_src_sz;

        const integer_t esc_cmp = cmpeq_epi8(vec, esc_vec);
        int num_of_bytes_to_first_esc = bytes_to_first_match(esc_cmp);
        if (num_of_bytes_to_first_esc > -1 && (unsigned)num_of_bytes_to_first_esc < chunk_src_sz) {
            sentinel_found = true;
            chunk_src_sz = num_of_bytes_to_first_esc;
            d->num_consumed += chunk_src_sz + 1;  // esc is also consumed
            if (!chunk_src_sz) continue;
        } else d->num_consumed += chunk_src_sz;

        if (chunk_src_sz < sizeof(integer_t)) vec = zero_last_n_bytes(vec, sizeof(integer_t) - chunk_src_sz);

        num_of_trailing_bytes = 0;
        bool check_for_trailing_bytes = !sentinel_found;

        debug_register(vec);
        int32_t ascii_mask;

#define abort_with_invalid_utf8() { \
    scalar_decode_all(d, start_of_current_chunk, chunk_src_sz + num_of_trailing_bytes); \
    d->num_consumed += num_of_trailing_bytes; \
    break; \
}

#define handle_trailing_bytes() if (num_of_trailing_bytes) { \
    if (p >= limit) { \
        scalar_decode_all(d, p - num_of_trailing_bytes, num_of_trailing_bytes); \
        d->num_consumed += num_of_trailing_bytes; \
        break; \
    } \
    p -= num_of_trailing_bytes; \
}

start_classification:
        // Check if we have pure ASCII and use fast path
        ascii_mask = movemask_epi8(vec);
        if (!ascii_mask) { // no bytes with high bit (0x80) set, so just plain ASCII
            FUNC(output_plain_ascii)(d, vec, chunk_src_sz);
            handle_trailing_bytes();
            continue;
        }
        // Classify the bytes
        integer_t state = set1_epi8(0x80);
        const integer_t vec_signed = add_epi8(vec, state); // needed because cmplt_epi8 works only on signed chars

        const integer_t bytes_indicating_start_of_two_byte_sequence = cmplt_epi8(set1_epi8(0xc0 - 1 - 0x80), vec_signed);
        state = blendv_epi8(state, set1_epi8(0xc2), bytes_indicating_start_of_two_byte_sequence);
        // state now has 0xc2 on all bytes that start a 2 or more byte sequence and 0x80 on the rest
        const integer_t bytes_indicating_start_of_three_byte_sequence = cmplt_epi8(set1_epi8(0xe0 - 1 - 0x80), vec_signed);
        state = blendv_epi8(state, set1_epi8(0xe3), bytes_indicating_start_of_three_byte_sequence);
        const integer_t bytes_indicating_start_of_four_byte_sequence = cmplt_epi8(set1_epi8(0xf0 - 1 - 0x80), vec_signed);
        state = blendv_epi8(state, set1_epi8(0xf4), bytes_indicating_start_of_four_byte_sequence);
        // state now has 0xc2 on all bytes that start a 2 byte sequence, 0xe3 on start of 3-byte, 0xf4 on 4-byte start and 0x80 on rest
        debug_register(state);
        const integer_t mask = and_si(state, set1_epi8(0xf8));  // keep upper 5 bits of state
        debug_register(mask);
        const integer_t count = and_si(state, set1_epi8(0x7));  // keep lower 3 bits of state
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
            if (start_of_current_chunk[chunk_src_sz-1] >= 0xc0) num_of_trailing_bytes = 1;      // 2-, 3- and 4-byte characters with only 1 byte left
            else if (chunk_src_sz > 1 && start_of_current_chunk[chunk_src_sz-2] >= 0xe0) num_of_trailing_bytes = 2; // 3- and 4-byte characters with only 1 byte left
            else if (chunk_src_sz > 2 && start_of_current_chunk[chunk_src_sz-3] >= 0xf0) num_of_trailing_bytes = 3; // 4-byte characters with only 3 bytes left
            chunk_src_sz -= num_of_trailing_bytes;
            d->num_consumed -= num_of_trailing_bytes;
            if (!chunk_src_sz) { abort_with_invalid_utf8(); }
            vec = zero_last_n_bytes(vec, sizeof(integer_t) - chunk_src_sz);
            goto start_classification;
        }
        // Only ASCII chars should have corresponding byte of counts == 0
        if (ascii_mask != movemask_epi8(cmpgt_epi8(counts, zero))) { abort_with_invalid_utf8(); }
        // The difference between a byte in counts and the next one should be negative,
        // zero, or one. Any other value means there is not enough continuation bytes.
        if (!is_zero(cmpgt_epi8(subtract_epi8(shift_right_by_one_byte(counts), counts), one))) { abort_with_invalid_utf8(); }

        // Process the bytes storing the three resulting bytes that make up the unicode codepoint
        // mask all control bits so that we have only useful bits left
        vec = andnot_si(mask, vec);
        debug_register(vec);

        // Now calculate the three output vectors

        // The lowest byte is made up of 6 bits from locations with counts == 1 and the lowest two bits from locations with count == 2
        // In addition, the ASCII bytes are copied unchanged from vec
        const integer_t vec_non_ascii = andnot_si(cmpeq_epi8(counts, zero), vec);
        debug_register(vec_non_ascii);
        integer_t output1 = blendv_epi8(vec,
                or_si(
                    // there are no count == 1 locations without a count == 2 location to its left so we dont need to AND with count2_locations
                    vec, and_si(shift_left_by_bits16(shift_right_by_one_byte(vec_non_ascii), 6), set1_epi8(0xc0))
                ),
                cmpeq_epi8(counts, one)
        );
        debug_register(output1);

        // The next byte is made up of 4 bits (5, 4, 3, 2) from locations with count == 2 and the first 4 bits from locations with count == 3
        const integer_t count2_locations = cmpeq_epi8(counts, two), count3_locations = cmpeq_epi8(counts, three);
        integer_t output2 = and_si(vec, count2_locations);
        output2 = shift_right_by_bits32(output2, 2);  // selects the bits 5, 4, 3, 2
        // select the first 4 bits from locs with count == 3 by shifting count 3 locations right by one byte and left by 4 bits
        output2 = or_si(output2,
            and_si(set1_epi8(0xf0),
                shift_left_by_bits16(shift_right_by_one_byte(and_si(count3_locations, vec_non_ascii)), 4)
            )
        );
        output2 = and_si(output2, count2_locations); // keep only the count2 bytes
        output2 = shift_right_by_one_byte(output2);
        debug_register(output2);

        // The last byte is made up of bits 5 and 6 from count == 3 and 3 bits from count == 4
        integer_t output3 = and_si(three, shift_right_by_bits32(vec, 4));  // bits 5 and 6 from count == 3
        const integer_t count4_locations = cmpeq_epi8(counts, set1_epi8(4));
        // 3 bits from count == 4 locations, placed at count == 3 locations shifted left by 2 bits
        output3 = or_si(output3,
            and_si(set1_epi8(0xfc),
                shift_left_by_bits16(shift_right_by_one_byte(and_si(count4_locations, vec_non_ascii)), 2)
            )
        );
        output3 = and_si(output3, count3_locations);  // keep only count3 bytes
        output3 = shift_right_by_two_bytes(output3);
        debug_register(output3);

        // Shuffle bytes to remove continuation bytes
        integer_t shifts = count_subs1;  // number of bytes we need to skip for each UTF-8 sequence
        // propagate the shifts to all subsequent bytes by shift and add
        shifts = add_epi8(shifts, shift_right_by_one_byte(shifts));
        shifts = add_epi8(shifts, shift_right_by_two_bytes(shifts));
        shifts = add_epi8(shifts, shift_right_by_four_bytes(shifts));
        shifts = add_epi8(shifts, shift_right_by_eight_bytes(shifts));
#if KITTY_SIMD_LEVEL == 256
        shifts = add_epi8(shifts, shift_right_by_sixteen_bytes(shifts));
#endif
        // zero the shifts for discarded continuation bytes
        shifts = and_si(shifts, cmplt_epi8(counts, two));
        // now we need to convert shifts into a mask for the shuffle. The mask has each byte of the
        // form 0000xxxx the lower four bits indicating the destination location for the byte. For 256 bit shuffle we use lower 5 bits.
        // First we move the numbers in shifts to discard the unwanted UTF-8 sequence bytes. We note that the numbers
        // are bounded by sizeof(integer_t) and so we need at most 4 (for 128 bit) or 5 (for 256 bit) moves. The numbers are
        // monotonic from left to right and change value only at the end of a UTF-8 sequence. We move them leftwards, accumulating the
        // moves bit-by-bit.
#define move(shifts, amt, which_bit) blendv_epi8(shifts, shift_left_by_##amt(shifts), shift_left_by_##amt(shift_left_by_bits16(shifts, 8 - which_bit)))
        shifts = move(shifts, one_byte, 1);
        shifts = move(shifts, two_bytes, 2);
        shifts = move(shifts, four_bytes, 3);
        shifts = move(shifts, eight_bytes, 4);
#if KITTY_SIMD_LEVEL == 256
        shifts = move(shifts, sixteen_bytes, 5);
#endif
#undef move
        // convert the shifts into a suitable mask for shuffle by adding the byte number to each byte
        shifts = add_epi8(shifts, numbered);
        debug_register(shifts);

        output1 = shuffle_epi8(output1, shifts);
        output2 = shuffle_epi8(output2, shifts);
        output3 = shuffle_epi8(output3, shifts);
        debug_register(output1);
        debug_register(output2);
        debug_register(output3);

        const unsigned num_of_discarded_bytes = sum_bytes(count_subs1);
        const unsigned num_codepoints = chunk_src_sz - num_of_discarded_bytes;
        debug("num_of_discarded_bytes: %u num_codepoints: %u\n", num_of_discarded_bytes, num_codepoints);
        FUNC(output_unicode)(d, output1, output2, output3, num_codepoints);
        handle_trailing_bytes();
    }
#ifdef compare_with_scalar
    if (debugdec.output.pos != d->output.pos || debugdec.num_consumed != d->num_consumed ||
        memcmp(d->output.storage, debugdec.output.storage, d->output.pos * sizeof(d->output.storage[0])) != 0 ||
        sentinel_found != scalar_sentinel_found || debugdec.state.cur != d->state.cur
    ) {
        fprintf(stderr, "vector decode output differs from scalar: input_sz=%zu consumed=(%u %u) output_sz=(%u %u) sentinel=(%d %d) state_changed: %d output_different: %d\n",
                src_len, debugdec.num_consumed, d->num_consumed, debugdec.output.pos, d->output.pos, scalar_sentinel_found, sentinel_found,
                debugdec.state.cur != d->state.cur,
                memcmp(d->output.storage, debugdec.output.storage, MIN(d->output.pos, debugdec.output.pos) * sizeof(d->output.storage[0]))
        );
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


#undef FUNC
#undef integer_t
#undef set1_epi8
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
#undef sum_bytes
#undef is_zero
#undef zero_upper
#undef print_register_as_bytes
#endif // KITTY_NO_SIMD
