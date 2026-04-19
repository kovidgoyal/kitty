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

#define DEFAULT_MIME_LIST_SIZE_CAP 1024u * 1024u
static size_t MIME_LIST_SIZE_CAP = DEFAULT_MIME_LIST_SIZE_CAP;
#define DEFAULT_PRESENT_DATA_CAP 64 * 1024 * 1024
static size_t PRESENT_DATA_CAP = DEFAULT_PRESENT_DATA_CAP;
#define DEFAULT_REMOTE_DRAG_LIMIT 1024 * 1024 * 1024
static size_t REMOTE_DRAG_LIMIT = DEFAULT_REMOTE_DRAG_LIMIT;
static PyObject *g_dnd_test_write_func = NULL;
static const unsigned file_permissions = 0644;
static const unsigned dir_permissions = 0755;

// Utils {{{
// In test mode, this callable is invoked instead of schedule_write_to_child_if_possible.
// It receives (window_id: int, data: bytes) and its return value is ignored.
static void drop_process_queue(Window *w);
static void drop_pop_request(Window *w);

static size_t
count_occurrences(const char *str, size_t len, char target) {
    size_t count = 0;
    const char *ptr = str;
    while ((ptr = memchr(ptr, target, len - (ptr - str))) != NULL) {
        count++; ptr++; // Move past the found character
        if (ptr >= str + len) break;
    }
    return count;
}

static const char*
get_errno_name(int err) {
    switch (err) {
        case EPERM: return "EPERM";
        case ENOENT: return "ENOENT";
        case EIO: return "EIO";
        case EINVAL: return "EINVAL";
        case EMFILE: return "EMFILE";
        case ENOMEM: return "ENOMEM";
        case EFBIG: return "EFBIG";
        case EISDIR: return "EISDIR";
        case ENOSPC: return "ENOSPC";
        case 0: return "OK";
        default: return "EUNKNOWN";
    }
}

static const char*
machine_id(void) {
    static bool done = false;
    static char ans[512] = {0};
    if (!done) {
        done = true;
        RAII_PyObject(mname, PyUnicode_DecodeFSDefault("kitty.machine_id"));
        if (mname) {
            RAII_PyObject(module, PyImport_Import(mname));
            if (module) {
                RAII_PyObject(func, PyObject_GetAttrString(module, "machine_id"));
                if (func) {
                    RAII_PyObject(ret, PyObject_CallFunction(func, "s", "tty-dnd-protocol-machine-id"));
                    if (ret) snprintf(ans, sizeof(ans), "%s", PyUnicode_AsUTF8(ret));
                }
            }
        }
        if (PyErr_Occurred()) PyErr_Print();
    }
    return ans;
}

static void
rmtree_best_effort(const char *relpath, int dirfd) {
    RAII_PyObject(mname, PyUnicode_DecodeFSDefault("kitty.utils"));
    if (mname) {
        RAII_PyObject(module, PyImport_Import(mname));
        if (module) {
            RAII_PyObject(func, PyObject_GetAttrString(module, "rmtree_best_effort"));
            if (func) {
                RAII_PyObject(ret, PyObject_CallFunction(func, "si", relpath, dirfd));
            }
        }
    }
    if (PyErr_Occurred()) PyErr_Print();
    safe_close(dirfd, __FILE__, __LINE__);
}

static char*
mktempdir_in_cache(const char *prefix, int *fd) {
    char *ans = NULL;
    RAII_PyObject(mname, PyUnicode_DecodeFSDefault("kitty.utils"));
    if (mname) {
        RAII_PyObject(module, PyImport_Import(mname));
        if (module) {
            RAII_PyObject(func, PyObject_GetAttrString(module, "mktempdir_in_cache"));
            if (func) {
                RAII_PyObject(ret, PyObject_CallFunction(func, "sO", prefix, dnd_is_test_mode() ? Py_False : Py_True));
                if (ret) {
                    if (PyArg_ParseTuple(ret, "si", &ans, fd)) {
                        if (*fd < 0) {
                            errno = -*fd;
                            return NULL;
                        }
                        ans = strdup(ans);
                        if (!ans) {
                            errno = ENOMEM; return NULL;
                        }
                        return ans;
                    }
                }
            }
        }
    }
    if (PyErr_Occurred()) PyErr_Print();
    errno = EIO;
    return NULL;
}

static char*
as_file_url(const char *wd, const char *middle, const char *filename) {
    RAII_PyObject(mname, PyUnicode_DecodeFSDefault("kitty.utils"));
    if (mname) {
        RAII_PyObject(module, PyImport_Import(mname));
        if (module) {
            RAII_PyObject(func, PyObject_GetAttrString(module, "as_file_url"));
            if (func) {
                RAII_PyObject(ret, PyObject_CallFunction(func, "sss", wd, middle, filename));
                if (ret) return strdup(PyUnicode_AsUTF8(ret));
            }
        }
    }
    if (PyErr_Occurred()) PyErr_Print();
    return NULL;
}

static char*
sanitized_filename_from_url(const char *url) {
    RAII_PyObject(mname, PyUnicode_DecodeFSDefault("kitty.utils"));
    if (mname) {
        RAII_PyObject(module, PyImport_Import(mname));
        if (module) {
            RAII_PyObject(func, PyObject_GetAttrString(module, "sanitized_filename_from_url"));
            if (func) {
                RAII_PyObject(ret, PyObject_CallFunction(func, "s", url));
                if (ret) return strdup(PyUnicode_AsUTF8(ret));
            }
        }
    }
    if (PyErr_Occurred()) PyErr_Print();
    return NULL;
}


static void
dnd_set_test_write_func(PyObject *func, size_t mime_list_size_cap, size_t present_data_cap, size_t remote_drag_limit) {
    (void)machine_id;
    Py_CLEAR(g_dnd_test_write_func);
    g_dnd_test_write_func = Py_XNewRef(func);
    MIME_LIST_SIZE_CAP = mime_list_size_cap ? mime_list_size_cap : DEFAULT_MIME_LIST_SIZE_CAP;
    PRESENT_DATA_CAP = present_data_cap ? present_data_cap : DEFAULT_PRESENT_DATA_CAP;
    REMOTE_DRAG_LIMIT = remote_drag_limit ? remote_drag_limit : DEFAULT_REMOTE_DRAG_LIMIT;
}

bool
dnd_is_test_mode(void) {
    return g_dnd_test_write_func != NULL;
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
        memcpy(buf, header, header_sz);
        if (data_sz - offset) memcpy(buf + header_sz, data, data_sz - offset);
        PendingEntry *e = &pending->items[pending->count++];
        e->buf = buf; e->header_sz = header_sz; e->data_sz = data_sz - offset;
        e->as_base64 = as_base64; e->client_id = client_id;
    }
    if (pending->count) check_for_pending_writes();
}

static bool
is_same_machine(const char *client_machine_id, size_t sz) {
    if (!sz || !client_machine_id) return true;
    if (sz < 20) return false;
    if (client_machine_id[0] != '1' || client_machine_id[1] != ':') return false;
    client_machine_id = client_machine_id + 2; sz -= 2;
    const char *host_machine_id = machine_id();
    if (!host_machine_id) return true;
    const size_t hsz = strlen(host_machine_id);
    return sz == hsz && memcmp(client_machine_id, host_machine_id, sz) == 0;
}

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

// }}}

// Dropping {{{
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

static void
drop_free_request_queue(Window *w) {
    w->drop.num_data_requests = 0;
    w->drop.current_request_x = 0;
    w->drop.current_request_y = 0;
    w->drop.current_request_Y = 0;
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
    drop_free_request_queue(w);
}

