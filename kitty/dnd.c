/*
 * dnd.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "dnd.h"
#include "base64.h"
#include "control-codes.h"
#include "iqsort.h"

static void
drop_free_offered_mimes(Window *w) {
    if (w->drop.offerred_mimes) {
        for (size_t i = 0; i < w->drop.num_offerred_mimes; i++) free((void*)w->drop.offerred_mimes[i]);
        free(w->drop.offerred_mimes); w->drop.offerred_mimes = NULL;
    }
    w->drop.num_offerred_mimes = 0;
    w->drop.offered_mimes_total_size = 0;
}

static void
drop_free_accepted_mimes(Window *w) {
    free(w->drop.accepted_mimes); w->drop.accepted_mimes = NULL;
    w->drop.accepted_mimes_sz = 0;
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
    drop_free_accepted_mimes(w);
    free_pending(&w->drop.pending);
    free(w->drop.registered_mimes); w->drop.registered_mimes = NULL;
    free(w->drop.uri_list); w->drop.uri_list = NULL;
    free(w->drop.getting_data_for_mime); w->drop.getting_data_for_mime = NULL;
}

static void
reset_drop(Window *w) {
    bool wanted = w->drop.wanted; uint32_t cid = w->drop.client_id;
    drop_free_data(w);
    zero_at_ptr(&w->drop);
    if (wanted) {
        w->drop.wanted = wanted;
        w->drop.client_id = cid;
    }
}

void
drop_register_window(Window *w, const uint8_t *payload, size_t payload_sz, bool on, uint32_t client_id, bool more) {
    w->drop.wanted = on;
    w->drop.client_id = client_id;
    if (!on) { drop_free_data(w); zero_at_ptr(&w->drop); return; }
    if (!payload || !payload_sz) return;
    size_t sz = w->drop.registered_mimes ? strlen(w->drop.registered_mimes) : 0;
    if (sz + payload_sz > 1024 * 1024) return;
    w->drop.registered_mimes = realloc(w->drop.registered_mimes, sz + payload_sz + 1);
    if (w->drop.registered_mimes) {
        memcpy(w->drop.registered_mimes + sz, payload, payload_sz);
        sz += payload_sz;
        w->drop.registered_mimes[sz] = 0;
    }
    if (more) return;
    if (w->drop.registered_mimes) {
        OSWindow *osw = os_window_for_kitty_window(w->id);
        if (osw) {
            size_t num = 0;
            RAII_ALLOC(const char*, mimes, malloc(sizeof(char*) * strlen(w->drop.registered_mimes)));
            if (mimes) {
                char* token = strtok(w->drop.registered_mimes, " ");
                while (token != NULL) {
                    mimes[num++] = token;
                    token = strtok(NULL, " ");
                }
                register_mimes_for_drop(osw, mimes, num);
            }
        }
    }
    free(w->drop.registered_mimes); w->drop.registered_mimes = NULL;
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
send_payload_to_child(id_type id, uint32_t client_id, const char *header, size_t header_sz, const char *data, const size_t data_sz, bool as_base64) {
    size_t offset = 0;
    char buf[4096 + 1024];
    memcpy(buf, header, header_sz);
    if (client_id) header_sz += snprintf(buf + header_sz, sizeof(buf) - header_sz, ":i=%u", (unsigned)client_id);
    if (!data_sz) {
        buf[header_sz++] = 0x1b; buf[header_sz++] = '\\';
        bool found, too_much_data;
        schedule_write_to_child_if_possible(id, buf, header_sz, &found, &too_much_data);
        if (too_much_data) return 0;
        return 1;
    }
    buf[header_sz++] = ':'; buf[header_sz++] = 'm'; buf[header_sz++] = '=';
    const size_t limit = as_base64 ? 3072 : 4096;
    while (offset < data_sz) {
        size_t chunk = data_sz - offset;
        if (chunk > limit) chunk = limit;
        size_t p = header_sz;
        const bool is_last = offset + chunk >= data_sz;
        buf[p++] = is_last ? '0' : '1'; buf[p++] = ';';
        if (as_base64) {
            size_t b64_len = sizeof(buf) - p;
            base64_encode8((const uint8_t*)data + offset, chunk, (uint8_t*)buf + p, &b64_len, false);
            p += b64_len;
        } else {
            memcpy(buf + p, data + offset, chunk);
            p += chunk;
        }
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
        size_t written = send_payload_to_child(id, e->client_id, e->buf, e->header_sz, e->buf + e->header_sz, e->data_sz, e->as_base64);
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
    return pending->count == 0;
}

#define check_for_pending_writes() \
    add_main_loop_timer(ms_to_monotonic_t(20), false, flush_pending_payloads, (void*)(uintptr_t)id, NULL)

static void
flush_pending_payloads(id_type timer_id UNUSED, void *x) {
    id_type id = (uintptr_t)x;
    Window *w = window_for_window_id(id);
    if (w && w->drop.wanted) {
        if (!flush_pending(w->id, &w->drop.pending)) check_for_pending_writes();
    }
}

static void
queue_payload_to_child(id_type id, uint32_t client_id, PendingData *pending, const char *header, size_t header_sz, const char *data, size_t data_sz, bool as_base64) {
    size_t offset = 0;
    if (flush_pending(id, pending)) offset = send_payload_to_child(id, client_id, header, header_sz, data, data_sz, as_base64);
    if (offset < data_sz || (!offset && !data_sz)) {
        ensure_space_for(pending, items, PendingEntry, pending->count + 1, capacity, 32, true);
        char *buf = malloc(header_sz + data_sz - offset);
        if (!buf) fatal("Out of memory");
        memcpy(buf, header, header_sz); memcpy(buf + header_sz, data, data_sz - offset);
        PendingEntry *e = &pending->items[pending->count++];
        e->buf = buf; e->header_sz = header_sz; e->data_sz = data_sz - offset;
        e->as_base64 = as_base64; e->client_id = client_id;
    }
    if (pending->count) check_for_pending_writes();
}

void
drop_move_on_child(Window *w, const char** mimes, size_t num_mimes, bool is_drop) {
    if (!w->drop.hovered) {
        reset_drop(w);
        w->drop.hovered = true;
    }
    if (is_drop) { w->drop.dropped = true; w->drop.hovered = false; }
    if (mimes && (w->drop.offerred_mimes == NULL || string_arrays_cmp(mimes, num_mimes, w->drop.offerred_mimes, w->drop.num_offerred_mimes) != 0)) {
        drop_free_offered_mimes(w);
        w->drop.offerred_mimes = malloc(num_mimes * sizeof(char*));
        if (w->drop.offerred_mimes) {
            w->drop.offered_mimes_total_size = 0;
            for (size_t i = 0; i < num_mimes; i++) {
                size_t l = strlen(mimes[i]);
                w->drop.offered_mimes_total_size += 1 + l;
                char *p = malloc(l + 1);
                if (!p) fatal("Out of memory");
                memcpy(p, mimes[i], l); p[l] = 0;
                w->drop.offerred_mimes[i] = p;
            }
        }
        w->drop.num_offerred_mimes = num_mimes;
    }
    // we simply drop this event if there is too much data being written to the child
    if (w->drop.pending.count && !is_drop) return;
    char buf[128];
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=%c:x=%u:y=%u:X=%d:Y=%d", DND_CODE,
            is_drop ? 'M' : 'm', w->mouse_pos.cell_x, w->mouse_pos.cell_y,
            (int)w->mouse_pos.global_x, (int)w->mouse_pos.global_y);
    if (w->drop.offered_mimes_total_size) {
        const size_t mimes_total_size = 1 + w->drop.offered_mimes_total_size;
        RAII_ALLOC(char, mbuf, malloc(mimes_total_size));
        if (mbuf) {
            size_t pos = 0;
            for (size_t i = 0; i < w->drop.num_offerred_mimes && pos < mimes_total_size; i++) {
                int n = snprintf(mbuf + pos, mimes_total_size - pos, "%s ", w->drop.offerred_mimes[i]);
                if (n < 0) break;
                pos += n;
            }
            queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, mbuf, pos, false);
        }
    } else {
        buf[header_size++] = 0x1b; buf[header_size++] = '\\';
        queue_payload_to_child(w->id, w->drop.client_id,  &w->drop.pending, buf, header_size, NULL, 0, false);
    }
}

void
drop_set_status(Window *w, int operation, const char *payload, size_t payload_sz, bool more) {
    if (!w->drop.accept_in_progress) {
        drop_free_accepted_mimes(w); w->drop.accept_in_progress = true; w->drop.accepted_operation = 0;
        switch(operation) {
            case 1: case 2: w->drop.accepted_operation = operation; break;
            default: w->drop.accepted_operation = 0; break;
        }
    }
    if (payload_sz) {
        w->drop.accepted_mimes = realloc(w->drop.accepted_mimes, w->drop.accepted_mimes_sz + payload_sz + 2);
        if (w->drop.accepted_mimes) {
            memcpy(w->drop.accepted_mimes + w->drop.accepted_mimes_sz, payload, payload_sz);
            w->drop.accepted_mimes_sz += payload_sz;
        }
    }
    if (!more) {
        w->drop.accept_in_progress = false;
        if (w->drop.accepted_mimes) {
            for (size_t i = 0; i < w->drop.accepted_mimes_sz; i++)
                if (w->drop.accepted_mimes[i] == ' ') w->drop.accepted_mimes[i] = 0;
            w->drop.accepted_mimes[w->drop.accepted_mimes_sz++] = 0;
        }
        OSWindow *osw = os_window_for_kitty_window(w->id);
        if (osw) request_drop_status_update(osw);
    }
}

void
drop_finish(Window *w) {
    OSWindow *osw = os_window_for_kitty_window(w->id);
    if (osw && osw->handle) {
        int op = GLFW_DRAG_OPERATION_GENERIC;
        if (w->drop.accepted_operation == 1) op = GLFW_DRAG_OPERATION_COPY;
        else if (w->drop.accepted_operation == 2) op = GLFW_DRAG_OPERATION_MOVE;
        glfwEndDrop(osw->handle, op);
    }
}

size_t
drop_update_mimes(Window *w, const char **allowed_mimes, size_t allowed_mimes_count) {
    if (w->drop.accept_in_progress) return allowed_mimes_count;
    if (!w->drop.accepted_operation) return 0;
    typedef struct mime_sorter { const char *m; ssize_t key; } mime_sorter;
    if (!w->drop.accepted_mimes) return allowed_mimes_count;
    RAII_ALLOC(mime_sorter, ms, malloc(sizeof(mime_sorter) * allowed_mimes_count));
    if (!ms) return allowed_mimes_count;
    const ssize_t sentinel = allowed_mimes_count;
    for (size_t i = 0; i < allowed_mimes_count; i++) {
        ms[i].m = allowed_mimes[i];
        const char *p = strstr(w->drop.accepted_mimes, ms[i].m);
        ms[i].key = p ? p - w->drop.accepted_mimes : sentinel;
    }
#define mimes_lt(a, b) ((a)->key < (b)->key)
    QSORT(mime_sorter, ms, allowed_mimes_count, mimes_lt);
#undef mimes_lt
    while(allowed_mimes_count && ms[allowed_mimes_count-1].key == sentinel) allowed_mimes_count--;
    for (size_t i = 0; i < allowed_mimes_count; i++) allowed_mimes[i] = ms[i].m;
    return allowed_mimes_count;
}

static const char*
get_errno_name(int err) {
    switch (err) {
        case EPERM: return "EPERM";
        case ENOENT: return "ENOENT";
        case EIO: return "EIO";
        default: return "EUNKNOWN";
    }
}

static void
drop_send_error(Window *w, int error_code) {
    char buf[128];
    const char *e = get_errno_name(error_code);
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=R", DND_CODE);
    queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, e, strlen(e), false);
}

void
drop_request_data(Window *w, const char *mime) {
    if (w->drop.getting_data_for_mime) { free(w->drop.getting_data_for_mime); w->drop.getting_data_for_mime = NULL; }
    OSWindow *osw = os_window_for_kitty_window(w->id);
    if (!osw) return;
    if (w->drop.offerred_mimes) {
        for (size_t i = 0; i < w->drop.num_offerred_mimes; i++) {
            if (strcmp(mime, w->drop.offerred_mimes[i]) == 0) {
                w->drop.getting_data_for_mime = strdup(mime);
                if (w->drop.getting_data_for_mime) request_drop_data(osw, w->id, mime);
                return;
            }
        }
    }
    drop_send_error(w, ENOENT);
}

void
drop_dispatch_data(Window *w, const char *mime, const char *data, ssize_t sz) {
    if (sz < 0) drop_send_error(w, -sz);
    else {
        char buf[128];
        int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=r", DND_CODE);
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, sz ? data : NULL, sz, true);
        if (strcmp(mime, "text/uri-list") == 0) {
            w->drop.uri_list_sz += sz;
            w->drop.uri_list = realloc(w->drop.uri_list, w->drop.uri_list_sz);
            if (w->drop.uri_list) memcpy(w->drop.uri_list + w->drop.uri_list_sz - sz, data, sz);
            else w->drop.uri_list_sz = 0;
        }
    }
}

void
drop_left_child(Window *w) {
    w->drop.hovered = false;
    w->drop.dropped = false;
    drop_free_offered_mimes(w);
    if (w->drop.wanted) {
        char buf[128];
        int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=m:x=-1:y=-1", DND_CODE);
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, NULL, 0, false);
    }
}
