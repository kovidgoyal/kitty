#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import sys

_plat = sys.platform.lower()
is_macos = 'darwin' in _plat
is_freebsd = 'freebsd' in _plat
is_netbsd = 'netbsd' in _plat
is_dragonflybsd = 'dragonfly' in _plat
is_bsd = is_freebsd or is_netbsd or is_dragonflybsd
base = os.path.dirname(os.path.abspath(__file__))


def wayland_protocol_file_name(base, ext='c'):
    base = os.path.basename(base).rpartition('.')[0]
    return 'wayland-{}-client-protocol.{}'.format(base, ext)


def init_env(env, pkg_config, at_least_version, test_compile, module='x11'):
    ans = env.copy()
    if not is_macos:
        ans.cflags.append('-pthread')
        ans.ldpaths.append('-pthread')
    ans.cflags.append('-fpic')
    ans.cppflags.append('-D_GLFW_' + module.upper())
    ans.cppflags.append('-D_GLFW_BUILD_DLL')

    if is_macos:
        ans.cppflags.append('-DGL_SILENCE_DEPRECATION')
        ans.ldpaths.extend(
            "-framework Cocoa -framework IOKit -framework CoreFoundation -framework CoreVideo".
            split()
        )
    else:
        ans.ldpaths.extend('-lrt -lm -ldl'.split())
    sinfo = json.load(open(os.path.join(base, 'source-info.json')))
    module_sources = list(sinfo[module]['sources'])
    if module in ('x11', 'wayland'):
        remove = 'linux_joystick.c' if is_bsd else 'null_joystick.c'
        module_sources.remove(remove)

    ans.sources = sinfo['common']['sources'] + module_sources
    ans.all_headers = [x for x in os.listdir(base) if x.endswith('.h')]

    if module in ('x11', 'wayland'):
        at_least_version('xkbcommon', 0, 5)

    if module == 'x11':
        for dep in 'x11 xrandr xinerama xcursor xkbcommon xkbcommon-x11 x11-xcb dbus-1'.split():
            ans.cflags.extend(pkg_config(dep, '--cflags-only-I'))
            ans.ldpaths.extend(pkg_config(dep, '--libs'))

    elif module == 'cocoa':
        for f in 'Cocoa IOKit CoreFoundation CoreVideo'.split():
            ans.ldpaths.extend(('-framework', f))

    elif module == 'wayland':
        at_least_version('wayland-protocols', *sinfo['wayland_protocols'])
        ans.wayland_packagedir = os.path.abspath(pkg_config('wayland-protocols', '--variable=pkgdatadir')[0])
        ans.wayland_scanner = os.path.abspath(pkg_config('wayland-scanner', '--variable=wayland_scanner')[0])
        scanner_version = tuple(map(int, pkg_config('wayland-scanner', '--modversion')[0].strip().split('.')))
        ans.wayland_scanner_code = 'private-code' if scanner_version >= (1, 14, 91) else 'code'
        ans.wayland_protocols = tuple(sinfo[module]['protocols'])
        for p in ans.wayland_protocols:
            ans.sources.append(wayland_protocol_file_name(p))
            ans.all_headers.append(wayland_protocol_file_name(p, 'h'))
        for dep in 'wayland-egl wayland-client wayland-cursor xkbcommon dbus-1'.split():
            ans.cflags.extend(pkg_config(dep, '--cflags-only-I'))
            ans.ldpaths.extend(pkg_config(dep, '--libs'))
        has_memfd_create = test_compile(env.cc, '-Werror', src='''#define _GNU_SOURCE
    #include <unistd.h>
    #include <sys/syscall.h>
    int main(void) {
        return syscall(__NR_memfd_create, "test", 0);
    }''')
        if has_memfd_create:
            ans.cppflags.append('-DHAS_MEMFD_CREATE')

    return ans


