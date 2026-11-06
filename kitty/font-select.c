/*
 * font-select.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Selection of fonts from the font specifications in kitty.conf, in pure C so
// that it can run in a thread during startup. See font-select.h. The
// algorithm is a port of the previous Python implementation, kept as close
// to it as possible, so that the selected fonts do not change.

#include "data-types.h"
#include "font-select.h"
#include "state.h"
#include "startup-timing.h"
#include "threading.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdarg.h>
#include <sys/stat.h>
#include <unistd.h>
#include <zlib.h>
#ifndef __APPLE__
#include <brotli/decode.h>
#include <fontconfig/fontconfig.h>
#endif

// Utilities {{{
static void *
xcalloc(size_t n, size_t sz) {
    void *ans = calloc(n ? n : 1, sz ? sz : 1);
    if (!ans) fatal("Out of memory");
    return ans;
}

static void *
xrealloc(void *p, size_t sz) {
    void *ans = realloc(p, sz ? sz : 1);
    if (!ans) fatal("Out of memory");
    return ans;
}

static char *
xstrdup(const char *s) {
    char *ans = strdup(s ? s : "");
    if (!ans) fatal("Out of memory");
    return ans;
}

#define grow(array, count, capacity)                                  \
    if ((count) >= (capacity)) {                                      \
        (capacity) = (capacity) ? 2 * (capacity) : 8;                 \
        (array) = xrealloc((array), (capacity) * sizeof((array)[0])); \
    }

static bool
is_space(unsigned char ch) {
    return ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' || ch == '\f' || ch == '\v';
}

static char
lower(char ch) {
    return ('A' <= ch && ch <= 'Z') ? ch + 32 : ch;
}

// Collapse runs of whitespace into a single space and strip leading and trailing whitespace
static char *
normalize_whitespace(const char *name) {
    if (!name) name = "";
    char *ans = xcalloc(strlen(name) + 1, 1);
    size_t o = 0;
    bool pending_space = false;
    for (; *name; name++) {
        if (is_space(*name)) {
            if (o) pending_space = true;
            continue;
        }
        if (pending_space) {
            ans[o++] = ' ';
            pending_space = false;
        }
        ans[o++] = *name;
    }
    ans[o] = 0;
    return ans;
}

// Must match family_name_to_key() in kitty/fonts/__init__.py, except that only ASCII is lowercased
char *
fs_name_to_key(const char *name) {
    char *ans = normalize_whitespace(name);
    for (char *p = ans; *p; p++) *p = lower(*p);
    return ans;
}

static char *
lowercased(const char *s) {
    char *ans = xstrdup(s);
    for (char *p = ans; *p; p++) *p = lower(*p);
    return ans;
}

// Case insensitive (for ASCII) string equality
static bool
ieq(const char *a, const char *b) {
    if (!a) a = "";
    if (!b) b = "";
    for (; *a && *b; a++, b++) {
        if (lower(*a) != lower(*b)) return false;
    }
    return *a == *b;
}

static bool
streq(const char *a, const char *b) {
    return strcmp(a ? a : "", b ? b : "") == 0;
}

static bool
is_empty(const char *s) {
    return !s || !s[0];
}

static uint32_t
tag_from_bytes(const uint8_t *b) {
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | b[3];
}

static uint32_t
tag_from_string(const char *s) {
    if (strlen(s) != 4) return 0;
    return tag_from_bytes((const uint8_t *)s);
}

static void
tag_to_str(uint32_t tag, char buf[5]) {
    buf[0] = (char)(tag >> 24);
    buf[1] = (char)(tag >> 16);
    buf[2] = (char)(tag >> 8);
    buf[3] = (char)tag;
    buf[4] = 0;
}

#define WGHT 0x77676874u // wght
#define ITAL 0x6974616cu // ital
#define SLNT 0x736c6e74u // slnt
#define WDTH 0x77647468u // wdth

typedef struct AxisMap {
    size_t count;
    FSAxisValue items[FS_MAX_AXES];
} AxisMap;

static const double *
axis_map_get(const AxisMap *m, uint32_t tag) {
    for (size_t i = 0; i < m->count; i++) {
        if (m->items[i].tag == tag) return &m->items[i].value;
    }
    return NULL;
}

static void
axis_map_set(AxisMap *m, uint32_t tag, double value) {
    for (size_t i = 0; i < m->count; i++) {
        if (m->items[i].tag == tag) {
            m->items[i].value = value;
            return;
        }
    }
    if (m->count < FS_MAX_AXES) m->items[m->count++] = (FSAxisValue){.tag = tag, .value = value};
}

static bool
axis_maps_equal(const AxisMap *a, const AxisMap *b) {
    if (a->count != b->count) return false;
    for (size_t i = 0; i < a->count; i++) {
        const double *v = axis_map_get(b, a->items[i].tag);
        if (!v || *v != a->items[i].value) return false;
    }
    return true;
}

static void
axis_map_from_values(AxisMap *m, const FSAxisValue *values, size_t count) {
    m->count = 0;
    for (size_t i = 0; i < count; i++) axis_map_set(m, values[i].tag, values[i].value);
}
// }}}

// Reading font tables {{{
static uint16_t
be16(const uint8_t *p) {
    return ((uint16_t)p[0] << 8) | p[1];
}

static uint32_t
be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static double
fixed(const uint8_t *p) {
    return ((int32_t)be32(p)) / 65536.0;
}

void
fs_free_font_tables(FSFontTables *t) {
    free(t->fvar);
    free(t->stat);
    free(t->name);
    memset(t, 0, sizeof(*t));
}

static bool
pread_all(int fd, uint8_t *buf, size_t sz, off_t offset) {
    size_t done = 0;
    while (done < sz) {
        ssize_t n = pread(fd, buf + done, sz - done, offset + (off_t)done);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) return false;
        done += (size_t)n;
    }
    return true;
}

#define MAX_FONT_TABLE_SIZE (64u * 1024u * 1024u)

// Return the location in t for storing the table with the specified tag or NULL if the table is not needed
static uint8_t **
table_slot(FSFontTables *t, const uint8_t *tag, size_t **len) {
    if (memcmp(tag, "fvar", 4) == 0) { *len = &t->fvar_len; return &t->fvar; }
    if (memcmp(tag, "STAT", 4) == 0) { *len = &t->stat_len; return &t->stat; }
    if (memcmp(tag, "name", 4) == 0) { *len = &t->name_len; return &t->name; }
    return NULL;
}

// WOFF: https://www.w3.org/TR/WOFF/ each table is individually compressed with zlib
static bool
read_woff_tables(int fd, FSFontTables *t) {
    uint8_t header[44];
    if (!pread_all(fd, header, sizeof(header), 0)) return false;
    const uint16_t num_tables = be16(header + 12);
    uint8_t *records = xcalloc(num_tables, 20);
    bool ok = false;
    if (!pread_all(fd, records, (size_t)num_tables * 20, sizeof(header))) goto end;
    for (uint16_t i = 0; i < num_tables; i++) {
        const uint8_t *r = records + 20 * i;
        size_t *dest_len;
        uint8_t **dest = table_slot(t, r, &dest_len);
        if (!dest || *dest) continue;
        const uint32_t offset = be32(r + 4), comp_length = be32(r + 8), orig_length = be32(r + 12);
        if (orig_length > MAX_FONT_TABLE_SIZE || comp_length > orig_length) continue;
        uint8_t *data = xcalloc(orig_length, 1);
        bool good;
        if (comp_length == orig_length) good = pread_all(fd, data, orig_length, offset);
        else {
            uint8_t *comp = xcalloc(comp_length, 1);
            uLongf sz = orig_length;
            good = pread_all(fd, comp, comp_length, offset) && uncompress(data, &sz, comp, comp_length) == Z_OK && sz == orig_length;
            free(comp);
        }
        if (good) { *dest = data; *dest_len = orig_length; }
        else free(data);
    }
    ok = true;
end:
    free(records);
    return ok;
}

#ifndef __APPLE__
// WOFF2: https://www.w3.org/TR/WOFF2/ all tables are concatenated into a
// single brotli compressed stream. Only the prefix of the stream containing
// the needed tables is decompressed.

static const char woff2_known_tags[63][5] = {
    "cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm", "glyf", "loca", "prep", "CFF ", "VORG", "EBDT",
    "EBLC", "gasp", "hdmx", "kern", "LTSH", "PCLT", "VDMX", "vhea", "vmtx", "BASE", "GDEF", "GPOS", "GSUB", "EBSC", "JSTF", "MATH",
    "CBDT", "CBLC", "COLR", "CPAL", "SVG ", "sbix", "acnt", "avar", "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar",
    "gvar", "hsty", "just", "lcar", "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat", "Gloc", "Feat", "Sill",
};

typedef struct ByteReader {
    const uint8_t *p, *end;
} ByteReader;

static bool
br_u8(ByteReader *r, uint8_t *v) {
    if (r->p >= r->end) return false;
    *v = *r->p++;
    return true;
}

static bool
br_u16(ByteReader *r, uint16_t *v) {
    if (r->end - r->p < 2) return false;
    *v = be16(r->p); r->p += 2;
    return true;
}

static bool
br_u32(ByteReader *r, uint32_t *v) {
    if (r->end - r->p < 4) return false;
    *v = be32(r->p); r->p += 4;
    return true;
}

static bool
br_base128(ByteReader *r, uint32_t *v) {
    uint32_t acc = 0;
    for (unsigned i = 0; i < 5; i++) {
        uint8_t b;
        if (!br_u8(r, &b) || (i == 0 && b == 0x80) || (acc & 0xFE000000)) return false;
        acc = (acc << 7) | (b & 0x7f);
        if (!(b & 0x80)) { *v = acc; return true; }
    }
    return false;
}

static bool
br_255uint16(ByteReader *r, uint16_t *v) {
    uint8_t code, b;
    if (!br_u8(r, &code)) return false;
    switch (code) {
        case 253: return br_u16(r, v);
        case 254: if (!br_u8(r, &b)) return false; *v = 253 * 2 + b; return true;
        case 255: if (!br_u8(r, &b)) return false; *v = 253 + b; return true;
        default: *v = code; return true;
    }
}

typedef struct Woff2Table {
    uint8_t tag[4];
    bool transformed;
    uint32_t src_offset, src_length;  // location in the decompressed stream
} Woff2Table;

// Parse the table directory and collection directory. Returns false if buf is
// too short or the data is invalid.
static bool
parse_woff2_directories(
    const uint8_t *buf, size_t sz, uint16_t num_tables, bool is_collection, unsigned face,
    Woff2Table *tables, uint16_t *font_tables, uint16_t *num_font_tables, size_t *dirs_size
) {
    ByteReader r = {.p = buf, .end = buf + sz};
    uint64_t src_offset = 0;
    for (uint16_t i = 0; i < num_tables; i++) {
        Woff2Table *tt = tables + i;
        uint8_t flags;
        if (!br_u8(&r, &flags)) return false;
        const unsigned tag_idx = flags & 0x3f, xform_version = (flags >> 6) & 3;
        if (tag_idx == 63) {
            if (r.end - r.p < 4) return false;
            memcpy(tt->tag, r.p, 4); r.p += 4;
        } else memcpy(tt->tag, woff2_known_tags[tag_idx], 4);
        uint32_t orig_length, length;
        if (!br_base128(&r, &orig_length)) return false;
        length = orig_length;
        // For glyf and loca version 3 is the null transform, for all other tables it is version 0
        const bool is_glyf_or_loca = memcmp(tt->tag, "glyf", 4) == 0 || memcmp(tt->tag, "loca", 4) == 0;
        tt->transformed = is_glyf_or_loca ? xform_version != 3 : xform_version != 0;
        if (tt->transformed && !br_base128(&r, &length)) return false;
        if (src_offset + length > UINT32_MAX) return false;
        tt->src_offset = (uint32_t)src_offset; tt->src_length = length;
        src_offset += length;
    }
    if (is_collection) {
        uint32_t version;
        uint16_t num_fonts;
        if (!br_u32(&r, &version) || !br_255uint16(&r, &num_fonts) || face >= num_fonts) return false;
        // All font entries must be parsed as the compressed stream starts after them
        for (unsigned f = 0; f < num_fonts; f++) {
            uint16_t n;
            uint32_t flavor;
            if (!br_255uint16(&r, &n) || !br_u32(&r, &flavor)) return false;
            for (uint16_t i = 0; i < n; i++) {
                uint16_t idx;
                if (!br_255uint16(&r, &idx) || idx >= num_tables) return false;
                if (f == face && i < num_tables) font_tables[(*num_font_tables)++] = idx;
            }
        }
    } else {
        for (uint16_t i = 0; i < num_tables; i++) font_tables[(*num_font_tables)++] = i;
    }
    *dirs_size = r.p - buf;
    return true;
}

static bool
read_woff2_tables(int fd, int index, FSFontTables *t) {
    uint8_t header[48];
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size < (off_t)sizeof(header) || !pread_all(fd, header, sizeof(header), 0)) return false;
    const bool is_collection = memcmp(header + 4, "ttcf", 4) == 0;
    const uint16_t num_tables = be16(header + 12);
    const uint32_t total_compressed_size = be32(header + 20);
    const size_t available = (size_t)st.st_size - sizeof(header);
    if (!num_tables || total_compressed_size > available) return false;
    Woff2Table *tables = xcalloc(num_tables, sizeof(tables[0]));
    uint16_t *font_tables = xcalloc(num_tables, sizeof(font_tables[0])), num_font_tables = 0;
    uint8_t *dirs = NULL, *out = NULL, *inbuf = NULL;
    BrotliDecoderState *dec = NULL;
    bool ok = false;
    // The size of the directories is unknown till they are parsed, so read
    // successively larger chunks
    size_t dirs_size = 0;
    for (size_t sz = 4096 + (size_t)num_tables * 16;; sz *= 2) {
        if (sz > available) sz = available;
        dirs = xrealloc(dirs, sz);
        if (!pread_all(fd, dirs, sz, sizeof(header))) goto end;
        num_font_tables = 0;
        if (parse_woff2_directories(dirs, sz, num_tables, is_collection, index & 0xffff, tables, font_tables, &num_font_tables, &dirs_size)) break;
        if (sz == available) goto end;
    }
    // Find the needed tables
    const Woff2Table *needed[3] = {0};
    size_t num_needed = 0, needed_end = 0;
    for (uint16_t i = 0; i < num_font_tables; i++) {
        const Woff2Table *tt = tables + font_tables[i];
        size_t *dest_len;
        uint8_t **dest = table_slot(t, tt->tag, &dest_len);
        if (!dest || tt->transformed || tt->src_length > MAX_FONT_TABLE_SIZE) continue;
        bool seen = false;
        for (size_t j = 0; j < num_needed; j++) if (memcmp(needed[j]->tag, tt->tag, 4) == 0) seen = true;
        if (seen) continue;
        needed[num_needed++] = tt;
        if (tt->src_offset + (size_t)tt->src_length > needed_end) needed_end = tt->src_offset + (size_t)tt->src_length;
    }
    if (!needed_end) { ok = true; goto end; }
    // Decompress the prefix of the stream that contains the needed tables in
    // fixed size chunks, copying out the parts of the needed tables. The
    // table buffers are allocated only when the stream reaches them, so that
    // memory use is bounded by the actual decompressed data, not by the
    // offsets in the directory, which could be corrupt.
    if (!(dec = BrotliDecoderCreateInstance(NULL, NULL, NULL))) goto end;
    enum { CHUNK_SIZE = 64 * 1024 };
    inbuf = xcalloc(CHUNK_SIZE, 1);
    out = xcalloc(CHUNK_SIZE, 1);
    off_t pos = sizeof(header) + dirs_size;
    size_t remaining = total_compressed_size, avail_in = 0, stream_pos = 0;
    if ((size_t)pos + remaining > (size_t)st.st_size) goto end;
    const uint8_t *next_in = inbuf;
    // The decoder can have pending output even when all input is consumed,
    // so read more input only when it asks for it
    BrotliDecoderResult res = BROTLI_DECODER_RESULT_NEEDS_MORE_INPUT;
    while (stream_pos < needed_end) {
        if (res == BROTLI_DECODER_RESULT_NEEDS_MORE_INPUT && !avail_in) {
            if (!remaining) goto end;
            const size_t n = remaining < CHUNK_SIZE ? remaining : CHUNK_SIZE;
            if (!pread_all(fd, inbuf, n, pos)) goto end;
            pos += n; remaining -= n; avail_in = n; next_in = inbuf;
        }
        uint8_t *next_out = out;
        size_t avail_out = needed_end - stream_pos < CHUNK_SIZE ? needed_end - stream_pos : CHUNK_SIZE;
        res = BrotliDecoderDecompressStream(dec, &avail_in, &next_in, &avail_out, &next_out, NULL);
        if (res == BROTLI_DECODER_RESULT_ERROR) goto end;
        const size_t produced = next_out - out, chunk_end = stream_pos + produced;
        for (size_t i = 0; i < num_needed; i++) {
            const size_t tstart = needed[i]->src_offset, tend = tstart + needed[i]->src_length;
            if (tend <= stream_pos || tstart >= chunk_end) continue;
            size_t *dest_len;
            uint8_t **dest = table_slot(t, needed[i]->tag, &dest_len);
            if (!*dest) { *dest = xcalloc(needed[i]->src_length, 1); *dest_len = needed[i]->src_length; }
            const size_t from = tstart > stream_pos ? tstart : stream_pos, to = tend < chunk_end ? tend : chunk_end;
            memcpy(*dest + (from - tstart), out + (from - stream_pos), to - from);
        }
        stream_pos = chunk_end;
        if (res == BROTLI_DECODER_RESULT_SUCCESS && stream_pos < needed_end) goto end;
    }
    ok = true;
end:
    if (dec) BrotliDecoderDestroyInstance(dec);
    free(tables); free(font_tables); free(dirs); free(out); free(inbuf);
    return ok;
}
#endif

bool
fs_read_font_tables_from_file(const char *path, int index, FSFontTables *t) {
    memset(t, 0, sizeof(*t));
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;
    bool ok = false;
    uint8_t header[12];
    uint8_t *records = NULL;
    if (!pread_all(fd, header, sizeof(header), 0)) goto end;
    if (memcmp(header, "wOFF", 4) == 0) {
        ok = read_woff_tables(fd, t);
        goto end;
    }
    if (memcmp(header, "wOF2", 4) == 0) {
#ifdef __APPLE__
        ok = true;  // brotli is not available on macOS, treat as having no variable font data
#else
        ok = read_woff2_tables(fd, index, t);
#endif
        goto end;
    }
    off_t dir_offset = 0;
    if (memcmp(header, "ttcf", 4) == 0) {
        const uint32_t num_fonts = be32(header + 8), face = index & 0xffff;
        uint8_t buf[4];
        if (face >= num_fonts || !pread_all(fd, buf, 4, 12 + 4 * (off_t)face)) goto end;
        dir_offset = be32(buf);
        if (!pread_all(fd, header, sizeof(header), dir_offset)) goto end;
    }
    const uint32_t version = be32(header);
    if (version != 0x00010000 && memcmp(header, "OTTO", 4) != 0 && memcmp(header, "true", 4) != 0) {
        // Not an sfnt font, so it has no variable font data
        ok = true;
        goto end;
    }
    const uint16_t num_tables = be16(header + 4);
    records = xcalloc(num_tables, 16);
    if (!pread_all(fd, records, (size_t)num_tables * 16, dir_offset + 12)) goto end;
    for (uint16_t i = 0; i < num_tables; i++) {
        const uint8_t *r = records + 16 * i;
        size_t *dest_len;
        uint8_t **dest = table_slot(t, r, &dest_len);
        if (!dest || *dest) continue;
        const uint32_t offset = be32(r + 8), length = be32(r + 12);
        if (length > MAX_FONT_TABLE_SIZE) continue;
        *dest = xcalloc(length, 1);
        if (!pread_all(fd, *dest, length, offset)) {
            free(*dest);
            *dest = NULL;
            continue;
        }
        *dest_len = length;
    }
    ok = true;
end:
    free(records);
    close(fd);
    if (!ok) fs_free_font_tables(t);
    return ok;
}

typedef struct NameRecord {
    uint16_t platform_id, encoding_id, language_id, name_id, length;
    const uint8_t *data;
} NameRecord;

typedef struct NameTable {
    NameRecord *records;
    size_t count, capacity;
} NameTable;

static void
parse_name_table(const uint8_t *table, size_t table_len, NameTable *nt) {
    memset(nt, 0, sizeof(*nt));
    if (!table || table_len < 18) return;
    const uint16_t num = be16(table + 2), storage_offset = be16(table + 4);
    const uint8_t *storage = table + storage_offset, *limit = table + table_len;
    if (storage >= limit) return;
    const uint8_t *p = table + 6;
    for (uint16_t i = 0; i < num && p + 12 <= limit; i++, p += 12) {
        NameRecord r = {.platform_id = be16(p), .encoding_id = be16(p + 2), .language_id = be16(p + 4), .name_id = be16(p + 6), .length = be16(p + 8)};
        const uint8_t *s = storage + be16(p + 10);
        if (s + r.length > limit) continue;
        r.data = s;
        grow(nt->records, nt->count, nt->capacity);
        nt->records[nt->count++] = r;
    }
}

static size_t
encode_utf8(uint32_t ch, char *dest) {
    if (ch < 0x80) {
        dest[0] = (char)ch;
        return 1;
    }
    if (ch < 0x800) {
        dest[0] = (char)((ch >> 6) | 0xC0);
        dest[1] = (char)((ch & 0x3F) | 0x80);
        return 2;
    }
    if (ch < 0x10000) {
        dest[0] = (char)((ch >> 12) | 0xE0);
        dest[1] = (char)(((ch >> 6) & 0x3F) | 0x80);
        dest[2] = (char)((ch & 0x3F) | 0x80);
        return 3;
    }
    dest[0] = (char)((ch >> 18) | 0xF0);
    dest[1] = (char)(((ch >> 12) & 0x3F) | 0x80);
    dest[2] = (char)(((ch >> 6) & 0x3F) | 0x80);
    dest[3] = (char)((ch & 0x3F) | 0x80);
    return 4;
}

static const uint16_t mac_roman[128] = {
    0x00C4, 0x00C5, 0x00C7, 0x00C9, 0x00D1, 0x00D6, 0x00DC, 0x00E1, 0x00E0, 0x00E2, 0x00E4, 0x00E3, 0x00E5, 0x00E7, 0x00E9, 0x00E8, 0x00EA, 0x00EB, 0x00ED,
    0x00EC, 0x00EE, 0x00EF, 0x00F1, 0x00F3, 0x00F2, 0x00F4, 0x00F6, 0x00F5, 0x00FA, 0x00F9, 0x00FB, 0x00FC, 0x2020, 0x00B0, 0x00A2, 0x00A3, 0x00A7, 0x2022,
    0x00B6, 0x00DF, 0x00AE, 0x00A9, 0x2122, 0x00B4, 0x00A8, 0x2260, 0x00C6, 0x00D8, 0x221E, 0x00B1, 0x2264, 0x2265, 0x00A5, 0x00B5, 0x2202, 0x2211, 0x220F,
    0x03C0, 0x222B, 0x00AA, 0x00BA, 0x03A9, 0x00E6, 0x00F8, 0x00BF, 0x00A1, 0x00AC, 0x221A, 0x0192, 0x2248, 0x2206, 0x00AB, 0x00BB, 0x2026, 0x00A0, 0x00C0,
    0x00C3, 0x00D5, 0x0152, 0x0153, 0x2013, 0x2014, 0x201C, 0x201D, 0x2018, 0x2019, 0x00F7, 0x25CA, 0x00FF, 0x0178, 0x2044, 0x20AC, 0x2039, 0x203A, 0xFB01,
    0xFB02, 0x2021, 0x00B7, 0x201A, 0x201E, 0x2030, 0x00C2, 0x00CA, 0x00C1, 0x00CB, 0x00C8, 0x00CD, 0x00CE, 0x00CF, 0x00CC, 0x00D3, 0x00D4, 0xF8FF, 0x00D2,
    0x00DA, 0x00DB, 0x00D9, 0x0131, 0x02C6, 0x02DC, 0x00AF, 0x02D8, 0x02D9, 0x02DA, 0x00B8, 0x02DD, 0x02DB, 0x02C7,
};

static char *
decode_name_record(const NameRecord *r) {
    char *ans = xcalloc((size_t)r->length * 3 + 4, 1);
    size_t o = 0;
    if ((r->platform_id == 3 && r->encoding_id == 1) || r->platform_id == 0) {
        for (size_t i = 0; i + 1 < r->length; i += 2) {
            uint32_t ch = be16(r->data + i);
            if (0xD800 <= ch && ch <= 0xDBFF && i + 3 < r->length) {
                const uint32_t low = be16(r->data + i + 2);
                if (0xDC00 <= low && low <= 0xDFFF) {
                    ch = 0x10000 + ((ch - 0xD800) << 10) + (low - 0xDC00);
                    i += 2;
                } else ch = 0xFFFD;
            } else if (0xD800 <= ch && ch <= 0xDFFF) ch = 0xFFFD;
            o += encode_utf8(ch, ans + o);
        }
    } else if (r->platform_id == 1 && r->encoding_id == 0 && r->language_id == 0) {
        for (size_t i = 0; i < r->length; i++) {
            const uint8_t b = r->data[i];
            o += encode_utf8(b < 0x80 ? b : mac_roman[b - 0x80], ans + o);
        }
    } else {
        for (size_t i = 0; i < r->length; i++) o += encode_utf8(r->data[i], ans + o);
    }
    ans[o] = 0;
    return ans;
}

static char *
get_best_name(const NameTable *nt, unsigned name_id) {
    const NameRecord *only = NULL;
    size_t count = 0;
    for (size_t i = 0; i < nt->count; i++) {
        if (nt->records[i].name_id == name_id) {
            if (!count) only = nt->records + i;
            count++;
        }
    }
    if (!count) return xstrdup("");
    if (count == 1) return decode_name_record(only);
    static const uint16_t priorities[][3] = {{3, 1, 1033}, {1, 0, 0}, {0, 6, 0}, {0, 4, 0}, {0, 3, 0}, {0, 2, 0}, {0, 1, 0}};
    for (size_t p = 0; p < arraysz(priorities); p++) {
        for (size_t i = 0; i < nt->count; i++) {
            const NameRecord *r = nt->records + i;
            if (r->name_id == name_id && r->platform_id == priorities[p][0] && r->encoding_id == priorities[p][1] && r->language_id == priorities[p][2])
                return decode_name_record(r);
        }
    }
    return xstrdup("");
}

static void
read_fvar(const uint8_t *table, size_t table_len, const NameTable *nt, FSVariableData *vd) {
    if (!table || table_len < 28) return;
    const uint8_t *limit = table + table_len;
    const uint16_t offset_to_axes = be16(table + 4), num_axes = be16(table + 8), axis_size = be16(table + 10), num_instances = be16(table + 12),
                   instance_size = be16(table + 14);
    const size_t size_of_coordinates = (size_t)num_axes * 4;
    if (instance_size < size_of_coordinates + 4 || axis_size < 20) return;
    const bool has_postscript_name = instance_size >= 6 + size_of_coordinates;
    vd->axes = xcalloc(num_axes, sizeof(vd->axes[0]));
    for (const uint8_t *pos = table + offset_to_axes; pos + axis_size <= limit && vd->num_axes < num_axes; pos += axis_size) {
        FSVarAxis *a = vd->axes + vd->num_axes++;
        a->tag = tag_from_bytes(pos);
        a->minimum = fixed(pos + 4);
        a->def = fixed(pos + 8);
        a->maximum = fixed(pos + 12);
        a->hidden = be16(pos + 16) & 1;
        a->strid = get_best_name(nt, be16(pos + 18));
    }
    vd->named_styles = xcalloc(num_instances, sizeof(vd->named_styles[0]));
    for (const uint8_t *pos = table + offset_to_axes + (size_t)num_axes * axis_size; pos + instance_size <= limit && vd->num_named_styles < num_instances;
         pos += instance_size) {
        FSNamedStyle *ns = vd->named_styles + vd->num_named_styles++;
        ns->name = get_best_name(nt, be16(pos));
        ns->values = xcalloc(vd->num_axes, sizeof(ns->values[0]));
        for (size_t i = 0; i < vd->num_axes; i++) {
            // use the same tag at most once, like a dict
            bool found = false;
            for (size_t j = 0; j < ns->num_values; j++) {
                if (ns->values[j].tag == vd->axes[i].tag) {
                    ns->values[j].value = fixed(pos + 4 + 4 * i);
                    found = true;
                }
            }
            if (!found) ns->values[ns->num_values++] = (FSAxisValue){.tag = vd->axes[i].tag, .value = fixed(pos + 4 + 4 * i)};
        }
        const uint16_t psname_id = has_postscript_name ? be16(pos + 4 + size_of_coordinates) : 0xffff;
        ns->psname = (psname_id != 0xffff && psname_id) ? get_best_name(nt, psname_id) : xstrdup("");
    }
}

static void
read_stat(const uint8_t *table, size_t table_len, const NameTable *nt, FSVariableData *vd) {
    if (!table || table_len < 20) return;
    const uint8_t *limit = table + table_len;
    const uint16_t major_version = be16(table), minor_version = be16(table + 2), size_of_design_axis_entry = be16(table + 4),
                   count_of_design_axis_entries = be16(table + 6);
    const uint32_t offset_to_design_axes = be32(table + 8);
    const uint16_t count_of_axis_value_entries = be16(table + 12);
    const uint32_t offset_to_axis_values = be32(table + 14);
    uint16_t elided_fallback_name_id = be16(table + 18);
    if (major_version == 1 && minor_version < 1) elided_fallback_name_id = 0;
    if (elided_fallback_name_id) {
        free(vd->elided_fallback_name);
        vd->elided_fallback_name = get_best_name(nt, elided_fallback_name_id);
    }
    if (size_of_design_axis_entry < 8) return;
    vd->design_axes = xcalloc(count_of_design_axis_entries, sizeof(vd->design_axes[0]));
    for (const uint8_t *pos = table + offset_to_design_axes; pos + size_of_design_axis_entry <= limit && vd->num_design_axes < count_of_design_axis_entries;
         pos += size_of_design_axis_entry) {
        FSDesignAxis *da = vd->design_axes + vd->num_design_axes++;
        da->tag = tag_from_bytes(pos);
        da->name = get_best_name(nt, be16(pos + 4));
        da->ordering = be16(pos + 6);
    }
    const uint8_t *offsets = table + offset_to_axis_values;
    size_t count = 0;
    for (const uint8_t *pos = offsets; pos + 2 <= limit && count < count_of_axis_value_entries; pos += 2, count++) {
        const uint8_t *v = offsets + be16(pos);
        if (v + 12 > limit) continue;
        const uint16_t format = be16(v), axis_index = be16(v + 2), flags = be16(v + 4), value_name_id = be16(v + 6);
        if (axis_index >= vd->num_design_axes) continue;
        FSDesignValue dv = {.format = format, .flags = flags};
        switch (format) {
            case 1: dv.value = fixed(v + 8); break;
            case 2:
                if (v + 20 > limit) continue;
                dv.value = fixed(v + 8);
                dv.minimum = fixed(v + 12);
                dv.maximum = fixed(v + 16);
                break;
            case 3:
                if (v + 16 > limit) continue;
                dv.value = fixed(v + 8);
                dv.linked_value = fixed(v + 12);
                break;
            default: continue;
        }
        dv.name = get_best_name(nt, value_name_id);
        FSDesignAxis *da = vd->design_axes + axis_index;
        grow(da->values, da->num_values, da->capacity);
        da->values[da->num_values++] = dv;
    }
}

char *
fs_postscript_name_from_tables(const FSFontTables *t) {
    NameTable nt;
    parse_name_table(t->name, t->name_len, &nt);
    char *ans = get_best_name(&nt, 6);
    free(nt.records);
    return ans;
}

bool
fs_variable_data_from_tables(const FSFontTables *t, FSVariableData *vd) {
    memset(vd, 0, sizeof(*vd));
    NameTable nt;
    parse_name_table(t->name, t->name_len, &nt);
    vd->elided_fallback_name = xstrdup("");
    read_fvar(t->fvar, t->fvar_len, &nt, vd);
    read_stat(t->stat, t->stat_len, &nt, vd);
    vd->variations_postscript_name_prefix = get_best_name(&nt, 25);
    free(nt.records);
    return true;
}

void
fs_free_variable_data(FSVariableData *vd) {
    free(vd->variations_postscript_name_prefix);
    free(vd->elided_fallback_name);
    for (size_t i = 0; i < vd->num_axes; i++) free(vd->axes[i].strid);
    free(vd->axes);
    for (size_t i = 0; i < vd->num_named_styles; i++) {
        free(vd->named_styles[i].name);
        free(vd->named_styles[i].psname);
        free(vd->named_styles[i].values);
    }
    free(vd->named_styles);
    for (size_t i = 0; i < vd->num_design_axes; i++) {
        for (size_t j = 0; j < vd->design_axes[i].num_values; j++) free(vd->design_axes[i].values[j].name);
        free(vd->design_axes[i].values);
        free(vd->design_axes[i].name);
    }
    free(vd->design_axes);
    memset(vd, 0, sizeof(*vd));
}
// }}}

// Context {{{
typedef struct ListCacheEntry {
    int kind;
    bool monospaced;
    char *key;
    FSCandidateList list;
} ListCacheEntry;

#define FS_LIST_VARIABLE_FAMILY 1000

typedef struct WeightRange {
    double minimum, maximum, medium, bold;
    bool valid;
} WeightRange;

struct FSContext {
    FSFontSpec specs[4];
    char **symbol_families;
    size_t num_symbol_families;

    FSCandidate **candidates;
    size_t num_candidates, candidates_capacity;
    ListCacheEntry *lists;
    size_t num_lists, lists_capacity;
    struct {
        char *path;
        FSVariableData vd;
    } *vds;
    size_t num_vds, vds_capacity;
    struct {
        char *family;
        WeightRange wr;
    } *wrs;
    size_t num_wrs, wrs_capacity;
    struct {
        char *path;
        bool val;
    } *actually_variable;
    size_t num_actually_variable, actually_variable_capacity;
#ifndef __APPLE__
    struct {
        char *family;
        bool bold, italic;
        int spacing;
        const FSCandidate *ans;
    } *matches;
    size_t num_matches, matches_capacity;
#endif

    char *error;
    char **messages;
    size_t num_messages, messages_capacity;
    void *backend_data;

    FSFont results[4];
    FSFont *symbols;
    bool *symbol_bold, *symbol_italic;
    FSBuiltinNerdFont nerd_font;
};

void **
fs_backend_data(FSContext *ctx) {
    return &ctx->backend_data;
}

FSCandidate *
fs_new_candidate(FSContext *ctx) {
    grow(ctx->candidates, ctx->num_candidates, ctx->candidates_capacity);
    FSCandidate *ans = xcalloc(1, sizeof(FSCandidate));
    ctx->candidates[ctx->num_candidates++] = ans;
    return ans;
}

bool
fs_list_append(FSCandidateList *l, const FSCandidate *c) {
    grow(l->items, l->count, l->capacity);
    l->items[l->count++] = c;
    return true;
}

static char *
vformat(const char *fmt, va_list ap) {
    va_list ap2;
    va_copy(ap2, ap);
    int n = vsnprintf(NULL, 0, fmt, ap2);
    va_end(ap2);
    if (n < 0) return xstrdup(fmt);
    char *ans = xcalloc((size_t)n + 1, 1);
    vsnprintf(ans, (size_t)n + 1, fmt, ap);
    return ans;
}

void
fs_set_error(FSContext *ctx, const char *fmt, ...) {
    if (ctx->error) return; // keep the first error
    va_list ap;
    va_start(ap, fmt);
    ctx->error = vformat(fmt, ap);
    va_end(ap);
}

void
fs_add_message(FSContext *ctx, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    grow(ctx->messages, ctx->num_messages, ctx->messages_capacity);
    ctx->messages[ctx->num_messages++] = vformat(fmt, ap);
    va_end(ap);
}

static void
free_spec(FSFontSpec *s) {
    free(s->family);
    free(s->style);
    free(s->postscript_name);
    free(s->full_name);
    free(s->system);
    free(s->variable_name);
    for (size_t i = 0; i < s->num_axes; i++) free(s->axes[i].name);
    free(s->axes);
    memset(s, 0, sizeof(*s));
}

static void
free_context(FSContext *ctx) {
    if (!ctx) return;
    for (size_t i = 0; i < arraysz(ctx->specs); i++) free_spec(ctx->specs + i);
    for (size_t i = 0; i < ctx->num_symbol_families; i++) free(ctx->symbol_families[i]);
    free(ctx->symbol_families);
    for (size_t i = 0; i < ctx->num_lists; i++) {
        free(ctx->lists[i].key);
        free(ctx->lists[i].list.items);
    }
    free(ctx->lists);
    for (size_t i = 0; i < ctx->num_vds; i++) {
        free(ctx->vds[i].path);
        fs_free_variable_data(&ctx->vds[i].vd);
    }
    free(ctx->vds);
    for (size_t i = 0; i < ctx->num_wrs; i++) free(ctx->wrs[i].family);
    free(ctx->wrs);
    for (size_t i = 0; i < ctx->num_actually_variable; i++) free(ctx->actually_variable[i].path);
    free(ctx->actually_variable);
#ifndef __APPLE__
    for (size_t i = 0; i < ctx->num_matches; i++) free(ctx->matches[i].family);
    free(ctx->matches);
#endif
    for (size_t i = 0; i < ctx->num_candidates; i++) {
        FSCandidate *c = ctx->candidates[i];
        fs_backend_free_candidate(c);
        free(c->path);
        free(c->family);
        free(c->style);
        free(c->full_name);
        free(c->postscript_name);
        free(c);
    }
    free(ctx->candidates);
    free(ctx->error);
    for (size_t i = 0; i < ctx->num_messages; i++) free(ctx->messages[i]);
    free(ctx->messages);
    if (ctx->backend_data) fs_backend_free_context_data(ctx->backend_data);
    free(ctx->symbols);
    free(ctx->symbol_bold);
    free(ctx->symbol_italic);
    fs_backend_free_builtin_nerd_font(&ctx->nerd_font);
    free(ctx->nerd_font.path);
    free(ctx);
}

static const FSCandidateList *
list_fonts(FSContext *ctx, FSListKind kind, const char *name, bool monospaced) {
    RAII_ALLOC(char, key, fs_name_to_key(name));
    for (size_t i = 0; i < ctx->num_lists; i++) {
        ListCacheEntry *e = ctx->lists + i;
        if (e->kind == (int)kind && e->monospaced == monospaced && strcmp(e->key, key) == 0) return &e->list;
    }
    FSCandidateList list = {0};
    if (key[0]) {
        // Also pass the name as specified by the user, with only whitespace normalized, for case sensitive font databases
        RAII_ALLOC(char, normalized, normalize_whitespace(name));
        if (!fs_backend_list(ctx, kind, normalized, key, monospaced, &list)) {
            free(list.items);
            list = (FSCandidateList){0};
        }
    }
    grow(ctx->lists, ctx->num_lists, ctx->lists_capacity);
    ListCacheEntry *e = ctx->lists + ctx->num_lists++;
    *e = (ListCacheEntry){.kind = kind, .monospaced = monospaced, .key = xstrdup(key), .list = list};
    return &e->list;
}

static int
cmp_by_path(const void *a_, const void *b_) {
    const FSCandidate *const *a = a_, *const *b = b_;
    return strcmp((*a)->path ? (*a)->path : "", (*b)->path ? (*b)->path : "");
}

// The fonts of the specified family that are variable fonts
static const FSCandidateList *
variable_fonts(FSContext *ctx, const char *family, bool monospaced) {
    RAII_ALLOC(char, key, fs_name_to_key(family));
    for (size_t i = 0; i < ctx->num_lists; i++) {
        ListCacheEntry *e = ctx->lists + i;
        if (e->kind == FS_LIST_VARIABLE_FAMILY && e->monospaced == monospaced && strcmp(e->key, key) == 0) return &e->list;
    }
    const FSCandidateList *all = list_fonts(ctx, FS_LIST_FAMILY, family, monospaced);
    FSCandidateList list = {0};
    for (size_t i = 0; i < all->count; i++) {
        if (all->items[i]->variable) fs_list_append(&list, all->items[i]);
    }
#ifdef __APPLE__
    // CoreText makes a separate descriptor for each named style in each
    // variable font file. Keep only the default style descriptor, which has an
    // empty variation dictionary. If no default exists, pick the one with the
    // smallest variation dictionary size.
    if (list.count > 1) {
        // stable sort by path
        for (size_t i = 1; i < list.count; i++) {
            const FSCandidate *x = list.items[i];
            size_t j = i;
            while (j > 0 && cmp_by_path(&list.items[j - 1], &x) > 0) {
                list.items[j] = list.items[j - 1];
                j--;
            }
            list.items[j] = x;
        }
        size_t o = 0;
        for (size_t i = 0; i < list.count;) {
            size_t j = i, best = i;
            for (; j < list.count && cmp_by_path(&list.items[i], &list.items[j]) == 0; j++) {
                if (list.items[j]->variation_count < list.items[best]->variation_count) best = j;
            }
            list.items[o++] = list.items[best];
            i = j;
        }
        list.count = o;
    }
#else
    (void)cmp_by_path;
#endif
    grow(ctx->lists, ctx->num_lists, ctx->lists_capacity);
    ListCacheEntry *e = ctx->lists + ctx->num_lists++;
    *e = (ListCacheEntry){.kind = FS_LIST_VARIABLE_FAMILY, .monospaced = monospaced, .key = xstrdup(key), .list = list};
    return &e->list;
}

static const FSVariableData *
variable_data(FSContext *ctx, const FSCandidate *c) {
    const char *path = c->path ? c->path : "";
    for (size_t i = 0; i < ctx->num_vds; i++) {
        if (strcmp(ctx->vds[i].path, path) == 0) return &ctx->vds[i].vd;
    }
    grow(ctx->vds, ctx->num_vds, ctx->vds_capacity);
    ctx->vds[ctx->num_vds].path = xstrdup(path);
    FSVariableData *vd = &ctx->vds[ctx->num_vds].vd;
    ctx->num_vds++;
    FSFontTables t = {0};
    if (!fs_backend_font_tables(ctx, c, &t)) memset(&t, 0, sizeof(t));
    fs_variable_data_from_tables(&t, vd);
    fs_free_font_tables(&t);
    return vd;
}
// }}}

// Variable fonts {{{
static FSFont
font_from_candidate(const FSCandidate *c) {
    return (FSFont){.base = c, .named_style = -1};
}

static bool
same_candidate(const FSCandidate *a, const FSCandidate *b) {
    if (a == b) return true;
    if (!a || !b) return false;
    return a->from_match == b->from_match && a->index == b->index && streq(a->path, b->path) && streq(a->postscript_name, b->postscript_name) &&
           streq(a->style, b->style) && streq(a->family, b->family) && a->variable == b->variable;
}

static bool
fonts_equal(const FSFont *a, const FSFont *b) {
    if (!a || !b) return a == b;
    if (!same_candidate(a->base, b->base) || a->named_style != b->named_style || a->has_axes != b->has_axes || a->has_matrix != b->has_matrix) return false;
    if (a->has_axes) {
        AxisMap ma, mb;
        axis_map_from_values(&ma, a->axes, a->num_axes);
        axis_map_from_values(&mb, b->axes, b->num_axes);
        if (!axis_maps_equal(&ma, &mb)) return false;
    }
    if (a->has_matrix && memcmp(a->matrix, b->matrix, sizeof(a->matrix)) != 0) return false;
    return true;
}

static bool
is_monospace(const FSFont *f) {
    return f->base->monospace;
}

static bool
is_variable(const FSFont *f) {
    return f->base->variable;
}

static int
find_named_style(const char *name, const FSVariableData *vd) {
    for (size_t i = 0; i < vd->num_named_styles; i++) {
        if (ieq(vd->named_styles[i].psname, name)) return (int)i;
    }
    for (size_t i = 0; i < vd->num_named_styles; i++) {
        if (ieq(vd->named_styles[i].name, name)) return (int)i;
    }
    if (!is_empty(vd->elided_fallback_name)) {
        RAII_ALLOC(char, q, lowercased(name));
        const char *efn = vd->elided_fallback_name;
        const size_t efn_len = strlen(efn);
        for (size_t i = 0; i < vd->num_named_styles; i++) {
            // remove all occurrences of efn from the name
            const char *src = vd->named_styles[i].name;
            RAII_ALLOC(char, removed, xcalloc(strlen(src) + 1, 1));
            size_t o = 0;
            while (*src) {
                if (strncmp(src, efn, efn_len) == 0) src += efn_len;
                else removed[o++] = *(src++);
            }
            removed[o] = 0;
            RAII_ALLOC(char, eq, fs_name_to_key(removed));
            if (strcmp(q, eq) == 0) return (int)i;
        }
    }
    return -1;
}

#ifdef __APPLE__
static void
set_font_axes(FSFont *font, const AxisMap *m) {
    font->has_axes = true;
    font->num_axes = m->count;
    memcpy(font->axes, m->items, m->count * sizeof(m->items[0]));
}

static bool
set_axis_values(const AxisMap *tag_map, FSFont *font, const FSVariableData *vd) {
    AxisMap previous = {0}, new = {0};
    if (font->has_axes) axis_map_from_values(&previous, font->axes, font->num_axes);
    new = previous;
    for (size_t i = 0; i < vd->num_axes; i++) {
        const double *val = axis_map_get(tag_map, vd->axes[i].tag);
        if (val) axis_map_set(&new, vd->axes[i].tag, *val);
    }
    set_font_axes(font, &new);
    return !axis_maps_equal(&new, &previous);
}

static bool
set_named_style(const char *name, FSFont *font, const FSVariableData *vd) {
    int idx = find_named_style(name, vd);
    if (idx < 0) return false;
    AxisMap m;
    axis_map_from_values(&m, vd->named_styles[idx].values, vd->named_styles[idx].num_values);
    return set_axis_values(&m, font, vd);
}

static void
get_axis_values(const FSFont *font, const FSVariableData *vd UNUSED, AxisMap *ans) {
    ans->count = 0;
    if (font->has_axes) axis_map_from_values(ans, font->axes, font->num_axes);
}
#else
static void
current_axes(const FSFont *font, const FSVariableData *vd, AxisMap *ans) {
    // in the order of the axes in vd
    ans->count = 0;
    for (size_t i = 0; i < vd->num_axes && i < FS_MAX_AXES; i++) {
        ans->items[ans->count++] =
            (FSAxisValue){.tag = vd->axes[i].tag, .value = (font->has_axes && font->num_axes && i < font->num_axes) ? font->axes[i].value : vd->axes[i].def};
    }
}

static void
lift_axes_to_named_style_if_possible(FSFont *font, const FSVariableData *vd) {
    AxisMap q, current;
    current_axes(font, vd, &current);
    axis_map_from_values(&q, current.items, current.count);
    for (size_t i = 0; i < vd->num_named_styles; i++) {
        AxisMap ns;
        axis_map_from_values(&ns, vd->named_styles[i].values, vd->named_styles[i].num_values);
        if (axis_maps_equal(&ns, &q)) {
            font->has_axes = false;
            font->num_axes = 0;
            font->named_style = (int)i;
            return;
        }
    }
}

static bool
set_axis_values(const AxisMap *tag_map, FSFont *font, const FSVariableData *vd) {
    AxisMap axes;
    current_axes(font, vd, &axes);
    bool changed = false;
    for (size_t i = 0; i < axes.count; i++) {
        const double *val = axis_map_get(tag_map, axes.items[i].tag);
        if (val) {
            changed = true;
            axes.items[i].value = *val;
        }
    }
    if (changed) {
        font->has_axes = true;
        font->num_axes = axes.count;
        memcpy(font->axes, axes.items, axes.count * sizeof(axes.items[0]));
        lift_axes_to_named_style_if_possible(font, vd);
    }
    return changed;
}

static bool
set_named_style(const char *name, FSFont *font, const FSVariableData *vd) {
    int idx = find_named_style(name, vd);
    if (idx < 0) return false;
    font->named_style = idx;
    return true;
}

static void
get_axis_values(const FSFont *font, const FSVariableData *vd, AxisMap *ans) {
    ans->count = 0;
    if (font->named_style > -1 && (size_t)font->named_style < vd->num_named_styles) {
        const FSNamedStyle *ns = vd->named_styles + font->named_style;
        axis_map_from_values(ans, ns->values, ns->num_values);
    }
    for (size_t i = 0; i < vd->num_axes; i++) {
        const uint32_t tag = vd->axes[i].tag;
        if (font->has_axes && i < font->num_axes) axis_map_set(ans, tag, font->axes[i].value);
        else if (!axis_map_get(ans, tag)) axis_map_set(ans, tag, vd->axes[i].def);
    }
}
#endif

typedef struct OptionalDouble {
    bool has;
    double val;
} OptionalDouble;

typedef struct FamilyAxisValues {
    OptionalDouble regular_weight, regular_slant, regular_ital, regular_width, bold_weight, italic_slant, italic_ital;
} FamilyAxisValues;

static OptionalDouble
opt_from_map(const AxisMap *m, uint32_t tag) {
    const double *v = axis_map_get(m, tag);
    return v ? (OptionalDouble){.has = true, .val = *v} : (OptionalDouble){0};
}

static OptionalDouble
family_axis_value(const FamilyAxisValues *f, uint32_t tag, bool bold, bool italic) {
    switch (tag) {
        case WGHT: return bold ? f->bold_weight : f->regular_weight;
        case ITAL: return italic ? f->italic_ital : f->regular_ital;
        case SLNT: return italic ? f->italic_slant : f->regular_slant;
        case WDTH: return f->regular_width;
    }
    return (OptionalDouble){0};
}

static void
set_regular_values(FamilyAxisValues *f, const AxisMap *m) {
    f->regular_weight = opt_from_map(m, WGHT);
    f->regular_width = opt_from_map(m, WDTH);
    f->regular_ital = opt_from_map(m, ITAL);
    f->regular_slant = opt_from_map(m, SLNT);
}

static void
set_bold_values(FamilyAxisValues *f, const AxisMap *m) {
    f->bold_weight = opt_from_map(m, WGHT);
}

static void
set_italic_values(FamilyAxisValues *f, const AxisMap *m) {
    f->italic_ital = opt_from_map(m, ITAL);
    f->italic_slant = opt_from_map(m, SLNT);
}

static FSFont
find_medium_variant(FSContext *ctx, FSFont font) {
    const FSVariableData *vd = variable_data(ctx, font.base);
    for (size_t i = 0; i < vd->num_named_styles; i++) {
        const FSNamedStyle *ns = vd->named_styles + i;
        if (strcmp(ns->name, "Regular") == 0) {
            set_named_style(is_empty(ns->psname) ? ns->name : ns->psname, &font, vd);
            return font;
        }
    }
    AxisMap axis_values = {0};
    for (size_t i = 0; i < vd->num_axes; i++) {
        const uint32_t tag = vd->axes[i].tag;
        for (size_t d = 0; d < vd->num_design_axes; d++) {
            const FSDesignAxis *dax = vd->design_axes + d;
            if (dax->tag != tag) continue;
            for (size_t v = 0; v < dax->num_values; v++) {
                const FSDesignValue *x = dax->values + v;
                if ((x->format == 1 || x->format == 2) && strcmp(x->name, "Regular") == 0) {
                    axis_map_set(&axis_values, tag, x->value);
                    break;
                }
            }
        }
    }
    if (axis_values.count) set_axis_values(&axis_values, &font, vd);
    return font;
}

static double
get_bold_design_weight(const FSDesignAxis *dax, double regular_weight) {
    bool found = false;
    double ans = regular_weight;
    for (size_t i = 0; i < dax->num_values; i++) {
        const FSDesignValue *x = dax->values + i;
        if ((x->format == 1 || x->format == 2) && x->value > regular_weight) {
            if (!found || x->value < ans) ans = x->value;
            found = true;
        }
    }
    return ans;
}

static double
get_design_value_for(const FSDesignAxis *dax, const FSVarAxis *ax, bool bold, bool italic, const FamilyAxisValues *fav) {
    OptionalDouble family_val = family_axis_value(fav, ax->tag, bold, italic);
    if (family_val.has && ax->minimum <= family_val.val && family_val.val <= ax->maximum) return family_val.val;
    const double def = ax->def;
    static const char *bold_keys[] = {"semibold", "bold", "heavy", "black", NULL}, *regular_weight_keys[] = {"regular", "medium", NULL},
                      *italic_keys[] = {"italic", "oblique", "slanted", "slant", NULL}, *upright_keys[] = {"regular", "normal", "medium", "upright", NULL};
    const char **keys;
    if (dax->tag == WGHT) keys = bold ? bold_keys : regular_weight_keys;
    else if (dax->tag == ITAL || dax->tag == SLNT) keys = italic ? italic_keys : upright_keys;
    else return def;
    // An insertion ordered dict of value -> priority
    RAII_ALLOC(double, values, xcalloc(dax->num_values, sizeof(double)));
    RAII_ALLOC(int, priorities, xcalloc(dax->num_values, sizeof(int)));
    size_t count = 0;
    for (size_t i = 0; i < dax->num_values; i++) {
        const FSDesignValue *x = dax->values + i;
        if (x->format != 1 && x->format != 2) continue;
        int idx = -1;
        for (int k = 0; keys[k]; k++) {
            if (ieq(keys[k], x->name)) {
                idx = k;
                break;
            }
        }
        if (idx < 0) continue;
        size_t j = 0;
        for (; j < count && values[j] != x->value; j++);
        if (j == count) values[count++] = x->value;
        priorities[j] = idx;
    }
    double ans = def;
    if (count) {
        size_t best = 0;
        for (size_t j = 1; j < count; j++) {
            if (priorities[j] < priorities[best]) best = j;
        }
        ans = values[best];
    }
    if (bold && ax->tag == WGHT && fav->regular_weight.has && ans <= fav->regular_weight.val) ans = get_bold_design_weight(dax, fav->regular_weight.val);
    return ans;
}
// }}}

// Scoring {{{
typedef struct Scorer {
    bool bold, italic, monospaced, prefer_variable;
} Scorer;

typedef struct Score {
    int variable_score;
    double style_score;
    int monospace_score;
    double width_score;
    size_t idx;
} Score;

static WeightRange
weight_range_for_family(FSContext *ctx, const char *family) {
    for (size_t i = 0; i < ctx->num_wrs; i++) {
        if (strcmp(ctx->wrs[i].family, family) == 0) return ctx->wrs[i].wr;
    }
    const FSCandidateList *faces = list_fonts(ctx, FS_LIST_FAMILY, family, true);
#ifdef __APPLE__
    const WeightRange sentinel = {.minimum = 99999, .maximum = -99999, .medium = -99999, .bold = -99999};
#else
    const WeightRange sentinel = {.minimum = 9223372036854775807.0, .maximum = -1, .medium = -1, .bold = -1};
    RAII_ALLOC(double, seen, xcalloc(faces->count, sizeof(double)));
    size_t num_seen = 0;
#endif
    WeightRange wr = sentinel;
    for (size_t i = 0; i < faces->count; i++) {
        const FSCandidate *face = faces->items[i];
        const double w = face->weight;
        if (w < wr.minimum) wr.minimum = w;
        if (w > wr.maximum) wr.maximum = w;
#ifndef __APPLE__
        size_t j = 0;
        for (; j < num_seen && seen[j] != w; j++);
        if (j == num_seen) seen[num_seen++] = w;
#endif
        // the first word of the lowercased style
        char first_word[32] = {0};
        const char *s = face->style ? face->style : "";
        while (*s && is_space(*s)) s++;
        size_t n = 0;
        while (*s && !is_space(*s) && n < sizeof(first_word) - 1) first_word[n++] = lower(*(s++));
        if (!n || (*s && !is_space(*s))) continue;
        if (strcmp(first_word, "semibold") == 0) wr.bold = w;
        else if (strcmp(first_word, "bold") == 0 && wr.bold == sentinel.bold) wr.bold = w;
        else if (strcmp(first_word, "regular") == 0) wr.medium = w;
        else if (strcmp(first_word, "medium") == 0 && wr.medium == sentinel.medium) wr.medium = w;
    }
    wr.valid = wr.minimum != sentinel.minimum && wr.maximum != sentinel.maximum && wr.medium != sentinel.medium && wr.bold != sentinel.bold;
#ifndef __APPLE__
    if (num_seen < 2) wr = sentinel;
#endif
    grow(ctx->wrs, ctx->num_wrs, ctx->wrs_capacity);
    ctx->wrs[ctx->num_wrs].family = xstrdup(family);
    ctx->wrs[ctx->num_wrs].wr = wr;
    ctx->num_wrs++;
    return wr;
}

static Score
score(const Scorer *s, const FSCandidate *c, const WeightRange *wr) {
    Score ans = {.variable_score = (s->prefer_variable && c->variable) ? 0 : 1};
#ifdef __APPLE__
    double bold_score = c->weight; // -1 to 1 with 0 being normal
    if (!wr) {
        if (bold_score < 0) bold_score = 2.0;                  // thinner than normal, reject
        else if (s->bold) bold_score = fabs(bold_score - 0.3); // prefer semibold=0.3 to full bold = 0.4
    } else bold_score = fabs(bold_score - (s->bold ? wr->bold : wr->medium));
    // -1 to 1 with 0 being upright < 0 being backward slant, abs(slant) == 1 implies 30 deg rotation
    double italic_score = c->slant;
    if (s->italic) italic_score = italic_score < 0 ? 2.0 : fabs(1 - italic_score);
    ans.style_score = bold_score + italic_score;
    ans.monospace_score = c->monospace ? 0 : 1;
    ans.width_score = (!c->expanded && !c->condensed) ? 0 : 1;
#else
    double bold_score;
    if (!wr) bold_score = fabs((s->bold ? FC_WEIGHT_SEMIBOLD : FC_WEIGHT_REGULAR) - c->weight);
    else bold_score = fabs((s->bold ? wr->bold : wr->medium) - c->weight);
    const double italic_score = fabs((s->italic ? FC_SLANT_ITALIC : FC_SLANT_ROMAN) - c->slant);
    ans.monospace_score = s->monospaced ? (c->spacing_is_mono ? 0 : 1) : 0;
    ans.width_score = fabs(c->width - FC_WIDTH_NORMAL);
    ans.style_score = bold_score / 1000 + italic_score / 110;
#endif
    return ans;
}

static int
cmp_score(const void *a_, const void *b_) {
    const Score *a = a_, *b = b_;
#define c(x)                    \
    if (a->x < b->x) return -1; \
    if (a->x > b->x) return 1;
    c(variable_score);
    c(style_score);
    c(monospace_score);
    c(width_score);
    c(idx);
#undef c
    return 0;
}

// Returns a newly allocated array of sorted candidates that the caller must free
static const FSCandidate **
sorted_candidates(FSContext *ctx, const Scorer *s, const FSCandidate *const *candidates, size_t count) {
    WeightRange wr = {0};
    bool use_wr = false;
    if (count) {
        bool single_family = true;
        for (size_t i = 1; i < count && single_family; i++) {
            if (!streq(candidates[i]->family, candidates[0]->family)) single_family = false;
        }
        if (single_family) {
            wr = weight_range_for_family(ctx, candidates[0]->family ? candidates[0]->family : "");
#ifdef __APPLE__
            use_wr = wr.valid && wr.medium < 0; // Operator Mono is an example of this craziness
#else
            use_wr = wr.valid && wr.medium < 100; // Operator Mono and Cascadia Code are examples
#endif
        }
    }
    RAII_ALLOC(Score, scores, xcalloc(count, sizeof(Score)));
    for (size_t i = 0; i < count; i++) {
        scores[i] = score(s, candidates[i], use_wr ? &wr : NULL);
        scores[i].idx = i;
    }
    qsort(scores, count, sizeof(Score), cmp_score);
    const FSCandidate **ans = xcalloc(count, sizeof(FSCandidate *));
    for (size_t i = 0; i < count; i++) ans[i] = candidates[scores[i].idx];
    return ans;
}

static const FSCandidate *
best_candidate(FSContext *ctx, const Scorer *s, const FSCandidate *const *candidates, size_t count) {
    if (!count) return NULL;
    RAII_ALLOC(const FSCandidate *, sorted, sorted_candidates(ctx, s, candidates, count));
    return sorted[0];
}

#ifndef __APPLE__
// Return the best candidate that is not ignore_face or NULL
static const FSCandidate *
find_best_match_in_candidates(FSContext *ctx, const Scorer *s, const FSCandidateList *l, const FSFont *ignore_face) {
    if (!l->count) return NULL;
    RAII_ALLOC(const FSCandidate *, sorted, sorted_candidates(ctx, s, l->items, l->count));
    for (size_t i = 0; i < l->count; i++) {
        FSFont f = font_from_candidate(sorted[i]);
        if (!ignore_face || !fonts_equal(&f, ignore_face)) return sorted[i];
    }
    return NULL;
}
#endif
// }}}

// Selection {{{
static bool
is_actually_variable_despite_fontconfigs_lies(FSContext *ctx, const FSFont *d) {
#ifdef __APPLE__
    (void)ctx;
    (void)d;
    return false;
#else
    const char *path = d->base->path ? d->base->path : "";
    for (size_t i = 0; i < ctx->num_actually_variable; i++) {
        if (strcmp(ctx->actually_variable[i].path, path) == 0) return ctx->actually_variable[i].val;
    }
    const FSCandidateList *l = variable_fonts(ctx, d->base->family, is_monospace(d));
    bool ans = false;
    for (size_t i = 0; i < l->count && !ans; i++) {
        if (streq(l->items[i]->path, path)) ans = true;
    }
    grow(ctx->actually_variable, ctx->num_actually_variable, ctx->actually_variable_capacity);
    ctx->actually_variable[ctx->num_actually_variable].path = xstrdup(path);
    ctx->actually_variable[ctx->num_actually_variable].val = ans;
    ctx->num_actually_variable++;
    return ans;
#endif
}

static bool
font_is_variable(FSContext *ctx, const FSFont *f) {
    return is_variable(f) || is_actually_variable_despite_fontconfigs_lies(ctx, f);
}

static const FSCandidate *find_last_resort_text_font(FSContext *ctx, bool bold, bool italic, bool monospaced);

#ifndef __APPLE__
static const FSCandidate *
fc_match(FSContext *ctx, const char *family, bool bold, bool italic, int spacing) {
    for (size_t i = 0; i < ctx->num_matches; i++) {
        if (strcmp(ctx->matches[i].family, family) == 0 && ctx->matches[i].bold == bold && ctx->matches[i].italic == italic &&
            ctx->matches[i].spacing == spacing)
            return ctx->matches[i].ans;
    }
    const FSCandidate *ans = fs_backend_fc_match(ctx, family, bold, italic, spacing);
    grow(ctx->matches, ctx->num_matches, ctx->matches_capacity);
    ctx->matches[ctx->num_matches].family = xstrdup(family);
    ctx->matches[ctx->num_matches].bold = bold;
    ctx->matches[ctx->num_matches].italic = italic;
    ctx->matches[ctx->num_matches].spacing = spacing;
    ctx->matches[ctx->num_matches].ans = ans;
    ctx->num_matches++;
    return ans;
}

static const FSCandidate *
find_last_resort_text_font(FSContext *ctx, bool bold, bool italic, bool monospaced) {
    // Use fc-match with a generic family
    const FSCandidate *ans = fc_match(ctx, monospaced ? "monospace" : "sans-serif", bold, italic, FC_MONO);
    if (!ans) fs_set_error(ctx, "Failed to find any font using fontconfig");
    return ans;
}

static bool
find_best_match(FSContext *ctx, const char *family, bool bold, bool italic, bool monospaced, const FSFont *ignore_face, bool prefer_variable, FSFont *ans) {
    const Scorer scorer = {.bold = bold, .italic = italic, .monospaced = monospaced, .prefer_variable = prefer_variable};
    // First look for an exact match
    const FSListKind groups[] = {FS_LIST_POSTSCRIPT_NAME, FS_LIST_FULL_NAME, FS_LIST_FAMILY};
    for (size_t g = 0; g < arraysz(groups); g++) {
        const FSCandidateList *cq = list_fonts(ctx, groups[g], family, monospaced);
        if (!cq->count) continue;
        // IBM Plex Mono has fullname of regular face == family_name under fontconfig
        if (groups[g] == FS_LIST_FULL_NAME && streq(cq->items[0]->family, cq->items[0]->full_name)) continue;
        const FSCandidate *exact_match = find_best_match_in_candidates(ctx, &scorer, cq, ignore_face);
        if (exact_match) {
            *ans = font_from_candidate(exact_match);
            return true;
        }
    }
    // Use fc-match to see if we can find a monospaced font that matches family
    // When aliases are defined, spacing can cause the incorrect font to be
    // returned, so check with and without spacing and use the one that matches.
    const FSCandidate *mono_possibility = fc_match(ctx, family, false, false, FC_MONO);
    const FSCandidate *dual_possibility = fc_match(ctx, family, false, false, FC_DUAL);
    const FSCandidate *any_possibility = fc_match(ctx, family, false, false, 0);
    const FSCandidate *tries[2] = {mono_possibility, dual_possibility};
    if (any_possibility && dual_possibility && fs_backend_fc_match_equal(any_possibility, dual_possibility)) {
        tries[0] = dual_possibility;
        tries[1] = mono_possibility;
    }
    for (size_t t = 0; t < arraysz(tries); t++) {
        const FSCandidate *possibility = tries[t];
        if (!possibility) continue;
        const struct {
            const char *val;
            FSListKind kind;
        } q[] = {
            {possibility->postscript_name, FS_LIST_POSTSCRIPT_NAME},
            {possibility->full_name, FS_LIST_FULL_NAME},
            {possibility->family, FS_LIST_FAMILY},
        };
        for (size_t k = 0; k < arraysz(q); k++) {
            if (is_empty(q[k].val)) continue;
            const FSCandidateList *candidates = list_fonts(ctx, q[k].kind, q[k].val, monospaced);
            if (!candidates->count) continue;
            if (candidates->count == 1) {
                // happens if the family name is an alias, so we search with
                // the actual family name to see if we can find all the
                // fonts in the family.
                const FSCandidateList *fc = list_fonts(ctx, FS_LIST_FAMILY, candidates->items[0]->family, monospaced);
                if (fc->count > 1) candidates = fc;
            }
            *ans = font_from_candidate(best_candidate(ctx, &scorer, candidates->items, candidates->count));
            return true;
        }
    }
    const FSCandidate *lr = find_last_resort_text_font(ctx, bold, italic, monospaced);
    if (!lr) return false;
    *ans = font_from_candidate(lr);
    return true;
}
#else
static const FSCandidate *
find_last_resort_text_font(FSContext *ctx, bool bold, bool italic, bool monospaced) {
    const FSCandidateList *candidates = list_fonts(ctx, FS_LIST_FAMILY, "Menlo", monospaced);
    const Scorer scorer = {.bold = bold, .italic = italic, .monospaced = monospaced};
    const FSCandidate *ans = best_candidate(ctx, &scorer, candidates->items, candidates->count);
    if (!ans) fs_set_error(ctx, "Failed to find the Menlo font");
    return ans;
}

static bool
find_best_match(FSContext *ctx, const char *family, bool bold, bool italic, bool monospaced, const FSFont *ignore_face, bool prefer_variable, FSFont *ans) {
    const Scorer scorer = {.bold = bold, .italic = italic, .monospaced = monospaced, .prefer_variable = prefer_variable};
    // First look for an exact match
    const FSListKind groups[] = {FS_LIST_POSTSCRIPT_NAME, FS_LIST_FULL_NAME};
    for (size_t g = 0; g < arraysz(groups); g++) {
        const FSCandidateList *candidates = list_fonts(ctx, groups[g], family, monospaced);
        const FSCandidate *possible = best_candidate(ctx, &scorer, candidates->items, candidates->count);
        if (possible) {
            FSFont f = font_from_candidate(possible);
            if (!fonts_equal(&f, ignore_face)) {
                *ans = f;
                return true;
            }
        }
    }
    // See if we have a variable font
    if (!bold && !italic) {
        const FSCandidateList *candidates = variable_fonts(ctx, family, monospaced);
        const FSCandidate *possible = best_candidate(ctx, &scorer, candidates->items, candidates->count);
        if (possible) {
            FSFont f = font_from_candidate(possible);
            if (!fonts_equal(&f, ignore_face)) {
                *ans = find_medium_variant(ctx, f);
                return true;
            }
        }
    }
    // Let CoreText choose the font if the family exists, otherwise fallback to Menlo
    const FSCandidateList *candidates = list_fonts(ctx, FS_LIST_FAMILY, family, monospaced);
    if (!candidates->count) {
        if (!ieq(family, "monospace") && !ieq(family, "symbols nerd font mono"))
            fs_add_message(ctx, "The font %s was not found, falling back to Menlo", family);
        candidates = list_fonts(ctx, FS_LIST_FAMILY, "Menlo", monospaced);
    }
    const FSCandidate *c = best_candidate(ctx, &scorer, candidates->items, candidates->count);
    if (!c) {
        fs_set_error(ctx, "Failed to find the Menlo font");
        return false;
    }
    *ans = font_from_candidate(c);
    return true;
}
#endif

static FSFont
find_bold_italic_variant(FSContext *ctx, const FSFont *medium, bool bold, bool italic, const FamilyAxisValues *fav) {
    // we first pick the best font file for bold/italic if there are more than
    // one. For example SourceCodeVF has Italic and Upright faces with variable
    // weights in each, so we rely on the OS font matcher to give us the best
    // font file.
    const bool monospaced = is_monospace(medium);
    const FSCandidateList *unsorted = variable_fonts(ctx, medium->base->family, monospaced);
    if (!unsorted->count) return *medium;
    const Scorer scorer = {.bold = bold, .italic = italic, .monospaced = monospaced};
    const FSCandidate *best = best_candidate(ctx, &scorer, unsorted->items, unsorted->count);
    const FSVariableData *vd = variable_data(ctx, best);
    FSFont ans = font_from_candidate(best);
    // now we need to specialise all axes in ans
    AxisMap axis_values = {0};
    for (size_t i = 0; i < vd->num_axes; i++) {
        const FSVarAxis *ax = vd->axes + i;
        const FSDesignAxis *dax = NULL;
        for (size_t d = 0; d < vd->num_design_axes; d++) {
            if (vd->design_axes[d].tag == ax->tag) dax = vd->design_axes + d;
        }
        if (dax) axis_map_set(&axis_values, ax->tag, get_design_value_for(dax, ax, bold, italic, fav));
    }
    if (axis_values.count) set_axis_values(&axis_values, &ans, vd);
    return ans;
}

static const FSCandidate *
find_best_variable_face(FSContext *ctx, const FSFontSpec *spec, bool bold, bool italic, bool monospaced, const FSCandidateList *candidates) {
    if (spec->has_variable_name) {
        for (size_t i = 0; i < candidates->count; i++) {
            const FSVariableData *vd = variable_data(ctx, candidates->items[i]);
            if (ieq(vd->variations_postscript_name_prefix, spec->variable_name)) return candidates->items[i];
        }
    }
    if (!is_empty(spec->style)) {
        for (size_t i = 0; i < candidates->count; i++) {
            const FSVariableData *vd = variable_data(ctx, candidates->items[i]);
            for (size_t n = 0; n < vd->num_named_styles; n++) {
                if (ieq(vd->named_styles[n].psname, spec->style)) return candidates->items[i];
            }
            for (size_t n = 0; n < vd->num_named_styles; n++) {
                if (ieq(vd->named_styles[n].name, spec->style)) return candidates->items[i];
            }
        }
    }
    const Scorer scorer = {.bold = bold, .italic = italic, .monospaced = monospaced};
    return best_candidate(ctx, &scorer, candidates->items, candidates->count);
}

static bool
apply_variation_to_pattern(FSContext *ctx, FSFont *pat, const FSFontSpec *spec) {
    const FSVariableData *vd = variable_data(ctx, pat->base);
    if (!is_empty(spec->style) && set_named_style(spec->style, pat, vd)) return true;
    AxisMap axis_values = {0};
    for (size_t a = 0; a < spec->num_axes; a++) {
        const char *qname = spec->axes[a].name;
        const uint32_t qtag = tag_from_string(qname);
        bool found = false;
        for (size_t i = 0; i < vd->num_axes && !found; i++) {
            char tag[5];
            tag_to_str(vd->axes[i].tag, tag);
            if (strcmp(tag, qname) == 0) {
                axis_map_set(&axis_values, qtag, spec->axes[a].value);
                found = true;
            }
        }
        if (found) continue;
        // later axes with the same name take precedence, like a dict
        uint32_t tag = 0;
        for (size_t i = 0; i < vd->num_axes; i++) {
            if (!is_empty(vd->axes[i].strid) && ieq(vd->axes[i].strid, qname)) tag = vd->axes[i].tag;
        }
        if (tag) axis_map_set(&axis_values, tag, spec->axes[a].value);
    }
    return set_axis_values(&axis_values, pat, vd);
}

static bool
get_fine_grained_font(
    FSContext *ctx,
    const FSFontSpec *spec,
    bool bold,
    bool italic,
    const FamilyAxisValues *fav,
    const FSFont *resolved_medium_font,
    bool *match_is_more_specific_than_family,
    FSFont *ans) {
    const bool monospaced = true;
    const Scorer scorer = {.bold = bold, .italic = italic, .monospaced = monospaced};
    if (!is_empty(spec->postscript_name)) {
        const FSCandidateList *l = list_fonts(ctx, FS_LIST_POSTSCRIPT_NAME, spec->postscript_name, monospaced);
        const FSCandidate *q = best_candidate(ctx, &scorer, l->items, l->count);
        if (q) {
            *match_is_more_specific_than_family = true;
            *ans = font_from_candidate(q);
            return true;
        }
    }
    if (!is_empty(spec->full_name)) {
        const FSCandidateList *l = list_fonts(ctx, FS_LIST_FULL_NAME, spec->full_name, monospaced);
        const FSCandidate *q = best_candidate(ctx, &scorer, l->items, l->count);
        if (q) {
            *match_is_more_specific_than_family = true;
            *ans = font_from_candidate(q);
            return true;
        }
    }
    if (!is_empty(spec->family)) {
        // First look for a variable font
        const FSCandidateList *candidates = variable_fonts(ctx, spec->family, monospaced);
        if (candidates->count) {
            const FSCandidate *q = candidates->count == 1 ? candidates->items[0] : find_best_variable_face(ctx, spec, bold, italic, monospaced, candidates);
            FSFont f = font_from_candidate(q);
            if (apply_variation_to_pattern(ctx, &f, spec)) {
                *match_is_more_specific_than_family = true;
                *ans = f;
                return true;
            }
            *ans = resolved_medium_font ? find_bold_italic_variant(ctx, resolved_medium_font, bold, italic, fav) : find_medium_variant(ctx, f);
            return true;
        }
        // Now look for any font
        const FSCandidateList *all = list_fonts(ctx, FS_LIST_FAMILY, spec->family, monospaced);
        if (all->count) {
            FSCandidateList filtered = {0};
            for (size_t i = 0; i < all->count; i++) {
                if (is_empty(spec->style) || ieq(all->items[i]->style, spec->style)) fs_list_append(&filtered, all->items[i]);
            }
            const FSCandidate *q = best_candidate(ctx, &scorer, filtered.items, filtered.count);
            free(filtered.items);
            if (q) {
                *ans = font_from_candidate(q);
                return true;
            }
        }
    }
    const FSCandidate *lr = find_last_resort_text_font(ctx, bold, italic, monospaced);
    if (!lr) return false;
    *ans = font_from_candidate(lr);
    return true;
}

static bool
get_font_from_spec(
    FSContext *ctx,
    const FSFontSpec *spec,
    bool bold,
    bool italic,
    const FamilyAxisValues *fav,
    const FSFont *resolved_medium_font,
    const FSFont *ignore_face,
    bool *match_is_more_specific_than_family,
    FSFont *ans) {
    if (is_empty(spec->system)) return get_fine_grained_font(ctx, spec, bold, italic, fav, resolved_medium_font, match_is_more_specific_than_family, ans);
    const char *family = spec->system;
    if (strcmp(family, "auto") == 0) {
        if (bold || italic) {
            if (!resolved_medium_font) {
                fs_set_error(ctx, "No resolved medium font when selecting the bold/italic font");
                return false;
            }
            family = resolved_medium_font->base->family ? resolved_medium_font->base->family : "";
            if (font_is_variable(ctx, resolved_medium_font)) {
                *ans = find_bold_italic_variant(ctx, resolved_medium_font, bold, italic, fav);
                return true;
            }
        } else family = "monospace";
    }
    return find_best_match(ctx, family, bold, italic, true, ignore_face, false, ans);
}

#ifndef __APPLE__
static void
apply_synthetic_matrix(FSContext *ctx, FSFont *font, bool bold, bool italic) {
    // fontconfig's FcFontList omits FC_MATRIX from its object set, so a roman
    // font found there carries no synthetic-italic shear and its "italic"
    // renders upright. For an italic slot whose chosen face is upright (no
    // slant) and has no matrix yet, ask fc_match what fontconfig would do.
    // fc_match returns a synthetic matrix only when there is no real italic
    // to use, so a font that is already italic is never double-slanted.
    if (!italic || font->has_matrix || font->base->has_matrix || font->base->slant != 0) return;
    const FSCandidate *m = fc_match(ctx, font->base->family ? font->base->family : "", bold, italic, is_monospace(font) ? FC_MONO : -1);
    if (m && m->has_matrix) {
        font->has_matrix = true;
        memcpy(font->matrix, m->matrix, sizeof(font->matrix));
    }
}
#endif

static bool
get_font_files(FSContext *ctx) {
    bool match_is_more_specific_than_family = false;
    FamilyAxisValues fav = {0};
    FSFont medium;
    if (!get_font_from_spec(ctx, &ctx->specs[0], false, false, &fav, NULL, NULL, &match_is_more_specific_than_family, &medium)) return false;
    const bool medium_font_is_variable = font_is_variable(ctx, &medium);
    if (!match_is_more_specific_than_family && medium_font_is_variable) medium = find_medium_variant(ctx, medium);
    if (medium_font_is_variable) {
        AxisMap av;
        get_axis_values(&medium, variable_data(ctx, medium.base), &av);
        set_regular_values(&fav, &av);
    }
    ctx->results[0] = medium;
    // In the Python implementation the medium font was compared to candidates
    // after its features were added, so it never compared equal to them.
    const FSFont *ignore_face = (is_empty(ctx->specs[0].system) && ctx->specs[0].has_features) ? NULL : &medium;
    static const bool styles[3][2] = {{true, false}, {false, true}, {true, true}};
    for (size_t i = 0; i < 3; i++) {
        const bool bold = styles[i][0], italic = styles[i][1];
        bool unused = false;
        FSFont font;
        if (!get_font_from_spec(ctx, &ctx->specs[i + 1], bold, italic, &fav, &medium, ignore_face, &unused, &font)) return false;
        // Set family axis values based on the values in font
        if (!(bold && italic) && font_is_variable(ctx, &medium)) {
            AxisMap av;
            get_axis_values(&font, variable_data(ctx, font.base), &av);
            if (italic) set_italic_values(&fav, &av);
            else set_bold_values(&fav, &av);
        }
        ctx->results[i + 1] = font;
    }
#ifndef __APPLE__
    apply_synthetic_matrix(ctx, &ctx->results[2], false, true);
    apply_synthetic_matrix(ctx, &ctx->results[3], true, true);
#endif
    return true;
}

static bool
select_symbol_fonts(FSContext *ctx) {
    if (!ctx->num_symbol_families) return true;
    ctx->symbols = xcalloc(ctx->num_symbol_families, sizeof(FSFont));
    ctx->symbol_bold = xcalloc(ctx->num_symbol_families, sizeof(bool));
    ctx->symbol_italic = xcalloc(ctx->num_symbol_families, sizeof(bool));
    for (size_t i = 0; i < ctx->num_symbol_families; i++) {
        FSFont *f = ctx->symbols + i;
        if (!find_best_match(ctx, ctx->symbol_families[i], false, false, false, NULL, false, f)) return false;
#ifdef __APPLE__
        ctx->symbol_bold[i] = f->base->bold;
        ctx->symbol_italic[i] = f->base->italic;
#else
        ctx->symbol_bold[i] = f->base->weight >= FC_WEIGHT_SEMIBOLD;
        ctx->symbol_italic[i] = f->base->slant != FC_SLANT_ROMAN;
#endif
    }
    return true;
}

static void
run_selection(FSContext *ctx) {
    if (!fs_backend_init(ctx)) {
        fs_set_error(ctx, "Failed to initialize the font database");
        return;
    }
    if (get_font_files(ctx)) select_symbol_fonts(ctx);
    if (ctx->nerd_font.path) fs_backend_prepare_builtin_nerd_font(ctx, &ctx->nerd_font);
}
// }}}

// Python interface {{{
PyObject *fs_backend_descriptor(const FSFont *f);
// Make the prepared builtin nerd font the one used for fallback and return its descriptor, runs in the main thread
PyObject *fs_backend_install_builtin_nerd_font(const FSBuiltinNerdFont *nf);

static struct {
    FSContext *ctx;
    pthread_t thread;
    bool thread_running;
    monotonic_t started_at, finished_at;
} pending = {0};

static void *
selection_thread(void *x) {
    set_thread_name("KittyFontSelect");
    pending.started_at = monotonic_clock_now();
    run_selection((FSContext *)x);
    pending.finished_at = monotonic_clock_now();
    return NULL;
}

static void
wait_for_thread(void) {
    if (!pending.thread_running) return;
    const monotonic_t start = monotonic();
    int ret = pthread_join(pending.thread, NULL);
    pending.thread_running = false;
    if (ret != 0) fatal("Failed to join the font selection thread with error: %s", strerror(ret));
    debug_rendering("Waited %.2f ms for the font selection thread to finish\n", monotonic_t_to_s_double(monotonic() - start) * 1000);
    startup_timing_thread("Font selection", pending.started_at, pending.finished_at);
    startup_timing("Font selection finished, waited %.2f ms for it", monotonic_t_to_s_double(monotonic() - start) * 1000);
}

void
fs_wait_for_selection_thread(void) {
    wait_for_thread();
}

void
fs_finalize_selection(void) {
    wait_for_thread();
    free_context(pending.ctx);
    pending.ctx = NULL;
}

static char *
optional_string(PyObject *x, bool *is_set) {
    if (is_set) *is_set = x != Py_None;
    if (x == Py_None) return NULL;
    const char *s = PyUnicode_AsUTF8(x);
    return s ? xstrdup(s) : NULL;
}

static bool
parse_spec(PyObject *src, FSFontSpec *spec) {
    PyObject *family, *style, *postscript_name, *full_name, *system, *variable_name, *axes;
    int has_features = 0;
    if (!PyArg_ParseTuple(src, "OOOOOOO!p", &family, &style, &postscript_name, &full_name, &system, &variable_name, &PyTuple_Type, &axes, &has_features))
        return false;
    spec->has_features = has_features;
#define S(x)                                                                                              \
    if (x != Py_None && !PyUnicode_Check(x)) {                                                            \
        PyErr_SetString(PyExc_TypeError, "The font specification field " #x " must be a string or None"); \
        return false;                                                                                     \
    }                                                                                                     \
    spec->x = optional_string(x, NULL);                                                                   \
    if (PyErr_Occurred()) return false;
    S(family);
    S(style);
    S(postscript_name);
    S(full_name);
    S(system);
    S(variable_name);
#undef S
    spec->has_variable_name = variable_name != Py_None;
    spec->num_axes = PyTuple_GET_SIZE(axes);
    spec->axes = xcalloc(spec->num_axes, sizeof(spec->axes[0]));
    for (size_t i = 0; i < spec->num_axes; i++) {
        const char *name;
        double value;
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(axes, i), "sd", &name, &value)) return false;
        spec->axes[i].name = xstrdup(name);
        spec->axes[i].value = value;
    }
    return true;
}

static PyObject *
start_font_selection(PyObject *self UNUSED, PyObject *args) {
    PyObject *specs, *families;
    int threaded = 1;
    const char *builtin_nerd_font_path = NULL;
    if (!PyArg_ParseTuple(args, "O!O!|pz", &PyTuple_Type, &specs, &PyTuple_Type, &families, &threaded, &builtin_nerd_font_path)) return NULL;
    if (PyTuple_GET_SIZE(specs) != 4) {
        PyErr_SetString(PyExc_ValueError, "Must specify exactly four font specifications");
        return NULL;
    }
    // discard any previous selection
    fs_finalize_selection();
    FSContext *ctx = xcalloc(1, sizeof(FSContext));
    for (size_t i = 0; i < 4; i++) {
        PyObject *s = PyTuple_GET_ITEM(specs, i);
        if (!PyTuple_Check(s)) {
            PyErr_SetString(PyExc_TypeError, "Font specifications must be tuples");
            free_context(ctx);
            return NULL;
        }
        if (!parse_spec(s, ctx->specs + i)) {
            free_context(ctx);
            return NULL;
        }
    }
    ctx->num_symbol_families = PyTuple_GET_SIZE(families);
    ctx->symbol_families = xcalloc(ctx->num_symbol_families, sizeof(char *));
    for (size_t i = 0; i < ctx->num_symbol_families; i++) {
        PyObject *f = PyTuple_GET_ITEM(families, i);
        const char *s = PyUnicode_Check(f) ? PyUnicode_AsUTF8(f) : NULL;
        if (!s) {
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_TypeError, "Symbol map font families must be strings");
            free_context(ctx);
            return NULL;
        }
        ctx->symbol_families[i] = xstrdup(s);
    }
    if (builtin_nerd_font_path && builtin_nerd_font_path[0]) ctx->nerd_font.path = xstrdup(builtin_nerd_font_path);
    pending.ctx = ctx;
    if (threaded) {
        int ret = pthread_create(&pending.thread, NULL, selection_thread, ctx);
        if (ret == 0) {
            pending.thread_running = true;
            Py_RETURN_NONE;
        }
        log_error("Failed to start thread to select fonts, selecting synchronously, with error: %s", strerror(ret));
    }
    run_selection(ctx);
    Py_RETURN_NONE;
}

static PyObject *
selection_result(const FSContext *ctx) {
    if (ctx->error) {
        PyErr_Format(PyExc_ValueError, "Failed to select fonts: %s", ctx->error);
        return NULL;
    }
    RAII_PyObject(symbols, PyTuple_New(ctx->num_symbol_families));
    if (!symbols) return NULL;
    for (size_t i = 0; i < ctx->num_symbol_families; i++) {
        RAII_PyObject(d, fs_backend_descriptor(ctx->symbols + i));
        if (!d) return NULL;
        PyObject *t = Py_BuildValue("OOO", d, ctx->symbol_bold[i] ? Py_True : Py_False, ctx->symbol_italic[i] ? Py_True : Py_False);
        if (!t) return NULL;
        PyTuple_SET_ITEM(symbols, i, t);
    }
    RAII_PyObject(medium, fs_backend_descriptor(ctx->results + 0));
    if (!medium) return NULL;
    RAII_PyObject(bold, fs_backend_descriptor(ctx->results + 1));
    if (!bold) return NULL;
    RAII_PyObject(italic, fs_backend_descriptor(ctx->results + 2));
    if (!italic) return NULL;
    RAII_PyObject(bi, fs_backend_descriptor(ctx->results + 3));
    if (!bi) return NULL;
    RAII_PyObject(nerd_font, ctx->nerd_font.prepared ? fs_backend_install_builtin_nerd_font(&ctx->nerd_font) : Py_NewRef(Py_None));
    if (!nerd_font) return NULL;
    return Py_BuildValue("{sO sO sO sO sO sO}", "medium", medium, "bold", bold, "italic", italic, "bi", bi, "symbols", symbols, "builtin_nerd_font", nerd_font);
}

static PyObject *
finish_font_selection(PyObject *self UNUSED, PyObject *args UNUSED) {
    if (!pending.ctx) {
        PyErr_SetString(PyExc_RuntimeError, "No font selection is in progress");
        return NULL;
    }
    wait_for_thread();
    FSContext *ctx = pending.ctx;
    pending.ctx = NULL;
    for (size_t i = 0; i < ctx->num_messages; i++) log_error("%s", ctx->messages[i]);
    PyObject *ans = selection_result(ctx);
    free_context(ctx);
    return ans;
}

static PyObject *
axis_values_to_python(const FSAxisValue *values, size_t count) {
    RAII_PyObject(ans, PyDict_New());
    if (!ans) return NULL;
    for (size_t i = 0; i < count; i++) {
        char tag[5];
        tag_to_str(values[i].tag, tag);
        RAII_PyObject(v, PyFloat_FromDouble(values[i].value));
        if (!v || PyDict_SetItemString(ans, tag, v) != 0) return NULL;
    }
    Py_INCREF(ans);
    return ans;
}

static PyObject *
variable_data_to_python(const FSVariableData *vd) {
    RAII_PyObject(axes, PyTuple_New(vd->num_axes));
    RAII_PyObject(named_styles, PyTuple_New(vd->num_named_styles));
    RAII_PyObject(design_axes, PyTuple_New(vd->num_design_axes));
    if (!axes || !named_styles || !design_axes) return NULL;
    char tag[5];
    for (size_t i = 0; i < vd->num_axes; i++) {
        const FSVarAxis *a = vd->axes + i;
        tag_to_str(a->tag, tag);
        PyObject *x = Py_BuildValue(
            "{sd sd sd sO ss ss}",
            "minimum",
            a->minimum,
            "maximum",
            a->maximum,
            "default",
            a->def,
            "hidden",
            a->hidden ? Py_True : Py_False,
            "tag",
            tag,
            "strid",
            a->strid);
        if (!x) return NULL;
        PyTuple_SET_ITEM(axes, i, x);
    }
    for (size_t i = 0; i < vd->num_named_styles; i++) {
        const FSNamedStyle *ns = vd->named_styles + i;
        PyObject *x = Py_BuildValue("{sN ss ss}", "axis_values", axis_values_to_python(ns->values, ns->num_values), "name", ns->name, "psname", ns->psname);
        if (!x) return NULL;
        PyTuple_SET_ITEM(named_styles, i, x);
    }
    for (size_t i = 0; i < vd->num_design_axes; i++) {
        const FSDesignAxis *da = vd->design_axes + i;
        RAII_PyObject(values, PyList_New(da->num_values));
        if (!values) return NULL;
        for (size_t j = 0; j < da->num_values; j++) {
            const FSDesignValue *v = da->values + j;
            PyObject *x = NULL;
            switch (v->format) {
                case 1: x = Py_BuildValue("{sI sI ss sd}", "format", v->format, "flags", v->flags, "name", v->name, "value", v->value); break;
                case 2:
                    x = Py_BuildValue(
                        "{sI sI ss sd sd sd}",
                        "format",
                        v->format,
                        "flags",
                        v->flags,
                        "name",
                        v->name,
                        "value",
                        v->value,
                        "minimum",
                        v->minimum,
                        "maximum",
                        v->maximum);
                    break;
                default:
                    x = Py_BuildValue(
                        "{sI sI ss sd sd}", "format", v->format, "flags", v->flags, "name", v->name, "value", v->value, "linked_value", v->linked_value);
                    break;
            }
            if (!x) return NULL;
            PyList_SET_ITEM(values, j, x);
        }
        tag_to_str(da->tag, tag);
        PyObject *x = Py_BuildValue("{ss ss sI sO}", "tag", tag, "name", da->name, "ordering", da->ordering, "values", values);
        if (!x) return NULL;
        PyTuple_SET_ITEM(design_axes, i, x);
    }
    return Py_BuildValue(
        "{sO sO sO ss ss}",
        "axes",
        axes,
        "named_styles",
        named_styles,
        "design_axes",
        design_axes,
        "variations_postscript_name_prefix",
        vd->variations_postscript_name_prefix,
        "elided_fallback_name",
        vd->elided_fallback_name);
}

static PyObject *
variable_data_from_font_file(PyObject *self UNUSED, PyObject *args) {
    const char *path;
    int index = 0;
    if (!PyArg_ParseTuple(args, "s|i", &path, &index)) return NULL;
    FSFontTables t = {0};
    if (!fs_read_font_tables_from_file(path, index, &t)) {
        PyErr_SetFromErrnoWithFilename(PyExc_OSError, path);
        return NULL;
    }
    FSVariableData vd;
    fs_variable_data_from_tables(&t, &vd);
    fs_free_font_tables(&t);
    PyObject *ans = variable_data_to_python(&vd);
    fs_free_variable_data(&vd);
    return ans;
}

static PyMethodDef module_methods[] = {
    METHODB(start_font_selection, METH_VARARGS),
    METHODB(finish_font_selection, METH_NOARGS),
    METHODB(variable_data_from_font_file, METH_VARARGS),
    {NULL, NULL, 0, NULL} /* Sentinel */
};

bool
init_font_select(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
