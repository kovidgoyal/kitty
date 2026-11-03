/*
 * memory.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Device memory, staging memory and buffers

#include "internal.h"

// Memory allocation {{{
// Vulkan implementations limit the number of device memory allocations, to
// as few as 4096, so small resources are sub-allocated from large blocks.
// Blocks are used either only for buffers or only for images, so that
// bufferImageGranularity never needs to be considered.

#define BLOCK_SIZE (32u * 1024u * 1024u)
#define DEDICATED_THRESHOLD (BLOCK_SIZE / 4)

typedef struct FreeRange {
    VkDeviceSize offset, size;
} FreeRange;

struct MemoryBlock {
    VkDeviceMemory memory;
    uint32_t memory_type;
    MemoryUsage usage;
    void *mapped;
    VkDeviceSize size;
    FreeRange *free_ranges; // sorted by offset, non-adjacent
    size_t num_free, free_capacity;
    MemoryBlock *next;
};

static int
find_memory_type(Driver *d, uint32_t type_bits, MemoryUsage usage) {
    const VkPhysicalDeviceMemoryProperties *p = &d->memory_properties;
    VkMemoryPropertyFlags required = 0, preferred = 0;
    switch (usage) {
        case MEMORY_DEVICE: preferred = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT; break;
        case MEMORY_UPLOAD:
            required = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
            preferred = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
            break;
        case MEMORY_READBACK:
            required = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
            preferred = VK_MEMORY_PROPERTY_HOST_CACHED_BIT;
            break;
    }
    int fallback = -1;
    for (uint32_t i = 0; i < p->memoryTypeCount; i++) {
        if (!(type_bits & (1u << i))) continue;
        const VkMemoryPropertyFlags f = p->memoryTypes[i].propertyFlags;
        if ((f & required) != required) continue;
        if ((f & preferred) == preferred) return (int)i;
        if (fallback < 0) fallback = (int)i;
    }
    return fallback;
}

static bool
allocate_device_memory(Driver *d, VkDeviceSize size, uint32_t memory_type, VkDeviceMemory *memory, void **mapped) {
    const VkMemoryAllocateInfo info = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = size, .memoryTypeIndex = memory_type};
    VkResult r = vkAllocateMemory(d->device, &info, NULL, memory);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to allocate %llu bytes of GPU memory with error: %s", (unsigned long long)size, vk_result_string(r));
        return false;
    }
    *mapped = NULL;
    if (d->memory_properties.memoryTypes[memory_type].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) {
        r = vkMapMemory(d->device, *memory, 0, VK_WHOLE_SIZE, 0, mapped);
        if (r != VK_SUCCESS) {
            vkFreeMemory(d->device, *memory, NULL);
            set_error(d, "Failed to map GPU memory with error: %s", vk_result_string(r));
            return false;
        }
    }
    return true;
}

static bool
block_allocate(MemoryBlock *b, VkDeviceSize size, VkDeviceSize alignment, VkDeviceSize *offset) {
    for (size_t i = 0; i < b->num_free; i++) {
        FreeRange *r = b->free_ranges + i;
        const VkDeviceSize start = (r->offset + alignment - 1) / alignment * alignment;
        if (start + size > r->offset + r->size) continue;
        const VkDeviceSize end = start + size, range_end = r->offset + r->size;
        *offset = start;
        if (start == r->offset && end == range_end) {
            memmove(r, r + 1, (b->num_free - i - 1) * sizeof(FreeRange));
            b->num_free--;
        } else if (start == r->offset) {
            r->offset = end;
            r->size = range_end - end;
        } else if (end == range_end) {
            r->size = start - r->offset;
        } else {
            // Split the range in two
            if (b->num_free >= b->free_capacity) {
                const size_t cap = MAX(16u, b->free_capacity * 2);
                FreeRange *n = realloc(b->free_ranges, cap * sizeof(FreeRange));
                if (!n) return false;
                b->free_ranges = n;
                b->free_capacity = cap;
                r = b->free_ranges + i;
            }
            memmove(r + 2, r + 1, (b->num_free - i - 1) * sizeof(FreeRange));
            b->num_free++;
            r[1] = (FreeRange){.offset = end, .size = range_end - end};
            r->size = start - r->offset;
        }
        return true;
    }
    return false;
}

static void
block_free(MemoryBlock *b, VkDeviceSize offset, VkDeviceSize size) {
    size_t i = 0;
    while (i < b->num_free && b->free_ranges[i].offset < offset) i++;
    // Merge with the previous and next ranges if adjacent
    const bool merge_prev = i > 0 && b->free_ranges[i - 1].offset + b->free_ranges[i - 1].size == offset;
    const bool merge_next = i < b->num_free && offset + size == b->free_ranges[i].offset;
    if (merge_prev && merge_next) {
        b->free_ranges[i - 1].size += size + b->free_ranges[i].size;
        memmove(b->free_ranges + i, b->free_ranges + i + 1, (b->num_free - i - 1) * sizeof(FreeRange));
        b->num_free--;
    } else if (merge_prev) {
        b->free_ranges[i - 1].size += size;
    } else if (merge_next) {
        b->free_ranges[i].offset = offset;
        b->free_ranges[i].size += size;
    } else {
        if (b->num_free >= b->free_capacity) {
            const size_t cap = MAX(16u, b->free_capacity * 2);
            FreeRange *n = realloc(b->free_ranges, cap * sizeof(FreeRange));
            if (!n) return; // the range is leaked, harmless
            b->free_ranges = n;
            b->free_capacity = cap;
        }
        memmove(b->free_ranges + i + 1, b->free_ranges + i, (b->num_free - i) * sizeof(FreeRange));
        b->free_ranges[i] = (FreeRange){.offset = offset, .size = size};
        b->num_free++;
    }
}

static bool
allocate_from_block(MemoryBlock *b, const VkMemoryRequirements *req, Allocation *ans) {
    VkDeviceSize offset;
    if (!block_allocate(b, req->size, MAX(1u, req->alignment), &offset)) return false;
    *ans = (Allocation){.memory = b->memory, .offset = offset, .size = req->size, .block = b, .mapped = b->mapped ? (uint8_t *)b->mapped + offset : NULL};
    return true;
}

bool
allocate_memory(Driver *d, const VkMemoryRequirements *req, MemoryUsage usage, Allocation *ans) {
    *ans = (Allocation){0};
    const int type = find_memory_type(d, req->memoryTypeBits, usage);
    if (type < 0) {
        set_error(d, "No suitable GPU memory type found");
        return false;
    }
    if (req->size >= DEDICATED_THRESHOLD) {
        if (!allocate_device_memory(d, req->size, (uint32_t)type, &ans->memory, &ans->mapped)) return false;
        ans->size = req->size;
        return true;
    }
    for (MemoryBlock *b = d->memory_blocks; b; b = b->next) {
        if (b->memory_type == (uint32_t)type && b->usage == usage && allocate_from_block(b, req, ans)) return true;
    }
    MemoryBlock *b = calloc(1, sizeof(MemoryBlock));
    if (!b) {
        set_error(d, "Out of memory");
        return false;
    }
    if (!allocate_device_memory(d, BLOCK_SIZE, (uint32_t)type, &b->memory, &b->mapped)) {
        free(b);
        return false;
    }
    b->memory_type = (uint32_t)type;
    b->usage = usage;
    b->size = BLOCK_SIZE;
    b->free_capacity = 16;
    b->free_ranges = calloc(b->free_capacity, sizeof(FreeRange));
    if (!b->free_ranges) {
        vkFreeMemory(d->device, b->memory, NULL);
        free(b);
        set_error(d, "Out of memory");
        return false;
    }
    b->free_ranges[0] = (FreeRange){.offset = 0, .size = BLOCK_SIZE};
    b->num_free = 1;
    b->next = d->memory_blocks;
    d->memory_blocks = b;
    if (!allocate_from_block(b, req, ans)) {
        set_error(d, "Failed to sub-allocate %llu bytes of GPU memory", (unsigned long long)req->size);
        return false;
    }
    return true;
}

void
free_memory(Driver *d, Allocation *a) {
    if (!a->memory) return;
    if (a->block) block_free(a->block, a->offset, a->size);
    else vkFreeMemory(d->device, a->memory, NULL);
    *a = (Allocation){0};
}

void
free_all_memory(Driver *d) {
    while (d->memory_blocks) {
        MemoryBlock *b = d->memory_blocks;
        d->memory_blocks = b->next;
        vkFreeMemory(d->device, b->memory, NULL);
        free(b->free_ranges);
        free(b);
    }
}

bool
create_buffer_with_memory(Driver *d, VkDeviceSize size, VkBufferUsageFlags usage, MemoryUsage mem_usage, VkBuffer *buffer, Allocation *alloc) {
    const VkBufferCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = MAX(16u, size), .usage = usage, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VkResult r = vkCreateBuffer(d->device, &info, NULL, buffer);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create a GPU buffer with error: %s", vk_result_string(r));
        return false;
    }
    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(d->device, *buffer, &req);
    if (!allocate_memory(d, &req, mem_usage, alloc)) {
        vkDestroyBuffer(d->device, *buffer, NULL);
        *buffer = VK_NULL_HANDLE;
        return false;
    }
    r = vkBindBufferMemory(d->device, *buffer, alloc->memory, alloc->offset);
    if (r != VK_SUCCESS) {
        free_memory(d, alloc);
        vkDestroyBuffer(d->device, *buffer, NULL);
        *buffer = VK_NULL_HANDLE;
        set_error(d, "Failed to bind GPU buffer memory with error: %s", vk_result_string(r));
        return false;
    }
    return true;
}
// }}}

// Staging {{{
#define STAGING_CHUNK_SIZE (4u * 1024u * 1024u)
// The value of used for staging buffers that cannot be shared
#define STAGING_NOT_SHAREABLE ((VkDeviceSize) - 1)

bool
allocate_staging(Driver *d, VkDeviceSize size, VkDeviceSize alignment, VkBuffer *buffer, VkDeviceSize *offset, void **mapped) {
    Context *c = current_context(d);
    alignment = MAX(16u, alignment);
    // Small uploads are sub-allocated from shared chunks
    for (size_t i = 0; i < c->num_staging; i++) {
        if (c->staging[i].used == STAGING_NOT_SHAREABLE) continue;
        const VkDeviceSize start = (c->staging[i].used + alignment - 1) / alignment * alignment;
        if (start + size <= c->staging[i].alloc.size) {
            c->staging[i].used = start + size;
            *buffer = c->staging[i].buffer;
            *offset = start;
            *mapped = (uint8_t *)c->staging[i].alloc.mapped + start;
            return true;
        }
    }
    if (c->num_staging >= arraysz(c->staging)) {
        // Wait for the commands recorded so far to complete, freeing all staging memory
        submit_commands(d, NULL, 0, true);
        c = current_context(d);
    }
    // Uploads too large for a chunk get a buffer of their own
    const bool shareable = size < STAGING_CHUNK_SIZE;
    const size_t idx = c->num_staging;
    if (!create_buffer_with_memory(
            d, shareable ? STAGING_CHUNK_SIZE : size, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, MEMORY_UPLOAD, &c->staging[idx].buffer, &c->staging[idx].alloc))
        return false;
    c->num_staging++;
    c->staging[idx].used = shareable ? size : STAGING_NOT_SHAREABLE;
    *buffer = c->staging[idx].buffer;
    *offset = 0;
    *mapped = c->staging[idx].alloc.mapped;
    return true;
}

void
release_staging(Driver *d, Context *c) {
    for (size_t i = 0; i < c->num_staging; i++) {
        vkDestroyBuffer(d->device, c->staging[i].buffer, NULL);
        free_memory(d, &c->staging[i].alloc);
    }
    c->num_staging = 0;
}
// }}}

// Buffers {{{
#define AS_BUFFER(handle) ((Buffer *)(uintptr_t)(handle))

static VkBufferUsageFlags
buffer_usage(GPUBufferKind kind) {
    return kind == GPU_BUFFER_UNIFORM ? VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT : VK_BUFFER_USAGE_VERTEX_BUFFER_BIT;
}

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

static void
destroy_storage(Driver *d, BufferStorage *s, bool deferred) {
    if (!s->buffer) return;
    if (deferred && s->last_use_serial > d->completed_serial) defer_destroy_buffer(d, s->buffer, &s->alloc);
    else {
        vkDestroyBuffer(d->device, s->buffer, NULL);
        free_memory(d, &s->alloc);
    }
    *s = (BufferStorage){0};
}

static void
free_buffer(Driver *d, Buffer *b, bool deferred) {
    destroy_storage(d, &b->storage, deferred);
    for (size_t i = 0; i < b->num_retired; i++) destroy_storage(d, b->retired + i, deferred);
    b->num_retired = 0;
}

void
buffer_destroy(void *driver, gpu_buffer_t buffer) {
    Driver *d = driver;
    Buffer *b = AS_BUFFER(buffer);
    if (!b) return;
    for (size_t i = 0; i < arraysz(d->bound_buffers); i++) {
        if (d->bound_buffers[i] == b) d->bound_buffers[i] = NULL;
    }
    free_buffer(d, b, true);
    LIST_REMOVE(d->buffers, b);
    free(b);
}

void
destroy_all_buffers(Driver *d) {
    while (d->buffers) {
        Buffer *b = d->buffers;
        free_buffer(d, b, false);
        LIST_REMOVE(d->buffers, b);
        free(b);
    }
}

// Get storage of the same size as the current storage that no commands use,
// reusing retired storage if possible
static bool
fresh_storage(Driver *d, Buffer *b, VkDeviceSize size, BufferStorage *ans) {
    for (size_t i = 0; i < b->num_retired; i++) {
        BufferStorage *s = b->retired + i;
        if (s->size == size && s->last_use_serial <= d->completed_serial) {
            *ans = *s;
            b->retired[i] = b->retired[--b->num_retired];
            return true;
        }
    }
    *ans = (BufferStorage){.size = size};
    return create_buffer_with_memory(d, size, buffer_usage(b->kind), MEMORY_UPLOAD, &ans->buffer, &ans->alloc);
}

static void
retire_storage(Driver *d, Buffer *b, BufferStorage *s) {
    if (!s->buffer) return;
    if (s->last_use_serial <= d->completed_serial && b->num_retired >= arraysz(b->retired)) {
        destroy_storage(d, s, false);
        return;
    }
    if (b->num_retired >= arraysz(b->retired)) {
        // Drop the oldest retired storage
        destroy_storage(d, b->retired, true);
        memmove(b->retired, b->retired + 1, (b->num_retired - 1) * sizeof(BufferStorage));
        b->num_retired--;
    }
    b->retired[b->num_retired++] = *s;
    *s = (BufferStorage){0};
}

void
buffer_allocate(void *driver, gpu_buffer_t buffer, size_t size, GPUUpdateFrequency frequency) {
    Driver *d = driver;
    Buffer *b = AS_BUFFER(buffer);
    b->frequency = frequency;
    if (b->storage.buffer && b->storage.size == size) return;
    // Retired storage of a different size is useless
    for (size_t i = 0; i < b->num_retired; i++) destroy_storage(d, b->retired + i, true);
    b->num_retired = 0;
    destroy_storage(d, &b->storage, true);
    if (!size) return;
    BufferStorage s;
    if (!fresh_storage(d, b, size, &s)) fatal(d, "Failed to allocate a GPU buffer of size %zu with error: %s", size, d->last_error);
    b->storage = s;
}

// Ensure the current storage of the buffer is not used by any commands,
// preserving its contents if preserve is true
static void
make_writable(Driver *d, Buffer *b, bool preserve) {
    if (b->storage.last_use_serial <= d->completed_serial) return;
    BufferStorage s;
    if (!fresh_storage(d, b, b->storage.size, &s)) fatal(d, "Failed to allocate a GPU buffer with error: %s", d->last_error);
    // Only the CPU writes to buffers, so the old contents are current
    if (preserve) memcpy(s.alloc.mapped, b->storage.alloc.mapped, b->storage.size);
    retire_storage(d, b, &b->storage);
    b->storage = s;
}

void *
buffer_map(void *driver, gpu_buffer_t buffer, GPUMapMode mode, size_t offset, size_t size) {
    Driver *d = driver;
    Buffer *b = AS_BUFFER(buffer);
    if (!b->storage.buffer) return NULL;
    switch (mode) {
        case GPU_MAP_READ: return b->storage.alloc.mapped;
        case GPU_MAP_WRITE: make_writable(d, b, true); return b->storage.alloc.mapped;
        case GPU_MAP_WRITE_DISCARD_ALL: make_writable(d, b, false); return (uint8_t *)b->storage.alloc.mapped + offset;
        case GPU_MAP_WRITE_DISCARD_RANGE:
            // The contents outside the range must be preserved
            make_writable(d, b, offset > 0 || size < b->storage.size);
            return (uint8_t *)b->storage.alloc.mapped + offset;
    }
    return NULL;
}

void
buffer_unmap(void *driver UNUSED, gpu_buffer_t buffer UNUSED) {
    // Buffers are persistently mapped in coherent memory
}

void
buffer_copy(void *driver, gpu_buffer_t src, size_t src_offset, gpu_buffer_t dst, size_t dst_offset, size_t size) {
    Driver *d = driver;
    Buffer *s = AS_BUFFER(src), *t = AS_BUFFER(dst);
    if (!size || !s->storage.buffer || !t->storage.buffer) return;
    if (src_offset + size > s->storage.size || dst_offset + size > t->storage.size) {
        log_error(d, "Out of bounds GPU buffer copy");
        return;
    }
    // Only the CPU writes to buffers, so copies are done by the CPU too
    make_writable(d, t, true);
    memmove((uint8_t *)t->storage.alloc.mapped + dst_offset, (uint8_t *)s->storage.alloc.mapped + src_offset, size);
}

bool
write_buffer(Driver *d, Buffer *b, const void *data, size_t size) {
    if (!b->storage.buffer || b->storage.size < size) return false;
    make_writable(d, b, size < b->storage.size);
    memcpy(b->storage.alloc.mapped, data, size);
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
    d->cmd_state.descriptors_dirty = true;
}

void
use_buffer(Driver *d, Buffer *b) {
    b->storage.last_use_serial = recording_serial(d);
}
// }}}
