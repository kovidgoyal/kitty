#include "state.h"
#include "gl.h"
#include <string.h>
#include <strings.h>
#include <stdlib.h>

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
    // TODO: Replace with real Metal renderer initialization once implemented.
    // Returning false keeps the current OpenGL path as the operational default.
    return false;
#else
    return false;
#endif
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
    GPUBackend desired = desired_backend_from_env();
    if (desired == GPU_BACKEND_METAL && try_init_metal_backend()) {
        global_state.gpu_backend = GPU_BACKEND_METAL;
        return;
    }
    gl_init();
    global_state.gpu_backend = GPU_BACKEND_OPENGL;
}
