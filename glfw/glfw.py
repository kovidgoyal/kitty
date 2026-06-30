#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys

_plat = sys.platform.lower()
is_linux = 'linux' in _plat
is_openbsd = 'openbsd' in _plat


class Arg:

    def __init__(self, decl: str):
        self.type, self.name = decl.rsplit(' ', 1)
        self.type = self.type.strip()
        self.name = self.name.strip()
        while self.name.startswith('*'):
            self.name = self.name[1:]
            self.type = self.type + '*'
        if '[' in self.name:
            self.type += '[' + self.name.partition('[')[-1]

    def __repr__(self) -> str:
        return f'Arg({self.type}, {self.name})'


class Function:

    def __init__(self, declaration: str, check_fail: bool = True):
        self.check_fail = check_fail
        m = re.match(
            r'(.+?)\s+(glfw[A-Z][a-zA-Z0-9]+)[(](.+)[)]$', declaration
        )
        if m is None:
            raise SystemExit('Failed to parse ' + repr(declaration))
        self.restype = m.group(1).strip()
        self.name = m.group(2)
        args = m.group(3).strip().split(',')
        args = [x.strip() for x in args]
        self.args = []
        for a in args:
            if a == 'void':
                continue
            self.args.append(Arg(a))
        if not self.args:
            self.args = [Arg('void v')]

    def declaration(self) -> str:
        return 'typedef {restype} (*{name}_func)({args});\nGFW_EXTERN {name}_func {name}_impl;\n#define {name} {name}_impl'.format(
            restype=self.restype,
            name=self.name,
            args=', '.join(a.type for a in self.args)
        )

    def load(self) -> str:
        ans = f'*(void **) (&{self.name}_impl) = dlsym(handle, "{self.name}");'
        ans += f'\n    if ({self.name}_impl == NULL) '
        if self.check_fail:
            ans += f'fail("Failed to load glfw function {self.name} with error: %s", dlerror());'
        else:
            ans += 'dlerror(); // clear error indicator'
        return ans