static void
reset_drop(Window *w) {
    bool wanted = w->drop.wanted; uint32_t cid = w->drop.client_id;
    bool is_remote_client = w->drop.is_remote_client;
    drop_free_data(w);
    zero_at_ptr(&w->drop);
    if (wanted) {
        w->drop.wanted = wanted;
        w->drop.client_id = cid;
        w->drop.is_remote_client = is_remote_client;
    }
}
void
drop_register_window(Window *w, const uint8_t *payload, size_t payload_sz, bool on, uint32_t client_id, bool more) {
    w->drop.wanted = on;
    w->drop.client_id = client_id;
    w->drop.is_remote_client = false;
    if (!on) { drop_free_data(w); zero_at_ptr(&w->drop); return; }
    if (!payload || !payload_sz) return;
    size_t sz = w->drop.registered_mimes ? strlen(w->drop.registered_mimes) : 0;
    if (sz + payload_sz > MIME_LIST_SIZE_CAP) return;
    char *tmp = realloc(w->drop.registered_mimes, sz + payload_sz + 1);
    if (tmp) {
        w->drop.registered_mimes = tmp;
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

void
drop_register_machine_id(Window *w, const uint8_t *machine_id, size_t sz) {
    w->drop.is_remote_client = !is_same_machine((const char*)machine_id, sz);
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

/* Append the current request disambiguation keys (x, y, Y) to a header buffer.
 * Returns the number of bytes written. */
static int
drop_append_request_keys(Window *w, char *buf, size_t bufsize) {
    int sz = 0;
    if (w->drop.current_request_x && sz < (int)bufsize - 1)
        sz += snprintf(buf + sz, bufsize - sz, ":x=%d", (int)w->drop.current_request_x);
    if (w->drop.current_request_y && sz < (int)bufsize - 1)
        sz += snprintf(buf + sz, bufsize - sz, ":y=%d", (int)w->drop.current_request_y);
    if (w->drop.current_request_Y && sz < (int)bufsize - 1)
        sz += snprintf(buf + sz, bufsize - sz, ":Y=%d", (int)w->drop.current_request_Y);
    return sz;
}

static void
drop_send_error(Window *w, int error_code) {
    char buf[128];
    const char *e = get_errno_name(error_code);
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=R", DND_CODE);
    header_size += drop_append_request_keys(w, buf + header_size, sizeof(buf) - header_size);
    queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, e, strlen(e), false);
}

void
drop_send_einval(Window *w) {
    drop_send_error(w, EINVAL);
}

/* Returns true if the request completed synchronously (error, no-op),
 * false if an async OS data fetch was started. */
static bool
do_drop_request_data(Window *w, int32_t idx) {
    if (w->drop.getting_data_for_mime) { free(w->drop.getting_data_for_mime); w->drop.getting_data_for_mime = NULL; }
    OSWindow *osw = os_window_for_kitty_window(w->id);
    if (!osw) return true;
    /* idx is 1-based */
    if (idx < 1 || !w->drop.offerred_mimes || (size_t)idx > w->drop.num_offerred_mimes) {
        drop_send_error(w, ENOENT);
        return true;
    }
    const char *mime = w->drop.offerred_mimes[idx - 1];
    w->drop.getting_data_for_mime = strdup(mime);
    if (w->drop.getting_data_for_mime) request_drop_data(osw, w->id, mime);
    return false; /* async: completion via drop_dispatch_data */
}

void
drop_dispatch_data(Window *w, const char *mime, const char *data, ssize_t sz) {
    if (sz < 0) {
        drop_send_error(w, -sz);
        drop_pop_request(w);
        drop_process_queue(w);
    } else {
        char buf[128];
        int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=r", DND_CODE);
        const bool is_uri_list = strcmp(mime, "text/uri-list") == 0;
        if (is_uri_list) header_size += snprintf(
            buf + header_size, sizeof(buf) - header_size, ":X=%d", w->drop.is_remote_client);
        header_size += drop_append_request_keys(w, buf + header_size, sizeof(buf) - header_size);
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, buf, header_size, sz ? data : NULL, sz, true);
        if (is_uri_list) {
            w->drop.uri_list_sz += sz;
            char *tmp = realloc(w->drop.uri_list, w->drop.uri_list_sz);
            if (tmp) { w->drop.uri_list = tmp; memcpy(w->drop.uri_list + w->drop.uri_list_sz - sz, data, sz); }
            else { free(w->drop.uri_list); w->drop.uri_list = NULL; w->drop.uri_list_sz = 0; }
        }
        if (sz == 0) { drop_pop_request(w); drop_process_queue(w); }
    }
}

// ---- Remote file / directory transfer ----

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
    header_size += drop_append_request_keys(w, buf + header_size, sizeof(buf) - header_size);
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
        drop_pop_request(w);
        drop_process_queue(w);
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
    hdr_sz += drop_append_request_keys(w, hdr + hdr_sz, sizeof(hdr) - hdr_sz);
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
            drop_pop_request(w);
            drop_process_queue(w);
            return;
        }
        if (n == 0) {
            /* EOF: close fd and send the empty end-of-data signal */
            drop_close_file_fd(w);
            queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, NULL, 0, true);
            drop_pop_request(w);
            drop_process_queue(w);
            return;
        }
        size_t sent = send_payload_to_child(w->id, w->drop.client_id, hdr, hdr_sz, buf, (size_t)n, true);
        if (sent > 0) w->drop.last_file_send_at = monotonic();
        if (sent < (size_t)n) {
            /* Partial send: rewind file pointer and retry via timer */
            if (lseek(w->drop.file_fd_plus_one - 1, -(off_t)(((size_t)n) - sent), SEEK_CUR) < 0) {
                drop_close_file_fd(w);
                drop_send_error(w, EIO);
                drop_pop_request(w);
                drop_process_queue(w);
                return;
            }
            w->drop.file_send_timer = add_main_loop_timer(ms_to_monotonic_t(20), false, file_send_timer_callback, (void*)(uintptr_t)w->id, NULL);
            return;
        }
        /* Full chunk sent: loop and read next chunk */
    }
}

/* Open a regular file and begin sending its contents as t=r chunks followed
 * by an empty end-of-data t=r, using chunked I/O to avoid large allocations.
 * Returns true if completed synchronously (error), false if async I/O started. */
static bool
drop_send_file_data(Window *w, const char *path) {
    drop_close_file_fd(w);
    int fd = safe_open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK, 0);
    if (fd < 0) {
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        return true;
    }
    struct stat st;
    if (fstat(fd, &st) < 0) {
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        safe_close(fd, __FILE__, __LINE__);
        return true;
    }
    if (!S_ISREG(st.st_mode)) { drop_send_error(w, EINVAL); safe_close(fd, __FILE__, __LINE__); return true; }
    w->drop.file_fd_plus_one = fd + 1;
    w->drop.last_file_send_at = monotonic();
    drop_send_file_chunks(w);
    return false; /* async: completion via drop_send_file_chunks */
}

/* Allocate a new DirHandle for the given path and entries (takes ownership of
 * entries array and its strings). Returns the new handle id. */
