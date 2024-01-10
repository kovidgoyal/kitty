/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifndef BITS
#define BITS 128
#endif

#include "simd-string.h"

// Boilerplate {{{
#ifdef __clang__
_Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#ifdef __clang__
_Pragma("clang diagnostic pop")
#endif


#define CONCAT(A, B) A##B
#define CONCAT_EXPAND(A, B) CONCAT(A,B)
#define FUNC(name) CONCAT_EXPAND(name##_, BITS)
#define integer_t CONCAT_EXPAND(CONCAT_EXPAND(simde__m, BITS), i)
#define shift_right_by_bytes128 simde_mm_srli_si128
#define count_trailing_zeros __builtin_ctz
#define zero_last_n_bytes FUNC(zero_last_n_bytes)

#if BITS == 128
#define set1_epi8(x) simde_mm_set1_epi8((char)(x))
#define set_epi8 simde_mm_set_epi8
#define add_epi8 simde_mm_add_epi8
#define load_unaligned simde_mm_loadu_si128
#define store_aligned simde_mm_store_si128
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define cmplt_epi8 simde_mm_cmplt_epi8
#define cmpgt_epi8 simde_mm_cmpgt_epi8
#define or_si simde_mm_or_si128
#define and_si simde_mm_and_si128
#define andnot_si simde_mm_andnot_si128
#define movemask_epi8 simde_mm_movemask_epi8
#define extract_lower_quarter_as_chars simde_mm_cvtepu8_epi32
#define shift_right_by_one_byte(x) simde_mm_slli_si128(x, 1)
#define shift_right_by_two_bytes(x) simde_mm_slli_si128(x, 2)
#define shift_right_by_four_bytes(x) simde_mm_slli_si128(x, 4)
#define shift_right_by_eight_bytes(x) simde_mm_slli_si128(x, 8)
#define shift_right_by_sixteen_bytes(x) simde_mm_slli_si128(x, 16)
#define shift_left_by_one_byte(x) simde_mm_srli_si128(x, 1)
#define shift_left_by_two_bytes(x) simde_mm_srli_si128(x, 2)
#define shift_left_by_four_bytes(x) simde_mm_srli_si128(x, 4)
#define shift_left_by_eight_bytes(x) simde_mm_srli_si128(x, 8)
#define shift_left_by_sixteen_bytes(x) simde_mm_srli_si128(x, 16)
#define blendv_epi8 simde_mm_blendv_epi8
#define shift_left_by_bits16 simde_mm_slli_epi16
#define shift_right_by_bits32 simde_mm_srli_epi32
#define shuffle_epi8 simde_mm_shuffle_epi8
#define numbered_bytes() set_epi8(15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
// output[i] = MAX(0, a[i] - b[1i])
#define subtract_saturate_epu8 simde_mm_subs_epu8
#define create_zero_integer simde_mm_setzero_si128

#else

#define set1_epi8(x) simde_mm256_set1_epi8((char)(x))
#define set_epi8 simde_mm256_set_epi8
#define add_epi8 simde_mm256_add_epi8
#define load_unaligned simde_mm256_loadu_si256
#define store_aligned simde_mm256_store_si256
#define cmpeq_epi8 simde_mm256_cmpeq_epi8
#define cmpgt_epi8 simde_mm256_cmpgt_epi8
#define cmplt_epi8(a, b) cmpgt_epi8(b, a)
#define or_si simde_mm256_or_si256
#define and_si simde_mm256_and_si256
#define andnot_si simde_mm256_andnot_si256
#define movemask_epi8 simde_mm256_movemask_epi8
#define extract_lower_half_as_chars simde_mm256_cvtepu8_epi32
#define blendv_epi8 simde_mm256_blendv_epi8
#define subtract_saturate_epu8 simde_mm256_subs_epu8
#define shift_left_by_bits16 simde_mm256_slli_epi16
#define shift_right_by_bits32 simde_mm256_srli_epi32
#define create_zero_integer simde_mm256_setzero_si256
#define shift_right_by_one_byte(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 1)
#define shift_right_by_two_bytes(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 2)
#define shift_right_by_four_bytes(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 4)
#define shift_right_by_eight_bytes(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 8)
#define shift_right_by_sixteen_bytes(vec) simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(0, 0, 2, 0))
#define shift_left_by_one_byte(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(2, 0, 0, 1)), 1)
#define shift_left_by_two_bytes(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(2, 0, 0, 1)), 2)
#define shift_left_by_four_bytes(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(2, 0, 0, 1)), 4)
#define shift_left_by_eight_bytes(vec) simde_mm256_alignr_epi8(vec, simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(2, 0, 0, 1)), 8)
#define shift_left_by_sixteen_bytes(vec) simde_mm256_permute2x128_si256(vec, vec, _MM_SHUFFLE(2, 0, 0, 1))
#define numbered_bytes() set_epi8(31,30,29,28,27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)

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
#endif
// }}}

