/*
 * dnd.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "dnd.h"
#include "base64.h"
#include "control-codes.h"
#include "safe-wrappers.h"
#include "iqsort.h"
#include "png-reader.h"
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

static const size_t MIME_LIST_SIZE_CAP = 1024 * 1024;
static const size_t PRESENT_DATA_CAP = 64 * 1024 * 1024;

// In test mode, this callable is invoked instead of schedule_write_to_child_if_possible.
// It receives (window_id: int, data: bytes) and its return value is ignored.
static PyObject *g_dnd_test_write_func = NULL;

void
dnd_set_test_write_func(PyObject *func) {
    Py_XDECREF(g_dnd_test_write_func);
    g_dnd_test_write_func = Py_XNewRef(func);
}

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

static void
drop_free_dir_handle(DirHandle *h) {
    free(h->path);
    for (size_t i = 0; i < h->num_entries; i++) free(h->entries[i]);
    free(h->entries);
    zero_at_ptr(h);
}

static void
drop_free_dir_handles(Window *w) {
    for (size_t i = 0; i < w->drop.num_dir_handles; i++)
        drop_free_dir_handle(&w->drop.dir_handles[i]);
    free(w->drop.dir_handles);
    w->drop.dir_handles = NULL;
    w->drop.num_dir_handles = 0;
    w->drop.dir_handles_capacity = 0;
    w->drop.next_dir_handle_id = 0;
}

static void
drop_close_file_fd(Window *w) {
    if (w->drop.file_fd_plus_one) {
        safe_close(w->drop.file_fd_plus_one - 1, __FILE__, __LINE__);
        w->drop.file_fd_plus_one = 0;
    }
    if (w->drop.file_send_timer) {
        remove_main_loop_timer(w->drop.file_send_timer);
        w->drop.file_send_timer = 0;
    }
}

void
drop_free_data(Window *w) {
    drop_close_file_fd(w);
    drop_free_offered_mimes(w);
    drop_free_accepted_mimes(w);
    free_pending(&w->drop.pending);
    free(w->drop.registered_mimes); w->drop.registered_mimes = NULL;
    free(w->drop.uri_list); w->drop.uri_list = NULL;
    free(w->drop.getting_data_for_mime); w->drop.getting_data_for_mime = NULL;
    drop_free_dir_handles(w);
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
    if (sz + payload_sz > MIME_LIST_SIZE_CAP) return;
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

static bool
test_write_chunk(id_type id, const char *buf, size_t sz) {
    // In test mode, deliver the chunk to the registered Python callable.
    // Returns true when the test interceptor consumed the data (no real write needed).
    if (!g_dnd_test_write_func) return false;
    RAII_PyObject(ret, PyObject_CallFunction(g_dnd_test_write_func, "Ky#", (unsigned long long)id, buf, (Py_ssize_t)sz));
    if (!ret) PyErr_Print();
    return true;
}

static size_t
send_payload_to_child(id_type id, uint32_t client_id, const char *header, size_t header_sz, const char *data, const size_t data_sz, bool as_base64) {
    size_t offset = 0;
    char buf[4096 + 1024];
    memcpy(buf, header, header_sz);
    if (client_id) header_sz += snprintf(buf + header_sz, sizeof(buf) - header_sz, ":i=%u", (unsigned)client_id);
    if (!data_sz) {
        buf[header_sz++] = 0x1b; buf[header_sz++] = '\\';
        if (!test_write_chunk(id, buf, header_sz)) {
            bool found, too_much_data;
            schedule_write_to_child_if_possible(id, buf, header_sz, &found, &too_much_data);
            if (too_much_data) return 0;
        }
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
        if (!test_write_chunk(id, buf, p)) {
            bool found, too_much_data;
            schedule_write_to_child_if_possible(id, buf, p, &found, &too_much_data);
            if (too_much_data) break;
            if (!found) return data_sz;
        }
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
        drop_free_accepted_mimes(w); w->drop.accept_in_progress = true;
        switch(operation) {
            case 1: w->drop.accepted_operation = GLFW_DRAG_OPERATION_COPY; break;
            case 2: w->drop.accepted_operation = GLFW_DRAG_OPERATION_MOVE; break;
            default: w->drop.accepted_operation = GLFW_DRAG_OPERATION_NONE; break;
        }
    }
    if (payload_sz) {
        if (w->drop.accepted_mimes_sz + payload_sz > MIME_LIST_SIZE_CAP) return;
        char *new_buf = realloc(w->drop.accepted_mimes, w->drop.accepted_mimes_sz + payload_sz + 2);
        if (!new_buf) return;
        w->drop.accepted_mimes = new_buf;
        memcpy(w->drop.accepted_mimes + w->drop.accepted_mimes_sz, payload, payload_sz);
        w->drop.accepted_mimes_sz += payload_sz;
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
        glfwEndDrop(osw->handle, w->drop.accepted_operation);
    }
}

size_t
drop_update_mimes(Window *w, const char **allowed_mimes, size_t allowed_mimes_count) {
    if (w->drop.accept_in_progress) return allowed_mimes_count;
    if (w->drop.accepted_operation == GLFW_DRAG_OPERATION_NONE) return 0;
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
        case EINVAL: return "EINVAL";
        case ENOMEM: return "ENOMEM";
        case 0: return "OK";
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
drop_send_einval(Window *w) {
    drop_send_error(w, EINVAL);
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

// ---- Remote file / directory transfer (t=s, t=d) ----

static void
url_decode_inplace(char *str) {
    char *src = str, *dst = str;
    while (*src) {
        if (*src == '%' && src[1] && src[2]) {
            unsigned int hi = 0, lo = 0;
            char c1 = src[1], c2 = src[2];
            if (c1 >= '0' && c1 <= '9') hi = c1 - '0';
            else if (c1 >= 'a' && c1 <= 'f') hi = c1 - 'a' + 10;
            else if (c1 >= 'A' && c1 <= 'F') hi = c1 - 'A' + 10;
            else { *dst++ = *src++; continue; }
            if (c2 >= '0' && c2 <= '9') lo = c2 - '0';
            else if (c2 >= 'a' && c2 <= 'f') lo = c2 - 'a' + 10;
            else if (c2 >= 'A' && c2 <= 'F') lo = c2 - 'A' + 10;
            else { *dst++ = *src++; continue; }
            *dst++ = (char)((hi << 4) | lo);
            src += 3;
        } else {
            *dst++ = *src++;
        }
    }
    *dst = 0;
}

/* Return the nth (0-based) file path from a text/uri-list.
 * On success returns true and *path_out is a malloc'd absolute resolved path.
 * On failure returns false and *error_out points to a static error string. */
