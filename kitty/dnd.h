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
void drop_send_einval(Window *w);
void drop_request_uri_data(Window *w, const char *payload, size_t payload_sz);
void drop_handle_dir_request(Window *w, uint32_t handle_id, int32_t entry_num);
void drop_enqueue_request(Window *w, int32_t cell_x, int32_t cell_y, int32_t pixel_y);
void drop_set_status(Window *w, int operation, const char *payload, size_t payload_sz, bool more);
size_t drop_update_mimes(Window *w, const char **allowed_mimes, size_t allowed_mimes_count);
void drop_dispatch_data(Window *w, const char *mime_type, const char *data, ssize_t sz);
void drop_finish(Window *w);
void dnd_set_test_write_func(PyObject *func);


typedef enum { DRAG_NOTIFY_ACCEPTED, DRAG_NOTIFY_ACTION_CHANGED, DRAG_NOTIFY_DROPPED, DRAG_NOTIFY_FINISHED } DragNotifyType;
void drag_free_offer(Window *w);
void drag_add_mimes(Window *w, int allowed_operations, uint32_t client_id, const char *data, size_t sz, bool has_more);
void drag_add_pre_sent_data(Window *w, unsigned idx, const uint8_t *payload, size_t sz);
void drag_add_image(Window *w, unsigned idx_, int fmt, int width, int height, const uint8_t *payload, size_t sz);
void drag_change_image(Window *w, unsigned idx);
void drag_start(Window *w);
void drag_notify(Window *w, DragNotifyType type);
int drag_free_data(Window *w, const char *mime_type, const char* data, size_t sz);
const char* drag_get_data(Window *w, const char *mime_type, size_t *sz, int *err_code);
void drag_process_item_data(Window *w, size_t idx, int has_more, const uint8_t *payload, size_t payload_sz);
void drag_receive_remote_data(Window *w, int32_t cell_x, int32_t cell_y, int32_t pixel_x, int32_t pixel_y, unsigned more, const uint8_t *payload, size_t payload_sz);
extern size_t remote_drag_max_bytes;
