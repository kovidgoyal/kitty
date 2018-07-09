//========================================================================
// GLFW 3.3 XKB - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2018 Kovid Goyal <kovid@kovidgoyal.net>
//
// This software is provided 'as-is', without any express or implied
// warranty. In no event will the authors be held liable for any damages
// arising from the use of this software.
//
// Permission is granted to anyone to use this software for any purpose,
// including commercial applications, and to alter it and redistribute it
// freely, subject to the following restrictions:
//
// 1. The origin of this software must not be misrepresented; you must not
//    claim that you wrote the original software. If you use this software
//    in a product, an acknowledgment in the product documentation would
//    be appreciated but is not required.
//
// 2. Altered source versions must be plainly marked as such, and must not
//    be misrepresented as being the original software.
//
// 3. This notice may not be removed or altered from any source
//    distribution.
//
//========================================================================

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "internal.h"
#include "ibus_glfw.h"

#define debug(...) if (_glfw.hints.init.debugKeyboard) printf(__VA_ARGS__);

static inline GLFWbool
has_env_var(const char *name, const char *val) {
    const char *q = getenv(name);
    return (q && strcmp(q, val) == 0) ? GLFW_TRUE : GLFW_FALSE;
}

static inline GLFWbool
MIN(size_t a, size_t b) {
    return a < b ? a : b;
}


static inline const char*
get_ibus_address_file_name(void) {
    const char *addr;
    static char ans[PATH_MAX];
    addr = getenv("IBUS_ADDRESS");
    int offset = 0;
    if (addr && addr[0]) {
        memcpy(ans, addr, MIN(strlen(addr), sizeof(ans)));
        return ans;
    }

    const char *de = getenv("DISPLAY");
    if (!de || !de[0]) de = ":0.0";
    char *display = strdup(de);
    const char *host = display;
    char *disp_num  = strrchr(display, ':');
    char *screen_num = strrchr(display, '.');

    if (!disp_num) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Could not get IBUS address file name as DISPLAY env var has no colon");
        free(display);
        return NULL;
    }
    *disp_num = 0;
    disp_num++;
    if (screen_num) *screen_num = 0;
    if (!*host) host = "unix";

    memset(ans, 0, sizeof(ans));
    const char *conf_env = getenv("XDG_CONFIG_HOME");
    if (conf_env && conf_env[0]) {
        offset = snprintf(ans, sizeof(ans), "%s", conf_env);
    } else {
        conf_env = getenv("HOME");
        if (!conf_env || !conf_env[0]) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Could not get IBUS address file name as no HOME env var is set");
            free(display);
            return NULL;
        }
        offset = snprintf(ans, sizeof(ans), "%s/.config", conf_env);
    }
    char *key = dbus_get_local_machine_id();
    snprintf(ans + offset, sizeof(ans) - offset, "/ibus/bus/%s-%s-%s", key, host, disp_num);
    dbus_free(key);
    free(display);
    return ans;
}


static inline const char*
read_ibus_address(const char *address_file) {
    FILE *addr_file = fopen(address_file, "r");
    static char buf[1024];
    if (!addr_file) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to open IBUS address file: %s with error: %s", address_file, strerror(errno));
        return NULL;
    }
    GLFWbool found = GLFW_FALSE;
    while (fgets(buf, sizeof(buf), addr_file)) {
        if (strncmp(buf, "IBUS_ADDRESS=", sizeof("IBUS_ADDRESS=")-1) == 0) {
            size_t sz = strlen(buf);
            if (buf[sz-1] == '\n') buf[sz-1] = 0;
            if (buf[sz-2] == '\r') buf[sz-2] = 0;
            found = GLFW_TRUE;
            break;
        }
    }
    fclose(addr_file); addr_file = NULL;
    if (found) return buf + sizeof("IBUS_ADDRESS=") - 1;
    _glfwInputError(GLFW_PLATFORM_ERROR, "Could not find IBUS_ADDRESS in %s", address_file);
    return NULL;
}


void
glfw_connect_to_ibus(_GLFWIBUSData *ibus, _GLFWDBUSData *dbus) {
    if (ibus->ok) return;
    if (!has_env_var("XMODIFIERS", "@im=ibus") && !has_env_var("GTK_IM_MODULE", "ibus") && !has_env_var("QT_IM_MODULE", "ibus")) return;
    if (!glfw_dbus_init(dbus)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Cannot connect to IBUS as connection to DBUS session bus failed");
    }
    const char* address_file_name = get_ibus_address_file_name();
    if (!address_file_name) return;
    const char *address = read_ibus_address(address_file_name);
    if (!address) return;
    ibus->conn = glfw_dbus_connect_to(address, "Failed to connect to the IBUS daemon, with error");
    if (!ibus->conn) return;
    ibus->ok = GLFW_TRUE;
    debug("Connected to IBUS daemon for IME input management\n");
}

void
glfw_ibus_terminate(_GLFWIBUSData *ibus) {
    if (ibus->conn) {
        glfw_dbus_close_connection(ibus->conn);
        ibus->conn = NULL;
    }
    ibus->ok = GLFW_FALSE;
}
