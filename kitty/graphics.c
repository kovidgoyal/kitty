/*
 * graphics.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "graphics.h"
#include "state.h"
#include "disk-cache.h"
#include "iqsort.h"
#include "safe-wrappers.h"

#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <stdlib.h>

#include <zlib.h>
#include <structmember.h>
#include "png-reader.h"
PyTypeObject GraphicsManager_Type;

#define DEFAULT_STORAGE_LIMIT 320u * (1024u * 1024u)
#define REPORT_ERROR(...) { log_error(__VA_ARGS__); }

// caching {{{
#define CACHE_KEY_BUFFER_SIZE 32

static inline size_t
cache_key(const ImageAndFrame x, char *key) {
    return snprintf(key, CACHE_KEY_BUFFER_SIZE, "%llx:%x", x.image_id, x.frame_id);
}
#define CK(x) key, cache_key(x, key)

static inline bool
add_to_cache(GraphicsManager *self, const ImageAndFrame x, const void *data, const size_t sz) {
    char key[CACHE_KEY_BUFFER_SIZE];
    return add_to_disk_cache(self->disk_cache, CK(x), data, sz);
}

static inline bool
remove_from_cache(GraphicsManager *self, const ImageAndFrame x) {
    char key[CACHE_KEY_BUFFER_SIZE];
    return remove_from_disk_cache(self->disk_cache, CK(x));
}

static inline bool
read_from_cache(const GraphicsManager *self, const ImageAndFrame x, void **data, size_t *sz) {
    char key[CACHE_KEY_BUFFER_SIZE];
    return read_from_disk_cache_simple(self->disk_cache, CK(x), data, sz, false);
}

static inline size_t
cache_size(const GraphicsManager *self) { return disk_cache_total_size(self->disk_cache); }
#undef CK
// }}}


GraphicsManager*
grman_alloc() {
    GraphicsManager *self = (GraphicsManager *)GraphicsManager_Type.tp_alloc(&GraphicsManager_Type, 0);
    self->images_capacity = self->capacity = 64;
    self->images = calloc(self->images_capacity, sizeof(Image));
    self->render_data = calloc(self->capacity, sizeof(ImageRenderData));
    self->storage_limit = DEFAULT_STORAGE_LIMIT;
    if (self->images == NULL || self->render_data == NULL) {
        PyErr_NoMemory();
        Py_CLEAR(self); return NULL;
    }
    self->disk_cache = create_disk_cache();
    if (!self->disk_cache) { Py_CLEAR(self); return NULL; }
    return self;
}

static inline void
free_refs_data(Image *img) {
    free(img->refs); img->refs = NULL;
    img->refcnt = 0; img->refcap = 0;
}

static inline void
free_load_data(LoadData *ld) {
    free(ld->buf); ld->buf_used = 0; ld->buf_capacity = 0; ld->buf = NULL;
    if (ld->mapped_file) munmap(ld->mapped_file, ld->mapped_file_sz);
    ld->mapped_file = NULL; ld->mapped_file_sz = 0;
    ld->loading_for = (const ImageAndFrame){0};
}

static inline void
free_image(GraphicsManager *self, Image *img) {
    if (img->texture_id) free_texture(&img->texture_id);
    ImageAndFrame key = { .image_id=img->internal_id, .frame_id = img->root_frame.id };
    if (!remove_from_cache(self, key) && PyErr_Occurred()) PyErr_Print();
    for (unsigned i = 0; i < img->extra_framecnt; i++) {
        key.frame_id = img->extra_frames[i].id;
        if (!remove_from_cache(self, key) && PyErr_Occurred()) PyErr_Print();
    }
    if (img->extra_frames) {
        free(img->extra_frames);
        img->extra_frames = NULL;
    }
    free_refs_data(img);
    self->used_storage -= img->used_storage;
}


static void
dealloc(GraphicsManager* self) {
    size_t i;
    if (self->images) {
        for (i = 0; i < self->image_count; i++) free_image(self, self->images + i);
        free(self->images);
    }
    free(self->render_data);
    Py_CLEAR(self->disk_cache);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static id_type internal_id_counter = 1;

static inline Image*
img_by_internal_id(GraphicsManager *self, id_type id) {
    for (size_t i = 0; i < self->image_count; i++) {
        if (self->images[i].internal_id == id) return self->images + i;
    }
    return NULL;
}

static inline Image*
img_by_client_id(GraphicsManager *self, uint32_t id) {
    for (size_t i = 0; i < self->image_count; i++) {
        if (self->images[i].client_id == id) return self->images + i;
    }
    return NULL;
}

static inline Image*
img_by_client_number(GraphicsManager *self, uint32_t number) {
    // get the newest image with the specified number
    for (size_t i = self->image_count; i-- > 0; ) {
        if (self->images[i].client_number == number) return self->images + i;
    }
    return NULL;
}


static inline void
remove_image(GraphicsManager *self, size_t idx) {
    free_image(self, self->images + idx);
    remove_i_from_array(self->images, idx, self->image_count);
    self->layers_dirty = true;
}

static inline void
remove_images(GraphicsManager *self, bool(*predicate)(Image*), id_type skip_image_internal_id) {
    for (size_t i = self->image_count; i-- > 0;) {
        Image *img = self->images + i;
        if (img->internal_id != skip_image_internal_id && predicate(img)) {
            remove_image(self, i);
        }
    }
}


// Loading image data {{{

static bool
trim_predicate(Image *img) {
    return !img->root_frame_data_loaded || !img->refcnt;
}


static inline void
apply_storage_quota(GraphicsManager *self, size_t storage_limit, id_type currently_added_image_internal_id) {
    // First remove unreferenced images, even if they have an id
    remove_images(self, trim_predicate, currently_added_image_internal_id);
    if (self->used_storage < storage_limit) return;

#define oldest_last(a, b) ((b)->atime < (a)->atime)
    QSORT(Image, self->images, self->image_count, oldest_last)
#undef oldest_last
    while (self->used_storage > storage_limit && self->image_count > 0) {
        remove_image(self, self->image_count - 1);
    }
    if (!self->image_count) self->used_storage = 0;  // sanity check
}

static char command_response[512] = {0};

static inline void
set_command_failed_response(const char *code, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    const size_t sz = sizeof(command_response)/sizeof(command_response[0]);
    const int num = snprintf(command_response, sz, "%s:", code);
    vsnprintf(command_response + num, sz - num, fmt, args);
    va_end(args);
}

// Decode formats {{{
#define ABRT(code, ...) { set_command_failed_response(#code, __VA_ARGS__); goto err; }

static inline bool
mmap_img_file(GraphicsManager *self, int fd, size_t sz, off_t offset) {
    if (!sz) {
        struct stat s;
        if (fstat(fd, &s) != 0) ABRT(EBADF, "Failed to fstat() the fd: %d file with error: [%d] %s", fd, errno, strerror(errno));
        sz = s.st_size;
    }
    void *addr = mmap(0, sz, PROT_READ, MAP_SHARED, fd, offset);
    if (addr == MAP_FAILED) ABRT(EBADF, "Failed to map image file fd: %d at offset: %zd with size: %zu with error: [%d] %s", fd, offset, sz, errno, strerror(errno));
    self->currently_loading.mapped_file = addr;
    self->currently_loading.mapped_file_sz = sz;
    return true;
err:
    return false;
}


static inline const char*
zlib_strerror(int ret) {
#define Z(x) case x: return #x;
    static char buf[128];
    switch(ret) {
        case Z_ERRNO:
            return strerror(errno);
        default:
            snprintf(buf, sizeof(buf)/sizeof(buf[0]), "Unknown error: %d", ret);
            return buf;
        Z(Z_STREAM_ERROR);
        Z(Z_DATA_ERROR);
        Z(Z_MEM_ERROR);
        Z(Z_BUF_ERROR);
        Z(Z_VERSION_ERROR);
    }
#undef Z
}

static inline bool
inflate_zlib(LoadData *load_data, uint8_t *buf, size_t bufsz) {
    bool ok = false;
    z_stream z;
    uint8_t *decompressed = malloc(load_data->data_sz);
    if (decompressed == NULL) fatal("Out of memory allocating decompression buffer");
    z.zalloc = Z_NULL;
    z.zfree = Z_NULL;
    z.opaque = Z_NULL;
    z.avail_in = bufsz;
    z.next_in = (Bytef*)buf;
    z.avail_out = load_data->data_sz;
    z.next_out = decompressed;
    int ret;
    if ((ret = inflateInit(&z)) != Z_OK) ABRT(ENOMEM, "Failed to initialize inflate with error: %s", zlib_strerror(ret));
    if ((ret = inflate(&z, Z_FINISH)) != Z_STREAM_END) ABRT(EINVAL, "Failed to inflate image data with error: %s", zlib_strerror(ret));
    if (z.avail_out) ABRT(EINVAL, "Image data size post inflation does not match expected size");
    free_load_data(load_data);
    load_data->buf_capacity = load_data->data_sz;
    load_data->buf = decompressed;
    load_data->buf_used = load_data->data_sz;
    ok = true;
err:
    inflateEnd(&z);
    if (!ok) free(decompressed);
    return ok;
}

static void
png_error_handler(const char *code, const char *msg) {
    set_command_failed_response(code, "%s", msg);
}

static inline bool
inflate_png(LoadData *load_data, uint8_t *buf, size_t bufsz) {
    png_read_data d = {.err_handler=png_error_handler};
    inflate_png_inner(&d, buf, bufsz);
    if (d.ok) {
        free_load_data(load_data);
        load_data->buf = d.decompressed;
        load_data->buf_capacity = d.sz;
        load_data->buf_used = d.sz;
        load_data->data_sz = d.sz;
        load_data->width = d.width; load_data->height = d.height;
    }
    else free(d.decompressed);
    free(d.row_pointers);
    return d.ok;
}
#undef ABRT
// }}}

static bool
add_trim_predicate(Image *img) {
    return !img->root_frame_data_loaded || (!img->client_id && !img->refcnt);
}

bool
png_path_to_bitmap(const char* path, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz) {
    FILE* fp = fopen(path, "r");
    if (fp == NULL) {
        log_error("The PNG image: %s could not be opened with error: %s", path, strerror(errno));
        return false;
    }
    size_t capacity = 16*1024, pos = 0;
    unsigned char *buf = malloc(capacity);
    if (!buf) { log_error("Out of memory reading PNG file at: %s", path); fclose(fp); return false; }
    while (!feof(fp)) {
        if (capacity - pos < 1024) {
            capacity *= 2;
            unsigned char *new_buf = realloc(buf, capacity);
            if (!new_buf) {
                free(buf);
                log_error("Out of memory reading PNG file at: %s", path); fclose(fp); return false;
            }
            buf = new_buf;
        }
        pos += fread(buf + pos, sizeof(char), capacity - pos, fp);
        int saved_errno = errno;
        if (ferror(fp) && saved_errno != EINTR) {
            log_error("Failed while reading from file: %s with error: %s", path, strerror(saved_errno));
            fclose(fp);
            free(buf);
            return false;
        }
    }
    fclose(fp); fp = NULL;
    png_read_data d = {0};
    inflate_png_inner(&d, buf, pos);
    free(buf);
    if (!d.ok) {
        free(d.decompressed); free(d.row_pointers);
        log_error("Failed to decode PNG image at: %s", path);
        return false;
    }
    *data = d.decompressed;
    free(d.row_pointers);
    *sz = d.sz;
    *height = d.height; *width = d.width;
    return true;
}


static inline Image*
find_or_create_image(GraphicsManager *self, uint32_t id, bool *existing) {
    if (id) {
        for (size_t i = 0; i < self->image_count; i++) {
            if (self->images[i].client_id == id) {
                *existing = true;
                return self->images + i;
            }
        }
    }
    *existing = false;
    ensure_space_for(self, images, Image, self->image_count + 1, images_capacity, 64, true);
    Image *ans = self->images + self->image_count++;
    zero_at_ptr(ans);
    return ans;
}

static inline uint32_t
get_free_client_id(const GraphicsManager *self) {
    if (!self->image_count) return 1;
    uint32_t *client_ids = malloc(sizeof(uint32_t) * self->image_count);
    size_t count = 0;
    for (size_t i = 0; i < self->image_count; i++) {
        Image *q = self->images + i;
        if (q->client_id) client_ids[count++] = q->client_id;
    }
    if (!count) { free(client_ids); return 1; }
#define int_lt(a, b) ((*a)<(*b))
    QSORT(uint32_t, client_ids, count, int_lt)
#undef int_lt
    uint32_t prev_id = 0, ans = 1;
    for (size_t i = 0; i < count; i++) {
        if (client_ids[i] == prev_id) continue;
        prev_id = client_ids[i];
        if (client_ids[i] != ans) break;
        ans = client_ids[i] + 1;
    }
    free(client_ids);
    return ans;
}

#define ABRT(code, ...) { set_command_failed_response(code, __VA_ARGS__); self->currently_loading.loading_completed_successfully = false; free_load_data(&self->currently_loading); return NULL; }

#define MAX_DATA_SZ (4u * 100000000u)
enum FORMATS { RGB=24, RGBA=32, PNG=100 };

static Image*
load_image_data(GraphicsManager *self, Image *img, const GraphicsCommand *g, const unsigned char transmission_type, const uint32_t data_fmt, const uint8_t *payload) {
    int fd;
    static char fname[2056] = {0};
    LoadData *load_data = &self->currently_loading;

    switch(transmission_type) {
        case 'd':  // direct
            if (load_data->buf_capacity - load_data->buf_used < g->payload_sz) {
                if (load_data->buf_used + g->payload_sz > MAX_DATA_SZ || data_fmt != PNG) ABRT("EFBIG", "Too much data");
                load_data->buf_capacity = MIN(2 * load_data->buf_capacity, MAX_DATA_SZ);
                load_data->buf = realloc(load_data->buf, load_data->buf_capacity);
                if (load_data->buf == NULL) {
                    load_data->buf_capacity = 0; load_data->buf_used = 0;
                    ABRT("ENOMEM", "Out of memory");
                }
            }
            memcpy(load_data->buf + load_data->buf_used, payload, g->payload_sz);
            load_data->buf_used += g->payload_sz;
            if (!g->more) { load_data->loading_completed_successfully = true; load_data->loading_for = (const ImageAndFrame){0}; }
            break;
        case 'f': // file
        case 't': // temporary file
        case 's': // POSIX shared memory
            if (g->payload_sz > 2048) ABRT("EINVAL", "Filename too long");
            snprintf(fname, sizeof(fname)/sizeof(fname[0]), "%.*s", (int)g->payload_sz, payload);
            if (transmission_type == 's') fd = safe_shm_open(fname, O_RDONLY, 0);
            else fd = safe_open(fname, O_CLOEXEC | O_RDONLY, 0);
            if (fd == -1) ABRT("EBADF", "Failed to open file for graphics transmission with error: [%d] %s", errno, strerror(errno));
            load_data->loading_completed_successfully = mmap_img_file(self, fd, g->data_sz, g->data_offset);
            safe_close(fd, __FILE__, __LINE__);
            if (transmission_type == 't') {
                if (global_state.boss) { call_boss(safe_delete_temp_file, "s", fname); }
                else unlink(fname);
            }
            else if (transmission_type == 's') shm_unlink(fname);
            if (!load_data->loading_completed_successfully) return NULL;
            break;
        default:
            ABRT("EINVAL", "Unknown transmission type: %c", g->transmission_type);
    }
    return img;
}

static Image*
process_image_data(GraphicsManager *self, Image* img, const GraphicsCommand *g, const unsigned char transmission_type, const uint32_t data_fmt) {
    bool needs_processing = g->compressed || data_fmt == PNG;
    if (needs_processing) {
        uint8_t *buf; size_t bufsz;
#define IB { if (self->currently_loading.buf) { buf = self->currently_loading.buf; bufsz = self->currently_loading.buf_used; } else { buf = self->currently_loading.mapped_file; bufsz = self->currently_loading.mapped_file_sz; } }
        switch(g->compressed) {
            case 'z':
                IB;
                if (!inflate_zlib(&self->currently_loading, buf, bufsz)) {
                    self->currently_loading.loading_completed_successfully = false; return NULL;
                }
                break;
            case 0:
                break;
            default:
                ABRT("EINVAL", "Unknown image compression: %c", g->compressed);
        }
        switch(data_fmt) {
            case PNG:
                IB;
                if (!inflate_png(&self->currently_loading, buf, bufsz)) {
                    self->currently_loading.loading_completed_successfully = false; return NULL;
                }
                break;
            default: break;
        }
#undef IB
        self->currently_loading.data = self->currently_loading.buf;
        if (self->currently_loading.buf_used < self->currently_loading.data_sz) {
            ABRT("ENODATA", "Insufficient image data: %zu < %zu", self->currently_loading.buf_used, self->currently_loading.data_sz);
        }
        if (self->currently_loading.mapped_file) {
            munmap(self->currently_loading.mapped_file, self->currently_loading.mapped_file_sz);
            self->currently_loading.mapped_file = NULL; self->currently_loading.mapped_file_sz = 0;
        }
    } else {
        if (transmission_type == 'd') {
            if (self->currently_loading.buf_used < self->currently_loading.data_sz) {
                ABRT("ENODATA", "Insufficient image data: %zu < %zu",  self->currently_loading.buf_used, self->currently_loading.data_sz);
            } else self->currently_loading.data = self->currently_loading.buf;
        } else {
            if (self->currently_loading.mapped_file_sz < self->currently_loading.data_sz) {
                ABRT("ENODATA", "Insufficient image data: %zu < %zu",  self->currently_loading.mapped_file_sz, self->currently_loading.data_sz);
            } else self->currently_loading.data = self->currently_loading.mapped_file;
        }
        self->currently_loading.loading_completed_successfully = true;
    }
    return img;
}

static Image*
initialize_load_data(GraphicsManager *self, const GraphicsCommand *g, Image *img, const unsigned char transmission_type, const uint32_t data_fmt, const uint32_t frame_id) {
    free_load_data(&self->currently_loading);
    self->currently_loading = (const LoadData){0};
    self->currently_loading.start_command = *g;
    self->currently_loading.width = g->data_width; self->currently_loading.height = g->data_height;
    switch(data_fmt) {
        case PNG:
            if (g->data_sz > MAX_DATA_SZ) ABRT("EINVAL", "PNG data size too large");
            self->currently_loading.is_4byte_aligned = true;
            self->currently_loading.is_opaque = false;
            self->currently_loading.data_sz = g->data_sz ? g->data_sz : 1024 * 100;
            break;
        case RGB:
        case RGBA:
            self->currently_loading.data_sz = (size_t)g->data_width * g->data_height * (data_fmt / 8);
            if (!self->currently_loading.data_sz) ABRT("EINVAL", "Zero width/height not allowed");
            self->currently_loading.is_4byte_aligned = data_fmt == RGBA || (self->currently_loading.width % 4 == 0);
            self->currently_loading.is_opaque = data_fmt == RGB;
            break;
        default:
            ABRT("EINVAL", "Unknown image format: %u", data_fmt);
    }
    self->currently_loading.loading_for.image_id = img->internal_id;
    self->currently_loading.loading_for.frame_id = frame_id;
    if (transmission_type == 'd') {
        self->currently_loading.buf_capacity = self->currently_loading.data_sz + (g->compressed ? 1024 : 10);  // compression header
        self->currently_loading.buf = malloc(self->currently_loading.buf_capacity);
        self->currently_loading.buf_used = 0;
        if (self->currently_loading.buf == NULL) {
            self->currently_loading.buf_capacity = 0; self->currently_loading.buf_used = 0;
            ABRT("ENOMEM", "Out of memory");
        }
    }
    return img;
}

#define INIT_CHUNKED_LOAD { \
    self->currently_loading.start_command.more = g->more; \
    self->currently_loading.start_command.payload_sz = g->payload_sz; \
    g = &self->currently_loading.start_command; \
    tt = g->transmission_type ? g->transmission_type : 'd'; \
    fmt = g->format ? g->format : RGBA; \
}
#define MAX_IMAGE_DIMENSION 10000u

static void
upload_to_gpu(GraphicsManager *self, Image *img, const bool is_opaque, const bool is_4byte_aligned, const uint8_t *data) {
    if (!self->context_made_current_for_this_command) {
        if (!self->window_id) return;
        if (!make_window_context_current(self->window_id)) return;
        self->context_made_current_for_this_command = true;
    }
    send_image_to_gpu(&img->texture_id, data, img->width, img->height, is_opaque, is_4byte_aligned, false, REPEAT_CLAMP);
}

static Image*
handle_add_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload, bool *is_dirty, uint32_t iid) {
    bool existing, init_img = true;
    Image *img = NULL;
    unsigned char tt = g->transmission_type ? g->transmission_type : 'd';
    uint32_t fmt = g->format ? g->format : RGBA;
    if (tt == 'd' && self->currently_loading.loading_for.image_id) init_img = false;
    if (init_img) {
        self->currently_loading.loading_for = (const ImageAndFrame){0};
        if (g->data_width > MAX_IMAGE_DIMENSION || g->data_height > MAX_IMAGE_DIMENSION) ABRT("EINVAL", "Image too large");
        remove_images(self, add_trim_predicate, 0);
        img = find_or_create_image(self, iid, &existing);
        if (existing) {
            img->root_frame_data_loaded = false;
            img->is_drawn = false;
            img->current_frame_shown_at = 0;
            free_refs_data(img);
            *is_dirty = true;
            self->layers_dirty = true;
        } else {
            img->internal_id = internal_id_counter++;
            img->client_id = iid;
            img->client_number = g->image_number;
            if (!img->client_id && img->client_number) {
                img->client_id = get_free_client_id(self);
                iid = img->client_id;
            }
        }
        img->atime = monotonic(); img->used_storage = 0;
        if (!initialize_load_data(self, g, img, tt, fmt, 0)) return NULL;
        self->currently_loading.start_command.id = iid;
    } else {
        INIT_CHUNKED_LOAD;
        img = img_by_internal_id(self, self->currently_loading.loading_for.image_id);
        if (img == NULL) {
            self->currently_loading.loading_for = (const ImageAndFrame){0};
            ABRT("EILSEQ", "More payload loading refers to non-existent image");
        }
    }
    img = load_image_data(self, img, g, tt, fmt, payload);
    if (!img || !self->currently_loading.loading_completed_successfully) return NULL;
        self->currently_loading.loading_for = (const ImageAndFrame){0};
    img = process_image_data(self, img, g, tt, fmt);
    if (!img) return NULL;
    size_t required_sz = (size_t)(self->currently_loading.is_opaque ? 3 : 4) * self->currently_loading.width * self->currently_loading.height;
    if (self->currently_loading.data_sz != required_sz) ABRT("EINVAL", "Image dimensions: %ux%u do not match data size: %zu, expected size: %zu", self->currently_loading.width, self->currently_loading.height, self->currently_loading.data_sz, required_sz);
    if (self->currently_loading.loading_completed_successfully) {
        img->width = self->currently_loading.width;
        img->height = self->currently_loading.height;
        if (img->root_frame.id) remove_from_cache(self, (const ImageAndFrame){.image_id=img->internal_id, .frame_id=img->root_frame.id});
        img->root_frame = (const Frame){
            .id = ++img->frame_id_counter,
            .is_opaque = self->currently_loading.is_opaque,
            .is_4byte_aligned = self->currently_loading.is_4byte_aligned,
            .width = img->width, .height = img->height,
        };
        if (!add_to_cache(self, (const ImageAndFrame){.image_id = img->internal_id, .frame_id=img->root_frame.id}, self->currently_loading.data, self->currently_loading.data_sz)) {
            if (PyErr_Occurred()) PyErr_Print();
            ABRT("ENOSPC", "Failed to store image data in disk cache");
        }
        upload_to_gpu(self, img, img->root_frame.is_opaque, img->root_frame.is_4byte_aligned, self->currently_loading.data);
        self->used_storage += required_sz;
        img->used_storage = required_sz;
        img->root_frame_data_loaded = true;
    }
    return img;
#undef MAX_DATA_SZ
}

static inline const char*
finish_command_response(const GraphicsCommand *g, bool data_loaded) {
    static char rbuf[sizeof(command_response)/sizeof(command_response[0]) + 128];
    bool is_ok_response = !command_response[0];
    if (g->quiet) {
        if (is_ok_response || g->quiet > 1) return NULL;
    }
    if (g->id || g->image_number) {
        if (is_ok_response) {
            if (!data_loaded) return NULL;
            snprintf(command_response, 10, "OK");
        }
        size_t pos = 0;
        rbuf[pos++] = 'G';
#define print(fmt, ...) if (arraysz(rbuf) - 1 > pos) pos += snprintf(rbuf + pos, arraysz(rbuf) - 1 - pos, fmt, __VA_ARGS__)
        if (g->id) print("i=%u", g->id);
        if (g->image_number) print(",I=%u", g->image_number);
        if (g->placement_id) print(",p=%u", g->placement_id);
        if (g->num_lines && (g->action == 'f' || g->action == 'a')) print(",r=%u", g->num_lines);
        print(";%s", command_response);
        return rbuf;
#undef print
    }
    return NULL;
}

// }}}

// Displaying images {{{

static inline void
update_src_rect(ImageRef *ref, Image *img) {
    // The src rect in OpenGL co-ords [0, 1] with origin at top-left corner of image
    ref->src_rect.left = (float)ref->src_x / (float)img->width;
    ref->src_rect.right = (float)(ref->src_x + ref->src_width) / (float)img->width;
    ref->src_rect.top = (float)ref->src_y / (float)img->height;
    ref->src_rect.bottom = (float)(ref->src_y + ref->src_height) / (float)img->height;
}

static inline void
update_dest_rect(ImageRef *ref, uint32_t num_cols, uint32_t num_rows, CellPixelSize cell) {
    uint32_t t;
    if (num_cols == 0) {
        t = ref->src_width + ref->cell_x_offset;
        num_cols = t / cell.width;
        if (t > num_cols * cell.width) num_cols += 1;
    }
    if (num_rows == 0) {
        t = ref->src_height + ref->cell_y_offset;
        num_rows = t / cell.height;
        if (t > num_rows * cell.height) num_rows += 1;
    }
    ref->effective_num_rows = num_rows;
    ref->effective_num_cols = num_cols;
}


static uint32_t
handle_put_command(GraphicsManager *self, const GraphicsCommand *g, Cursor *c, bool *is_dirty, Image *img, CellPixelSize cell) {
    if (img == NULL) {
        if (g->id) img = img_by_client_id(self, g->id);
        else if (g->image_number) img = img_by_client_number(self, g->image_number);
        if (img == NULL) { set_command_failed_response("ENOENT", "Put command refers to non-existent image with id: %u and number: %u", g->id, g->image_number); return g->id; }
    }
    if (!img->root_frame_data_loaded) { set_command_failed_response("ENOENT", "Put command refers to image with id: %u that could not load its data", g->id); return img->client_id; }
    ensure_space_for(img, refs, ImageRef, img->refcnt + 1, refcap, 16, true);
    *is_dirty = true;
    self->layers_dirty = true;
    ImageRef *ref = NULL;
    if (g->placement_id && img->client_id) {
        for (size_t i=0; i < img->refcnt; i++) {
            if (img->refs[i].client_id == g->placement_id) {
                ref = img->refs + i;
                break;
            }
        }
    }
    if (ref == NULL) {
        ref = img->refs + img->refcnt++;
        zero_at_ptr(ref);
    }
    img->atime = monotonic();
    ref->src_x = g->x_offset; ref->src_y = g->y_offset; ref->src_width = g->width ? g->width : img->width; ref->src_height = g->height ? g->height : img->height;
    ref->src_width = MIN(ref->src_width, img->width - (img->width > ref->src_x ? ref->src_x : img->width));
    ref->src_height = MIN(ref->src_height, img->height - (img->height > ref->src_y ? ref->src_y : img->height));
    ref->z_index = g->z_index;
    ref->start_row = c->y; ref->start_column = c->x;
    ref->cell_x_offset = MIN(g->cell_x_offset, cell.width - 1);
    ref->cell_y_offset = MIN(g->cell_y_offset, cell.height - 1);
    ref->num_cols = g->num_cells; ref->num_rows = g->num_lines;
    if (img->client_id) ref->client_id = g->placement_id;
    update_src_rect(ref, img);
    update_dest_rect(ref, g->num_cells, g->num_lines, cell);
    // Move the cursor, the screen will take care of ensuring it is in bounds
    if (g->cursor_movement != 1) {
        c->x += ref->effective_num_cols; c->y += ref->effective_num_rows - 1;
    }
    return img->client_id;
}

static inline void
set_vertex_data(ImageRenderData *rd, const ImageRef *ref, const ImageRect *dest_rect) {
#define R(n, a, b) rd->vertices[n*4] = ref->src_rect.a; rd->vertices[n*4 + 1] = ref->src_rect.b; rd->vertices[n*4 + 2] = dest_rect->a; rd->vertices[n*4 + 3] = dest_rect->b;
        R(0, right, top); R(1, right, bottom); R(2, left, bottom); R(3, left, top);
#undef R
}

void
gpu_data_for_centered_image(ImageRenderData *ans, unsigned int screen_width_px, unsigned int screen_height_px, unsigned int width, unsigned int height) {
    static const ImageRef source_rect = { .src_rect = { .left=0, .top=0, .bottom=1, .right=1 }};
    const ImageRef *ref = &source_rect;
    float width_frac = 2 * MIN(1, width / (float)screen_width_px), height_frac = 2 * MIN(1, height / (float)screen_height_px);
    float hmargin = (2 - width_frac) / 2;
    float vmargin = (2 - height_frac) / 2;
    const ImageRect r = { .left = -1 + hmargin, .right = -1 + hmargin + width_frac, .top = 1 - vmargin, .bottom = 1 - vmargin - height_frac };
    set_vertex_data(ans, ref, &r);
}

bool
grman_update_layers(GraphicsManager *self, unsigned int scrolled_by, float screen_left, float screen_top, float dx, float dy, unsigned int num_cols, unsigned int num_rows, CellPixelSize cell) {
    if (self->last_scrolled_by != scrolled_by) self->layers_dirty = true;
    self->last_scrolled_by = scrolled_by;
    if (!self->layers_dirty) return false;
    self->layers_dirty = false;
    size_t i, j;
    self->num_of_below_refs = 0;
    self->num_of_negative_refs = 0;
    self->num_of_positive_refs = 0;
    Image *img; ImageRef *ref;
    ImageRect r;
    float screen_width = dx * num_cols, screen_height = dy * num_rows;
    float screen_bottom = screen_top - screen_height;
    float screen_width_px = num_cols * cell.width;
    float screen_height_px = num_rows * cell.height;
    float y0 = screen_top - dy * scrolled_by;

    // Iterate over all visible refs and create render data
    self->count = 0;
    for (i = 0; i < self->image_count; i++) {
        img = self->images + i;
        bool was_drawn = img->is_drawn;
        img->is_drawn = false;

        for (j = 0; j < img->refcnt; j++) { ref = img->refs + j;
            r.top = y0 - ref->start_row * dy - dy * (float)ref->cell_y_offset / (float)cell.height;
            if (ref->num_rows > 0) r.bottom = y0 - (ref->start_row + (int32_t)ref->num_rows) * dy;
            else r.bottom = r.top - screen_height * (float)ref->src_height / screen_height_px;
            if (r.top <= screen_bottom || r.bottom >= screen_top) continue;  // not visible

            r.left = screen_left + ref->start_column * dx + dx * (float)ref->cell_x_offset / (float) cell.width;
            if (ref->num_cols > 0) r.right = screen_left + (ref->start_column + (int32_t)ref->num_cols) * dx;
            else r.right = r.left + screen_width * (float)ref->src_width / screen_width_px;

            if (ref->z_index < ((int32_t)INT32_MIN/2))
                self->num_of_below_refs++;
            else if (ref->z_index < 0)
                self->num_of_negative_refs++;
            else
                self->num_of_positive_refs++;
            ensure_space_for(self, render_data, ImageRenderData, self->count + 1, capacity, 64, true);
            ImageRenderData *rd = self->render_data + self->count;
            zero_at_ptr(rd);
            set_vertex_data(rd, ref, &r);
            self->count++;
            rd->z_index = ref->z_index; rd->image_id = img->internal_id;
            rd->texture_id = img->texture_id;
            img->is_drawn = true;
        }
        if (img->is_drawn && !was_drawn && img->animation_state != ANIMATION_STOPPED && img->extra_framecnt && img->animation_duration) {
            self->has_images_needing_animation = true;
            global_state.check_for_active_animated_images = true;
        }
    }
    if (!self->count) return false;
    // Sort visible refs in draw order (z-index, img)
#define lt(a, b) ( (a)->z_index < (b)->z_index || ((a)->z_index == (b)->z_index && (a)->image_id < (b)->image_id) )
    QSORT(ImageRenderData, self->render_data, self->count, lt);
#undef lt
    // Calculate the group counts
    i = 0;
    while (i < self->count) {
        id_type image_id = self->render_data[i].image_id, start = i;
        if (start == self->count - 1) i = self->count;
        else {
            while (i < self->count - 1 && self->render_data[++i].image_id == image_id) {}
        }
        self->render_data[start].group_count = i - start;
    }
    return true;
}

// }}}

// Animation {{{
#define DEFAULT_GAP 40
#define _frame_number num_lines
#define _other_frame_number num_cells
#define _gap z_index
#define _animation_state data_width
#define _blend_mode cell_x_offset
#define _bgcolor cell_y_offset
#define _loop_count data_height

static inline Frame*
current_frame(Image *img) {
    if (img->current_frame_index > img->extra_framecnt) return NULL;
    return img->current_frame_index ? img->extra_frames + img->current_frame_index - 1 : &img->root_frame;
}

static inline Frame*
frame_for_id(Image *img, const uint32_t frame_id) {
    if (img->root_frame.id == frame_id) return &img->root_frame;
    for (unsigned i = 0; i < img->extra_framecnt; i++) {
        if (img->extra_frames[i].id == frame_id) return img->extra_frames + i;
    }
    return NULL;
}

static inline Frame*
frame_for_number(Image *img, const uint32_t frame_number) {
    switch(frame_number) {
        case 1:
            return &img->root_frame;
        case 0:
            return NULL;
        default:
            if (frame_number - 2 < img->extra_framecnt) return img->extra_frames + frame_number - 2;
            return NULL;
    }
}

static inline void
change_gap(Image *img, Frame *f, int32_t gap) {
    uint32_t prev_gap = f->gap;
    f->gap = MAX(0, gap);
    img->animation_duration = prev_gap < img->animation_duration ? img->animation_duration - prev_gap : 0;
    img->animation_duration += f->gap;
}

typedef struct {
    uint8_t *buf;
    bool is_4byte_aligned, is_opaque;
} CoalescedFrameData;

static inline void
blend_on_opaque(uint8_t *under_px, const uint8_t *over_px) {
    const float alpha = (float)over_px[3] / 255.f;
    const float alpha_op = 1.f - alpha;
    for (unsigned i = 0; i < 3; i++) under_px[i] = (uint8_t)(over_px[i] * alpha + under_px[i] * alpha_op);
}

static inline void
alpha_blend(uint8_t *dest_px, const uint8_t *src_px) {
    if (src_px[3]) {
        const float dest_a = (float)dest_px[3] / 255.f, src_a = (float)src_px[3] / 255.f;
        const float alpha = src_a + dest_a * (1.f - src_a);
        dest_px[3] = (uint8_t)(255 * alpha);
        if (!dest_px[3]) { dest_px[0] = 0; dest_px[1] = 0; dest_px[2] = 0; return; }
        for (unsigned i = 0; i < 3; i++) dest_px[i] = (uint8_t)((src_px[i] * src_a + dest_px[i] * dest_a * (1.f - src_a))/alpha);
    }
}

typedef struct {
    bool needs_blending;
    uint32_t over_px_sz, under_px_sz;
    uint32_t over_width, over_height, under_width, under_height, over_offset_x, over_offset_y;
} ComposeData;

static inline void
compose(const ComposeData d, uint8_t *under_data, const uint8_t *over_data) {
    const bool can_copy_rows = !d.needs_blending && d.over_px_sz == d.under_px_sz;
    unsigned min_row_sz = d.over_offset_x < d.under_width ? d.under_width - d.over_offset_x : 0;
    min_row_sz = MIN(min_row_sz, d.over_width);
#define ROW_ITER for (unsigned y = 0; y + d.over_offset_y < d.under_height && y < d.over_height; y++) { \
        uint8_t *under_row = under_data + (y + d.over_offset_y) * d.under_px_sz * d.under_width + d.under_px_sz * d.over_offset_x; \
        const uint8_t *over_row = over_data + y * d.over_px_sz * d.over_width;
    if (can_copy_rows) {
        ROW_ITER memcpy(under_row, over_row, (size_t)d.over_px_sz * min_row_sz);}
        return;
    }
#define PIX_ITER for (unsigned x = 0; x < min_row_sz; x++) { \
        uint8_t *under_px = under_row + (d.under_px_sz * x); \
        const uint8_t *over_px = over_row + (d.over_px_sz * x);
#define COPY_RGB under_px[0] = over_px[0]; under_px[1] = over_px[1]; under_px[2] = over_px[2];
    if (d.needs_blending) {
        if (d.under_px_sz == 3) {
            ROW_ITER PIX_ITER blend_on_opaque(under_px, over_px); }}
        } else {
            ROW_ITER PIX_ITER alpha_blend(under_px, over_px); }}
        }
    } else {
        if (d.under_px_sz == 4) {
            if (d.over_px_sz == 4) {
                ROW_ITER PIX_ITER COPY_RGB under_px[3] = over_px[3]; }}
            } else {
                ROW_ITER PIX_ITER COPY_RGB under_px[3] = 255; }}
            }
        } else {
            ROW_ITER PIX_ITER COPY_RGB }}
        }
    }
#undef COPY_RGB
#undef PIX_ITER
#undef ROW_ITER
}

static CoalescedFrameData
get_coalesced_frame_data_standalone(const Image *img, const Frame *f, uint8_t *frame_data) {
    CoalescedFrameData ans = {0};
    bool is_full_frame = f->width == img->width && f->height == img->height && !f->x && !f->y;
    if (is_full_frame) {
        ans.buf = frame_data;
        ans.is_4byte_aligned = f->is_4byte_aligned;
        ans.is_opaque = f->is_opaque;
        return ans;
    }
    const unsigned bytes_per_pixel = f->is_opaque ? 3 : 4;
    uint8_t *base;
    if (f->bgcolor) {
        base = malloc((size_t)img->width * img->height * bytes_per_pixel);
        if (base) {
            uint8_t *p = base;
            const uint8_t r = (f->bgcolor >> 24) & 0xff,
                  g = (f->bgcolor >> 16) & 0xff, b = (f->bgcolor >> 8) & 0xff, a = f->bgcolor & 0xff;
            if (bytes_per_pixel == 4) {
                for (uint32_t i = 0; i < img->width * img->height; i++) {
                    *(p++) = r; *(p++) = g; *(p++) = b; *(p++) = a;
                }
            } else {
                for (uint32_t i = 0; i < img->width * img->height; i++) {
                    *(p++) = r; *(p++) = g; *(p++) = b;
                }
            }
        }
    } else base = calloc((size_t)img->width * img->height, bytes_per_pixel);
    if (!base) { free(frame_data); return ans; }
    ComposeData d = {
        .over_px_sz = bytes_per_pixel, .under_px_sz = bytes_per_pixel,
        .over_width = f->width, .over_height = f->height, .over_offset_x = f->x, .over_offset_y = f->y,
        .under_width = img->width, .under_height = img->height,
        .needs_blending = f->alpha_blend && !f->is_opaque
    };
    compose(d, base, frame_data);
    ans.buf = base;
    ans.is_4byte_aligned = bytes_per_pixel == 4 || (img->width % 4) == 0;
    ans.is_opaque = f->is_opaque;
    free(frame_data);
    return ans;
}


static CoalescedFrameData
get_coalesced_frame_data_impl(GraphicsManager *self, Image *img, const Frame *f, unsigned count) {
    CoalescedFrameData ans = {0};
    if (count > 32) return ans;  // prevent stack overflows, infinite recursion
    size_t frame_data_sz; void *frame_data;
    ImageAndFrame key = {.image_id = img->internal_id, .frame_id = f->id};
    if (!read_from_cache(self, key, &frame_data, &frame_data_sz)) return ans;
    if (!f->base_frame_id) return get_coalesced_frame_data_standalone(img, f, frame_data);
    Frame *base = frame_for_id(img, f->base_frame_id);
    if (!base) { free(frame_data); return ans; }
    CoalescedFrameData base_data = get_coalesced_frame_data_impl(self, img, base, count + 1);
    if (!base_data.buf) { free(frame_data); return ans; }
    ComposeData d = {
        .over_px_sz = f->is_opaque ? 3 : 4,
        .under_px_sz = base_data.is_opaque ? 3 : 4,
        .over_width = f->width, .over_height = f->height, .over_offset_x = f->x, .over_offset_y = f->y,
        .under_width = img->width, .under_height = img->height,
        .needs_blending = f->alpha_blend && !f->is_opaque
    };
    compose(d, base_data.buf, frame_data);
    free(frame_data);
    return base_data;
}

static inline CoalescedFrameData
get_coalesced_frame_data(GraphicsManager *self, Image *img, const Frame *f) {
    return get_coalesced_frame_data_impl(self, img, f, 0);
}

static void
update_current_frame(GraphicsManager *self, Image *img, const CoalescedFrameData *data) {
    bool needs_load = data == NULL;
    CoalescedFrameData cfd;
    if (needs_load) {
        Frame *f = current_frame(img);
        if (f == NULL) return;
        cfd = get_coalesced_frame_data(self, img, f);
        if (!cfd.buf) {
            if (PyErr_Occurred()) PyErr_Print();
            return;
        }
        data = &cfd;
    }
    upload_to_gpu(self, img, data->is_opaque, data->is_4byte_aligned, data->buf);
    if (needs_load) free(data->buf);
    img->current_frame_shown_at = monotonic();
}

static bool
reference_chain_too_large(Image *img, const Frame *frame) {
    uint32_t limit = img->width * img->height * 2;
    uint32_t drawn_area = frame->width * frame->height;
    unsigned num = 1;
    while (drawn_area < limit && num < 5) {
        if (!frame->base_frame_id || !(frame = frame_for_id(img, frame->base_frame_id))) break;
        drawn_area += frame->width * frame->height;
        num++;
    }
    return num >= 5 || drawn_area >= limit;
}

static Image*
handle_animation_frame_load_command(GraphicsManager *self, GraphicsCommand *g, Image *img, const uint8_t *payload, bool *is_dirty) {
    uint32_t frame_number = g->_frame_number, fmt = g->format ? g->format : RGBA;
    if (!frame_number || frame_number > img->extra_framecnt + 2) frame_number = img->extra_framecnt + 2;
    bool is_new_frame = frame_number == img->extra_framecnt + 2;
    g->_frame_number = frame_number;
    unsigned char tt = g->transmission_type ? g->transmission_type : 'd';
    if (tt == 'd' && self->currently_loading.loading_for.image_id == img->internal_id) {
        INIT_CHUNKED_LOAD;
    } else {
        self->currently_loading.loading_for = (const ImageAndFrame){0};
        if (g->data_width > MAX_IMAGE_DIMENSION || g->data_height > MAX_IMAGE_DIMENSION) ABRT("EINVAL", "Image too large");
        if (!initialize_load_data(self, g, img, tt, fmt, frame_number - 1)) return NULL;
    }
    LoadData *load_data = &self->currently_loading;
    img = load_image_data(self, img, g, tt, fmt, payload);
    if (!img || !load_data->loading_completed_successfully) return NULL;
    self->currently_loading.loading_for = (const ImageAndFrame){0};
    img = process_image_data(self, img, g, tt, fmt);
    if (!img || !load_data->loading_completed_successfully) return img;

    const unsigned long bytes_per_pixel = load_data->is_opaque ? 3 : 4;
    if (load_data->data_sz < bytes_per_pixel * load_data->width * load_data->height)
        ABRT("ENODATA", "Insufficient image data %zu < %zu", load_data->data_sz, bytes_per_pixel * g->data_width, g->data_height);
    if (load_data->width > img->width)
        ABRT("EINVAL", "Frame width %u larger than image width: %u", load_data->width, img->width);
    if (load_data->height > img->height)
        ABRT("EINVAL", "Frame height %u larger than image height: %u", load_data->height, img->height);
    if (is_new_frame && cache_size(self) + load_data->data_sz > self->storage_limit * 5) {
        remove_images(self, trim_predicate, img->internal_id);
        if (is_new_frame && cache_size(self) + load_data->data_sz > self->storage_limit * 5)
            ABRT("ENOSPC", "Cache size exceeded cannot add new frames");
    }

    Frame transmitted_frame = {
        .width = load_data->width, .height = load_data->height,
        .x = g->x_offset, .y = g->y_offset,
        .is_4byte_aligned = load_data->is_4byte_aligned,
        .is_opaque = load_data->is_opaque,
        .alpha_blend = g->_blend_mode != 1 && !load_data->is_opaque,
        .gap = g->_gap > 0 ? g->_gap : (g->_gap < 0) ? 0 : DEFAULT_GAP,
        .bgcolor = g->_bgcolor,
    };
    Frame *frame;
    if (is_new_frame) {
        transmitted_frame.id = ++img->frame_id_counter;
        Frame *frames = realloc(img->extra_frames, sizeof(img->extra_frames[0]) * (img->extra_framecnt + 1));
        if (!frames) ABRT("ENOMEM", "Out of memory");
        img->extra_frames = frames;
        img->extra_framecnt++;
        frame = img->extra_frames + frame_number - 2;
        const ImageAndFrame key = { .image_id = img->internal_id, .frame_id = transmitted_frame.id };
        if (g->_other_frame_number) {
            Frame *other_frame = frame_for_number(img, g->_other_frame_number);
            if (!other_frame) {
                img->extra_framecnt--;
                ABRT("EINVAL", "No frame with number: %u found", g->_other_frame_number);
            }
            if (other_frame->base_frame_id && reference_chain_too_large(img, other_frame)) {
                // since there is a long reference chain to render this frame, make
                // it a fully coalesced key frame, for performance
                CoalescedFrameData cfd = get_coalesced_frame_data(self, img, other_frame);
                if (!cfd.buf) ABRT("EINVAL", "Failed to get data from frame referenced by frame: %u", frame_number);
                ComposeData d = {
                    .over_px_sz = transmitted_frame.is_opaque ? 3 : 4, .under_px_sz = cfd.is_opaque ? 3: 4,
                    .over_width = transmitted_frame.width, .over_height = transmitted_frame.height,
                    .over_offset_x = transmitted_frame.x, .over_offset_y = transmitted_frame.y,
                    .under_width = img->width, .under_height = img->height,
                    .needs_blending = transmitted_frame.alpha_blend && !transmitted_frame.is_opaque
                };
                compose(d, cfd.buf, load_data->data);
                free_load_data(load_data);
                load_data->data = cfd.buf; load_data->data_sz = (size_t)img->width * img->height * d.under_px_sz;
                transmitted_frame.width = img->width; transmitted_frame.height = img->height;
                transmitted_frame.x = 0; transmitted_frame.y = 0;
                transmitted_frame.is_4byte_aligned = cfd.is_4byte_aligned;
                transmitted_frame.is_opaque = cfd.is_opaque;
            } else {
                transmitted_frame.base_frame_id = other_frame->id;
            }
        }
        *frame = transmitted_frame;
        if (!add_to_cache(self, key, load_data->data, load_data->data_sz)) {
            img->extra_framecnt--;
            if (PyErr_Occurred()) PyErr_Print();
            ABRT("ENOSPC", "Failed to cache data for image frame");
        }
        img->animation_duration += frame->gap;
        if (img->animation_state == ANIMATION_LOADING) {
            self->has_images_needing_animation = true;
            global_state.check_for_active_animated_images = true;
        }
    } else {
        frame = frame_for_number(img, frame_number);
        if (!frame) ABRT("EINVAL", "No frame with number: %u found", frame_number);
        if (g->_gap != 0) change_gap(img, frame, transmitted_frame.gap);
        CoalescedFrameData cfd = get_coalesced_frame_data(self, img, frame);
        if (!cfd.buf) ABRT("EINVAL", "No data associated with frame number: %u", frame_number);
        frame->alpha_blend = false; frame->base_frame_id = 0; frame->bgcolor = 0;
        frame->is_opaque = cfd.is_opaque; frame->is_4byte_aligned = cfd.is_4byte_aligned;
        frame->x = 0; frame->y = 0; frame->width = img->width; frame->height = img->height;
        const unsigned bytes_per_pixel = frame->is_opaque ? 3: 4;
        ComposeData d = {
            .over_px_sz = transmitted_frame.is_opaque ? 3 : 4, .under_px_sz = bytes_per_pixel,
            .over_width = transmitted_frame.width, .over_height = transmitted_frame.height,
            .over_offset_x = transmitted_frame.x, .over_offset_y = transmitted_frame.y,
            .under_width = frame->width, .under_height = frame->height,
            .needs_blending = transmitted_frame.alpha_blend && !transmitted_frame.is_opaque
        };
        compose(d, cfd.buf, load_data->data);
        const ImageAndFrame key = { .image_id = img->internal_id, .frame_id = frame->id };
        bool added = add_to_cache(self, key, cfd.buf, (size_t)bytes_per_pixel * frame->width * frame->height);
        if (added && frame == current_frame(img)) {
            update_current_frame(self, img, &cfd);
            *is_dirty = true;
        }
        free(cfd.buf);
        if (!added) {
            if (PyErr_Occurred()) PyErr_Print();
            ABRT("ENOSPC", "Failed to cache data for image frame");
        }
    }
    return img;
}

#undef ABRT

static Image*
handle_delete_frame_command(GraphicsManager *self, const GraphicsCommand *g, bool *is_dirty) {
    if (!g->id && !g->image_number) {
        REPORT_ERROR("Delete frame data command without image id or number");
        return NULL;
    }
    Image *img = g->id ? img_by_client_id(self, g->id) : img_by_client_number(self, g->image_number);
    if (!img) {
        REPORT_ERROR("Animation command refers to non-existent image with id: %u and number: %u", g->id, g->image_number);
        return NULL;
    }
    uint32_t frame_number = MIN(img->extra_framecnt + 1, g->_frame_number);
    if (!frame_number) frame_number = 1;
    if (!img->extra_framecnt) return g->delete_action == 'F' ? img : NULL;
    *is_dirty = true;
    ImageAndFrame key = {.image_id=img->internal_id};
    bool remove_root = frame_number == 1;
    uint32_t removed_gap = 0;
    if (remove_root) {
        key.frame_id = img->root_frame.id;
        remove_from_cache(self, key);
        if (PyErr_Occurred()) PyErr_Print();
        removed_gap = img->root_frame.gap;
        img->root_frame = img->extra_frames[0];
    }
    unsigned removed_idx = remove_root ? 0 : frame_number - 2;
    if (!remove_root) {
        key.frame_id = img->extra_frames[removed_idx].id;
        removed_gap = img->extra_frames[removed_idx].gap;
        remove_from_cache(self, key);
    }
    img->animation_duration = removed_gap < img->animation_duration ? img->animation_duration - removed_gap : 0;
    if (PyErr_Occurred()) PyErr_Print();
    if (removed_idx < img->extra_framecnt - 1) memmove(img->extra_frames + removed_idx, img->extra_frames + removed_idx + 1, sizeof(img->extra_frames[0]) * (img->extra_framecnt - 1 - removed_idx));
    img->extra_framecnt--;
    if (img->current_frame_index > img->extra_framecnt) {
        img->current_frame_index = img->extra_framecnt;
        update_current_frame(self, img, NULL);
        return NULL;
    }
    if (removed_idx == img->current_frame_index) update_current_frame(self, img, NULL);
    else if (removed_idx < img->current_frame_index) img->current_frame_index--;
    return NULL;
}

static void
handle_animation_control_command(GraphicsManager *self, bool *is_dirty, const GraphicsCommand *g, Image *img) {
    if (g->_frame_number) {
        uint32_t frame_idx = g->_frame_number - 1;
        if (frame_idx <= img->extra_framecnt) {
            Frame *f = frame_idx ? img->extra_frames + frame_idx - 1 : &img->root_frame;
            if (g->_gap) change_gap(img, f, g->_gap);
        }
    }
    if (g->_other_frame_number) {
        uint32_t frame_idx = g->_other_frame_number - 1;
        if (frame_idx != img->current_frame_index && frame_idx <= img->extra_framecnt) {
            img->current_frame_index = frame_idx;
            *is_dirty = true;
            update_current_frame(self, img, NULL);
        }
    }
    if (g->_animation_state) {
        AnimationState old_state = img->animation_state;
        switch(g->_animation_state) {
            case 1:
                img->animation_state = ANIMATION_STOPPED; break;
            case 2:
                img->animation_state = ANIMATION_LOADING; break;
            case 3:
                img->animation_state = ANIMATION_RUNNING; break;
            default:
                break;
        }
        if (img->animation_state == ANIMATION_STOPPED) {
            img->current_loop = 0;
        } else {
            if (old_state == ANIMATION_STOPPED) img->current_frame_shown_at = monotonic();
            self->has_images_needing_animation = true;
            global_state.check_for_active_animated_images = true;
        }
        img->current_loop = 0;
    }
    if (g->_loop_count) {
        img->max_loops = g->_loop_count - 1;
        global_state.check_for_active_animated_images = true;
    }
}

static inline bool
image_is_animatable(const Image *img) {
    return img->animation_state != ANIMATION_STOPPED && img->extra_framecnt && img->is_drawn && img->animation_duration && (
            !img->max_loops || img->current_loop < img->max_loops);
}

bool
scan_active_animations(GraphicsManager *self, const monotonic_t now, monotonic_t *minimum_gap, bool os_window_context_set) {
    bool dirtied = false;
    *minimum_gap = MONOTONIC_T_MAX;
    if (!self->has_images_needing_animation) return dirtied;
    self->has_images_needing_animation = false;
    self->context_made_current_for_this_command = os_window_context_set;
    for (size_t i = self->image_count; i-- > 0;) {
        Image *img = self->images + i;
        if (image_is_animatable(img)) {
            Frame *f = current_frame(img);
            if (f) {
                self->has_images_needing_animation = true;
                monotonic_t next_frame_at = img->current_frame_shown_at + ms_to_monotonic_t(f->gap);
                if (now >= next_frame_at) {
                    do {
                        uint32_t next = (img->current_frame_index + 1) % (img->extra_framecnt + 1);
                        if (!next) {
                            if (img->animation_state == ANIMATION_LOADING) goto skip_image;
                            if (++img->current_loop >= img->max_loops && img->max_loops) goto skip_image;
                        }
                        img->current_frame_index = next;
                    } while (!current_frame(img)->gap);
                    dirtied = true;
                    update_current_frame(self, img, NULL);
                    f = current_frame(img);
                    next_frame_at = img->current_frame_shown_at + ms_to_monotonic_t(f->gap);
                }
                if (next_frame_at > now && next_frame_at - now < *minimum_gap) *minimum_gap = next_frame_at - now;
            }
        }
        skip_image:;
    }
    return dirtied;
}
// }}}

// Image lifetime/scrolling {{{

static inline void
filter_refs(GraphicsManager *self, const void* data, bool free_images, bool (*filter_func)(const ImageRef*, Image*, const void*, CellPixelSize), CellPixelSize cell, bool only_first_image) {
    bool matched = false;
    for (size_t i = self->image_count; i-- > 0;) {
        Image *img = self->images + i;
        for (size_t j = img->refcnt; j-- > 0;) {
            ImageRef *ref = img->refs + j;
            if (filter_func(ref, img, data, cell)) {
                remove_i_from_array(img->refs, j, img->refcnt);
                self->layers_dirty = true;
                matched = true;
            }
        }
        if (img->refcnt == 0 && (free_images || img->client_id == 0)) remove_image(self, i);
        if (only_first_image && matched) break;
    }
}


static inline void
modify_refs(GraphicsManager *self, const void* data, bool free_images, bool (*filter_func)(ImageRef*, Image*, const void*, CellPixelSize), CellPixelSize cell) {
    for (size_t i = self->image_count; i-- > 0;) {
        Image *img = self->images + i;
        for (size_t j = img->refcnt; j-- > 0;) {
            if (filter_func(img->refs + j, img, data, cell)) remove_i_from_array(img->refs, j, img->refcnt);
        }
        if (img->refcnt == 0 && (free_images || img->client_id == 0)) remove_image(self, i);
    }
}


static inline bool
scroll_filter_func(ImageRef *ref, Image UNUSED *img, const void *data, CellPixelSize cell UNUSED) {
    ScrollData *d = (ScrollData*)data;
    ref->start_row += d->amt;
    return ref->start_row + (int32_t)ref->effective_num_rows <= d->limit;
}

static inline bool
ref_within_region(const ImageRef *ref, index_type margin_top, index_type margin_bottom) {
    return ref->start_row >= (int32_t)margin_top && ref->start_row + ref->effective_num_rows <= margin_bottom;
}

static inline bool
ref_outside_region(const ImageRef *ref, index_type margin_top, index_type margin_bottom) {
    return ref->start_row + ref->effective_num_rows <= margin_top || ref->start_row > (int32_t)margin_bottom;
}

static inline bool
scroll_filter_margins_func(ImageRef* ref, Image* img, const void* data, CellPixelSize cell) {
    ScrollData *d = (ScrollData*)data;
    if (ref_within_region(ref, d->margin_top, d->margin_bottom)) {
        ref->start_row += d->amt;
        if (ref_outside_region(ref, d->margin_top, d->margin_bottom)) return true;
        // Clip the image if scrolling has resulted in part of it being outside the page area
        uint32_t clip_amt, clipped_rows;
        if (ref->start_row < (int32_t)d->margin_top) {
            // image moved up
            clipped_rows = d->margin_top - ref->start_row;
            clip_amt = cell.height * clipped_rows;
            if (ref->src_height <= clip_amt) return true;
            ref->src_y += clip_amt; ref->src_height -= clip_amt;
            ref->effective_num_rows -= clipped_rows;
            update_src_rect(ref, img);
            ref->start_row += clipped_rows;
        } else if (ref->start_row + ref->effective_num_rows > d->margin_bottom) {
            // image moved down
            clipped_rows = ref->start_row + ref->effective_num_rows - d->margin_bottom;
            clip_amt = cell.height * clipped_rows;
            if (ref->src_height <= clip_amt) return true;
            ref->src_height -= clip_amt;
            ref->effective_num_rows -= clipped_rows;
            update_src_rect(ref, img);
        }
        return ref_outside_region(ref, d->margin_top, d->margin_bottom);
    }
    return false;
}

void
grman_scroll_images(GraphicsManager *self, const ScrollData *data, CellPixelSize cell) {
    if (self->image_count) {
        self->layers_dirty = true;
        modify_refs(self, data, true, data->has_margins ? scroll_filter_margins_func : scroll_filter_func, cell);
    }
}

static inline bool
clear_filter_func(const ImageRef *ref, Image UNUSED *img, const void UNUSED *data, CellPixelSize cell UNUSED) {
    return ref->start_row + (int32_t)ref->effective_num_rows > 0;
}

static inline bool
clear_all_filter_func(const ImageRef *ref UNUSED, Image UNUSED *img, const void UNUSED *data, CellPixelSize cell UNUSED) {
    return true;
}

void
grman_clear(GraphicsManager *self, bool all, CellPixelSize cell) {
    filter_refs(self, NULL, true, all ? clear_all_filter_func : clear_filter_func, cell, false);
}

static inline bool
id_filter_func(const ImageRef *ref, Image *img, const void *data, CellPixelSize cell UNUSED) {
    const GraphicsCommand *g = data;
    if (g->id && img->client_id == g->id) return !g->placement_id || ref->client_id == g->placement_id;
    return false;
}

static inline bool
number_filter_func(const ImageRef *ref, Image *img, const void *data, CellPixelSize cell UNUSED) {
    const GraphicsCommand *g = data;
    if (g->image_number && img->client_number == g->image_number) return !g->placement_id || ref->client_id == g->placement_id;
    return false;
}


static inline bool
x_filter_func(const ImageRef *ref, Image UNUSED *img, const void *data, CellPixelSize cell UNUSED) {
    const GraphicsCommand *g = data;
    return ref->start_column <= (int32_t)g->x_offset - 1 && ((int32_t)g->x_offset - 1) < ((int32_t)(ref->start_column + ref->effective_num_cols));
}

static inline bool
y_filter_func(const ImageRef *ref, Image UNUSED *img, const void *data, CellPixelSize cell UNUSED) {
    const GraphicsCommand *g = data;
    return ref->start_row <= (int32_t)g->y_offset - 1 && ((int32_t)(g->y_offset - 1 < ref->start_row + ref->effective_num_rows));
}

static inline bool
z_filter_func(const ImageRef *ref, Image UNUSED *img, const void *data, CellPixelSize cell UNUSED) {
    const GraphicsCommand *g = data;
    return ref->z_index == g->z_index;
}


static inline bool
point_filter_func(const ImageRef *ref, Image *img, const void *data, CellPixelSize cell) {
    return x_filter_func(ref, img, data, cell) && y_filter_func(ref, img, data, cell);
}

static inline bool
point3d_filter_func(const ImageRef *ref, Image *img, const void *data, CellPixelSize cell) {
    return z_filter_func(ref, img, data, cell) && point_filter_func(ref, img, data, cell);
}


static void
handle_delete_command(GraphicsManager *self, const GraphicsCommand *g, Cursor *c, bool *is_dirty, CellPixelSize cell) {
    GraphicsCommand d;
    bool only_first_image = false;
    switch (g->delete_action) {
#define I(u, data, func) filter_refs(self, data, g->delete_action == u, func, cell, only_first_image); *is_dirty = true; break
#define D(l, u, data, func) case l: case u: I(u, data, func)
#define G(l, u, func) D(l, u, g, func)
        case 0:
        D('a', 'A', NULL, clear_filter_func);
        G('i', 'I', id_filter_func);
        G('p', 'P', point_filter_func);
        G('q', 'Q', point3d_filter_func);
        G('x', 'X', x_filter_func);
        G('y', 'Y', y_filter_func);
        G('z', 'Z', z_filter_func);
        case 'c':
        case 'C':
            d.x_offset = c->x + 1; d.y_offset = c->y + 1;
            I('C', &d, point_filter_func);
        case 'n':
        case 'N':
            only_first_image = true;
            I('N', g, number_filter_func);
        case 'f':
        case 'F':
            if (handle_delete_frame_command(self, g, is_dirty) != NULL) {
                filter_refs(self, g, true, id_filter_func, cell, true);
                *is_dirty = true;
            }
            break;
        default:
            REPORT_ERROR("Unknown graphics command delete action: %c", g->delete_action);
            break;
#undef G
#undef D
#undef I
    }
    if (!self->image_count && self->count) self->count = 0;
}

// }}}

void
grman_resize(GraphicsManager *self, index_type UNUSED old_lines, index_type UNUSED lines, index_type UNUSED old_columns, index_type UNUSED columns) {
    self->layers_dirty = true;
}

void
grman_rescale(GraphicsManager *self, CellPixelSize cell) {
    ImageRef *ref; Image *img;
    self->layers_dirty = true;
    for (size_t i = self->image_count; i-- > 0;) {
        img = self->images + i;
        for (size_t j = img->refcnt; j-- > 0;) {
            ref = img->refs + j;
            ref->cell_x_offset = MIN(ref->cell_x_offset, cell.width - 1);
            ref->cell_y_offset = MIN(ref->cell_y_offset, cell.height - 1);
            update_dest_rect(ref, ref->num_cols, ref->num_rows, cell);
        }
    }
}

const char*
grman_handle_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload, Cursor *c, bool *is_dirty, CellPixelSize cell) {
    const char *ret = NULL;
    command_response[0] = 0;
    self->context_made_current_for_this_command = false;

    if (g->id && g->image_number) {
        set_command_failed_response("EINVAL", "Must not specify both image id and image number");
        return finish_command_response(g, false);
    }

    switch(g->action) {
        case 0:
        case 't':
        case 'T':
        case 'q': {
            uint32_t iid = g->id, q_iid = iid;
            bool is_query = g->action == 'q';
            if (is_query) { iid = 0; if (!q_iid) { REPORT_ERROR("Query graphics command without image id"); break; } }
            Image *image = handle_add_command(self, g, payload, is_dirty, iid);
            if (!self->currently_loading.loading_for.image_id) free_load_data(&self->currently_loading);
            GraphicsCommand *lg = &self->currently_loading.start_command;
            if (g->quiet) lg->quiet = g->quiet;
            if (is_query) ret = finish_command_response(&(const GraphicsCommand){.id=q_iid, .quiet=g->quiet}, image != NULL);
            else ret = finish_command_response(lg, image != NULL);
            if (lg->action == 'T' && image && image->root_frame_data_loaded) handle_put_command(self, lg, c, is_dirty, image, cell);
            id_type added_image_id = image ? image->internal_id : 0;
            if (g->action == 'q') remove_images(self, add_trim_predicate, 0);
            if (self->used_storage > self->storage_limit) apply_storage_quota(self, self->storage_limit, added_image_id);
            break;
        }
        case 'a':
        case 'f': {
            if (!g->id && !g->image_number && !self->currently_loading.loading_for.image_id) {
                REPORT_ERROR("Add frame data command without image id or number");
                break;
            }
            Image *img;
            if (self->currently_loading.loading_for.image_id) img = img_by_internal_id(self, self->currently_loading.loading_for.image_id);
            else img = g->id ? img_by_client_id(self, g->id) : img_by_client_number(self, g->image_number);
            if (!img) {
                set_command_failed_response("ENOENT", "Animation command refers to non-existent image with id: %u and number: %u", g->id, g->image_number);
                ret = finish_command_response(g, false);
            } else {
                GraphicsCommand ag = *g;
                if (ag.action == 'f') {
                    img = handle_animation_frame_load_command(self, &ag, img, payload, is_dirty);
                    if (!self->currently_loading.loading_for.image_id) free_load_data(&self->currently_loading);
                    if (g->quiet) ag.quiet = g->quiet;
                    else ag.quiet = self->currently_loading.start_command.quiet;
                    ret = finish_command_response(&ag, img != NULL);
                } else if (ag.action == 'a') {
                    handle_animation_control_command(self, is_dirty, &ag, img);
                }
            }
            break;
        }
        case 'p': {
            if (!g->id && !g->image_number) {
                REPORT_ERROR("Put graphics command without image id or number");
                break;
            }
            uint32_t image_id = handle_put_command(self, g, c, is_dirty, NULL, cell);
            GraphicsCommand rg = *g; rg.id = image_id;
            ret = finish_command_response(&rg, true);
            break;
        }
        case 'd':
            handle_delete_command(self, g, c, is_dirty, cell);
            break;
        default:
            REPORT_ERROR("Unknown graphics command action: %c", g->action);
            break;
    }
    return ret;
}


// Boilerplate {{{
static PyObject *
new(PyTypeObject UNUSED *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    PyObject *ans = (PyObject*)grman_alloc();
    if (ans == NULL) PyErr_NoMemory();
    return ans;
}

static inline PyObject*
image_as_dict(GraphicsManager *self, Image *img) {
#define U(x) #x, (unsigned int)(img->x)
#define B(x) #x, img->x ? Py_True : Py_False
    PyObject *frames = PyTuple_New(img->extra_framecnt);
    for (unsigned i = 0; i < img->extra_framecnt; i++) {
        Frame *f = img->extra_frames + i;
        CoalescedFrameData cfd = get_coalesced_frame_data(self, img, f);
        if (!cfd.buf) { PyErr_SetString(PyExc_RuntimeError, "Failed to get data for frame"); return NULL; }
        PyTuple_SET_ITEM(frames, i, Py_BuildValue(
            "{sI sI sy#}",
            "gap", f->gap,
            "id", f->id,
            "data", cfd.buf, (Py_ssize_t)((cfd.is_opaque ? 3 : 4) * img->width * img->height)
        ));
        free(cfd.buf);
        if (PyErr_Occurred()) { Py_CLEAR(frames); return NULL; }
    }
    CoalescedFrameData cfd = get_coalesced_frame_data(self, img, &img->root_frame);
    if (!cfd.buf) { PyErr_SetString(PyExc_RuntimeError, "Failed to get data for root frame"); return NULL; }
    PyObject *ans = Py_BuildValue("{sI sI sI sI sI sI sI " "sO sI sO " "sI sI sI " "sI sy# sN}",
        U(texture_id), U(client_id), U(width), U(height), U(internal_id), U(refcnt), U(client_number),

        B(root_frame_data_loaded), U(animation_state), "is_4byte_aligned", img->root_frame.is_4byte_aligned ? Py_True : Py_False,

        U(current_frame_index), "root_frame_gap", img->root_frame.gap, U(current_frame_index),

        U(animation_duration), "data", cfd.buf, (Py_ssize_t)((cfd.is_opaque ? 3 : 4) * img->width * img->height), "extra_frames", frames
    );
    free(cfd.buf);
    return ans;
#undef B
#undef U
}

#define W(x) static PyObject* py##x(GraphicsManager UNUSED *self, PyObject *args)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;

W(image_for_client_id) {
    unsigned long id = PyLong_AsUnsignedLong(args);
    bool existing = false;
    Image *img = find_or_create_image(self, id, &existing);
    if (!existing) { Py_RETURN_NONE; }
    return image_as_dict(self, img);
}

W(image_for_client_number) {
    unsigned long num = PyLong_AsUnsignedLong(args);
    Image *img = img_by_client_number(self, num);
    if (!img) Py_RETURN_NONE;
    return image_as_dict(self, img);
}

W(shm_write) {
    const char *name, *data;
    Py_ssize_t sz;
    PA("ss#", &name, &data, &sz);
    int fd = shm_open(name, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR);
    if (fd == -1) { PyErr_SetFromErrnoWithFilename(PyExc_OSError, name); return NULL; }
    int ret = ftruncate(fd, sz);
    if (ret != 0) { safe_close(fd, __FILE__, __LINE__); PyErr_SetFromErrnoWithFilename(PyExc_OSError, name); return NULL; }
    void *addr = mmap(0, sz, PROT_WRITE, MAP_SHARED, fd, 0);
    if (addr == MAP_FAILED) { safe_close(fd, __FILE__, __LINE__); PyErr_SetFromErrnoWithFilename(PyExc_OSError, name); return NULL; }
    memcpy(addr, data, sz);
    if (munmap(addr, sz) != 0) { safe_close(fd, __FILE__, __LINE__); PyErr_SetFromErrnoWithFilename(PyExc_OSError, name); return NULL; }
    safe_close(fd, __FILE__, __LINE__);
    Py_RETURN_NONE;
}

W(shm_unlink) {
    char *name;
    PA("s", &name);
    int ret = shm_unlink(name);
    if (ret == -1) { PyErr_SetFromErrnoWithFilename(PyExc_OSError, name); return NULL; }
    Py_RETURN_NONE;
}

W(update_layers) {
    unsigned int scrolled_by, sx, sy; float xstart, ystart, dx, dy;
    CellPixelSize cell;
    PA("IffffIIII", &scrolled_by, &xstart, &ystart, &dx, &dy, &sx, &sy, &cell.width, &cell.height);
    grman_update_layers(self, scrolled_by, xstart, ystart, dx, dy, sx, sy, cell);
    PyObject *ans = PyTuple_New(self->count);
    for (size_t i = 0; i < self->count; i++) {
        ImageRenderData *r = self->render_data + i;
#define R(offset) Py_BuildValue("{sf sf sf sf}", "left", r->vertices[offset + 8], "top", r->vertices[offset + 1], "right", r->vertices[offset], "bottom", r->vertices[offset + 5])
        PyTuple_SET_ITEM(ans, i,
            Py_BuildValue("{sN sN sI si sK}", "src_rect", R(0), "dest_rect", R(2), "group_count", r->group_count, "z_index", r->z_index, "image_id", r->image_id)
        );
#undef R
    }
    return ans;
}

#define M(x, va) {#x, (PyCFunction)py##x, va, ""}

static PyMethodDef methods[] = {
    M(image_for_client_id, METH_O),
    M(image_for_client_number, METH_O),
    M(update_layers, METH_VARARGS),
    {NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"image_count", T_PYSSIZET, offsetof(GraphicsManager, image_count), READONLY, "image_count"},
    {"storage_limit", T_PYSSIZET, offsetof(GraphicsManager, storage_limit), 0, "storage_limit"},
    {"disk_cache", T_OBJECT_EX, offsetof(GraphicsManager, disk_cache), READONLY, "disk_cache"},
    {NULL},
};

PyTypeObject GraphicsManager_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.GraphicsManager",
    .tp_basicsize = sizeof(GraphicsManager),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "GraphicsManager",
    .tp_new = new,
    .tp_methods = methods,
    .tp_members = members,
};

static PyObject*
pycreate_canvas(PyObject *self UNUSED, PyObject *args) {
    unsigned int bytes_per_pixel;
    unsigned int over_width, width, height, x, y;
    Py_ssize_t over_sz;
    const uint8_t *over_data;
    if (!PyArg_ParseTuple(args, "y#IIIIII", &over_data, &over_sz, &over_width, &x, &y, &width, &height, &bytes_per_pixel)) return NULL;
    size_t canvas_sz = (size_t)width * height * bytes_per_pixel;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, canvas_sz);
    if (!ans) return NULL;

    uint8_t* canvas = (uint8_t*)PyBytes_AS_STRING(ans);
    memset(canvas, 0, canvas_sz);
    ComposeData cd = {
        .needs_blending = bytes_per_pixel == 4,
        .over_width = over_width, .over_height = over_sz / (bytes_per_pixel * over_width),
        .under_width = width, .under_height = height,
        .over_px_sz = bytes_per_pixel, .under_px_sz = bytes_per_pixel,
        .over_offset_x = x, .over_offset_y = y
    };
    compose(cd, canvas, over_data);

    return ans;
}

static PyMethodDef module_methods[] = {
    M(shm_write, METH_VARARGS),
    M(shm_unlink, METH_VARARGS),
    M(create_canvas, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_graphics(PyObject *module) {
    if (PyType_Ready(&GraphicsManager_Type) < 0) return false;
    if (PyModule_AddObject(module, "GraphicsManager", (PyObject *)&GraphicsManager_Type) != 0) return false;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    Py_INCREF(&GraphicsManager_Type);
    return true;
}
// }}}
