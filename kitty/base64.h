/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define inner_func base64_decode_inner8
#define decode_func base64_decode8
#define encode_func base64_encode8

bool decode_func(const uint8_t *src, size_t src_sz, uint8_t *dest, size_t *dest_sz);
bool encode_func(const unsigned char *src, size_t src_len, unsigned char *out, size_t *out_len, bool add_padding);
static inline size_t required_buffer_size_for_base64_decode(size_t src_sz) { return (src_sz * 3) / 4 + 4; }
static inline size_t required_buffer_size_for_base64_encode(size_t src_sz) { return (src_sz * 4) / 3 + 5; }

#ifdef INCLUDE_BASE64_DEFINITIONS
// standard decoding using + and / with = being the padding character
static uint8_t b64_decoding_table[256] = {
0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 62, 0, 0, 0, 63, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 0, 0, 0, 0, 0, 0, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

static void
inner_func(const uint8_t *src, size_t src_sz, uint8_t *dest) {
    for (size_t i = 0, j = 0; i < src_sz;) {
        uint32_t sextet_a = b64_decoding_table[src[i++] & 0xff];
        uint32_t sextet_b = b64_decoding_table[src[i++] & 0xff];
        uint32_t sextet_c = b64_decoding_table[src[i++] & 0xff];
        uint32_t sextet_d = b64_decoding_table[src[i++] & 0xff];
        uint32_t triple = (sextet_a << 3 * 6) + (sextet_b << 2 * 6) + (sextet_c << 1 * 6) + (sextet_d << 0 * 6);

        dest[j++] = (triple >> 2 * 8) & 0xFF;
        dest[j++] = (triple >> 1 * 8) & 0xFF;
        dest[j++] = (triple >> 0 * 8) & 0xFF;
    }
}

bool
decode_func(const uint8_t *src, size_t src_sz, uint8_t *dest, size_t *dest_sz) {
    while (src_sz && src[src_sz-1] == '=') src_sz--;  // remove trailing padding
    if (!src_sz) { *dest_sz = 0; return true; }
    const size_t dest_capacity = *dest_sz;
    *dest_sz = src_sz / 4;
    size_t extra = src_sz - 4 * *dest_sz;
    *dest_sz *= 3;
    src_sz -= extra;
    if (*dest_sz + 4 > dest_capacity) return false;
    if (src_sz) inner_func(src, src_sz, dest);
    if (extra > 1 && extra < 4) {  // < 4 is not needed but it helps compiler unroll the loop
        uint8_t buf[4] = {0};
        for (size_t i = 0; i < extra; i++) buf[i] = src[src_sz+i];
        inner_func(buf, extra, dest + *dest_sz);
        *dest_sz += extra - 1;
    }
    if (*dest_sz + 1 > dest_capacity) return false;
    dest[*dest_sz] = 0;  // ensure zero-terminated
    return true;
}

static const unsigned char base64_table[65] =
	"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

bool
encode_func(const unsigned char *src, size_t src_len, unsigned char *out, size_t *out_len, bool add_padding) {
    size_t required_len = required_buffer_size_for_base64_encode(src_len);
    if (*out_len < required_len) return false;

    const unsigned char *end = src + src_len, *in = src;
	unsigned char *pos = out;
	while (end - in >= 3) {
		*pos++ = base64_table[in[0] >> 2];
		*pos++ = base64_table[((in[0] & 0x03) << 4) | (in[1] >> 4)];
		*pos++ = base64_table[((in[1] & 0x0f) << 2) | (in[2] >> 6)];
		*pos++ = base64_table[in[2] & 0x3f];
		in += 3;
	}

	if (end - in) {
		*pos++ = base64_table[in[0] >> 2];
		if (end - in == 1) {
			*pos++ = base64_table[(in[0] & 0x03) << 4];
            if (add_padding) *pos++ = '=';
		} else {
			*pos++ = base64_table[((in[0] & 0x03) << 4) |
					      (in[1] >> 4)];
			*pos++ = base64_table[(in[1] & 0x0f) << 2];
		}
		if (add_padding) *pos++ = '=';
	}
	*pos = '\0';
    *out_len = pos - out;
	return true;
}
#undef encode_func
#undef decode_func
#undef inner_func
#endif