static uint32_t
drop_alloc_dir_handle(Window *w, const char *path, char **entries, size_t num_entries) {
    ensure_space_for(&w->drop, dir_handles, DirHandle, w->drop.num_dir_handles + 1, dir_handles_capacity, 4, true);
    w->drop.next_dir_handle_id++;
    /* Handles 0 and 1 are reserved (0 = absent, 1 = symlink indicator), so
     * valid directory handles must be >= 2. */
    if (w->drop.next_dir_handle_id < 2) w->drop.next_dir_handle_id = 2;
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
    DIR *dir = opendir(path);
    if (!dir) {
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        return;
    }

    /* Build null-separated payload: entry1\0entry2\0... */
    size_t payload_cap = 4096, payload_sz = 0;
    char *payload = malloc(payload_cap);
    if (!payload) { closedir(dir); drop_send_error(w, EIO); return; }

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
    int hdr_sz = snprintf(hdr, sizeof(hdr), "\x1b]%d;t=r", DND_CODE);
    /* Echo all request keys (x, y, Y) so the client can unambiguously identify
     * which filesystem object this listing corresponds to.  For top-level URI
     * file requests Y is absent; for sub-dir reads Y holds the parent handle
     * and x holds the 1-based entry index.  The new handle is X itself (a value
     * > 1 distinguishes directories from regular files (X absent / X=0) and
     * symlinks (X=1)). */
    hdr_sz += drop_append_request_keys(w, hdr + hdr_sz, sizeof(hdr) - hdr_sz);
    hdr_sz += snprintf(hdr + hdr_sz, sizeof(hdr) - hdr_sz, ":X=%u", (unsigned)handle_id);
    /* payload_sz includes a trailing null; omit it – the null-separated format
     * does not require a trailing null after the last entry. */
    size_t send_sz = payload_sz > 0 ? payload_sz - 1 : 0;
    if (send_sz)
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, payload, send_sz, true);
    free(payload);
    /* end-of-listing signal (empty payload) */
    queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, NULL, 0, true);
}

/* Handle a t=s request: send the file/directory at URI-list index idx.
 * Returns true if completed synchronously, false if async file I/O started. */
static bool
do_drop_request_uri_data(Window *w, int32_t mime_idx, int32_t file_idx) {
    if (!w->drop.uri_list || !w->drop.uri_list_sz) {
        drop_send_error(w, EINVAL); return true;
    }
    if (global_state.drag_source.from_window == w->id && w->drag_source.state != DRAG_SOURCE_NONE) {
        drop_send_error(w, EPERM); return true;
    }

    /* Verify mime_idx (1-based) points to text/uri-list */
    if (mime_idx < 1 || !w->drop.offerred_mimes || (size_t)mime_idx > w->drop.num_offerred_mimes ||
        strcmp(w->drop.offerred_mimes[mime_idx - 1], "text/uri-list") != 0) {
        drop_send_error(w, EINVAL); return true;
    }

    /* file_idx is 1-based, convert to 0-based for get_nth_file_url */
    if (file_idx < 1) { drop_send_error(w, EINVAL); return true; }
    int file_n = file_idx - 1;

    char *path = NULL;
    const char *err = NULL;
    if (!get_nth_file_url(w->drop.uri_list, w->drop.uri_list_sz, file_n, &path, &err)) {
        drop_send_error_str(w, err);
        return true;
    }

    struct stat st;
    if (stat(path, &st) < 0) {
        free(path);
        switch (errno) {
            case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
            default:                   drop_send_error(w, EIO); break;
        }
        return true;
    }

    bool sync;
    if (S_ISDIR(st.st_mode)) {
        drop_send_dir_listing(w, path);
        sync = true;
    } else if (S_ISREG(st.st_mode)) {
        sync = drop_send_file_data(w, path);
    } else {
        drop_send_error(w, EINVAL);
        sync = true;
    }
    free(path);
    return sync;
}

/* Handle a directory request from the client.
 * handle_id: the directory handle (Y= key).
 * entry_num: 0 means close the handle; >=1 means read that entry (x= key, 1-based).
 * Returns true if completed synchronously, false if async file I/O started. */
static bool
do_drop_handle_dir_request(Window *w, uint32_t handle_id, int32_t entry_num) {
    if (!handle_id) { drop_send_error(w, EINVAL); return true; }

    DirHandle *h = drop_find_dir_handle(w, handle_id);
    if (!h) { drop_send_error(w, EINVAL); return true; }

    if (entry_num == 0) {
        /* Close the handle */
        size_t hidx = (size_t)(h - w->drop.dir_handles);
        drop_free_dir_handle(h);
        remove_i_from_array(w->drop.dir_handles, hidx, w->drop.num_dir_handles);
        return true;
    }

    /* Read the entry at 1-based index */
    size_t eidx = (size_t)(entry_num - 1);
    if (eidx >= h->num_entries) { drop_send_error(w, ENOENT); return true; }

    char full[PATH_MAX];
    if (snprintf(full, sizeof(full), "%s/%s", h->path, h->entries[eidx]) >= (int)sizeof(full)) {
        drop_send_error(w, EIO); return true;
    }

    struct stat lst;
    if (lstat(full, &lst) < 0) {
        switch (errno) {
            case ENOENT: case ENOTDIR: case ELOOP: drop_send_error(w, ENOENT); break;
            case EACCES: case EPERM:               drop_send_error(w, EPERM); break;
            default:                               drop_send_error(w, EIO); break;
        }
        return true;
    }

    if (S_ISLNK(lst.st_mode)) {
        /* Symlink: send the symlink target as t=r:X=1 */
        char target[PATH_MAX];
        ssize_t tlen = readlink(full, target, sizeof(target) - 1);
        if (tlen < 0) {
            switch (errno) {
                case ENOENT: case ENOTDIR: drop_send_error(w, ENOENT); break;
                case EACCES: case EPERM:   drop_send_error(w, EPERM); break;
                default:                   drop_send_error(w, EIO); break;
            }
            return true;
        }
        target[tlen] = '\0';
        char hdr[128];
        int hdr_sz = snprintf(hdr, sizeof(hdr), "\x1b]%d;t=r", DND_CODE);
        hdr_sz += drop_append_request_keys(w, hdr + hdr_sz, sizeof(hdr) - hdr_sz);
        hdr_sz += snprintf(hdr + hdr_sz, sizeof(hdr) - hdr_sz, ":X=1");
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, target, (size_t)tlen, true);
        queue_payload_to_child(w->id, w->drop.client_id, &w->drop.pending, hdr, hdr_sz, NULL, 0, true);
        return true;
    }

    if (S_ISDIR(lst.st_mode)) {
        drop_send_dir_listing(w, full);
        return true;
    } else if (S_ISREG(lst.st_mode)) {
        return drop_send_file_data(w, full);
    } else {
        drop_send_error(w, EINVAL);
        return true;
    }
}

void
drop_handle_dir_request(Window *w, uint32_t handle_id, int32_t entry_num) {
    do_drop_handle_dir_request(w, handle_id, entry_num);
}

/* --- Request queue management --- */

/* Pop the head of the queue (the request that just completed). */
static void
drop_pop_request(Window *w) {
    if (w->drop.num_data_requests == 0) return;
    w->drop.num_data_requests--;
    if (w->drop.num_data_requests > 0) {
        memmove(w->drop.data_requests, w->drop.data_requests + 1,
                w->drop.num_data_requests * sizeof(w->drop.data_requests[0]));
    }
    w->drop.current_request_x = 0;
    w->drop.current_request_y = 0;
    w->drop.current_request_Y = 0;
}

static void
drop_finish_and_clear_queue(Window *w) {
    drop_close_file_fd(w);
    drop_free_request_queue(w);
    drop_finish(w);
}

/* Process queued requests in FIFO order.
 * Must be called after popping a completed request, or after enqueuing
 * the first request into an empty queue. */
static void
drop_process_queue(Window *w) {
    while (w->drop.num_data_requests > 0) {
        int32_t x = w->drop.data_requests[0].cell_x;
        int32_t y = w->drop.data_requests[0].cell_y;
        int32_t Y = w->drop.data_requests[0].pixel_y;
        w->drop.current_request_x = x;
        w->drop.current_request_y = y;
        w->drop.current_request_Y = Y;
        bool sync = true;
        if (Y != 0) {
            /* Directory request: Y=handle, x=entry_num */
            sync = do_drop_handle_dir_request(w, (uint32_t)Y, x);
        } else if (y != 0) {
            /* URI file request: x=mime_idx, y=file_idx */
            sync = do_drop_request_uri_data(w, x, y);
        } else if (x != 0) {
            /* MIME data request: x=idx */
            sync = do_drop_request_data(w, x);
        } else {
            /* Finish: x=0, y=0, Y=0 */
            drop_pop_request(w);
            drop_finish_and_clear_queue(w);
            return;
        }
        if (sync) {
            drop_pop_request(w);
            /* Loop continues to process next request */
        } else {
            /* Async operation in progress; completion will call drop_process_queue */
            return;
        }
    }
}

