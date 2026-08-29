/*
 * simd-string-512.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 *
 * AVX-512 (F, BW, VL, VBMI2) implementations of utf8_decode_to_esc,
 * find_either_of_two_bytes, xor_data64, printable_ascii_run_length and the
 * pixel compositing functions. Unlike
 * the 128/256 bit implementations in simd-string-impl.h these are x86-64 only
 * and use native intrinsics, since the algorithms are built around mask
 * registers and masked loads/stores (and vpcompressb for UTF-8 decoding),
 * which have no efficient equivalents on other platforms. The overall UTF-8
 * decoding algorithm is the same as the one in simd-string-impl.h, see there
 * for detailed comments, only the differences are commented here.
 */

#include "data-types.h"
#include "simd-string.h"

#if (defined(__x86_64__) || defined(__amd64__)) && !defined(KITTY_NO_SIMD)

#include "charsets.h"
#include <immintrin.h>

// Masked loads and stores fault-suppress the masked out bytes, so unlike the
// 128/256 bit implementations no alignment gymnastics are needed to avoid
// reading or writing beyond the ends of buffers.

const uint8_t *
find_either_of_two_bytes_512(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    const __m512i a_vec = _mm512_set1_epi8((char)a), b_vec = _mm512_set1_epi8((char)b);
    const uint8_t *ans = NULL;
    for (size_t i = 0; i < sz; i += 64) {
        const uint64_t chunk_bits = sz - i >= 64 ? ~0ull : (1ull << (sz - i)) - 1;
        // the masked load zeroes the bytes beyond the end of the haystack, exclude
        // them from the matches as a or b could be zero
        const __m512i chunk = _mm512_maskz_loadu_epi8(chunk_bits, haystack + i);
        const uint64_t matches = chunk_bits & (_mm512_cmpeq_epi8_mask(chunk, a_vec) | _mm512_cmpeq_epi8_mask(chunk, b_vec));
        if (matches) {
            ans = haystack + i + __builtin_ctzll(matches);
            break;
        }
    }
    _mm256_zeroupper();
    return ans;
}

void
xor_data64_512(const uint8_t key[64], uint8_t *data, const size_t data_sz) {
    // The key size equals the register width, so unlike the 128/256 bit
    // implementations no rotation of the key is ever needed.
    const __m512i key_vec = _mm512_loadu_si512(key);
    size_t i = 0;
    for (; i + 64 <= data_sz; i += 64) _mm512_storeu_si512(data + i, _mm512_xor_si512(_mm512_loadu_si512(data + i), key_vec));
    if (i < data_sz) {
        const uint64_t tail_bits = (1ull << (data_sz - i)) - 1;
        _mm512_mask_storeu_epi8(data + i, tail_bits, _mm512_xor_si512(_mm512_maskz_loadu_epi8(tail_bits, data + i), key_vec));
    }
    _mm256_zeroupper();
}

size_t
printable_ascii_run_length_512(const uint32_t *chars, const size_t sz) {
    // Length of the prefix of chars that contains only printable ASCII codepoints, 32 <= ch <= 126
    const __m512i lower = _mm512_set1_epi32(32), upper = _mm512_set1_epi32(126);
    size_t ans = sz;
    for (size_t i = 0; i < sz; i += 16) {
        const uint16_t chunk_bits = sz - i >= 16 ? 0xffff : (uint16_t)((1u << (sz - i)) - 1);
        // the masked load zeroes the chars beyond the end of the buffer, exclude them
        // from the non printable chars as zero is itself non printable
        const __m512i chunk = _mm512_maskz_loadu_epi32(chunk_bits, chars + i);
        const uint16_t non_printable = chunk_bits & (_mm512_cmplt_epu32_mask(chunk, lower) | _mm512_cmpgt_epu32_mask(chunk, upper));
        if (non_printable) {
            ans = i + __builtin_ctz(non_printable);
            break;
        }
    }
    _mm256_zeroupper();
    return ans;
}

// Pixel compositing {{{

void
composite_alpha_mask_512(uint32_t *dst, const uint8_t *mask, const size_t num_pixels, const uint32_t color_rgb) {
    const __m512i col = _mm512_set1_epi32((int32_t)((color_rgb << 8) & 0xffffff00)), low_byte = _mm512_set1_epi32(0xff);
    for (size_t i = 0; i < num_pixels; i += 16) {
        const __mmask16 k = num_pixels - i >= 16 ? (__mmask16)0xffff : (__mmask16)((1u << (num_pixels - i)) - 1);
        const __m512i m = _mm512_cvtepu8_epi32(_mm_maskz_loadu_epi8(k, mask + i));
        const __m512i d = _mm512_maskz_loadu_epi32(k, dst + i);
        _mm512_mask_storeu_epi32(dst + i, k, _mm512_or_si512(col, _mm512_max_epu32(m, _mm512_and_si512(d, low_byte))));
    }
    _mm256_zeroupper();
}

