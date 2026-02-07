#include "state.h"
#include "gl.h"
#ifdef __APPLE__
#include "metal_renderer.h"
#endif
#include <string.h>
#include <strings.h>
#include <stdlib.h>
#ifdef _WIN32
#define strcasecmp _stricmp
#endif

// Placeholder backend selector. The intention is to allow a Metal renderer
// implementation to slot in for macOS while keeping the existing OpenGL path
// untouched for other platforms or as a fallback.

static GPUBackend
desired_backend_from_env(void) {
    const char *env = getenv("KITTY_GPU_BACKEND");
    if (!env) return GPU_BACKEND_OPENGL;
    if (strcasecmp(env, "metal") == 0) return GPU_BACKEND_METAL;
    if (strcasecmp(env, "opengl") == 0) return GPU_BACKEND_OPENGL;
    return GPU_BACKEND_OPENGL;
}

static bool
try_init_metal_backend(void) {
#ifdef __APPLE__
    return metal_backend_init();
#else
    return false;
#endif
}

static bool backend_chosen = false;

void
gpu_pick_backend(void) {
    if (backend_chosen) return;
    GPUBackend desired = desired_backend_from_env();
    if (desired == GPU_BACKEND_METAL && try_init_metal_backend()) {
        global_state.gpu_backend = GPU_BACKEND_METAL;
    } else {
        global_state.gpu_backend = GPU_BACKEND_OPENGL;
    }
    backend_chosen = true;
}

GPUBackend
gpu_backend(void) {
    return global_state.gpu_backend;
}

const char*
GPUBackend_name(GPUBackend b) {
    switch (b) {
        case GPU_BACKEND_METAL: return "metal";
        case GPU_BACKEND_OPENGL: default: return "opengl";
    }
}

void
gpu_init(void) {
    if (!backend_chosen) gpu_pick_backend();
    if (global_state.gpu_backend == GPU_BACKEND_OPENGL) {
        gl_init();
    } else {
#ifdef __APPLE__
        metal_backend_init();
#endif
    }
}
