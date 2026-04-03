/*
 * dnd.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */
#pragma once

#include "state.h"

void drop_register_window(Window *w, const uint8_t *payload, size_t payload_sz, bool on, uint32_t client_id, bool more);
void drop_move_on_child(Window *w, const char **mimes, size_t num_mimes, bool is_drop);
void drop_left_child(Window *w);
void drop_free_data(Window *w);
void drop_request_data(Window *w, const char *mime);
void drop_send_einval(Window *w);
void drop_request_uri_data(Window *w, const char *payload, size_t payload_sz);
void drop_handle_dir_request(Window *w, uint32_t handle_id, int32_t entry_num);
void drop_set_status(Window *w, int operation, const char *payload, size_t payload_sz, bool more);
size_t drop_update_mimes(Window *w, const char **allowed_mimes, size_t allowed_mimes_count);
void drop_dispatch_data(Window *w, const char *mime_type, const char *data, ssize_t sz);
void drop_finish(Window *w);
void dnd_set_test_write_func(PyObject *func);


void drag_free_offer(Window *w);