static inline __m512i
div255_epu16_512(const __m512i x) {
    // rounding division of 16-bit lanes by 255, exact for values <= 65407, matches div255_round()
    const __m512i y = _mm512_add_epi16(x, _mm512_set1_epi16(128));
    return _mm512_srli_epi16(_mm512_add_epi16(y, _mm512_srli_epi16(y, 8)), 8);
}

// Blend the 4-byte RGBA pixels in over onto the pixels in under, with under considered fully
// opaque: out_c = round((over_c * alpha + under_c * (255 - alpha)) / 255) for each of the first
// three channels, with the alpha bytes set to 255
static inline __m512i
blend_opaque_pixels_512(const __m512i under, const __m512i over) {
    const __m512i zero = _mm512_setzero_si512();
    const __m512i alpha = _mm512_shuffle_epi8(over, _mm512_broadcast_i32x4(_mm_set_epi8(15, 15, 15, 15, 11, 11, 11, 11, 7, 7, 7, 7, 3, 3, 3, 3)));
    const __m512i inv_alpha = _mm512_xor_si512(alpha, _mm512_set1_epi64(-1)); // 255 - alpha in every byte
    const __m512i lo = div255_epu16_512(_mm512_add_epi16(
        _mm512_mullo_epi16(_mm512_unpacklo_epi8(over, zero), _mm512_unpacklo_epi8(alpha, zero)),
        _mm512_mullo_epi16(_mm512_unpacklo_epi8(under, zero), _mm512_unpacklo_epi8(inv_alpha, zero))));
    const __m512i hi = div255_epu16_512(_mm512_add_epi16(
        _mm512_mullo_epi16(_mm512_unpackhi_epi8(over, zero), _mm512_unpackhi_epi8(alpha, zero)),
        _mm512_mullo_epi16(_mm512_unpackhi_epi8(under, zero), _mm512_unpackhi_epi8(inv_alpha, zero))));
    // the per 128-bit lane unpacks and pack are symmetric so byte order is preserved
    return _mm512_or_si512(_mm512_packus_epi16(lo, hi), _mm512_set1_epi32((int32_t)0xff000000));
}

void
blend_over_opaque_512(uint8_t *dst, const unsigned dst_bpp, const uint8_t *src, const size_t num_pixels) {
    if (dst_bpp == 4) {
        for (size_t i = 0; i < num_pixels; i += 16) {
            const size_t px = MIN(num_pixels - i, (size_t)16u);
            const __mmask64 k = px == 16 ? ~0ull : ((1ull << (4 * px)) - 1);
            const __m512i s = _mm512_maskz_loadu_epi8(k, src + 4 * i), d = _mm512_maskz_loadu_epi8(k, dst + 4 * i);
            _mm512_mask_storeu_epi8(dst + 4 * i, k, blend_opaque_pixels_512(d, s));
        }
    } else {
        // 3-byte destination pixels: the byte expand and compress instructions this would need
        // (VBMI2) are slower than the 128-bit shuffle based kernel, at least on the Zen CPUs
        // tested, so just use that.
        blend_over_opaque_128(dst, dst_bpp, src, num_pixels);
        return;
    }
    _mm256_zeroupper();
}

