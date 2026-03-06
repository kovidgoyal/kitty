/*
 * dnd.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "dnd.h"
#include "base64.h"
#include "control-codes.h"

static void
drop_free_offered_mimes(Window *w) {
    if (w->drop.offerred_mimes) {
        for (size_t i = 0; i < w->drop.num_offerred_mimes; i++) free((void*)w->drop.offerred_mimes[i]);
        free(w->drop.offerred_mimes); w->drop.offerred_mimes = NULL;
    }
    w->drop.num_offerred_mimes = 0;
}

static void
free_pending(PendingData *pending) {
    if (pending->items) {
        for (size_t i = 0; i < pending->count; i++) free(pending->items[i].buf);
        free(pending->items);
    }
    zero_at_ptr(pending);
}

void
drop_free_data(Window *w) {
    drop_free_offered_mimes(w);
    free_pending(&w->drop.pending);
}

static int
string_arrays_cmp(const char **a, size_t an, const char **b, size_t bn) {
    if (an != bn) return (int)an - (int)bn;
    for (size_t i = 0; i < an; i++) {
        int ret = strcmp(a[i], b[i]);
        if (ret != 0) return ret;
    }
    return 0;
}

static size_t
send_payload_to_child(id_type id, const char *header, size_t header_sz, const char *data, const size_t data_sz) {
    size_t offset = 0;
    char buf[4096 + 1024];
    memcpy(buf, header, header_sz);
    buf[header_sz++] = ':'; buf[header_sz++] = 'm'; buf[header_sz++] = '=';
    if (!data_sz) {
        buf[header_sz++] = 0x1b; buf[header_sz++] = '\\';
        bool found, too_much_data;
        schedule_write_to_child_if_possible(id, buf, header_sz, &found, &too_much_data);
        if (too_much_data) return 0;
        return 1;
    }
    while (offset < data_sz) {
        size_t chunk = data_sz - offset;
        size_t p = header_sz;
        buf[p++] = offset + 3072 >= data_sz ? '0' : '1';
        buf[p++] = ';';
        size_t b64_len = sizeof(buf) - p;
        base64_encode8((const uint8_t*)data + offset, chunk, (uint8_t*)buf + p, &b64_len, false);
        p += b64_len;
        buf[p++] = 0x1b; buf[p++] = '\\';
        bool found, too_much_data;
        schedule_write_to_child_if_possible(id, buf, p, &found, &too_much_data);
        if (too_much_data) break;
        if (!found) return data_sz;
        offset += chunk;
    }
    return offset;
}

static bool
flush_pending(id_type id, PendingData *pending) {
    while (pending->count) {
        PendingEntry *e = pending->items;
        size_t written = send_payload_to_child(id, e->buf, e->header_sz, e->buf + e->header_sz, e->data_sz);
        if (written < e->data_sz) {
            if (written) {
                e->data_sz -= written;
                memmove(e->buf + e->header_sz, e->buf + e->header_sz + written, e->data_sz);
            }
            break;
        } else {
            if (!e->data_sz && !written) break;
            free(e->buf); zero_at_ptr(e);
            remove_i_from_array(pending->items, 0, pending->count);
        }
    }
    return pending->count > 0;
}

static void
queue_payload_to_child(id_type id, PendingData *pending, const char *header, size_t header_sz, const char *data, size_t data_sz) {
    size_t offset = 0;
    if (flush_pending(id, pending)) offset = send_payload_to_child(id, header, header_sz, data, data_sz);
    if (offset < data_sz || (!offset && !data_sz)) {
        ensure_space_for(pending, items, PendingEntry, pending->count + 1, capacity, 32, true);
        char *buf = malloc(header_sz + data_sz - offset);
        if (!buf) fatal("Out of memory");
        memcpy(buf, header, header_sz); memcpy(buf + header_sz, data, data_sz - offset);
        PendingEntry *e = &pending->items[pending->count++];
        e->buf = buf; e->header_sz = header_sz; e->data_sz = data_sz - offset;
    }
}

void
drop_move_on_child(Window *w, const char** mimes, size_t num_mimes) {
    if (!w->drop.hovered) {
        drop_free_offered_mimes(w);
        w->drop.hovered = true;
    }
    size_t mimes_total_size = 0;
    if (mimes && (w->drop.offerred_mimes == NULL || string_arrays_cmp(mimes, num_mimes, w->drop.offerred_mimes, w->drop.num_offerred_mimes) != 0)) {
        drop_free_offered_mimes(w);
        w->drop.offerred_mimes = malloc(num_mimes * sizeof(char*));
        if (w->drop.offerred_mimes) {
            for (size_t i = 0; i < num_mimes; i++) {
                size_t l = strlen(mimes[i]);
                mimes_total_size += 1 + l;
                char *p = malloc(l + 1);
                if (!p) fatal("Out of memory");
                memcpy(p, mimes[i], l); p[l] = 0;
                w->drop.offerred_mimes[i] = p;
            }
        }
        w->drop.num_offerred_mimes = num_mimes;
    }
    // we simply drop this event if there is too much data being written to the child
    if (w->drop.pending.count) return;
    char buf[128];
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;i=%u:t=m:x=%u:y=%u:X=%d:Y=%d", DND_CODE, w->drop.client_id,
            w->mouse_pos.cell_x, w->mouse_pos.cell_y, (int)w->mouse_pos.global_x, (int)w->mouse_pos.global_y);
    if (mimes_total_size) {
        mimes_total_size += 1;
        RAII_ALLOC(char, mbuf, malloc(mimes_total_size));
        if (mbuf) {
            size_t pos = 0;
            for (size_t i = 0; i < w->drop.num_offerred_mimes && pos < mimes_total_size; i++) {
                int n = snprintf(mbuf, mimes_total_size - pos, mbuf + pos, "%s ", w->drop.offerred_mimes[i]);
                if (n < 0) break;
                pos += n;
            }
            queue_payload_to_child(w->id, &w->drop.pending, buf, header_size, mbuf, pos);
        }
    } else {
        buf[header_size++] = 0x1b; buf[header_size++] = '\\';
        bool found, too_much_data;
        schedule_write_to_child_if_possible(w->id, buf, header_size, &found, &too_much_data);
    }
}

void
drop_left_child(Window *w) {
    w->drop.hovered = false;
    drop_free_offered_mimes(w);
    if (w->drop.allowed) {
        char buf[128];
        int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;i=%u:t=m:x=-1:y=-1", DND_CODE, w->drop.client_id);
        queue_payload_to_child(w->id, &w->drop.pending, buf, header_size, NULL, 0);
    }
}