static inline integer_t
FUNC(zero_last_n_bytes)(integer_t vec, int n) {
    const integer_t threshold = set1_epi8(n);
    const integer_t index = numbered_bytes();
    return andnot_si(cmpgt_epi8(threshold, index), vec);
}

static inline const uint8_t*
FUNC(find_either_of_two_bytes)(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    const integer_t a_vec = set1_epi8(a), b_vec = set1_epi8(b);
    for (const uint8_t* limit = haystack + sz; haystack < limit; haystack += sizeof(integer_t)) {
        const integer_t chunk = load_unaligned((integer_t*)haystack);
        const integer_t a_cmp = cmpeq_epi8(chunk, a_vec);
        const integer_t b_cmp = cmpeq_epi8(chunk, b_vec);
        const integer_t matches = or_si(a_cmp, b_cmp);
        const int mask = movemask_epi8(matches);
        if (mask != 0) {
            size_t pos = count_trailing_zeros(mask);
            const uint8_t *ans = haystack + pos;
            if (ans < limit) return ans;
        }
    }
    return NULL;
}

#if 1
#define print_register_as_bytes(r) { \
    printf("%s:\n", #r); \
    alignas(64) uint8_t data[sizeof(r)]; \
    store_aligned((integer_t*)data, r); \
    for (unsigned i = 0; i < sizeof(integer_t); i++) { \
        uint8_t ch = data[i]; \
        if (' ' <= ch && ch < 0x7f) printf("_%c ", ch); else printf("%.2x ", ch); \
    } \
    printf("\n"); \
}
#else
#define print_register_as_bytes(r)
#endif

static inline void
FUNC(output_plain_ascii)(UTF8Decoder *d, integer_t vec, size_t src_sz) {
#if BITS == 128
    for (const uint32_t *limit = d->output + src_sz, *p = d->output; p < limit; p += sizeof(integer_t)/sizeof(uint32_t)) {
        const integer_t unpacked = extract_lower_quarter_as_chars(vec);
        store_aligned((integer_t*)p, unpacked);
        vec = shift_right_by_bytes128(vec, sizeof(integer_t)/sizeof(uint32_t));
    }
#else
    const uint32_t *limit = d->output + src_sz, *p = d->output;
    simde__m128i x = simde_mm256_extracti128_si256(vec, 0);
    integer_t unpacked = extract_lower_half_as_chars(x);
    store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
    if (p < limit) {
        x = shift_right_by_bytes128(x, sizeof(integer_t)/sizeof(uint32_t));
        unpacked = extract_lower_half_as_chars(x);
        store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
        if (p < limit) {
            x = simde_mm256_extracti128_si256(vec, 1);
            unpacked = extract_lower_half_as_chars(x);
            store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
            if (p < limit) {
                x = shift_right_by_bytes128(x, sizeof(integer_t)/sizeof(uint32_t));
                unpacked = extract_lower_half_as_chars(x);
                store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
            }
        }
    }
#endif
    d->output_sz = src_sz;
}