void
blend_over_straight_512(uint8_t *dst, const uint8_t *src, const size_t num_pixels) {
    // Four pixels per iteration unpacked into 32-bit lanes, four consecutive lanes per pixel.
    // Matches the arithmetic of blend_pixel_over_straight() bit for bit: exact integer numerator
    // and denominator, IEEE single precision division, round to nearest.
    const __m512i c255 = _mm512_set1_epi32(255), c128 = _mm512_set1_epi32(128), zero = _mm512_setzero_si512();
    for (size_t i = 0; i < num_pixels; i += 4) {
        const size_t px = MIN(num_pixels - i, (size_t)4u);
        const __mmask16 k = px == 4 ? (__mmask16)0xffff : (__mmask16)((1u << (4 * px)) - 1);
        const __m512i s = _mm512_cvtepu8_epi32(_mm_maskz_loadu_epi8(k, src + 4 * i));
        const __m512i d = _mm512_cvtepu8_epi32(_mm_maskz_loadu_epi8(k, dst + 4 * i));
        const __m512i alpha = _mm512_shuffle_epi32(s, _MM_PERM_DDDD), dst_alpha = _mm512_shuffle_epi32(d, _MM_PERM_DDDD);
        const __m512i inv_alpha = _mm512_sub_epi32(c255, alpha);
        const __m512i denom = _mm512_add_epi32(_mm512_mullo_epi32(alpha, c255), _mm512_mullo_epi32(dst_alpha, inv_alpha));
        const __m512i num =
            _mm512_add_epi32(_mm512_mullo_epi32(_mm512_mullo_epi32(s, alpha), c255), _mm512_mullo_epi32(_mm512_mullo_epi32(d, dst_alpha), inv_alpha));
        __m512i r = _mm512_cvtps_epi32(_mm512_div_ps(_mm512_cvtepi32_ps(num), _mm512_cvtepi32_ps(denom)));
        const __m512i y = _mm512_add_epi32(denom, c128); // out alpha = round(denom / 255)
        const __m512i out_alpha = _mm512_srli_epi32(_mm512_add_epi32(y, _mm512_srli_epi32(y, 8)), 8);
        r = _mm512_mask_mov_epi32(r, 0x8888, out_alpha);
        // both src and dst fully transparent => leave dst unchanged (this also discards the NaN from the 0/0 above)
        r = _mm512_mask_mov_epi32(r, _mm512_cmpeq_epi32_mask(denom, zero), d);
        _mm_mask_storeu_epi8(dst + 4 * i, k, _mm512_cvtepi32_epi8(r));
    }
    _mm256_zeroupper();
}

// }}}

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

static size_t
scalar_decode_to_accept(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (pos < src_sz && d->state.cur != UTF8_ACCEPT) { do_one_byte }
    return pos;
}

static size_t
scalar_decode_all(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (pos < src_sz) { do_one_byte }
    return pos;
}

#undef do_one_byte

// Shift bytes towards higher memory addresses, filling with zeroes. Done by
// first constructing a copy of the register with the 128-bit lanes shifted up
// by one and then using it to fill in the bytes shifted across lane boundaries.
#define shift_right_by_bytes512(A, n) _mm512_alignr_epi8(A, _mm512_alignr_epi64(A, _mm512_setzero_si512(), 6), 16 - (n))

// The caller must ensure output has sufficient capacity and that src_sz bytes
// are readable from src. Widens directly from memory, which is faster than
// extracting the 128-bit quarters from an already loaded register.
static inline void
output_plain_ascii_from_memory_512(UTF8Decoder *d, const uint8_t *src, const size_t src_sz) {
    uint32_t *out = d->output.storage + d->output.pos;
    for (size_t i = 0; i < src_sz; i += 16) _mm512_storeu_si512(out + i, _mm512_cvtepu8_epi32(_mm_loadu_si128((const __m128i *)(src + i))));
    d->output.pos += src_sz;
}

// The caller must ensure output has sufficient capacity
static inline void
output_plain_ascii_512(UTF8Decoder *d, const __m512i vec, const size_t src_sz) {
    uint32_t *out = d->output.storage + d->output.pos;
    _mm512_storeu_si512(out, _mm512_cvtepu8_epi32(_mm512_castsi512_si128(vec)));
    if (src_sz > 16) {
        _mm512_storeu_si512(out + 16, _mm512_cvtepu8_epi32(_mm512_extracti32x4_epi32(vec, 1)));
        if (src_sz > 32) {
            _mm512_storeu_si512(out + 32, _mm512_cvtepu8_epi32(_mm512_extracti32x4_epi32(vec, 2)));
            if (src_sz > 48) { _mm512_storeu_si512(out + 48, _mm512_cvtepu8_epi32(_mm512_extracti32x4_epi32(vec, 3))); }
        }
    }
    d->output.pos += src_sz;
}