static bool
get_nth_file_url(const char *uri_list, size_t uri_list_sz, int n, char **path_out, const char **error_out) {
    *path_out = NULL;
    RAII_ALLOC(char, buf, malloc(uri_list_sz + 1));
    if (!buf) { *error_out = "ENOMEM"; return false; }
    memcpy(buf, uri_list, uri_list_sz);
    buf[uri_list_sz] = 0;

    const char *found_line = NULL;
    char *p = buf;
    while (*p) {
        char *eol = p + strcspn(p, "\r\n");
        char saved = *eol; *eol = 0;
        /* trim trailing whitespace */
        char *end = eol;
        while (end > p && (end[-1] == ' ' || end[-1] == '\t')) { end--; *end = 0; }
        if (*p && *p != '#') {
            if (n <= 0) { found_line = p; break; }
            n--;
        }
        if (saved == 0) break;
        p = eol + 1;
        while (*p == '\r' || *p == '\n') p++;
    }

    if (!found_line) { *error_out = "ENOENT"; return false; }

    /* Must be a file:// URL */
    if (strncmp(found_line, "file://", 7) != 0) { *error_out = "EUNKNOWN"; return false; }

    const char *rest = found_line + 7;
    const char *slash = strchr(rest, '/');
    if (!slash) { *error_out = "EINVAL"; return false; }

    /* Host part must be empty or "localhost" */
    size_t host_len = (size_t)(slash - rest);
    if (host_len > 0 && !(host_len == 9 && strncasecmp(rest, "localhost", 9) == 0)) {
        *error_out = "EUNKNOWN"; return false;
    }

    RAII_ALLOC(char, path, strdup(slash));
    if (!path) { *error_out = "ENOMEM"; return false; }
    /* Strip any query (?...) or fragment (#...) from the path */
    char *query_or_fragment_start = path + strcspn(path, "?#");
    *query_or_fragment_start = 0;
    url_decode_inplace(path);
    if (path[0] != '/') { *error_out = "EINVAL"; return false; }

    char resolved[PATH_MAX];
    if (!realpath(path, resolved)) {
        switch (errno) {
            case ENOENT: case ENOTDIR: *error_out = "ENOENT"; break;
            case EACCES: case EPERM:   *error_out = "EPERM"; break;
            case ELOOP:                *error_out = "ENOENT"; break;
            default:                   *error_out = "EINVAL"; break;
        }
        return false;
    }

    *path_out = strdup(resolved);
    if (!*path_out) { *error_out = "ENOMEM"; return false; }
    return true;
}

/* Send error using a literal string (for cases where we have a string, not int). */
static void
drop_send_error_str(Window *w, const char *err_name) {
    char buf[128];
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=R", DND_CODE);
    queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, err_name, strlen(err_name), false);
}