static inline void
FUNC(output_unicode)(UTF8Decoder *d, integer_t output1, integer_t output2, integer_t output3, const size_t num_codepoints) {
#if BITS == 128
    for (const uint32_t *limit = d->output + num_codepoints, *p = d->output; p < limit; p += sizeof(integer_t)/sizeof(uint32_t)) {
        const integer_t unpacked1 = extract_lower_quarter_as_chars(output1);
        const integer_t unpacked2 = shift_left_by_one_byte(extract_lower_quarter_as_chars(output2));
        const integer_t unpacked3 = shift_left_by_two_bytes(extract_lower_quarter_as_chars(output3));
        store_aligned((integer_t*)p, or_si(or_si(unpacked1, unpacked2), unpacked3));
        output1 = shift_right_by_bytes128(output1, sizeof(integer_t)/sizeof(d->output[0]));
        output2 = shift_right_by_bytes128(output2, sizeof(integer_t)/sizeof(d->output[0]));
        output3 = shift_right_by_bytes128(output3, sizeof(integer_t)/sizeof(d->output[0]));
    }
#else
    const uint32_t *limit = d->output + num_codepoints;
    uint32_t *p = d->output;
    simde__m128i x1, x2, x3;
#define chunk() { \
        const integer_t unpacked1 = extract_lower_half_as_chars(x1); \
        const integer_t unpacked2 = shift_left_by_one_byte(extract_lower_half_as_chars(x2)); \
        const integer_t unpacked3 = shift_left_by_two_bytes(extract_lower_half_as_chars(x3)); \
        store_aligned((integer_t*)p, or_si(or_si(unpacked1, unpacked2), unpacked3)); \
        p += sizeof(integer_t)/sizeof(uint32_t); \
}
#define extract(which) x1 = simde_mm256_extracti128_si256(output1, which); x2 = simde_mm256_extracti128_si256(output2, which); x3 = simde_mm256_extracti128_si256(output3, which);
#define shift() x1 = shift_right_by_bytes128(x1, sizeof(integer_t)/sizeof(d->output[0])); x2 = shift_right_by_bytes128(x2, sizeof(integer_t)/sizeof(d->output[0])); x3 = shift_right_by_bytes128(x3, sizeof(integer_t)/sizeof(d->output[0]));
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
    d->output_sz += num_codepoints;
}

#ifndef SIMD_STRING_IMPL_INCLUDED_ONCE
static void
scalar_decode_to_accept(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    while (d->num_consumed < src_sz && d->output_sz < arraysz(d->output) && d->state.cur != UTF8_ACCEPT) {
        const uint8_t ch = src[d->num_consumed++];
        switch(ch) {
            case UTF8_ACCEPT:
                d->output[d->output_sz++] = d->state.codep;
                break;
            case UTF8_REJECT: {
                    const bool prev_was_accept = d->state.prev == UTF8_ACCEPT;
                    zero_at_ptr(&d->state);
                    d->output[d->output_sz++] = 0xfffd;
                    if (!prev_was_accept && d->num_consumed) {
                        d->num_consumed--;
                        continue; // so that prev is correct
                    }
            } break;
        }
        d->state.prev = d->state.cur;
    }
}
#endif

