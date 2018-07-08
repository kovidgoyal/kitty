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

#include <stdlib.h>
#include <string.h>

#include "internal.h"
#include "ibus_glfw.h"

static inline GLFWbool
has_env_var(const char *name, const char *val) {
    const char *q = getenv(name);
    return (q && strcmp(q, val)) ? GLFW_TRUE : GLFW_FALSE;
}

void
glfw_connect_to_ibus(_GLFWIBUSData *ibus, _GLFWDBUSData *dbus) {
    if (ibus->ok) return;
    if (!has_env_var("XMODIFIERS", "@im=ibus") && !has_env_var("GTK_IM_MODULE", "ibus") && !has_env_var("QT_IM_MODULE", "ibus")) return;
    if (!glfw_dbus_init(dbus)) return;
}