/* Size of each file read chunk; fits in one base64 sub-chunk (≤4096 chars). */
#define FILE_CHUNK_SIZE 3072
/* Abort file transfer if no data has been sent to the child for this long. */
#define FILE_SEND_TIMEOUT_SECONDS 90

static void drop_send_file_chunks(Window *w);

static void
file_send_timer_callback(id_type timer_id UNUSED, void *x) {
    id_type id = (uintptr_t)x;
    Window *w = window_for_window_id(id);
    if (!w || !w->drop.file_fd_plus_one) return;
    w->drop.file_send_timer = 0;
    if (monotonic() - w->drop.last_file_send_at > s_to_monotonic_t(FILE_SEND_TIMEOUT_SECONDS)) {
        drop_close_file_fd(w);
        drop_send_error(w, EIO);
        return;
    }
    drop_send_file_chunks(w);
}

static void
drop_send_file_chunks(Window *w) {
    if (!flush_pending(w->id, &w->drop.pending)) {
        w->drop.file_send_timer = add_main_loop_timer(ms_to_monotonic_t(20), false, file_send_timer_callback, (void*)(uintptr_t)w->id, NULL);
        return;
    }
    char hdr[128];
    int hdr_sz = snprintf(hdr, sizeof(hdr), "\x1b]%d;t=r", DND_CODE);
    while (1) {
        char buf[FILE_CHUNK_SIZE];
        ssize_t n;
        do { n = read(w->drop.file_fd_plus_one - 1, buf, sizeof(buf)); } while (n < 0 && errno == EINTR);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                /* No data available right now; retry via timer */
                w->drop.file_send_timer = add_main_loop_timer(ms_to_monotonic_t(20), false, file_send_timer_callback, (void*)(uintptr_t)w->id, NULL);
                return;
            }
            drop_close_file_fd(w);
            drop_send_error(w, EIO);
            return;
        }
        if (n == 0) {
            /* EOF: close fd and send the empty end-of-data signal */
            drop_close_file_fd(w);
            queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, NULL, 0, true);
            return;
        }
        size_t sent = send_payload_to_child(w->id, w->drop.client_id, hdr, hdr_sz, buf, (size_t)n, true);
        if (sent > 0) w->drop.last_file_send_at = monotonic();
        if (sent < (size_t)n) {
            /* Partial send: rewind file pointer and retry via timer */
            if (lseek(w->drop.file_fd_plus_one - 1, -(off_t)(((size_t)n) - sent), SEEK_CUR) < 0) {
                drop_close_file_fd(w);
                drop_send_error(w, EIO);
                return;
            }
            w->drop.file_send_timer = add_main_loop_timer(ms_to_monotonic_t(20), false, file_send_timer_callback, (void*)(uintptr_t)w->id, NULL);
            return;
        }
        /* Full chunk sent: loop and read next chunk */
    }
}

/* Open a regular file and begin sending its contents as t=r chunks followed
 * by an empty end-of-data t=r, using chunked I/O to avoid large allocations. */
static void
drop_send_file_data(Window *w, const char *path) {
    drop_close_file_fd(w);
    int fd = safe_open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK, 0);
    if (fd < 0) {
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        return;
    }
    struct stat st;
    if (fstat(fd, &st) < 0) {
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        safe_close(fd, __FILE__, __LINE__);
        return;
    }
    if (!S_ISREG(st.st_mode)) { drop_send_error(w, EINVAL); safe_close(fd, __FILE__, __LINE__); return; }
    w->drop.file_fd_plus_one = fd + 1;
    w->drop.last_file_send_at = monotonic();
    drop_send_file_chunks(w);
}

/* Allocate a new DirHandle for the given path and entries (takes ownership of
 * entries array and its strings). Returns the new handle id. */
static uint32_t
drop_alloc_dir_handle(Window *w, const char *path, char **entries, size_t num_entries) {
    ensure_space_for(&w->drop, dir_handles, DirHandle, w->drop.num_dir_handles + 1, dir_handles_capacity, 4, true);
    w->drop.next_dir_handle_id++;
    if (w->drop.next_dir_handle_id == 0) w->drop.next_dir_handle_id = 1;
    DirHandle *h = &w->drop.dir_handles[w->drop.num_dir_handles++];
    zero_at_ptr(h);
    h->id = w->drop.next_dir_handle_id;
    h->path = strdup(path);
    if (!h->path) fatal("Out of memory");
    h->entries = entries;
    h->num_entries = num_entries;
    return h->id;
}

static DirHandle *
drop_find_dir_handle(Window *w, uint32_t id) {
    for (size_t i = 0; i < w->drop.num_dir_handles; i++)
        if (w->drop.dir_handles[i].id == id) return &w->drop.dir_handles[i];
    return NULL;
}