def build_wayland_protocols(env, Command, parallel_run, emphasis, newer, dest_dir):
    items = []
    for protocol in env.wayland_protocols:
        src = os.path.join(env.wayland_packagedir, protocol)
        if not os.path.exists(src):
            raise SystemExit('The wayland-protocols package on your system is missing the {} protocol definition file'.format(protocol))
        for ext in 'hc':
            dest = wayland_protocol_file_name(src, ext)
            dest = os.path.join(dest_dir, dest)
            if newer(dest, src):
                q = 'client-header' if ext == 'h' else env.wayland_scanner_code
                items.append(Command(
                    'Generating {} ...'.format(emphasis(os.path.basename(dest))),
                    [env.wayland_scanner, q, src, dest],
                    lambda: True, None, None, None))
    if items:
        parallel_run(items)


class Arg:

    def __init__(self, decl):
        self.type, self.name = decl.rsplit(' ', 1)
        self.type = self.type.strip()
        self.name = self.name.strip()
        while self.name.startswith('*'):
            self.name = self.name[1:]
            self.type = self.type + '*'

    def __repr__(self):
        return 'Arg({}, {})'.format(self.type, self.name)


class Function:

    def __init__(self, declaration, check_fail=True):
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

    def declaration(self):
        return 'typedef {restype} (*{name}_func)({args});\n{name}_func {name}_impl;\n#define {name} {name}_impl'.format(
            restype=self.restype,
            name=self.name,
            args=', '.join(a.type for a in self.args)
        )

    def load(self):
        ans = '*(void **) (&{name}_impl) = dlsym(handle, "{name}");'.format(
            name=self.name
        )
        if self.check_fail:
            ans += '\n    if ({name}_impl == NULL) fail("Failed to load glfw function {name} with error: %s", dlerror());'.format(
                name=self.name
            )
        return ans


def generate_wrappers(glfw_header):
    src = open(glfw_header).read()
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
    GLFWcocoatogglefullscreenfun glfwSetCocoaToggleFullscreenIntercept(GLFWwindow *window, GLFWcocoatogglefullscreenfun callback)
    GLFWapplicationshouldhandlereopenfun glfwSetApplicationShouldHandleReopen(GLFWapplicationshouldhandlereopenfun callback)
    void glfwGetCocoaKeyEquivalent(int glfw_key, int glfw_mods, void* cocoa_key, void* cocoa_mods)
    void glfwCocoaRequestRenderFrame(GLFWwindow *w, GLFWcocoarenderframefun callback)
    void* glfwGetX11Display(void)
    int32_t glfwGetX11Window(GLFWwindow* window)
    void glfwSetPrimarySelectionString(GLFWwindow* window, const char* string)
    const char* glfwGetPrimarySelectionString(GLFWwindow* window, void)
    int glfwGetXKBScancode(const char* key_name, int case_sensitive)
    void glfwRequestWaylandFrameEvent(GLFWwindow *handle, unsigned long long id, GLFWwaylandframecallbackfunc callback)
    unsigned long long glfwDBusUserNotify(const char *app_name, const char* icon, const char *summary, const char *body, \
const char *action_text, int32_t timeout, GLFWDBusnotificationcreatedfun callback, void *data)
    void glfwDBusSetUserNotificationHandler(GLFWDBusnotificationactivatedfun handler)
'''.splitlines():
        if line:
            functions.append(Function(line.strip(), check_fail=False))

    declarations = [f.declaration() for f in functions]
    p = src.find(' * GLFW API tokens')
    p = src.find('*/', p)
    preamble = src[p + 2:first]
    header = '''\
#pragma once
#include <stddef.h>
#include <stdint.h>

{}

typedef int (* GLFWcocoatextinputfilterfun)(int,int,unsigned int,unsigned long);
typedef int (* GLFWapplicationshouldhandlereopenfun)(int);
typedef int (* GLFWcocoatogglefullscreenfun)(GLFWwindow*);
typedef void (* GLFWcocoarenderframefun)(GLFWwindow*);
typedef void (*GLFWwaylandframecallbackfunc)(unsigned long long id);
typedef void (*GLFWDBusnotificationcreatedfun)(unsigned long long, uint32_t, void*);
typedef void (*GLFWDBusnotificationactivatedfun)(uint32_t, const char*);
{}

const char* load_glfw(const char* path);
'''.format(preamble, '\n\n'.join(declarations))
    with open('../kitty/glfw-wrapper.h', 'w') as f:
        f.write(header)

    code = '''
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


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    generate_wrappers('glfw3.h')


if __name__ == '__main__':
    main()