void
drop_enqueue_request(Window *w, int32_t cell_x, int32_t cell_y, int32_t pixel_y) {
    /* Handle finish (x=0, y=0, Y=0): if there are no in-flight requests, finish immediately */
    if (cell_x == 0 && cell_y == 0 && pixel_y == 0 && w->drop.num_data_requests == 0) {
        drop_finish_and_clear_queue(w);
        return;
    }

    if (w->drop.num_data_requests >= arraysz(w->drop.data_requests)) {
        /* Queue full: deny with EMFILE and end the drop */
        int32_t saved_x = w->drop.current_request_x;
        int32_t saved_y = w->drop.current_request_y;
        int32_t saved_Y = w->drop.current_request_Y;
        w->drop.current_request_x = cell_x;
        w->drop.current_request_y = cell_y;
        w->drop.current_request_Y = pixel_y;
        drop_send_error(w, EMFILE);
        w->drop.current_request_x = saved_x;
        w->drop.current_request_y = saved_y;
        w->drop.current_request_Y = saved_Y;
        drop_finish_and_clear_queue(w);
        return;
    }

    size_t idx = w->drop.num_data_requests;
    w->drop.data_requests[idx].cell_x = cell_x;
    w->drop.data_requests[idx].cell_y = cell_y;
    w->drop.data_requests[idx].pixel_y = pixel_y;
    bool was_empty = (w->drop.num_data_requests == 0);
    w->drop.num_data_requests++;
    if (was_empty) drop_process_queue(w);
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
// }}}

// Dragging {{{
#define ds w->drag_source

static void
drag_free_remote_item(DragRemoteItem *x) {
    free(x->dir_entry_name);
    free(x->data);
    if (x->fd_plus_one) safe_close(x->fd_plus_one-1, __FILE__, __LINE__);
    if (x->top_level_parent_dir_fd_plus_one) safe_close(x->top_level_parent_dir_fd_plus_one-1, __FILE__, __LINE__);
    if (x->children) {
        for (size_t i = 0; i < x->children_sz; i++) drag_free_remote_item(x->children + i);
        free(x->children);
    }
    zero_at_ptr(x);
}

void
drag_free_offer(Window *w) {
    free(ds.mimes_buf); ds.mimes_buf = NULL; ds.bufsz = 0;
    if (ds.items) {
        for (size_t i=0; i < ds.num_mimes; i++) {
            free(ds.items[i].optional_data);
            if (ds.items[i].fd_plus_one > 0) safe_close(ds.items[i].fd_plus_one - 1, __FILE__, __LINE__);
            if (ds.items[i].uri_list) {
                for (size_t k = 0; k < ds.items[i].num_uris; k++) free(ds.items[i].uri_list[k]);
                free(ds.items[i].uri_list);
            }
            if (ds.items[i].remote_items) {
                for (size_t k = 0; k < ds.items[i].num_remote_items; k++) drag_free_remote_item(&ds.items[i].remote_items[k]);
                free(ds.items[i].remote_items); ds.items[i].remote_items = NULL;
                ds.items[i].num_remote_items = 0;
            }
            if (ds.items[i].base_dir_fd_plus_one) {
                rmtree_best_effort(".", ds.items[i].base_dir_fd_plus_one - 1);
                ds.items[i].base_dir_fd_plus_one = 0;
            }
            free(ds.items[i].base_dir_for_remote_items); ds.items[i].base_dir_for_remote_items = NULL;
        }
        free(ds.items);
        ds.items = NULL;
    }
    ds.num_mimes = 0;
    ds.total_remote_data_size = 0;
    for (size_t i = 0; i < arraysz(ds.images); i++) {
        if (ds.images[i].data) free(ds.images[i].data);
        zero_at_ptr(ds.images + i);
    }
    free_pending(&ds.pending);
    ds.allowed_operations = 0;
    ds.state = DRAG_SOURCE_NONE;
    ds.pre_sent_total_sz = 0;
    ds.images_sent_total_sz = 0;
    zero_at_ptr(&ds.in_flight_remote_file_data);
}

static void
drag_send_error(Window *w, int error_code) {
    char buf[128];
    const char *e = get_errno_name(error_code);
    int header_size = snprintf(buf, sizeof(buf), "\x1b]%d;t=E", DND_CODE);
    queue_payload_to_child(
        w->id, w->drag_source.client_id, &w->drag_source.pending, buf, header_size, e, strlen(e), false);
}

static void
cancel_drag(Window *w, int error_code) {
    if (error_code) drag_send_error(w, error_code);
    if (global_state.drag_source.is_active && global_state.drag_source.from_window == w->id) cancel_current_drag_source();
    drag_free_offer(w);
}

#define abrt(code) { cancel_drag(w, code); return; }

void
drag_start_offerring(Window *w, const char *client_machine_id, size_t sz) {
    ds.can_offer = true;
    ds.is_remote_client = !is_same_machine(client_machine_id, sz);
}

void
drag_stop_offerring(Window *w) {
    drag_free_offer(w);
    ds.can_offer = false; ds.is_remote_client = false;
}

void
drag_add_mimes(Window *w, int allowed_operations, uint32_t client_id, const char *data, size_t sz, bool has_more) {
    if (!ds.can_offer) abrt(EINVAL);
    if (allowed_operations && !ds.allowed_operations) ds.allowed_operations = allowed_operations;
    if (!ds.allowed_operations || ds.state > DRAG_SOURCE_BEING_BUILT) abrt(EINVAL);
    ds.state = DRAG_SOURCE_BEING_BUILT;
    ds.client_id = client_id;
    size_t new_sz = ds.bufsz + sz;
    if (new_sz > MIME_LIST_SIZE_CAP) abrt(EFBIG);
    char *tmp = realloc(ds.mimes_buf, ds.bufsz + sz + 1);
    if (!tmp) abrt(ENOMEM);
    ds.mimes_buf = tmp;
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
                ds.items[ds.num_mimes].is_uri_list = strcmp(p, "text/uri-list") == 0;
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
        uint8_t *tmp = realloc(item.optional_data, newcap);
        if (!tmp) abrt(ENOMEM);
        item.optional_data = tmp;
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
        uint8_t *tmp = realloc(img.data, newcap);
        if (!tmp) abrt(ENOMEM);
        img.data = tmp;
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
    const size_t sz = (size_t)img.width * (size_t)img.height * 4u;
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
    if (ds.state < DRAG_SOURCE_STARTED) return;
    char buf[128];
    size_t sz = snprintf(buf, sizeof(buf), "\x1b]%d;t=e:x=%d", DND_CODE, type + 1);
    switch(type) {
        case DRAG_NOTIFY_ACCEPTED:
            for (size_t i = 0; i < ds.num_mimes; i++) {
                if (strcmp(ds.items[i].mime_type, global_state.drag_source.accepted_mime_type) == 0) {
                    sz += snprintf(buf + sz, sizeof(buf) - sz, ":y=%zu", i); break;
                }
            } break;
        case DRAG_NOTIFY_ACTION_CHANGED:
            switch (global_state.drag_source.action) {
                case GLFW_DRAG_OPERATION_MOVE:
                    sz += snprintf(buf + sz, sizeof(buf) - sz, ":o=2"); break;
                default:
                    sz += snprintf(buf + sz, sizeof(buf) - sz, ":o=1"); break;
            } break;
        case DRAG_NOTIFY_DROPPED: ds.state = DRAG_SOURCE_DROPPED; break;
        case DRAG_NOTIFY_FINISHED:
            sz += snprintf(buf + sz, sizeof(buf) - sz, ":y=%d", global_state.drag_source.was_canceled ? 1 : 0); break;
    }
    queue_payload_to_child(w->id, w->drag_source.client_id, &w->drag_source.pending, buf, sz, NULL, 0, false);
    if (type == DRAG_NOTIFY_FINISHED) drag_free_offer(w);
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
    if (!ds.items || ds.state < DRAG_SOURCE_DROPPED) return NULL;
    for (size_t i = 0; i < ds.num_mimes; i++) {
        if (strcmp(ds.items[i].mime_type, mime_type) == 0) {
            if (ds.items[i].fd_plus_one < 0) {
                // Error was stored by drag_process_item_data
                *err_code = -ds.items[i].fd_plus_one;
                ds.items[i].fd_plus_one = 0;
                return NULL;
            }
            if (ds.items[i].fd_plus_one > 0) {
                // data_size = read position, data_capacity = bytes written to file
                if (ds.items[i].data_capacity > ds.items[i].data_size) {
                    // Unread data available, use pread to read from read_pos
                    size_t available = ds.items[i].data_capacity - ds.items[i].data_size;
                    char *data = malloc(available);
                    if (!data) { *err_code = ENOMEM; return NULL; }
                    size_t total = 0;
                    while (total < available) {
                        ssize_t n = pread(ds.items[i].fd_plus_one - 1, data + total,
                                          available - total,
                                          (off_t)(ds.items[i].data_size + total));
                        if (n < 0) {
                            if (errno == EINTR) continue;
                            free(data);
                            *err_code = EIO;
                            return NULL;
                        }
                        if (n == 0) break;
                        total += (size_t)n;
                    }
                    ds.items[i].data_size += total;
                    *sz = total;
                    *err_code = 0;
                    return data;
                }
                // No unread data
                if (!ds.items[i].data_decode_initialized) {
                    // Transfer complete and all data read
                    *err_code = 0;
                    return NULL;
                }
                // Still receiving data from client, wait
                *err_code = EAGAIN;
                return NULL;
            }
            // No fd yet, request data from the client
            char buf[128];
            ds.items[i].requested_remote_files = ds.is_remote_client && ds.items[i].is_uri_list;
            int header_sz = snprintf(buf, sizeof(buf), "\x1b]%d;t=e:x=%d:y=%zu:Y=%d",
                    DND_CODE, DRAG_NOTIFY_FINISHED + 2, i, ds.items[i].requested_remote_files);
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
    if (sz >= 6 && memcmp(data, "EMFILE", 6) == 0) return EMFILE;
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
    if ((ds.state < DRAG_SOURCE_DROPPED) || idx >= ds.num_mimes || !ds.items) {
        abrt(EINVAL);
        return;
    }

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

    // End of data: has_more == 0 and empty payload
    if (has_more == 0 && payload_sz == 0) {
        ds.items[idx].data_decode_initialized = false;
        if (ds.items[idx].fd_plus_one > 0) {
            if (!ds.items[idx].requested_remote_files) {
                int ret = notify_drag_data_ready(global_state.drag_source.from_os_window, ds.items[idx].mime_type);
                if (ret) cancel_drag(w, ret);
            }
        }
        return;
    }

    // Open temp file if not yet open
    if (!ds.items[idx].fd_plus_one) {
        int fd = open_item_tmpfile();
        if (fd < 0) { cancel_drag(w, EIO); return; }
        ds.items[idx].fd_plus_one = fd + 1;
        ds.items[idx].data_decode_initialized = true;
        ds.items[idx].data_size = 0;     // read position for pread
        ds.items[idx].data_capacity = 0; // bytes written to file
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
            ssize_t n = safe_write(ds.items[idx].fd_plus_one - 1, decoded + written, outlen - written);
            if (n < 0) {
                cancel_drag(w, EIO);
                return;
            }
            written += (size_t)n;
        }
        ds.items[idx].data_capacity += outlen;
        // Notify as soon as any data is available
        if (!ds.items[idx].requested_remote_files) {
            int ret = notify_drag_data_ready(global_state.drag_source.from_os_window, ds.items[idx].mime_type);
            if (ret) cancel_drag(w, ret);
        }
    }
}

static char**
parse_uri_list(Window *w, int fd, size_t *num_uris_out) {
    *num_uris_out = 0;
    // Determine file size and read all data
    off_t file_size = lseek(fd, 0, SEEK_END);
    if (file_size < 0) { cancel_drag(w, EIO); return NULL; }
    if (lseek(fd, 0, SEEK_SET) < 0) { cancel_drag(w, EIO); return NULL; }
    RAII_ALLOC(char, buf, malloc((size_t)file_size + 1));
    if (!buf) { cancel_drag(w, ENOMEM); return NULL; }
    size_t total = 0;
    while (total < (size_t)file_size) {
        ssize_t n = read(fd, buf + total, (size_t)file_size - total);
        if (n < 0) {
            if (errno == EINTR) continue;
            cancel_drag(w, EIO); return NULL;
        }
        if (n == 0) break;
        total += (size_t)n;
    }
    buf[total] = '\0';

    // First pass: count non-comment, non-empty lines
    size_t count = 0;
    char *p = buf;
    while (*p) {
        char *eol = p + strcspn(p, "\r\n");
        char saved = *eol; *eol = '\0';
        char *end = eol;
        while (end > p && (end[-1] == ' ' || end[-1] == '\t')) end--;
        char saved_end = *end; *end = '\0';
        if (*p && *p != '#') count++;
        *end = saved_end;
        *eol = saved;
        if (saved == '\0') break;
        p = eol + 1;
        while (*p == '\r' || *p == '\n') p++;
    }

    char **result = calloc((count + 1), sizeof(const char*));
    if (!result) { cancel_drag(w, ENOMEM); return NULL; }

    // Second pass: fill in decoded URI strings
    size_t idx = 0;
    p = buf;
    while (*p && idx < count) {
        char *eol = p + strcspn(p, "\r\n");
        char saved = *eol; *eol = '\0';
        char *end = eol;
        while (end > p && (end[-1] == ' ' || end[-1] == '\t')) end--;
        *end = '\0';
        if (*p && *p != '#') {
            char *decoded = strdup(p);
            if (!decoded) {
                for (size_t k = 0; k < idx; k++) free((char*)result[k]);
                free(result); cancel_drag(w, ENOMEM); return NULL;
            }
            result[idx++] = decoded;
        }
        *eol = saved;
        if (saved == '\0') break;
        p = eol + 1;
        while (*p == '\r' || *p == '\n') p++;
    }
    *num_uris_out = idx;
    return result;
}

static int
write_all(int fd, const void *buf, size_t sz) {
    size_t pos = 0; const char *p = buf;
    while (pos < sz) {
        ssize_t ret = safe_write(fd, p + pos, sz - pos);
        if (ret < 0) return ret;
        pos += ret;
    }
    return 0;
}

static void
finish_remote_data(Window *w, size_t item_idx) {
    const int fd = ds.items[item_idx].fd_plus_one - 1;
    if (safe_ftruncate(fd, 0) != 0) abrt(errno);
    if (lseek(fd, 0, SEEK_SET) == -1) abrt(errno);
    for (size_t i = 0; i < ds.items[item_idx].num_uris; i++) {
        int ret = write_all(fd, ds.items[item_idx].uri_list[i], strlen(ds.items[item_idx].uri_list[i]));
        free((char*)ds.items[item_idx].uri_list[i]); ds.items[item_idx].uri_list[i] = NULL;
        if (ret) abrt(ret);
        if ((ret = write_all(fd, "\r\n", 2))) abrt(ret);
    }
    free(ds.items[item_idx].uri_list); ds.items[item_idx].uri_list = NULL; ds.items[item_idx].num_uris = 0;
    int ret = notify_drag_data_ready(global_state.drag_source.from_os_window, ds.items[item_idx].mime_type);
    abrt(ret);
}

#define mi ds.items[mime_item_idx]

static void
populate_dir_entries(Window *w, DragRemoteItem *ri) {
    size_t num = count_occurrences((char*)ri->data, ri->data_sz, 0) + 1;
    ri->children = calloc(num + 1, sizeof(ri->children[0]));
    if (!ri->children) abrt(ENOMEM);
    ri->children_sz = 0;
    const char *ptr = (char*)ri->data;
    const char *end = (char*)ri->data + ri->data_sz;
    while (ptr < end) {
        const char *p = memchr(ptr, 0, (size_t)(end - ptr));
        size_t len = p ? (size_t)(p - ptr) : (size_t)(end - ptr);
        if (len > 0) {
            char *name = strndup(ptr, len);
            if (!name) abrt(ENOMEM);
            ri->children[ri->children_sz++].dir_entry_name = name;
        }
        ptr = p ? p + 1 : end;
    }
}

static void
add_payload(Window *w, DragRemoteItem *ri, bool has_more, const uint8_t *payload, size_t payload_sz, int dirfd) {
    if (payload_sz && payload) {
        if (payload_sz > 4096) abrt(EINVAL);
        switch (ri->type) {
            case 0: {
                if (!ri->fd_plus_one) {
                    int fd = safe_openat(dirfd, ri->dir_entry_name, O_CREAT | O_WRONLY, file_permissions);
                    if (fd < 0) abrt(errno);
                    ri->fd_plus_one = fd + 1;
                }
                uint8_t buf[4096];
                size_t outlen = sizeof(buf);
                if (!base64_decode_stream(&ri->base64_state, payload, payload_sz, buf, &outlen)) abrt(EINVAL);
                ds.total_remote_data_size += outlen;
                if (outlen && write_all(ri->fd_plus_one-1, buf, outlen) < 0) abrt(errno);
            } break;
            default: {
                if (ri->data_sz + payload_sz > ri->data_capacity) {
                    size_t cap = MAX(ri->data_capacity * 2, ri->data_sz + payload_sz + 4096);
                    if (cap > PRESENT_DATA_CAP) abrt(EMFILE);
                    uint8_t *tmp = realloc(ri->data, cap);
                    if (!tmp) abrt(ENOMEM);
                    ri->data = tmp;
                    ri->data_capacity = cap;
                }
                size_t outlen = ri->data_capacity - ri->data_sz;
                if (!base64_decode_stream(&ri->base64_state, payload, payload_sz, ri->data + ri->data_sz, &outlen)) abrt(EINVAL);
                ds.total_remote_data_size += outlen;
                ri->data_sz += outlen;
            } break;
        }
    }
    if (ds.total_remote_data_size > REMOTE_DRAG_LIMIT) abrt(EMFILE);
    if (!has_more && !payload_sz) {  // all data received
        switch (ri->type) {
            case 0:
                safe_close(ri->fd_plus_one-1, __FILE__, __LINE__);
                ri->fd_plus_one = 0;
                break;
            case 1:
                // Ensure room for the null terminator needed by symlinkat
                if (ri->data_sz >= ri->data_capacity) {
                    uint8_t *tmp = realloc(ri->data, ri->data_sz + 1);
                    if (!tmp) abrt(ENOMEM);
                    ri->data = tmp;
                    ri->data_capacity = ri->data_sz + 1;
                }
                ri->data[ri->data_sz] = 0;
                if (symlinkat((char*)ri->data, dirfd, ri->dir_entry_name) != 0) abrt(errno);
                break;
            default:
                if (mkdirat(dirfd, ri->dir_entry_name, dir_permissions) != 0 && errno != EEXIST) abrt(errno);
                populate_dir_entries(w, ri);
                break;
        }
        free(ri->data); ri->data = 0; ri->data_capacity = 0; ri->data_sz = 0;
    }

}

static void
toplevel_data_for_drag(
    Window *w, unsigned mime_item_idx, unsigned uri_item_idx, unsigned item_type,
    bool has_more, const uint8_t *payload, size_t payload_sz
) {
    if (!mi.remote_items) {
        mi.remote_items = calloc(mi.num_uris, sizeof(mi.remote_items[0]));
        if (!mi.remote_items) abrt(ENOMEM);
        mi.num_remote_items = mi.num_uris;
    }
    if (!mi.base_dir_for_remote_items) {
        int fd;
        mi.base_dir_for_remote_items = mktempdir_in_cache("dnd-drag-", &fd);
        if (!mi.base_dir_for_remote_items) abrt(errno);
        mi.base_dir_fd_plus_one = fd + 1;
    }
    if (uri_item_idx >= mi.num_remote_items) abrt(EINVAL);
    DragRemoteItem *ri = mi.remote_items + uri_item_idx;
    if (!ri->started) {
        ri->started = true;
        ri->type = item_type;
        base64_init_stream_decoder(&ri->base64_state);
        if (uri_item_idx >= mi.num_uris) abrt(EINVAL);
        const char *uri = mi.uri_list[uri_item_idx];
        char *fname = sanitized_filename_from_url(uri);
        if (!fname) abrt(EINVAL);
        ri->dir_entry_name = fname;
        char path[32];
        snprintf(path, sizeof(path), "%u", uri_item_idx);
        if (mkdirat(mi.base_dir_fd_plus_one - 1, path, dir_permissions) != 0 && errno != EEXIST) abrt(errno);
        int fd = safe_openat(mi.base_dir_fd_plus_one - 1, path, O_RDONLY | O_DIRECTORY, 0);
        if (fd < 0) abrt(errno);
        ri->top_level_parent_dir_fd_plus_one = fd + 1;
        free(mi.uri_list[uri_item_idx]);
        mi.uri_list[uri_item_idx] = as_file_url(mi.base_dir_for_remote_items, path, ri->dir_entry_name);
    }
    add_payload(w, ri, has_more, payload, payload_sz, ri->top_level_parent_dir_fd_plus_one - 1);
}

static DragRemoteItem*
find_by_handle(DragRemoteItem *parent, int handle, char *path_to_parent, size_t *path_len) {
    if (parent->type == handle) return parent;
    DragRemoteItem *x;
    for (size_t i = 0; i < parent->children_sz; i++) {
        DragRemoteItem *child = parent->children + i;
        size_t before = *path_len;
        size_t n = snprintf(path_to_parent + before, PATH_MAX - before, "/%s", child->dir_entry_name);
        if (n + before + 1 >= PATH_MAX) return NULL;
        *path_len += n;
        if ((x = find_by_handle(parent->children + i, handle, path_to_parent, path_len))) return x;
        *path_len = before;
    }
    return NULL;
}

static void
subdir_data_for_drag(
    Window *w, unsigned mime_item_idx, unsigned uri_item_idx, int handle, unsigned entry_num, unsigned item_type,
    bool has_more, const uint8_t *payload, size_t payload_sz
) {
    if (!mi.remote_items || uri_item_idx >= mi.num_remote_items) abrt(EINVAL);
    DragRemoteItem *parent = NULL;
    if (mi.currently_open_subdir) {
        if (mi.currently_open_subdir->type == handle) parent = mi.currently_open_subdir;
        else {
            if (mi.currently_open_subdir->fd_plus_one) {
                safe_close(mi.currently_open_subdir->fd_plus_one - 1, __FILE__, __LINE__);
                mi.currently_open_subdir->fd_plus_one = 0;
            }
            mi.currently_open_subdir = NULL;
        }
    }
    if (parent == NULL || !parent->fd_plus_one) {
        char path[PATH_MAX+1]; path[PATH_MAX] = 0;
        DragRemoteItem *root = mi.remote_items + uri_item_idx;
        if (!root->dir_entry_name) abrt(EINVAL);
        size_t pos = snprintf(path, PATH_MAX, "%s/%u/%s",
            mi.base_dir_for_remote_items, uri_item_idx, root->dir_entry_name);
        parent = find_by_handle(root, handle, path, &pos);
        if (!parent) abrt(EINVAL);
        mi.currently_open_subdir = parent;
        if (!parent->fd_plus_one) {
            int fd = safe_open(path, O_DIRECTORY | O_RDONLY, 0);
            if (fd < 0) abrt(errno);
            parent->fd_plus_one = fd + 1;
        }
    }
    if (entry_num >= parent->children_sz) abrt(EINVAL);
    DragRemoteItem *ri = parent->children + entry_num;
    if (!ri->started) {
        ri->started = true;
        ri->type = item_type;
        base64_init_stream_decoder(&ri->base64_state);
    }
    add_payload(w, ri, has_more, payload, payload_sz, parent->fd_plus_one - 1);
}
#undef mi

void
drag_remote_file_data(
    Window *w, int32_t x, int32_t y, int32_t X, int32_t Y, bool has_more, const uint8_t *payload, size_t payload_sz
) {
    if (ds.in_flight_remote_file_data.active) {
        x = ds.in_flight_remote_file_data.x; y = ds.in_flight_remote_file_data.y;
        ds.in_flight_remote_file_data.Y = Y; ds.in_flight_remote_file_data.X = X;
    }
    if (!has_more) zero_at_ptr(&ds.in_flight_remote_file_data);
    else if (!ds.in_flight_remote_file_data.active) {
        ds.in_flight_remote_file_data.active = true;
        ds.in_flight_remote_file_data.x = x; ds.in_flight_remote_file_data.y = y;
        ds.in_flight_remote_file_data.Y = Y; ds.in_flight_remote_file_data.X = X;
    }
    size_t item_idx = ds.num_mimes;
    for (size_t i = 0; i < ds.num_mimes; i++) {
        if (ds.items[i].requested_remote_files) {
            item_idx = i; break;
        }
    }
    if (item_idx == ds.num_mimes || ds.items[item_idx].fd_plus_one == 0) abrt(EINVAL);
    if (ds.items[item_idx].uri_list == NULL) {
        ds.items[item_idx].uri_list = parse_uri_list(w, ds.items[item_idx].fd_plus_one-1, &ds.items[item_idx].num_uris);
        if (!ds.items[item_idx].uri_list) return;
    }
    if (X < 0) abrt(EINVAL);
    if (!x && !y && !Y) { finish_remote_data(w, item_idx); return; }
    if (!Y) toplevel_data_for_drag(w, item_idx, x - 1, X, has_more, payload, payload_sz);
    else subdir_data_for_drag(w, item_idx, x - 1, Y, y - 1, X, has_more, payload, payload_sz);
}
#undef img
#undef abrt
#undef ds
// }}}

// DnD testing infrastructure {{{

static PyObject *
py_dnd_set_test_write_func(PyObject *self UNUSED, PyObject *args) {
    PyObject *func = Py_None; unsigned mime_list_size_cap = 0, present_data_cap = 0, remote_drag_limit = 0;
    if (!PyArg_ParseTuple(args, "|OIII", &func, &mime_list_size_cap, &present_data_cap, &remote_drag_limit)) return NULL;
    // Pass None to clear the interceptor and restore normal operation.
    dnd_set_test_write_func(func == Py_None ? NULL : func, mime_list_size_cap, present_data_cap, remote_drag_limit);
    Py_RETURN_NONE;
}

static void
destroy_fake_window_contents(Window *w) {
    // Free window resources without touching GPU objects (none allocated for fake windows).
    drop_free_data(w);
    drag_free_offer(w);
    free(w->pending_clicks.clicks); zero_at_ptr(&w->pending_clicks);
    free(w->buffered_keys.key_data); zero_at_ptr(&w->buffered_keys);
    Py_CLEAR(w->render_data.screen);
    Py_CLEAR(w->title);
    Py_CLEAR(w->title_bar_data.last_drawn_title_object_id);
    free(w->title_bar_data.buf); w->title_bar_data.buf = NULL;
    Py_CLEAR(w->url_target_bar_data.last_drawn_title_object_id);
    free(w->url_target_bar_data.buf); w->url_target_bar_data.buf = NULL;
    // render_data.vao_idx is -1 so release_gpu_resources_for_window is safe, but we skip it
    // since we never allocated those resources.
}

static PyObject *
dnd_test_create_fake_window(PyObject *self UNUSED, PyObject *args UNUSED) {
    // Create a minimal OS window + tab + window without any OpenGL/GPU resources.
    // Returns (os_window_id, window_id).
    ensure_space_for(&global_state, os_windows, OSWindow, global_state.num_os_windows + 1, capacity, 1, true);
    OSWindow *osw = global_state.os_windows + global_state.num_os_windows++;
    zero_at_ptr(osw);
    osw->id = ++global_state.os_window_id_counter;
    osw->tab_bar_render_data.vao_idx = -1;
    osw->background_opacity.alpha = OPT(background_opacity);
    osw->created_at = monotonic();
    // osw->handle intentionally left NULL - no real GLFW window

    ensure_space_for(osw, tabs, Tab, 1, capacity, 1, true);
    Tab *tab = &osw->tabs[0];
    zero_at_ptr(tab);
    tab->id = ++global_state.tab_id_counter;
    tab->border_rects.vao_idx = -1;
    osw->num_tabs = 1;
    osw->active_tab = 0;

    ensure_space_for(tab, windows, Window, 1, capacity, 1, true);
    Window *w = &tab->windows[0];
    zero_at_ptr(w);
    w->id = ++global_state.window_id_counter;
    w->visible = true;
    w->render_data.vao_idx = -1;
    w->window_title_render_data.vao_idx = -1;
    w->drop.wanted = true;
    tab->num_windows = 1;
    tab->active_window = 0;

    global_state.mouse_hover_in_window = w->id;
    return Py_BuildValue("KK", (unsigned long long)osw->id, (unsigned long long)w->id);
}

static PyObject *
dnd_test_cleanup_fake_window(PyObject *self UNUSED, PyObject *args) {
    unsigned long long os_window_id;
    if (!PyArg_ParseTuple(args, "K", &os_window_id)) return NULL;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].id == (id_type)os_window_id) {
            OSWindow *osw = global_state.os_windows + i;
            for (size_t t = 0; t < osw->num_tabs; t++) {
                Tab *tab = osw->tabs + t;
                for (size_t j = 0; j < tab->num_windows; j++) {
                    Window *win = tab->windows + j;
                    if (global_state.mouse_hover_in_window == win->id)
                        global_state.mouse_hover_in_window = 0;
                    destroy_fake_window_contents(win);
                }
                free(tab->border_rects.rect_buf); tab->border_rects.rect_buf = NULL;
                free(tab->windows); tab->windows = NULL;
            }
            Py_CLEAR(osw->window_title);
            Py_CLEAR(osw->tab_bar_render_data.screen);
            free(osw->tabs); osw->tabs = NULL;
            remove_i_from_array(global_state.os_windows, i, global_state.num_os_windows);
            break;
        }
    }
    Py_RETURN_NONE;
}

