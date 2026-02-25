/*
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include "base64.h"

// Write the kitty graphics protocol escape codes for a 32-bit RGBA raster
// image to fp.  rgba must point to width * height uint32_t values; each
// uint32_t holds one pixel with the red component in the least-significant
// byte followed by green, blue, and alpha in successive bytes.
//
// The pixel data is base64-encoded and split into chunks.  3072 raw bytes
// encode to exactly 4096 base64 bytes (3072 / 3 * 4 == 4096), which satisfies
// the protocol requirement that every chunk except the last must be a multiple
// of four base64 bytes and no chunk may exceed 4096 base64 bytes.
// Reference: https://sw.kovidgoyal.net/kitty/graphics-protocol/
static void
write_kitty_image_to_file(const uint32_t *rgba, uint32_t width, uint32_t height, FILE *fp) {
    const uint8_t *data = (const uint8_t *)rgba;
    const size_t total_bytes = (size_t)width * height * 4;
    unsigned char b64_buf[4096];
    size_t offset = 0;
    bool first = true;

    while (offset < total_bytes) {
        size_t chunk = total_bytes - offset;
        if (chunk > 3072) chunk = 3072;
        size_t b64_len = sizeof(b64_buf);
        base64_encode8(data + offset, chunk, b64_buf, &b64_len, false);
        offset += chunk;
        const bool last = (offset >= total_bytes);

        if (first) {
            fprintf(fp, "\x1b_Ga=T,f=32,s=%u,v=%u,m=%d;", width, height, last ? 0 : 1);
            first = false;
        } else {
            fprintf(fp, "\x1b_Gm=%d;", last ? 0 : 1);
        }
        fwrite(b64_buf, 1, b64_len, fp);
        fputs("\x1b\\", fp);
    }

    if (first) {
        /* Empty image: send a single chunk with no payload. */
        fputs("\x1b_Ga=T,f=32,s=0,v=0,m=0;\x1b\\", fp);
    }
}
