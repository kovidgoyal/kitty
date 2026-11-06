/*
 * simd-string-512.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 *
 * AVX-512 (F, BW, VL) implementations of find_either_of_two_bytes,
 * xor_data64, printable_ascii_run_length and the pixel compositing functions.
 * Unlike the 128/256 bit implementations in simd-string-impl.h these are
 * x86-64 only and use native intrinsics, since the algorithms are built around
 * mask registers and masked loads/stores, which have no efficient equivalents
 * on other platforms. There is no AVX-512 UTF-8 decoder, as the AVX2 one in
 * simd-string-impl.h is faster.
 */

#include "data-types.h"
#include "simd-string.h"

#if (defined(__x86_64__) || defined(__amd64__)) && !defined(KITTY_NO_SIMD)

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

#else

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