static PyObject *
dnd_test_set_mouse_pos(PyObject *self UNUSED, PyObject *args) {
    unsigned long long window_id;
    int cell_x, cell_y, pixel_x, pixel_y;
    if (!PyArg_ParseTuple(args, "Kiiii", &window_id, &cell_x, &cell_y, &pixel_x, &pixel_y)) return NULL;
    Window *w = window_for_window_id((id_type)window_id);
    if (!w) { PyErr_SetString(PyExc_ValueError, "Window not found"); return NULL; }
    w->mouse_pos.cell_x = (unsigned int)cell_x;
    w->mouse_pos.cell_y = (unsigned int)cell_y;
    w->mouse_pos.global_x = pixel_x;
    w->mouse_pos.global_y = pixel_y;
    Py_RETURN_NONE;
}

static PyObject *
dnd_test_fake_drop_event(PyObject *self UNUSED, PyObject *args) {
    // Simulate a drop enter/move/drop event. mimes_seq must be a sequence of str, or
    // None to simulate a leave event.
    unsigned long long window_id;
    int is_drop;
    PyObject *mimes_seq;
    if (!PyArg_ParseTuple(args, "KpO", &window_id, &is_drop, &mimes_seq)) return NULL;
    Window *w = window_for_window_id((id_type)window_id);
    if (!w) { PyErr_SetString(PyExc_ValueError, "Window not found"); return NULL; }
    if (mimes_seq == Py_None) {
        drop_left_child(w);
        Py_RETURN_NONE;
    }
    RAII_PyObject(fast_seq, PySequence_Fast(mimes_seq, "mimes must be a sequence"));
    if (!fast_seq) return NULL;
    Py_ssize_t num_mimes = PySequence_Fast_GET_SIZE(fast_seq);
    RAII_ALLOC(const char*, mimes, malloc(sizeof(const char*) * (num_mimes ? num_mimes : 1)));
    if (!mimes) return PyErr_NoMemory();
    for (Py_ssize_t i = 0; i < num_mimes; i++) {
        mimes[i] = PyUnicode_AsUTF8(PySequence_Fast_GET_ITEM(fast_seq, i));
        if (!mimes[i]) return NULL;
    }
    drop_move_on_child(w, mimes, (size_t)num_mimes, is_drop ? true : false);
    Py_RETURN_NONE;
}