/* Open a directory, build the null-separated listing, create a handle, and
 * send the listing to the client as a t=d:x=handle_id response. */
static void
drop_send_dir_listing(Window *w, const char *path) {
    struct stat st;
    if (stat(path, &st) < 0) { drop_send_error(w, EIO); return; }

    DIR *dir = opendir(path);
    if (!dir) {
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        return;
    }

    /* Build null-separated payload: unique_id\0entry1\0entry2\0... */
    size_t payload_cap = 4096, payload_sz = 0;
    char *payload = malloc(payload_cap);
    if (!payload) { closedir(dir); drop_send_error(w, EIO); return; }

    /* First entry: unique identifier (device:inode) */
    char uid[64];
    int uid_len = snprintf(uid, sizeof(uid), "%llu:%llu",
                           (unsigned long long)st.st_dev,
                           (unsigned long long)st.st_ino);

#define APPEND(s, n) do { \
    size_t _n = (size_t)(n); \
    size_t _need = payload_sz + _n + 1; \
    if (_need > payload_cap) { \
        while (payload_cap < _need) payload_cap *= 2; \
        char *_np = realloc(payload, payload_cap); \
        if (!_np) { free(payload); closedir(dir); drop_send_error(w, EIO); return; } \
        payload = _np; \
    } \
    memcpy(payload + payload_sz, (s), _n); \
    payload_sz += _n; \
    payload[payload_sz++] = 0; \
} while(0)

    APPEND(uid, uid_len);

    /* Collect directory entries */
    size_t ents_cap = 16, ents_num = 0;
    char **ents = malloc(sizeof(char *) * ents_cap);
    if (!ents) { free(payload); closedir(dir); drop_send_error(w, EIO); return; }

    struct dirent *de;
    while ((de = readdir(dir)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;

        unsigned char dtype = de->d_type;
        if (dtype == DT_UNKNOWN) {
            /* Fall back to lstat when d_type is unavailable */
            char full[PATH_MAX];
            if (snprintf(full, sizeof(full), "%s/%s", path, de->d_name) >= (int)sizeof(full)) continue;
            struct stat est;
            if (lstat(full, &est) < 0) continue;
            if      (S_ISREG(est.st_mode)) dtype = DT_REG;
            else if (S_ISDIR(est.st_mode)) dtype = DT_DIR;
            else if (S_ISLNK(est.st_mode)) dtype = DT_LNK;
            else continue;
        }
        if (dtype != DT_REG && dtype != DT_DIR && dtype != DT_LNK) continue;

        if (ents_num >= ents_cap) {
            ents_cap *= 2;
            char **ne = realloc(ents, sizeof(char *) * ents_cap);
            if (!ne) {
                for (size_t i = 0; i < ents_num; i++) free(ents[i]);
                free(ents); free(payload); closedir(dir);
                drop_send_error(w, EIO); return;
            }
            ents = ne;
        }
        ents[ents_num] = strdup(de->d_name);
        if (!ents[ents_num]) {
            for (size_t i = 0; i < ents_num; i++) free(ents[i]);
            free(ents); free(payload); closedir(dir);
            drop_send_error(w, EIO); return;
        }
        ents_num++;

        APPEND(de->d_name, strlen(de->d_name));
    }
    closedir(dir);

#undef APPEND

    uint32_t handle_id = drop_alloc_dir_handle(w, path, ents, ents_num);

    char hdr[128];
    int hdr_sz = snprintf(hdr, sizeof(hdr), "\x1b]%d;t=d:x=%u", DND_CODE, (unsigned)handle_id);
    /* payload_sz includes a trailing null; omit it – the null-separated format
     * does not require a trailing null after the last entry. */
    size_t send_sz = payload_sz > 0 ? payload_sz - 1 : 0;
    if (send_sz)
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, payload, send_sz, true);
    free(payload);
    /* end-of-listing signal (empty payload) */
    queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, NULL, 0, true);
}