def generate_wrappers(glfw_header: str) -> None:
    with open(glfw_header) as f:
        src = f.read()
    functions = []
    first = None
    for m in re.finditer(r'^GLFWAPI\s+(.+[)]);\s*$', src, flags=re.MULTILINE):
        if first is None:
            first = m.start()
        decl = m.group(1)
        if 'VkInstance' in decl:
            continue
        functions.append(Function(decl))
    for line in '''\
    void* glfwGetCocoaWindow(GLFWwindow* window)
    void* glfwGetNSGLContext(GLFWwindow *window)
    uint32_t glfwGetCocoaMonitor(GLFWmonitor* monitor)
    GLFWcocoatextinputfilterfun glfwSetCocoaTextInputFilter(GLFWwindow* window, GLFWcocoatextinputfilterfun callback)
    GLFWhandleurlopen glfwSetCocoaURLOpenCallback(GLFWhandleurlopen callback)
    GLFWcocoatogglefullscreenfun glfwSetCocoaToggleFullscreenIntercept(GLFWwindow *window, GLFWcocoatogglefullscreenfun callback)
    GLFWapplicationshouldhandlereopenfun glfwSetApplicationShouldHandleReopen(GLFWapplicationshouldhandlereopenfun callback)
    GLFWapplicationwillfinishlaunchingfun glfwSetApplicationWillFinishLaunching(GLFWapplicationwillfinishlaunchingfun callback)
    uint32_t glfwGetCocoaKeyEquivalent(uint32_t glfw_key, int glfw_mods, int* cocoa_mods)
    void glfwCocoaRequestRenderFrame(GLFWwindow *w, GLFWcocoarenderframefun callback)
    bool glfwCocoaRecreateGLDrawable(GLFWwindow *w)
    GLFWcocoarenderframefun glfwCocoaSetWindowResizeCallback(GLFWwindow *w, GLFWcocoarenderframefun callback)
    void* glfwGetX11Display(void)
    unsigned long glfwGetX11Window(GLFWwindow* window)
    void glfwSetPrimarySelectionString(GLFWwindow* window, const char* string)
    void glfwCocoaCycleThroughOSWindows(bool backwards)
    void glfwCocoaSetWindowChrome(GLFWwindow* window, unsigned int color, bool use_system_color, unsigned int system_color,\
    int background_blur, unsigned int hide_window_decorations, bool show_text_in_titlebar, int color_space, float background_opacity, bool resizable)
    void glfwCocoaRegisterMIMETypes(GLFWwindow *window, const char **mimes, size_t count)
    void glfwCocoaSetWindowLevel(GLFWwindow *window, const char *level_spec)
    const char* glfwGetPrimarySelectionString(GLFWwindow* window, void)
    int glfwGetNativeKeyForName(const char* key_name, int case_sensitive)
    void glfwRequestWaylandFrameEvent(GLFWwindow *handle, unsigned long long id, GLFWwaylandframecallbackfunc callback)
    void glfwWaylandActivateWindow(GLFWwindow *handle, const char *activation_token)
    const char* glfwWaylandMissingCapabilities(void)
    void glfwWaylandRunWithActivationToken(GLFWwindow *handle, GLFWactivationcallback cb, void *cb_data)
    bool glfwWaylandSetTitlebarColor(GLFWwindow *handle, uint32_t color, bool use_system_color)
    void glfwWaylandSetTitlebarHidden(GLFWwindow *handle, bool hidden)
    void glfwWaylandSetInitialWindowSizeCallback(GLFWwaylandinitialsizefun callback)
    void glfwWaylandRedrawCSDWindowTitle(GLFWwindow *handle)
    bool glfwWaylandIsWindowFullyCreated(GLFWwindow *handle)
    bool glfwWaylandBeep(GLFWwindow *handle)
    pid_t glfwWaylandCompositorPID(void)
    double glfwGetWaylandCurrentMonitorFractionalScale(void)
    void glfwConfigureMomentumScroller(double friction, double min_velocity, double max_velocity, unsigned timer_interval)
    unsigned long long glfwDBusUserNotify(const GLFWDBUSNotificationData *n, GLFWDBusnotificationcreatedfun callback, void *data)
    void glfwDBusSetUserNotificationHandler(GLFWDBusnotificationactivatedfun handler)
    int glfwSetX11LaunchCommand(GLFWwindow *handle, char **argv, int argc)
'''.splitlines():
        if line:
            functions.append(Function(line.strip(), check_fail=False))

    declarations = [f.declaration() for f in functions]
    p = src.find(' * GLFW API tokens')
    p = src.find('*/', p)
    preamble = src[p + 2:first]
    header = '''\
//
// THIS FILE IS GENERATED BY glfw.py
//
// SAVE YOURSELF SOME TIME, DO NOT MANUALLY EDIT
//

#pragma once
#include <stddef.h>
#include <stdint.h>
#include "monotonic.h"

#ifndef GFW_EXTERN
#define GFW_EXTERN extern
#endif
{}

typedef int (* GLFWcocoatextinputfilterfun)(int,int,unsigned int,unsigned long);
typedef bool (* GLFWapplicationshouldhandlereopenfun)(int);
typedef bool (* GLFWhandleurlopen)(const char*);
typedef void (* GLFWapplicationwillfinishlaunchingfun)(bool);
typedef bool (* GLFWcocoatogglefullscreenfun)(GLFWwindow*);
typedef void (* GLFWcocoarenderframefun)(GLFWwindow*);
typedef void (*GLFWwaylandframecallbackfunc)(unsigned long long id);
typedef void (*GLFWDBusnotificationcreatedfun)(unsigned long long, uint32_t, void*);
typedef void (*GLFWDBusnotificationactivatedfun)(uint32_t, int, const char*);
{}

const char* load_glfw(const char* path);
'''.format(preamble, '\n\n'.join(declarations))
    with open('../kitty/glfw-wrapper.h', 'w') as f:
        f.write(header)

    code = '''
// generated by glfw.py DO NOT edit

#define GFW_EXTERN
#include "data-types.h"
#include "glfw-wrapper.h"
#include <dlfcn.h>

static void* handle = NULL;

#define fail(msg, ...) { snprintf(buf, sizeof(buf), msg, __VA_ARGS__); return buf; }

const char*
load_glfw(const char* path) {
    static char buf[2048];
    handle = dlopen(path, RTLD_LAZY);
    if (handle == NULL) fail("Failed to dlopen %s with error: %s", path, dlerror());
    dlerror();

    LOAD

    return NULL;
}

void
unload_glfw(void) {
    if (handle) { dlclose(handle); handle = NULL; }
}
'''.replace('LOAD', '\n\n    '.join(f.load() for f in functions))
    with open('../kitty/glfw-wrapper.c', 'w') as f:
        f.write(code)


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    generate_wrappers('glfw3.h')


if __name__ == '__main__':
    main()
