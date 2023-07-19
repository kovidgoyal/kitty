/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>

static inline uint16_t
be16dec(const void *pp) {
    uint8_t const *p = (uint8_t const *)pp;
    return (((unsigned)p[0] << 8) | p[1]);
}

static inline uint32_t
be32dec(const void *pp) {
    uint8_t const *p = (uint8_t const *)pp;
    return (((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
            ((uint32_t)p[2] << 8) | p[3]);
}

static inline uint64_t
be64dec(const void *pp) {
    uint8_t const *p = (uint8_t const *)pp;
    return (((uint64_t)be32dec(p) << 32) | be32dec(p + 4));
}

static inline uint16_t
le16dec(const void *pp) {
    uint8_t const *p = (uint8_t const *)pp;
    return (((unsigned)p[1] << 8) | p[0]);
}

static inline uint32_t
le32dec(const void *pp) {
    uint8_t const *p = (uint8_t const *)pp;
    return (((uint32_t)p[3] << 24) | ((uint32_t)p[2] << 16) |
            ((uint32_t)p[1] << 8) | p[0]);
}

static inline uint64_t
le64dec(const void *pp) {
    uint8_t const *p = (uint8_t const *)pp;
    return (((uint64_t)le32dec(p + 4) << 32) | le32dec(p));
}

static inline void
be16enc(void *pp, uint16_t u) {
    uint8_t *p = (uint8_t *)pp;
    p[0] = (u >> 8) & 0xff;
    p[1] = u & 0xff;
}

static inline void
be32enc(void *pp, uint32_t u) {
    uint8_t *p = (uint8_t *)pp;
    p[0] = (u >> 24) & 0xff;
    p[1] = (u >> 16) & 0xff;
    p[2] = (u >> 8) & 0xff;
    p[3] = u & 0xff;
}

static inline void
be64enc(void *pp, uint64_t u) {
    uint8_t *p = (uint8_t *)pp;
    be32enc(p, (uint32_t)(u >> 32));
    be32enc(p + 4, (uint32_t)(u & 0xffffffffU));
}

static inline void
le16enc(void *pp, uint16_t u) {
    uint8_t *p = (uint8_t *)pp;
    p[0] = u & 0xff;
    p[1] = (u >> 8) & 0xff;
}

static inline void
le32enc(void *pp, uint32_t u) {
    uint8_t *p = (uint8_t *)pp;
    p[0] = u & 0xff;
    p[1] = (u >> 8) & 0xff;
    p[2] = (u >> 16) & 0xff;
    p[3] = (u >> 24) & 0xff;
}

static inline void
le64enc(void *pp, uint64_t u) {
    uint8_t *p = (uint8_t *)pp;
    le32enc(p, (uint32_t)(u & 0xffffffffU));
    le32enc(p + 4, (uint32_t)(u >> 32));
}