/* Handle a t=s request: send the file/directory at URI-list index idx. */
void
drop_request_uri_data(Window *w, const char *payload, size_t payload_sz) {
    if (!w->drop.uri_list || !w->drop.uri_list_sz) {
        drop_send_error(w, EINVAL); return;
    }

    /* Payload format: "text/uri-list:idx" */
    const char *colon = memchr(payload, ':', payload_sz);
    if (!colon) { drop_send_error(w, EINVAL); return; }

    size_t mime_len = (size_t)(colon - payload);
    if (mime_len != 13 || strncmp(payload, "text/uri-list", 13) != 0) {
        drop_send_error(w, EINVAL); return;
    }

    const char *idx_str = colon + 1;
    size_t idx_len = payload_sz - mime_len - 1;
    char idx_buf[32];
    if (!idx_len || idx_len >= sizeof(idx_buf)) { drop_send_error(w, EINVAL); return; }
    memcpy(idx_buf, idx_str, idx_len);
    idx_buf[idx_len] = 0;

    char *endp;
    long idx = strtol(idx_buf, &endp, 10);
    if (endp == idx_buf || *endp != 0 || idx < 0) { drop_send_error(w, EINVAL); return; }

    char *path = NULL;
    const char *err = NULL;
    if (!get_nth_file_url(w->drop.uri_list, w->drop.uri_list_sz, (int)idx, &path, &err)) {
        drop_send_error_str(w, err);
        return;
    }

    struct stat st;
    if (stat(path, &st) < 0) {
        free(path);
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        return;
    }

    if (S_ISDIR(st.st_mode)) {
        drop_send_dir_listing(w, path);
    } else if (S_ISREG(st.st_mode)) {
        drop_send_file_data(w, path);
    } else {
        drop_send_error(w, EINVAL);
    }
    free(path);
}

/* Handle a t=d request from the client.
 * handle_id: the directory handle (x= key).
 * entry_num: 0 means close the handle; >=1 means read that entry (1-based). */
