/*
 * savepoints.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

Savepoint* savepoints_push(SavepointBuffer *self) {
    Savepoint *ans = self->buf + ((self->start_of_data + self->count) % SAVEPOINTS_SZ);
    if (self->count == SAVEPOINTS_SZ) self->start_of_data = (self->start_of_data + 1) % SAVEPOINTS_SZ;
    else self->count++;
    return ans;
}

Savepoint* savepoints_pop(SavepointBuffer *self) {
    if (self->count == 0) return NULL;
    self->count--;
    return self->buf + ((self->start_of_data + self->count) % SAVEPOINTS_SZ);
}