static PyObject *
dnd_test_fake_drop_data(PyObject *self UNUSED, PyObject *args) {
    // Simulate OS delivering drop data for the given MIME type.
    // If error_code > 0, simulate an error (e.g. ENOENT=2, EIO=5, EPERM=1).
    // Otherwise deliver data and the mandatory end-of-data signal.
    unsigned long long window_id;
    const char *mime;
    RAII_PY_BUFFER(data);
    int error_code = 0;
    if (!PyArg_ParseTuple(args, "Ksy*|i", &window_id, &mime, &data, &error_code)) return NULL;
    Window *w = window_for_window_id((id_type)window_id);
    if (!w) { PyErr_SetString(PyExc_ValueError, "Window not found"); return NULL; }
    if (error_code > 0) {
        drop_dispatch_data(w, mime, NULL, -(ssize_t)error_code);
    } else if (data.len > 0) {
        drop_dispatch_data(w, mime, (const char*)data.buf, (ssize_t)data.len);
        drop_dispatch_data(w, mime, NULL, 0);  // mandatory end-of-data signal
    } else {
        // Empty data: just the end-of-data signal (sz=0 is the sentinel for "no more data").
        drop_dispatch_data(w, mime, NULL, 0);
    }
    Py_RETURN_NONE;
}

static PyObject *
dnd_test_force_drag_dropped(PyObject *self UNUSED, PyObject *args) {
    // Force the drag source state to DROPPED for testing purposes.
    // This simulates what would happen after start_window_drag() succeeds
    // and the drop target receives the data.
    unsigned long long window_id;
    if (!PyArg_ParseTuple(args, "K", &window_id)) return NULL;
    Window *w = window_for_window_id((id_type)window_id);
    if (!w) { PyErr_SetString(PyExc_ValueError, "Window not found"); return NULL; }
    if (w->drag_source.state != DRAG_SOURCE_BEING_BUILT) {
        PyErr_SetString(PyExc_ValueError, "Drag source state is not BEING_BUILT");
        return NULL;
    }
    // Simulate what drag_start does on success, without calling start_window_drag
    for (size_t i = 0; i < w->drag_source.num_mimes; i++) {
        free(w->drag_source.items[i].optional_data);
        w->drag_source.items[i].optional_data = NULL;
        w->drag_source.items[i].data_size = 0;
        w->drag_source.items[i].data_capacity = 0;
        w->drag_source.items[i].data_decode_initialized = false;
    }
    for (size_t i = 0; i < arraysz(w->drag_source.images); i++) {
        if (w->drag_source.images[i].data) free(w->drag_source.images[i].data);
        zero_at_ptr(w->drag_source.images + i);
    }
    w->drag_source.state = DRAG_SOURCE_DROPPED;
    Py_RETURN_NONE;
}