static inline bool
FUNC(utf8_decode_to_esc)(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    // Based on the algorithm described in: https://woboq.com/blog/utf-8-processing-using-simd.html
    d->output_sz = 0; d->num_consumed = 0;
    if (d->state.cur != UTF8_ACCEPT) {
        scalar_decode_to_accept(d, src, src_sz);
        src += d->num_consumed; src_sz -= d->num_consumed;
        if (!src_sz) return false;
    }
    src_sz = MIN(src_sz, sizeof(integer_t));
    integer_t vec = load_unaligned((integer_t*)src);

    const integer_t esc_vec = set1_epi8(0x1b);
    const integer_t esc_cmp = cmpeq_epi8(vec, esc_vec);
    const int esc_test_mask = movemask_epi8(esc_cmp);
    bool sentinel_found = false;
    const unsigned num_of_bytes_to_first_esc = count_trailing_zeros(esc_test_mask);
    if (num_of_bytes_to_first_esc < src_sz) {
        sentinel_found = true;
        src_sz = num_of_bytes_to_first_esc;
        d->num_consumed = src_sz + 1;  // esc is also consumed
    } else d->num_consumed = src_sz;
    if (src_sz < sizeof(integer_t)/8) zero_last_n_bytes(vec, sizeof(integer_t)/8 - src_sz);

    const integer_t one = set1_epi8(1), two = set1_epi8(2), three = set1_epi8(3);
    // Classify the bytes
    print_register_as_bytes(vec);
    integer_t state = set1_epi8(0x80);
    const integer_t vec_signed = add_epi8(vec, state); // needed because cmplt_epi8 works only on signed chars

    const integer_t bytes_indicating_start_of_two_byte_sequence = cmplt_epi8(set1_epi8(0xc0 - 1 - 0x80), vec_signed);
    if (
            (unsigned)count_trailing_zeros(movemask_epi8(bytes_indicating_start_of_two_byte_sequence)) >= src_sz &&
            (unsigned)count_trailing_zeros(movemask_epi8(vec)) >= src_sz)
    { // no bytes with high bit (0x80) set, so just plain ASCII
        FUNC(output_plain_ascii)(d, vec, src_sz);
        return sentinel_found;
    }
    state = blendv_epi8(state, set1_epi8(0xc2), bytes_indicating_start_of_two_byte_sequence);
    // state now has 0xc2 on all bytes that start a 2 or more byte sequence and 0x80 on the rest
    const integer_t bytes_indicating_start_of_three_byte_sequence = cmplt_epi8(set1_epi8(0xe0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state, set1_epi8(0xe3), bytes_indicating_start_of_three_byte_sequence);
    const integer_t bytes_indicating_start_of_four_byte_sequence = cmplt_epi8(set1_epi8(0xf0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state, set1_epi8(0xf4), bytes_indicating_start_of_four_byte_sequence);
    // state now has 0xc2 on all bytes that start a 2 byte sequence, 0xe3 on start of 3-byte sequence, 0xf4 on 4-byte start and 0x80 on rest
    print_register_as_bytes(state);
    integer_t mask = and_si(state, set1_epi8(0xf8));  // keep upper 5 bits of state
    print_register_as_bytes(mask);
    integer_t count = and_si(state, set1_epi8(0x7));  // keep lower 3 bits of state
    print_register_as_bytes(count);
    // count contains 0 for ASCII and number of bytes in sequence for other bytes
#define subtract_shift_and_add(target, amt, s) add_epi8(target, shift_right_by_##amt(subtract_saturate_epu8(target, s)))
    // shift 02 bytes by 1 and subtract 1
    integer_t counts = subtract_shift_and_add(count, one_byte, one);
    // shift 03 and 04 bytes by 2 and subtract 2
    counts = subtract_shift_and_add(counts, two_bytes, two);
    // counts now contains the number of bytes remaining in each utf-8 sequence of 2 or more bytes
    print_register_as_bytes(counts);
#undef subtract_shift_and_add

    // Process the bytes storing the three resulting bytes that make up the unicode codepoint
    // mask all control bits so that we have only useful bits left
    vec = andnot_si(mask, vec);
    print_register_as_bytes(vec);

    // Now calculate the three output vectors

    // The lowest byte is made up of 6 bits from locations with counts == 1 and the lowest two bits from locations with count == 2
    // In addition, the ASCII bytes are copied unchanged from vec
    integer_t vec_non_ascii = andnot_si(cmpeq_epi8(counts, create_zero_integer()), vec);
    print_register_as_bytes(vec_non_ascii);
    integer_t vec_right1 = shift_right_by_one_byte(vec_non_ascii);
    integer_t output1 = blendv_epi8(vec,
            or_si(
                vec, and_si(shift_left_by_bits16(vec_right1, 6), set1_epi8(0xc0))
            ),
            cmpeq_epi8(counts, one)
    );
    print_register_as_bytes(output1);

    // The next byte is made up of 4 bits (5, 4, 3, 2) from locations with count == 2 and the first 4 bits from locations with count == 3
    integer_t count2_locations = cmpeq_epi8(counts, two);
    integer_t output2 = and_si(vec, count2_locations);
    output2 = shift_right_by_bits32(output2, 2);  // selects the bits 5, 4, 3, 2
    output2 = or_si(output2, and_si(shift_left_by_bits16(vec_right1, 4), set1_epi8(0xf0))); // move 4 bits left and mask lower four bits and OR
    output2 = and_si(output2, count2_locations); // keep only the count2 bytes
    output2 = shift_right_by_one_byte(output2);
    print_register_as_bytes(output2);

    // The last byte is made up of bits 5 and 6 from count == 3 and 3 bits from count == 4
    integer_t count3_locations = cmpeq_epi8(counts, three);
    integer_t output3 = and_si(three, shift_right_by_bits32(vec, 4));  // bits 5 and 6 from count == 3
    // bits from count == 4 locations, placed at count == 3 locations shifted left by 2 bits
    output3 = or_si(output3, and_si(set1_epi8(0xfc), shift_left_by_bits16(vec_right1, 2)));
    output3 = and_si(output3, count3_locations);  // keep only count3 bytes
    output3 = shift_right_by_two_bytes(output3);
    print_register_as_bytes(output3);

    // Shuffle bytes to remove continuation bytes
    integer_t shifts = subtract_saturate_epu8(count, one);  // number of bytes we need to skip for each UTF-8 sequence
    // propagate the shifts to all subsequent bytes by shift and add
    shifts = add_epi8(shifts, shift_right_by_one_byte(shifts));
    shifts = add_epi8(shifts, shift_right_by_two_bytes(shifts));
    shifts = add_epi8(shifts, shift_right_by_four_bytes(shifts));
    shifts = add_epi8(shifts, shift_right_by_eight_bytes(shifts));
#if BITS == 256
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
    //
#define move(shifts, amt, which_bit) blendv_epi8(shifts, shift_left_by_##amt(shifts), shift_left_by_##amt(shift_left_by_bits16(shifts, 8 - which_bit)))
    shifts = move(shifts, one_byte, 1);
    shifts = move(shifts, two_bytes, 2);
    shifts = move(shifts, four_bytes, 3);
    shifts = move(shifts, eight_bytes, 4);
#if BITS == 256
    shifts = move(shifts, sixteen_bytes, 5);
#endif
#undef move
    // convert the shifts into a suitable mask for shuffle by adding the byte number to each byte
    shifts = add_epi8(shifts, numbered_bytes());
    print_register_as_bytes(shifts);

    output1 = shuffle_epi8(output1, shifts);
    output2 = shuffle_epi8(output2, shifts);
    output3 = shuffle_epi8(output3, shifts);
    print_register_as_bytes(output1);
    print_register_as_bytes(output2);
    print_register_as_bytes(output3);
    return sentinel_found;
}


#undef FUNC
#undef integer_t
#undef set1_epi8
#undef set_epi8
#undef load_unaligned
#undef store_aligned
#undef cmpeq_epi8
#undef cmplt_epi8
#undef cmpgt_epi8
#undef or_si
#undef and_si
#undef andnot_si
#undef movemask_epi8
#undef CONCAT
#undef CONCAT_EXPAND
#undef BITS
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
#undef create_zero_integer
#undef shuffle_epi8
#undef numbered_bytes
#undef zero_last_n_bytes
#ifndef SIMD_STRING_IMPL_INCLUDED_ONCE
#define SIMD_STRING_IMPL_INCLUDED_ONCE
#endif