// The caller must ensure output has sufficient capacity. The outputN vectors
// contain the three little-endian bytes of each codepoint, already compacted.
static inline void
output_unicode_512(UTF8Decoder *d, __m512i output1, __m512i output2, __m512i output3, const unsigned num_codepoints) {
    uint32_t *out = d->output.storage + d->output.pos;
    for (unsigned i = 0; i < num_codepoints; i += 16) {
        const __m512i unpacked1 = _mm512_cvtepu8_epi32(_mm512_castsi512_si128(output1));
        const __m512i unpacked2 = _mm512_slli_epi32(_mm512_cvtepu8_epi32(_mm512_castsi512_si128(output2)), 8);
        const __m512i unpacked3 = _mm512_slli_epi32(_mm512_cvtepu8_epi32(_mm512_castsi512_si128(output3)), 16);
        _mm512_storeu_si512(out + i, _mm512_or_si512(_mm512_or_si512(unpacked1, unpacked2), unpacked3));
        // shift the registers down by 16 bytes for the next group of codepoints
        output1 = _mm512_alignr_epi64(_mm512_setzero_si512(), output1, 2);
        output2 = _mm512_alignr_epi64(_mm512_setzero_si512(), output2, 2);
        output3 = _mm512_alignr_epi64(_mm512_setzero_si512(), output3, 2);
    }
    d->output.pos += num_codepoints;
}

