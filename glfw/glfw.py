#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import shutil
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
    ans.cflags = [
        x for x in ans.cflags
        if x not in '-Wpedantic -Wextra -pedantic-errors'.split()
    ]
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


def build_wayland_protocols(env, run_tool, emphasis, newer, dest_dir):
    for protocol in env.wayland_protocols:
        src = os.path.join(env.wayland_packagedir, protocol)
        if not os.path.exists(src):
            raise SystemExit('The wayland-protocols package on your system is missing the {} protocol definition file'.format(protocol))
        for ext in 'hc':
            dest = wayland_protocol_file_name(src, ext)
            dest = os.path.join(dest_dir, dest)
            if newer(dest, src):
                q = 'client-header' if ext == 'h' else env.wayland_scanner_code
                run_tool([env.wayland_scanner, q, src, dest],
                         desc='Generating {} ...'.format(emphasis(os.path.basename(dest))))


def collect_source_information():
    raw = open('src/CMakeLists.txt').read()
    mraw = open('CMakeLists.txt').read()

    def extract_sources(group, start_pos=0):
        for which in 'HEADERS SOURCES'.split():
            yield which.lower(), list(filter(
                lambda x: x[0] not in '"$',
                re.search(
                    r'{0}_{1}\s+([^)]+?)[)]'.format(group, which),
                    raw[start_pos:]
                ).group(1).strip().split()
            ))

    wayland_protocols = re.search(r'WaylandProtocols\s+(\S+)\s+', mraw).group(1)
    wayland_protocols = list(map(int, wayland_protocols.split('.')))
    ans = {
        'common': dict(extract_sources('common')),
        'wayland_protocols': wayland_protocols,
    }
    for group in 'cocoa win32 x11 wayland osmesa'.split():
        m = re.search('_GLFW_' + group.upper(), raw)
        ans[group] = dict(extract_sources('glfw', m.start()))
        if group in ('x11', 'wayland'):
            for joystick in ('linux', 'null'):
                ans[group]['headers'].append('{}_joystick.h'.format(joystick))
                ans[group]['sources'].append('{}_joystick.c'.format(joystick))
        if group == 'wayland':
            ans[group]['protocols'] = p = []
            for m in re.finditer(r'WAYLAND_PROTOCOLS_PKGDATADIR\}/(.+?)"?$', raw, flags=re.M):
                p.append(m.group(1))
    return ans


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


def generate_wrappers(glfw_header, glfw_native_header):
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
    void* glfwGetX11Display(void)
    int32_t glfwGetX11Window(GLFWwindow* window)
    void glfwSetX11SelectionString(const char* string)
    const char* glfwGetX11SelectionString(void)
    int glfwGetXKBScancode(const char* key_name, int case_sensitive)
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

typedef int (* GLFWcocoatextinputfilterfun)(int,int,unsigned int);
typedef int (* GLFWapplicationshouldhandlereopenfun)(int);
typedef int (* GLFWcocoatogglefullscreenfun)(GLFWwindow*);

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
unload_glfw() {
    if (handle) { dlclose(handle); handle = NULL; }
}
'''.replace('LOAD', '\n\n    '.join(f.load() for f in functions))
    with open('../kitty/glfw-wrapper.c', 'w') as f:
        f.write(code)


def from_glfw(glfw_dir):
    os.chdir(glfw_dir)
    sinfo = collect_source_information()
    files_to_copy = set()
    for x in sinfo.values():
        if isinstance(x, dict):
            headers, sources = x['headers'], x['sources']
            for name in headers + sources:
                files_to_copy.add(os.path.abspath(os.path.join('src', name)))
    glfw_header = os.path.abspath('include/GLFW/glfw3.h')
    glfw_native_header = os.path.abspath('include/GLFW/glfw3native.h')
    os.chdir(base)
    for x in os.listdir('.'):
        if x.rpartition('.') in ('c', 'h'):
            os.unlink(x)
    for src in files_to_copy:
        shutil.copy2(src, '.')
    shutil.copy2(glfw_header, '.')
    json.dump(
        sinfo,
        open('source-info.json', 'w'),
        indent=2,
        ensure_ascii=False,
        sort_keys=True
    )
    generate_wrappers(glfw_header, glfw_native_header)


def to_glfw(glfw_dir):
    src = base
    for x in os.listdir(src):
        if x in ('glfw.py', 'glfw3.h', '__pycache__', 'source-info.json') or x.startswith('wayland-'):
            continue
        xp = os.path.join(src, x)
        shutil.copyfile(xp, os.path.join(glfw_dir, 'src', x))
    shutil.copyfile(os.path.join(src, 'glfw3.h'), os.path.join(glfw_dir, 'include/GLFW/glfw3.h'))


def main():
    glfw_dir = os.path.abspath(os.path.join(base, '../../glfw'))
    q = sys.argv[1].lower().replace('_', '-')
    if q == 'from-glfw':
        from_glfw(glfw_dir)
    elif q == 'to-glfw':
        to_glfw(glfw_dir)
    else:
        raise SystemExit('First argument must be one of to-glfw or from-glfw')


if __name__ == '__main__':
    main()