void
drop_handle_dir_request(Window *w, uint32_t handle_id, int32_t entry_num) {
    if (!handle_id) { drop_send_error(w, EINVAL); return; }

    DirHandle *h = drop_find_dir_handle(w, handle_id);
    if (!h) { drop_send_error(w, EINVAL); return; }

    if (entry_num == 0) {
        /* Close the handle */
        size_t hidx = (size_t)(h - w->drop.dir_handles);
        drop_free_dir_handle(h);
        remove_i_from_array(w->drop.dir_handles, hidx, w->drop.num_dir_handles);
        return;
    }

    /* Read the entry at 1-based index */
    size_t eidx = (size_t)(entry_num - 1);
    if (eidx >= h->num_entries) { drop_send_error(w, ENOENT); return; }

    char full[PATH_MAX];
    if (snprintf(full, sizeof(full), "%s/%s", h->path, h->entries[eidx]) >= (int)sizeof(full)) {
        drop_send_error(w, EIO); return;
    }

    struct stat st;
    if (stat(full, &st) < 0) {
        switch (errno) {
            case ENOENT: case ENOTDIR: case ELOOP: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:               drop_send_error(w, EPERM); break;
            default:                               drop_send_error(w, EIO); break;
        }
        return;
    }

    if (S_ISDIR(st.st_mode)) {
        drop_send_dir_listing(w, full);
    } else if (S_ISREG(st.st_mode)) {
        drop_send_file_data(w, full);
    } else {
        drop_send_error(w, EINVAL);
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

#define ds w->drag_source

static void
drag_free_built_data(Window *w) {
    if (ds.items) {
        for (size_t i=0; i < ds.num_mimes; i++) {
            free(ds.items[i].optional_data);
            if (ds.items[i].fd_plus_one > 0) safe_close(ds.items[i].fd_plus_one - 1, __FILE__, __LINE__);
        }
        free(ds.items);
    }
    for (size_t i = 0; i < arraysz(ds.images); i++) {
        if (ds.images[i].data) free(ds.images[i].data);
        zero_at_ptr(ds.images + i);
    }
}

void
drag_free_offer(Window *w) {
    free(ds.mimes_buf); ds.mimes_buf = NULL;
    drag_free_built_data(w);
    ds.allowed_operations = 0;
    ds.state = DRAG_SOURCE_NONE;
    ds.num_mimes = 0;
    ds.pre_sent_total_sz = 0;
    ds.images_sent_total_sz = 0;
}

static void
drag_send_error(Window *w, int error_code) {
    char buf[128];
    const char *e = get_errno_name(error_code);
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=R", DND_CODE);
    queue_payload_to_child(
        w->id, w->drag_source.client_id, &w->drag_source.pending, buf, header_size, e, strlen(e), false);
}

static void
cancel_drag(Window *w, int error_code) {
    if (error_code) drag_send_error(w, error_code);
    if (global_state.drag_source.is_active && global_state.drag_source.from_window == w->id) cancel_current_drag_source();
    drag_free_offer(w);
}

void
drag_add_mimes(Window *w, int allowed_operations, uint32_t client_id, const char *data, size_t sz, bool has_more) {
#define abrt(code) { cancel_drag(w, code); return; }
    if (allowed_operations && ds.state != DRAG_SOURCE_NONE) cancel_drag(w, 0);
    if (allowed_operations && !ds.allowed_operations) ds.allowed_operations = allowed_operations;
    if (!ds.allowed_operations) { abrt(EINVAL); }
    ds.state = DRAG_SOURCE_BEING_BUILT;
    ds.client_id = client_id;
    size_t new_sz = ds.bufsz + sz;
    if (new_sz > MIME_LIST_SIZE_CAP) abrt(EFBIG);
    ds.mimes_buf = realloc(ds.mimes_buf, ds.bufsz + sz + 1);
    if (!ds.mimes_buf) abrt(ENOMEM);
    memcpy(ds.mimes_buf + ds.bufsz, data, sz);
    ds.bufsz = new_sz;
    ds.mimes_buf[ds.bufsz] = 0;
    if (!has_more) {
        char *ptr = ds.mimes_buf;
        size_t rough_count = 0;
        while ((ptr = strchr(ptr, ' ')) != NULL) {
            *ptr = 0; ptr++;
            rough_count++;
        }
        ds.items = calloc(rough_count + 2, sizeof(ds.items[0]));
        if (!ds.items) abrt(ENOMEM);
        char *p = ds.mimes_buf, *end = ds.mimes_buf + ds.bufsz;
        ds.num_mimes = 0;
        while (p < end) {
            if (*p) {
                if (ds.num_mimes >= rough_count + 1) break;
                ds.items[ds.num_mimes++].mime_type = p;
                p += strlen(p) + 1;
            } else p++;
        }
        ds.pre_sent_total_sz = 0;
    }
}

void
drag_add_pre_sent_data(Window *w, unsigned idx, const uint8_t *payload, size_t sz) {
    if (ds.state != DRAG_SOURCE_BEING_BUILT || idx >= ds.num_mimes) abrt(EINVAL);
    if (sz + ds.pre_sent_total_sz > PRESENT_DATA_CAP) abrt(EFBIG);
    ds.pre_sent_total_sz += sz;
#define item ds.items[idx]
    if (!item.data_decode_initialized) {
        item.data_decode_initialized = true;
        base64_init_stream_decoder(&item.base64_state);
    }
    if (item.data_capacity < sz + item.data_size) {
        size_t newcap = MAX(item.data_capacity * 2, sz + item.data_size);
        item.optional_data = realloc(item.optional_data, newcap);
        if (!item.optional_data) abrt(ENOMEM);
        item.data_capacity = newcap;
    }
    size_t outlen = item.data_capacity - item.data_size;
    if (!base64_decode_stream(&item.base64_state, payload, sz, item.optional_data + item.data_size, &outlen)) abrt(EINVAL);
    item.data_size += outlen;
#undef item
}

#define img ds.images[idx]

void
drag_add_image(Window *w, unsigned idx, int fmt, int width, int height, const uint8_t *payload, size_t sz) {
    if (ds.state != DRAG_SOURCE_BEING_BUILT) abrt(EINVAL);
    if (idx + 1 >= arraysz(ds.images)) abrt(EFBIG);
    if (ds.images_sent_total_sz + sz > PRESENT_DATA_CAP) abrt(EFBIG);
    ds.images_sent_total_sz += sz;
    if (!img.started) {
        if (fmt != 24 && fmt != 32 && fmt != 100) abrt(EINVAL);
        if (width < 1 || height < 1) abrt(EINVAL);
        img.started = true;
        img.width = width; img.height = height;
        img.fmt = fmt;
        base64_init_stream_decoder(&img.base64_state);
    }
    if (img.capacity < sz + img.sz) {
        size_t newcap = MAX(img.capacity * 2, sz + img.sz);
        img.data = realloc(img.data, newcap);
        if (!img.data) abrt(ENOMEM);
        img.capacity = newcap;
    }
    size_t outlen = img.capacity - img.sz;
    if (!base64_decode_stream(&img.base64_state, payload, sz, img.data + img.sz, &outlen)) abrt(EINVAL);
    img.sz += outlen;
}

void
drag_change_image(Window *w, unsigned idx) {
    ds.img_idx = idx;
    if (ds.state == DRAG_SOURCE_STARTED) change_drag_image(idx);
}

static bool
expand_rgb_data(Window *w, size_t idx) {
#define fail(code) { cancel_drag(w, code); return false; }
    if (img.sz != (size_t)img.width * (size_t)img.height * 3) fail(EINVAL);
    const size_t sz = img.width * img.height * 4;
    RAII_ALLOC(uint8_t, expanded, malloc(sz));
    if (!expanded) fail(ENOMEM);
    memset(expanded, 0xff, sz);
    for (int r = 0; r < img.height; r++) {
        uint8_t *src_row = img.data + r * img.width * 3, *dest_row = expanded + r * img.width * 4;
        for (int c = 0; c < img.width; c++) memcpy(dest_row + c * 4, src_row + c * 3, 3);
    }
    SWAP(img.data, expanded); img.sz = sz; img.fmt = 32;
    return true;
}

static bool
expand_png_data(Window *w, size_t idx) {
    png_read_data d = {0};
    inflate_png_inner(&d, img.data, img.sz, 2000);
    if (d.ok) {
        free(img.data);
        img.data = d.decompressed;
        img.sz = d.sz;
        img.width = d.width; img.height = d.height;
    } else free(d.decompressed);
    free(d.row_pointers);
    return d.ok;
}
#undef fail

void
drag_start(Window *w) {
    if (ds.state != DRAG_SOURCE_BEING_BUILT) abrt(EINVAL);
    size_t total_size = 0;
    for (size_t idx = 0; idx < arraysz(ds.images); idx++) {
        if (img.sz) {
            switch (img.fmt) {
                case 24:
                    if (!expand_rgb_data(w, idx)) return;
                    break;
                case 100:
                    if (!expand_png_data(w, idx)) return;
                    break;
            }
            total_size += img.sz;
            if (total_size > 2 * PRESENT_DATA_CAP) abrt(EFBIG);
            if (img.sz != (size_t)img.width * (size_t)img.height * 4u) abrt(EINVAL);
        }
    }
    int err = start_window_drag(w);
    if (err != 0) {
        abrt(err);
    } else {
        // Free images and optional_data but keep the items array for later
        // data requests from the drop target
        for (size_t i = 0; i < ds.num_mimes; i++) {
            free(ds.items[i].optional_data);
            ds.items[i].optional_data = NULL;
            ds.items[i].data_size = 0;
            ds.items[i].data_capacity = 0;
            ds.items[i].data_decode_initialized = false;
        }
        for (size_t i = 0; i < arraysz(ds.images); i++) {
            if (ds.images[i].data) free(ds.images[i].data);
            zero_at_ptr(ds.images + i);
        }
        ds.state = DRAG_SOURCE_STARTED;
        drag_send_error(w, 0);  // send OK
    }
}

void
drag_notify(Window *w, DragNotifyType type) {
    char buf[128];
    size_t sz = snprintf(buf, sizeof(buf), "t=e:x=%d", type + 1);
    switch(type) {
        case DRAG_NOTIFY_ACCEPTED:
            for (size_t i = 0; i < ds.num_mimes; i++) {
                if (strcmp(ds.items[i].mime_type, global_state.drag_source.accepted_mime_type) == 0) {
                    sz += snprintf(buf + sz, sizeof(buf) - sz, "y=%zu", i); break;
                }
            }
        case DRAG_NOTIFY_ACTION_CHANGED:
            switch (global_state.drag_source.action) {
                case GLFW_DRAG_OPERATION_MOVE:
                    sz += snprintf(buf + sz, sizeof(buf) - sz, "o=2"); break;
                default:
                    sz += snprintf(buf + sz, sizeof(buf) - sz, "o=1"); break;
            }
        case DRAG_NOTIFY_DROPPED: break;
        case DRAG_NOTIFY_FINISHED:
            sz += snprintf(buf + sz, sizeof(buf) - sz, "y=%d", global_state.drag_source.was_canceled ? 1 : 0); break;
    }
    queue_payload_to_child(w->id, w->drag_source.client_id, &w->drag_source.pending, buf, sz, NULL, 0, false);
}

int
drag_free_data(Window *w, const char *mime_type, const char* data, size_t sz) {
    (void)w; (void)mime_type; (void)sz;
    free((void*)data);
    return 0;
}

const char*
drag_get_data(Window *w, const char *mime_type, size_t *sz, int *err_code) {
    *err_code = ENOENT; *sz = 0;
    if (!ds.items) return NULL;
    for (size_t i = 0; i < ds.num_mimes; i++) {
        if (strcmp(ds.items[i].mime_type, mime_type) == 0) {
            if (ds.items[i].fd_plus_one < 0) {
                // Error was stored by drag_process_item_data
                *err_code = -ds.items[i].fd_plus_one;
                ds.items[i].fd_plus_one = 0;
                return NULL;
            }
            if (ds.items[i].fd_plus_one > 0) {
                // Data is available in the temp file, read it
                int fd = ds.items[i].fd_plus_one - 1;
                off_t end = lseek(fd, 0, SEEK_END);
                if (end < 0) { *err_code = EIO; return NULL; }
                if (lseek(fd, 0, SEEK_SET) < 0) { *err_code = EIO; return NULL; }
                char *data = malloc(end ? (size_t)end : 1);
                if (!data) { *err_code = ENOMEM; return NULL; }
                size_t total = 0;
                while (total < (size_t)end) {
                    ssize_t n = read(fd, data + total, (size_t)end - total);
                    if (n < 0) {
                        if (errno == EINTR) continue;
                        free(data);
                        *err_code = EIO;
                        return NULL;
                    }
                    if (n == 0) break;
                    total += (size_t)n;
                }
                // Close and reset the fd after reading
                safe_close(fd, __FILE__, __LINE__);
                ds.items[i].fd_plus_one = 0;
                *sz = total;
                *err_code = 0;
                return data;
            }
            // No fd yet, request data from the client
            char buf[128];
            int header_sz = snprintf(buf, sizeof(buf), "\x1b]%d;t=e:x=%d:y=%zu", DND_CODE, DRAG_NOTIFY_FINISHED + 2, i);
            queue_payload_to_child(w->id, w->drag_source.client_id, &w->drag_source.pending, buf, header_sz, NULL, 0, false);
            *err_code = EAGAIN;
            return NULL;
        }
    }
    return NULL;
}

static int
parse_errno_name(const uint8_t *data, size_t sz) {
    if (sz >= 6 && memcmp(data, "ENOENT", 6) == 0) return ENOENT;
    if (sz >= 5 && memcmp(data, "EPERM", 5) == 0) return EPERM;
    if (sz >= 6 && memcmp(data, "EINVAL", 6) == 0) return EINVAL;
    if (sz >= 6 && memcmp(data, "ENOMEM", 6) == 0) return ENOMEM;
    if (sz >= 5 && memcmp(data, "EFBIG", 5) == 0) return EFBIG;
    if (sz >= 3 && memcmp(data, "EIO", 3) == 0) return EIO;
    return EIO;
}

static int
open_item_tmpfile(void) {
    int fd = -1;
#ifdef O_TMPFILE
    fd = safe_open("/tmp", O_TMPFILE | O_CLOEXEC | O_EXCL | O_RDWR, S_IRUSR | S_IWUSR);
#endif
    if (fd < 0) {
        char name[] = "/tmp/kitty-dnd-XXXXXXXXXXXX";
        fd = safe_mkstemp(name);
        if (fd >= 0) unlink(name);
    }
    return fd;
}

void
drag_process_item_data(Window *w, size_t idx, int has_more, const uint8_t *payload, size_t payload_sz) {
    if ((ds.state != DRAG_SOURCE_STARTED && ds.state != DRAG_SOURCE_DROPPED) || idx >= ds.num_mimes || !ds.items) return;

    if (has_more < 0) {
        // Error from the client program
        if (ds.items[idx].fd_plus_one > 0) {
            safe_close(ds.items[idx].fd_plus_one - 1, __FILE__, __LINE__);
        }
        int err = parse_errno_name(payload, payload_sz);
        ds.items[idx].fd_plus_one = -err;
        ds.items[idx].data_decode_initialized = false;
        int ret = notify_drag_data_ready(global_state.drag_source.from_os_window, ds.items[idx].mime_type);
        if (ret) cancel_drag(w, ret);
        return;
    }

    // Open temp file if not yet open
    if (!ds.items[idx].fd_plus_one) {
        int fd = open_item_tmpfile();
        if (fd < 0) { cancel_drag(w, ENOMEM); return; }
        ds.items[idx].fd_plus_one = fd + 1;
        ds.items[idx].data_decode_initialized = true;
        base64_init_stream_decoder(&ds.items[idx].base64_state);
    }

    // Decode and write payload data
    if (payload_sz > 0) {
        RAII_ALLOC(uint8_t, decoded, malloc(payload_sz));
        if (!decoded) { cancel_drag(w, ENOMEM); return; }
        size_t outlen = payload_sz;
        if (!base64_decode_stream(&ds.items[idx].base64_state, payload, payload_sz, decoded, &outlen)) {
            cancel_drag(w, EINVAL);
            return;
        }
        size_t written = 0;
        while (written < outlen) {
            ssize_t n = write(ds.items[idx].fd_plus_one - 1, decoded + written, outlen - written);
            if (n < 0) {
                if (errno == EINTR) continue;
                cancel_drag(w, EIO);
                return;
            }
            written += (size_t)n;
        }
    }

    if (has_more == 0) {
        // All data received, seek to beginning and notify
        if (lseek(ds.items[idx].fd_plus_one - 1, 0, SEEK_SET) < 0) {
            cancel_drag(w, EIO);
            return;
        }
        ds.items[idx].data_decode_initialized = false;
        int ret = notify_drag_data_ready(global_state.drag_source.from_os_window, ds.items[idx].mime_type);
        if (ret) cancel_drag(w, ret);
    }
}
#undef img
#undef abrt
#undef ds
