/* Native GTK/libadwaita rendering for the existing Wayland CSD surfaces. */
#pragma once
#include "internal.h"
int csd_native_titlebar_margin(_GLFWwindow *window);
bool csd_native_titlebar_shadows(_GLFWwindow *window);
int csd_native_titlebar_height(_GLFWwindow *window);
bool csd_native_titlebar_render(_GLFWwindow *window, uint8_t *output);
void csd_native_titlebar_free(_GLFWwindow *window);
void csd_native_titlebar_terminate(void);
