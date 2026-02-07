#pragma once

typedef enum GPUBackend {
    GPU_BACKEND_OPENGL = 0,
    GPU_BACKEND_METAL = 1,
} GPUBackend;

GPUBackend gpu_backend(void);
const char* GPUBackend_name(GPUBackend backend);
void gpu_init(void);
