/*
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

// Create a Secret object containing a copy of data
PyObject *secret_from_data(const void *data, size_t len);
// Get the data of a Secret object, without copying it. Sets a Python exception and returns false if obj is not a Secret.
bool secret_data(PyObject *obj, const void **data, size_t *len);
