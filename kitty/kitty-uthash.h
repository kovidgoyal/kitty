/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#define uthash_fatal(msg) fatal(msg)
#define hash_handle_type UT_hash_handle
#include "../3rdparty/uthash.h"