bool
utf8_decode_to_esc_512(UTF8Decoder *d, const uint8_t *src_data, size_t src_len) {
    d->output.pos = 0;
    d->num_consumed = 0;
    if (d->state.cur != UTF8_ACCEPT) {
        // Finish the trailing sequence only
        d->num_consumed = scalar_decode_to_accept(d, src_data, src_len);
        src_data += d->num_consumed;
        src_len -= d->num_consumed;
    }
    utf8_decoder_ensure_capacity(d, src_len + 64);
    const __m512i esc_vec = _mm512_set1_epi8(0x1b), zero = _mm512_setzero_si512(), one = _mm512_set1_epi8(1), two = _mm512_set1_epi8(2),
                  three = _mm512_set1_epi8(3);
    const uint8_t *limit = src_data + src_len, *p = src_data, *start_of_current_chunk = src_data;
    bool sentinel_found = false;
    unsigned chunk_src_sz = 0;
    unsigned num_of_trailing_bytes = 0;
    bool prev_chunk_was_all_ascii = true;

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

    while (p < limit && !sentinel_found) {
        // Fast path: process pairs of full chunks that contain only ASCII and no ESC
        if (prev_chunk_was_all_ascii) {
            while ((size_t)(limit - p) >= 128) {
                const __m512i v1 = _mm512_loadu_si512(p), v2 = _mm512_loadu_si512(p + 64);
                const __mmask64 bad = _mm512_cmpeq_epi8_mask(v1, esc_vec) | _mm512_cmpeq_epi8_mask(v2, esc_vec) | _mm512_movepi8_mask(_mm512_or_si512(v1, v2));
                if (bad) break;
                output_plain_ascii_from_memory_512(d, p, 128);
                d->num_consumed += 128;
                p += 128;
            }
            if (p >= limit) break;
        }
        chunk_src_sz = MIN((size_t)(limit - p), 64u);
        // The masked load both avoids reading beyond the end of the input and zeroes the tail bytes
        const uint64_t chunk_bits = chunk_src_sz == 64 ? ~0ull : (1ull << chunk_src_sz) - 1;
        __m512i vec = _mm512_maskz_loadu_epi8(chunk_bits, p);
        start_of_current_chunk = p;
        p += chunk_src_sz;

        uint64_t ascii_mask = _mm512_movepi8_mask(vec); // bit set for every non-ASCII byte
        const uint64_t esc_mask = _mm512_cmpeq_epi8_mask(vec, esc_vec);
        if (esc_mask) {
            sentinel_found = true;
            chunk_src_sz = __builtin_ctzll(esc_mask);
            const uint64_t kept_bits = (1ull << chunk_src_sz) - 1;
            ascii_mask &= kept_bits;
            vec = _mm512_maskz_mov_epi8(kept_bits, vec);
            d->num_consumed += chunk_src_sz + 1; // esc is also consumed
            if (!chunk_src_sz) continue;
        } else d->num_consumed += chunk_src_sz;

        num_of_trailing_bytes = 0;
        bool check_for_trailing_bytes = !sentinel_found;

    start_classification:
        if (!ascii_mask) { // no bytes with high bit (0x80) set, so just plain ASCII
            output_plain_ascii_512(d, vec, chunk_src_sz);
            prev_chunk_was_all_ascii = true;
            handle_trailing_bytes();
            continue;
        }
        prev_chunk_was_all_ascii = false;

        // Classify the bytes by the length of the UTF-8 sequence they start. As in the
        // 128/256-bit implementations, this is an initial, potential classification:
        // 0xC0, 0xC1 and 0xF5..0xFF are classified as starter bytes here and rejected
        // in the validation checks below.
        const __mmask64 starts_two = _mm512_cmpge_epu8_mask(vec, _mm512_set1_epi8((char)0xc0));
        const __mmask64 starts_three = _mm512_cmpge_epu8_mask(vec, _mm512_set1_epi8((char)0xe0));
        const __mmask64 starts_four = _mm512_cmpge_epu8_mask(vec, _mm512_set1_epi8((char)0xf0));
        // count contains the number of bytes in the sequence for the start byte of every sequence and zero elsewhere
        __m512i count = _mm512_maskz_mov_epi8(starts_two, two);
        count = _mm512_mask_add_epi8(count, starts_three, count, one);
        count = _mm512_mask_add_epi8(count, starts_four, count, one);
        // the UTF-8 marker bits to strip from each byte: 0x80 for ASCII and continuation bytes, the sequence length markers for starters
        __m512i strip = _mm512_set1_epi8((char)0x80);
        strip = _mm512_mask_mov_epi8(strip, starts_two, _mm512_set1_epi8((char)0xc0));
        strip = _mm512_mask_mov_epi8(strip, starts_three, _mm512_set1_epi8((char)0xe0));
        strip = _mm512_mask_mov_epi8(strip, starts_four, _mm512_set1_epi8((char)0xf0));

        // counts contains the number of bytes remaining in each UTF-8 sequence of 2 or more bytes
        const __m512i count_subs1 = _mm512_subs_epu8(count, one);
        __m512i counts = _mm512_add_epi8(count, shift_right_by_bytes512(count_subs1, 1));
        counts = _mm512_add_epi8(counts, shift_right_by_bytes512(_mm512_subs_epu8(counts, two), 2));

        // bytes that are neither ASCII nor the last byte of a multi-byte sequence
        const uint64_t discarded_locations = _mm512_cmpgt_epu8_mask(counts, one);

        // check for an incomplete trailing utf8 sequence
        if (check_for_trailing_bytes && ((discarded_locations >> (chunk_src_sz - 1)) & 1)) {
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
                const uint64_t kept_bits = (1ull << chunk_src_sz) - 1;
                ascii_mask &= kept_bits;
                vec = _mm512_maskz_mov_epi8(kept_bits, vec);
            }
            goto start_classification;
        }

        // Validation, see simd-string-impl.h for detailed comments. Note that unlike
        // there, ill-formed chunks are detected with mask registers directly.
        uint64_t chunk_is_invalid = ascii_mask ^ _mm512_cmpgt_epu8_mask(counts, zero);
        // 2-byte sequence starters must be >= 0xC2 to avoid overlong encodings
        chunk_is_invalid |= _mm512_mask_cmplt_epu8_mask(starts_two, vec, _mm512_set1_epi8((char)0xc2));
        // 4-byte sequence starters must be <= 0xF4 to stay within the Unicode codespace
        chunk_is_invalid |= _mm512_cmpgt_epu8_mask(vec, _mm512_set1_epi8((char)0xf4));
        // continuation bytes' positions must not have starter bytes
        chunk_is_invalid |= _mm512_mask_cmpgt_epu8_mask(starts_two, counts, count);
        // second byte restrictions for E0, ED, F0 and F4 starters. These are stricter than
        // the checks in simd-string-impl.h, also matching ASCII bytes at the follower
        // positions, which is fine as those chunks are ill-formed anyway and the scalar
        // fallback decodes them correctly.
        const __m512i prev_bytes = shift_right_by_bytes512(vec, 1);
        chunk_is_invalid |= _mm512_mask_cmplt_epu8_mask(_mm512_cmpeq_epi8_mask(prev_bytes, _mm512_set1_epi8((char)0xe0)), vec, _mm512_set1_epi8((char)0xa0));
        chunk_is_invalid |= _mm512_mask_cmpgt_epu8_mask(_mm512_cmpeq_epi8_mask(prev_bytes, _mm512_set1_epi8((char)0xed)), vec, _mm512_set1_epi8((char)0x9f));
        chunk_is_invalid |= _mm512_mask_cmplt_epu8_mask(_mm512_cmpeq_epi8_mask(prev_bytes, _mm512_set1_epi8((char)0xf0)), vec, _mm512_set1_epi8((char)0x90));
        chunk_is_invalid |= _mm512_mask_cmpgt_epu8_mask(_mm512_cmpeq_epi8_mask(prev_bytes, _mm512_set1_epi8((char)0xf4)), vec, _mm512_set1_epi8((char)0x8f));
        if (chunk_is_invalid) { abort_with_invalid_utf8(); }

        // Assemble the three output bytes for each codepoint, at the position of the
        // last byte of its sequence, see simd-string-impl.h for detailed comments.
        vec = _mm512_andnot_si512(strip, vec);
        const __mmask64 count1_locations = _mm512_cmpeq_epu8_mask(counts, one);
        const __mmask64 count2_locations = _mm512_cmpeq_epu8_mask(counts, two);
        const __mmask64 count3_locations = _mm512_cmpeq_epu8_mask(counts, three);
        const __mmask64 count4_locations = _mm512_cmpeq_epu8_mask(counts, _mm512_set1_epi8(4));
        const __m512i vec_non_ascii = _mm512_maskz_mov_epi8(_mm512_cmpgt_epu8_mask(counts, zero), vec);
        const __m512i prev_non_ascii = shift_right_by_bytes512(vec_non_ascii, 1);

        const __m512i low_two_bits_of_starter = _mm512_and_si512(_mm512_slli_epi16(prev_non_ascii, 6), _mm512_set1_epi8((char)0xc0));
        __m512i output1 = _mm512_mask_mov_epi8(vec, count1_locations, _mm512_or_si512(vec, low_two_bits_of_starter));

        __m512i output2 = _mm512_srli_epi32(_mm512_maskz_mov_epi8(count2_locations, vec), 2);
        output2 = _mm512_or_si512(
            output2, _mm512_and_si512(_mm512_set1_epi8((char)0xf0), _mm512_slli_epi16(_mm512_maskz_mov_epi8(count3_locations << 1, prev_non_ascii), 4)));
        output2 = shift_right_by_bytes512(_mm512_maskz_mov_epi8(count2_locations, output2), 1);

        __m512i output3 = _mm512_and_si512(three, _mm512_srli_epi32(vec, 4));
        output3 = _mm512_or_si512(
            output3, _mm512_and_si512(_mm512_set1_epi8((char)0xfc), _mm512_slli_epi16(_mm512_maskz_mov_epi8(count4_locations << 1, prev_non_ascii), 2)));
        output3 = shift_right_by_bytes512(_mm512_maskz_mov_epi8(count3_locations, output3), 2);

        // Discard the continuation bytes, compacting the codepoints. This replaces the
        // whole prefix sum, move and shuffle machinery of the 128/256 implementations.
        const uint64_t kept_locations = ~discarded_locations & (chunk_src_sz == 64 ? ~0ull : (1ull << chunk_src_sz) - 1);
        output1 = _mm512_maskz_compress_epi8(kept_locations, output1);
        output2 = _mm512_maskz_compress_epi8(kept_locations, output2);
        output3 = _mm512_maskz_compress_epi8(kept_locations, output3);
        const unsigned num_codepoints = __builtin_popcountll(kept_locations);
        output_unicode_512(d, output1, output2, output3, num_codepoints);
        handle_trailing_bytes();
    }
    if (sentinel_found && d->state.cur != UTF8_ACCEPT) {
        // an incomplete UTF-8 sequence was cut off by the sentinel, matching
        // the scalar implementation, emit a replacement char for it
        utf8_decoder_ensure_capacity(d, 1);
        d->output.storage[d->output.pos++] = 0xfffd;
        zero_at_ptr(&d->state);
    }
    _mm256_zeroupper();
    return sentinel_found;
#undef abort_with_invalid_utf8
#undef handle_trailing_bytes
}

#else

bool
utf8_decode_to_esc_512(UTF8Decoder *d UNUSED, const uint8_t *src UNUSED, size_t src_sz UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

const uint8_t *
find_either_of_two_bytes_512(const uint8_t *haystack UNUSED, const size_t sz UNUSED, const uint8_t a UNUSED, const uint8_t b UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

void
xor_data64_512(const uint8_t key[64] UNUSED, uint8_t *data UNUSED, const size_t data_sz UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

size_t
printable_ascii_run_length_512(const uint32_t *chars UNUSED, const size_t sz UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

void
blend_over_straight_512(uint8_t *dst UNUSED, const uint8_t *src UNUSED, size_t num_pixels UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

void
blend_over_opaque_512(uint8_t *dst UNUSED, unsigned dst_bpp UNUSED, const uint8_t *src UNUSED, size_t num_pixels UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

void
composite_alpha_mask_512(uint32_t *dst UNUSED, const uint8_t *mask UNUSED, size_t num_pixels UNUSED, uint32_t color_rgb UNUSED) {
    fatal("No AVX-512 implementation for this platform");
}

#endif // x86-64
