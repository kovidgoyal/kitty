/*
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

PyObject* create_disk_cache(void);
bool add_to_disk_cache(PyObject *self, const void *key, size_t key_sz, const uint8_t *data, size_t data_sz);
bool remove_from_disk_cache(PyObject *self_, const void *key, size_t key_sz);
bool read_from_disk_cache(PyObject *self_, const void *key, size_t key_sz, uint8_t **data, size_t *data_sz);
