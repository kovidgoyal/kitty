/*
 * buffers.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Buffers, see internal.h for how they preserve the OpenGL semantics kitty relies on

#include "internal.h"

#define AS_BUFFER(handle) ((Buffer *)(uintptr_t)(handle))

// Storage {{{
static bool
create_storage(Driver *d, size_t size, BufferStorage *ans) {
    *ans = (BufferStorage){.size = size};
    // Metal does not allow buffers of size zero
    ans->buffer = [d->device newBufferWithLength:MAX((size_t)16u, size) options:MTLResourceStorageModeShared];
    if (ans->buffer == nil) {
        set_error(d, "Failed to allocate a GPU buffer of size %zu", size);
        return false;
    }
    return true;
}

static void
destroy_storage(BufferStorage *s) {
    // Command buffers retain the buffers they use, so it can be released immediately
    [s->buffer release];
    *s = (BufferStorage){0};
}

static void
free_buffer(Buffer *b) {
    destroy_storage(&b->storage);
    for (size_t i = 0; i < b->num_retired; i++) destroy_storage(b->retired + i);
    b->num_retired = 0;
    [b->repacked.buffer release];
    b->repacked.buffer = nil;
}

// Get storage of the specified size that no commands use, reusing retired storage if possible
static bool
fresh_storage(Driver *d, Buffer *b, size_t size, BufferStorage *ans) {
    const uint64_t done = completed_serial(d);
    for (size_t i = 0; i < b->num_retired; i++) {
        BufferStorage *s = b->retired + i;
        if (s->size == size && s->last_use_serial <= done) {
            *ans = *s;
            b->retired[i] = b->retired[--b->num_retired];
            return true;
        }
    }
    return create_storage(d, size, ans);
}

static void
retire_storage(Buffer *b, BufferStorage *s) {
    if (s->buffer == nil) return;
    if (b->num_retired >= arraysz(b->retired)) {
        // Drop the oldest retired storage
        destroy_storage(b->retired);
        memmove(b->retired, b->retired + 1, (b->num_retired - 1) * sizeof(BufferStorage));
        b->num_retired--;
    }
    b->retired[b->num_retired++] = *s;
    *s = (BufferStorage){0};
}

// Ensure the current storage of the buffer is not used by any commands,
// preserving its contents if preserve is true
static void
make_writable(Driver *d, Buffer *b, bool preserve) {
    b->generation++;
    if (b->storage.last_use_serial <= completed_serial(d)) return;
    BufferStorage s;
    if (!fresh_storage(d, b, b->storage.size, &s)) fatal(d, "Failed to allocate a GPU buffer with error: %s", d->last_error);
    // Only the CPU writes to buffers, so the old contents are current
    if (preserve) memcpy([s.buffer contents], [b->storage.buffer contents], b->storage.size);
    retire_storage(b, &b->storage);
    b->storage = s;
}
// }}}

// API {{{
gpu_buffer_t
buffer_create(void *driver, GPUBufferKind kind) {
    Driver *d = driver;
    Buffer *b = calloc(1, sizeof(Buffer));
    if (!b) {
        set_error(d, "Out of memory");
        return GPU_NULL_HANDLE;
    }
    b->kind = kind;
    b->frequency = GPU_UPDATE_RARELY;
    LIST_ADD(d->buffers, b);
    return AS_HANDLE(b);
}

void
buffer_destroy(void *driver, gpu_buffer_t buffer) {
    Driver *d = driver;
    Buffer *b = AS_BUFFER(buffer);
    if (!b) return;
    for (size_t i = 0; i < arraysz(d->bound_buffers); i++) {
        if (d->bound_buffers[i] == b) d->bound_buffers[i] = NULL;
    }
    free_buffer(b);
    LIST_REMOVE(d->buffers, b);
    free(b);
}

void
destroy_all_buffers(Driver *d) {
    while (d->buffers) buffer_destroy(d, AS_HANDLE(d->buffers));
}

void
buffer_allocate(void *driver, gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency) {
    Driver *d = driver;
    Buffer *b = AS_BUFFER(buffer);
    b->frequency = frequency;
    if (b->storage.buffer != nil && b->storage.size == size) return;
    // Retired storage of a different size is useless
    free_buffer(b);
    b->generation++;
    if (!size) return;
    if (!create_storage(d, size, &b->storage)) fatal(d, "Failed to allocate a GPU buffer of size %zu with error: %s", size, d->last_error);
}

void *
buffer_map(void *driver, gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size) {
    Driver *d = driver;
    Buffer *b = AS_BUFFER(buffer);
    if (b->storage.buffer == nil) return NULL;
    switch (mode) {
        case GPU_MAP_READ: return [b->storage.buffer contents];
        case GPU_MAP_WRITE: make_writable(d, b, true); return [b->storage.buffer contents];
        case GPU_MAP_WRITE_DISCARD_ALL: make_writable(d, b, false); return (uint8_t *)[b->storage.buffer contents] + offset;
        case GPU_MAP_WRITE_DISCARD_RANGE:
            // The contents outside the range must be preserved
            make_writable(d, b, offset > 0 || size < b->storage.size);
            return (uint8_t *)[b->storage.buffer contents] + offset;
    }
    return NULL;
}

void
buffer_unmap(void *driver UNUSED, gpu_buffer_t buffer UNUSED) {
    // Buffers are in shared memory, which is coherent, and are always mapped
}

void
buffer_copy(void *driver, gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size) {
    Driver *d = driver;
    Buffer *s = AS_BUFFER(src), *t = AS_BUFFER(dst);
    if (!size || s->storage.buffer == nil || t->storage.buffer == nil) return;
    if (src_offset + size > s->storage.size || dst_offset + size > t->storage.size) {
        log_error(d, "Out of bounds GPU buffer copy");
        return;
    }
    // Only the CPU writes to buffers, so copies are done by the CPU too
    make_writable(d, t, true);
    memmove((uint8_t *)[t->storage.buffer contents] + dst_offset, (uint8_t *)[s->storage.buffer contents] + src_offset, size);
}

bool
write_buffer(Driver *d, Buffer *b, const void *data, size_t size) {
    if (b->storage.buffer == nil || b->storage.size < size) return false;
    make_writable(d, b, size < b->storage.size);
    memcpy([b->storage.buffer contents], data, size);
    return true;
}

void
bind_uniform_buffer(void *driver, uint32_t slot, gpu_buffer_t buffer) {
    Driver *d = driver;
    if (slot >= MAX_BINDING_SLOTS) {
        log_error(d, "Invalid uniform buffer binding slot: %u", slot);
        return;
    }
    d->bound_buffers[slot] = AS_BUFFER(buffer);
}

void
use_buffer(Driver *d, Buffer *b) {
    b->storage.last_use_serial = recording_serial(d);
}
// }}}

// Vertex buffers {{{
// Metal requires the offsets and strides of vertex buffers to be multiples
// of four bytes. kitty has vertex inputs with one byte elements that are
// tightly packed, such as the selection state of cells, whose elements are
// copied into a buffer where each element starts at a multiple of four bytes.
// The copy is cached with the buffer, it is made again only when the
// contents of the buffer change.
static bool
needs_repack(const VertexAttribute *a) {
    return (a->offset % 4) != 0 || (a->stride % 4) != 0;
}

uint32_t
vertex_buffer_stride(const VertexAttribute *a, size_t element_size) {
    return needs_repack(a) ? (uint32_t)((element_size + 3u) / 4u * 4u) : a->stride;
}

id<MTLBuffer>
vertex_buffer_for(Driver *d, const VertexAttribute *a, size_t element_size, size_t *offset, uint32_t *stride) {
    Buffer *b = a->buffer;
    if (!b || b->storage.buffer == nil) return nil;
    use_buffer(d, b);
    if (!needs_repack(a)) {
        *offset = a->offset;
        *stride = a->stride;
        return b->storage.buffer;
    }
    const uint32_t new_stride = vertex_buffer_stride(a, element_size);
    *offset = 0;
    *stride = new_stride;
    if (b->repacked.buffer != nil && b->repacked.generation == b->generation && b->repacked.offset == a->offset && b->repacked.stride == a->stride &&
        b->repacked.element_size == element_size && b->repacked.size == b->storage.size)
        return b->repacked.buffer;
    // The number of whole elements in the buffer
    size_t count = 0;
    if (b->storage.size >= a->offset + element_size) count = (b->storage.size - a->offset - element_size) / a->stride + 1;
    // The previous copy may still be used by commands, which retain it, so a new one is made
    id<MTLBuffer> buf = [d->device newBufferWithLength:MAX((size_t)16u, count * new_stride) options:MTLResourceStorageModeShared];
    if (buf == nil) {
        log_error(d, "Failed to allocate a GPU buffer of size %zu for repacking vertex data", count * new_stride);
        return nil;
    }
    const uint8_t *src = (const uint8_t *)[b->storage.buffer contents] + a->offset;
    uint8_t *dst = [buf contents];
    for (size_t i = 0; i < count; i++) memcpy(dst + i * new_stride, src + i * a->stride, element_size);
    [b->repacked.buffer release];
    b->repacked.buffer = buf;
    b->repacked.generation = b->generation;
    b->repacked.offset = a->offset;
    b->repacked.stride = a->stride;
    b->repacked.element_size = (uint32_t)element_size;
    b->repacked.size = b->storage.size;
    return buf;
}
// }}}
