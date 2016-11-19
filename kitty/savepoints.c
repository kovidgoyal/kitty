/*
 * savepoints.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#define ADVANCE(x) \
    self->x = (self->x >= self->buf + SAVEPOINTS_SZ - 1) ? self->buf : self->x + 1;

#define RETREAT(x) \
    self->x = self->x == self->buf ? self->buf + SAVEPOINTS_SZ - 1 : self->x - 1;

Savepoint* savepoints_push(SavepointBuffer *self) {
    ADVANCE(end_of_data);
    if (self->end_of_data == self->start_of_data) ADVANCE(start_of_data);
    return self->end_of_data;
}

Savepoint* savepoints_pop(SavepointBuffer *self) {
    if (self->start_of_data == self->end_of_data) return NULL;
    RETREAT(end_of_data);
    return self->end_of_data;
}

void savepoints_init(SavepointBuffer *self) {
    self->end_of_data = self->buf;
    self->start_of_data = self->buf;
}