static PyObject *
dnd_test_request_drag_data(PyObject *self UNUSED, PyObject *args) {
    // Simulate what drag_get_data does initially: find the MIME item at the
    // given index, set requested_remote_files if appropriate, and return the
    // escape code that would be sent to the client.
    unsigned long long window_id;
    unsigned idx;
    if (!PyArg_ParseTuple(args, "KI", &window_id, &idx)) return NULL;
    Window *w = window_for_window_id((id_type)window_id);
    if (!w) { PyErr_SetString(PyExc_ValueError, "Window not found"); return NULL; }
    if (w->drag_source.state < DRAG_SOURCE_DROPPED || idx >= w->drag_source.num_mimes || !w->drag_source.items) {
        PyErr_SetString(PyExc_ValueError, "Invalid state or index"); return NULL;
    }
    w->drag_source.items[idx].requested_remote_files = w->drag_source.is_remote_client && w->drag_source.items[idx].is_uri_list;
    Py_RETURN_NONE;
}

static PyObject *
dnd_test_drag_notify(PyObject *self UNUSED, PyObject *args) {
    // Call drag_notify with a specific type for testing the protocol output.
    // type: 0=ACCEPTED, 1=ACTION_CHANGED, 2=DROPPED, 3=FINISHED
    // accepted_mime: the MIME type to set in global_state.drag_source.accepted_mime_type (for ACCEPTED)
    // action: the action to set in global_state.drag_source.action (for ACTION_CHANGED)
    // was_canceled: whether the drag was canceled (for FINISHED)
    unsigned long long window_id;
    int type;
    const char *accepted_mime = NULL;
    int action = 0, was_canceled = 0;
    if (!PyArg_ParseTuple(args, "Ki|sii", &window_id, &type, &accepted_mime, &action, &was_canceled)) return NULL;
    Window *w = window_for_window_id((id_type)window_id);
    if (!w) { PyErr_SetString(PyExc_ValueError, "Window not found"); return NULL; }
    if (type < 0 || type > 3) { PyErr_SetString(PyExc_ValueError, "Invalid type"); return NULL; }
    if (accepted_mime && *accepted_mime) {
        free(global_state.drag_source.accepted_mime_type);
        global_state.drag_source.accepted_mime_type = strdup(accepted_mime);
        if (!global_state.drag_source.accepted_mime_type) { PyErr_NoMemory(); return NULL; }
    }
    global_state.drag_source.action = action;
    global_state.drag_source.was_canceled = was_canceled;
    drag_notify(w, (DragNotifyType)type);
    Py_RETURN_NONE;
}

static PyMethodDef dnd_methods[] = {
    {"dnd_set_test_write_func", (PyCFunction)py_dnd_set_test_write_func, METH_VARARGS, ""},
    METHODB(dnd_test_create_fake_window, METH_NOARGS),
    METHODB(dnd_test_cleanup_fake_window, METH_VARARGS),
    METHODB(dnd_test_set_mouse_pos, METH_VARARGS),
    METHODB(dnd_test_fake_drop_event, METH_VARARGS),
    METHODB(dnd_test_fake_drop_data, METH_VARARGS),
    METHODB(dnd_test_force_drag_dropped, METH_VARARGS),
    METHODB(dnd_test_request_drag_data, METH_VARARGS),
    METHODB(dnd_test_drag_notify, METH_VARARGS),
    {NULL, NULL, 0, NULL}
};

bool
init_dnd(PyObject *m) {
    if (PyModule_AddFunctions(m, dnd_methods) != 0) return false;
    return true;
}
// }}}
