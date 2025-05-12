#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import subprocess
import sys
from enum import Enum
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

_plat = sys.platform.lower()
is_linux = 'linux' in _plat
is_openbsd = 'openbsd' in _plat
base = os.path.dirname(os.path.abspath(__file__))


def null_func() -> None:
    return None


class CompileKey(NamedTuple):
    src: str
    dest: str


class Command(NamedTuple):
    desc: str
    cmd: Sequence[str]
    is_newer_func: Callable[[], bool]
    on_success: Callable[[], None] = null_func
    key: Optional[CompileKey] = None
    keyfile: Optional[str] = None


class ISA(Enum):
    X86 = 0x03
    AMD64 = 0x3e
    ARM64 = 0xb7
    Other = 0x0


class BinaryArch(NamedTuple):
    bits: int = 64
    isa: ISA = ISA.AMD64


class CompilerType(Enum):
    gcc = 'gcc'
    clang = 'clang'
    unknown = 'unknown'


class Env:

    cc: List[str] = []
    cppflags: List[str] = []
    cflags: List[str] = []
    ldflags: List[str] = []
    library_paths: Dict[str, List[str]] = {}
    ldpaths: List[str] = []
    ccver: Tuple[int, int]
    vcs_rev: str = ''
    binary_arch: BinaryArch = BinaryArch()
    native_optimizations: bool = False
    primary_version: int = 0
    secondary_version: int = 0
    xt_version: str = ''
    has_copy_file_range: bool = False

    # glfw stuff
    all_headers: List[str] = []
    sources: List[str] = []
    wayland_packagedir: str = ''
    wayland_scanner: str = ''
    wayland_scanner_code: str = ''
    wayland_protocols: Tuple[str, ...] = ()

    def __init__(
        self, cc: List[str] = [], cppflags: List[str] = [], cflags: List[str] = [], ldflags: List[str] = [],
        library_paths: Dict[str, List[str]] = {}, ldpaths: Optional[List[str]] = None, ccver: Tuple[int, int] = (0, 0),
        vcs_rev: str = '', binary_arch: BinaryArch = BinaryArch(),
        native_optimizations: bool = False,
    ):
        self.cc, self.cppflags, self.cflags, self.ldflags, self.library_paths = cc, cppflags, cflags, ldflags, library_paths
        self.ldpaths = ldpaths or []
        self.ccver = ccver
        self.vcs_rev = vcs_rev
        self.binary_arch = binary_arch
        self.native_optimizations = native_optimizations
        self._cc_version_string = ''
        self._compiler_type: Optional[CompilerType] = None

    @property
    def cc_version_string(self) -> str:
        if not self._cc_version_string:
            self._cc_version_string = subprocess.check_output(self.cc + ['--version']).decode()
        return self._cc_version_string

    @property
    def compiler_type(self) -> CompilerType:
        if self._compiler_type is None:
            raw = self.cc_version_string
            if 'Free Software Foundation' in raw:
                self._compiler_type = CompilerType.gcc
            elif 'clang' in raw.lower().split():
                self._compiler_type = CompilerType.clang
            else:
                self._compiler_type = CompilerType.unknown
        return self._compiler_type

    def copy(self) -> 'Env':
        ans = Env(self.cc, list(self.cppflags), list(self.cflags), list(self.ldflags), dict(self.library_paths), list(self.ldpaths), self.ccver)
        ans.all_headers = list(self.all_headers)
        ans._cc_version_string = self._cc_version_string
        ans.sources = list(self.sources)
        ans.wayland_packagedir = self.wayland_packagedir
        ans.wayland_scanner = self.wayland_scanner
        ans.wayland_scanner_code = self.wayland_scanner_code
        ans.wayland_protocols = self.wayland_protocols
        ans.vcs_rev = self.vcs_rev
        ans.binary_arch = self.binary_arch
        ans.native_optimizations = self.native_optimizations
        ans.primary_version = self.primary_version
        ans.secondary_version = self.secondary_version
        ans.xt_version = self.xt_version
        ans.has_copy_file_range = self.has_copy_file_range
        return ans


def wayland_protocol_file_name(base: str, ext: str = 'c') -> str:
    base = os.path.basename(base).rpartition('.')[0]
    return f'wayland-{base}-client-protocol.{ext}'


def init_env(
    env: Env,
    pkg_config: Callable[..., List[str]],
    pkg_version: Callable[[str], Tuple[int, int]],
    at_least_version: Callable[..., None],
    test_compile: Callable[..., Any],
    module: str = 'x11'
) -> Env:
    ans = env.copy()
    ans.cflags.append('-fPIC')
    ans.cppflags.append(f'-D_GLFW_{module.upper()}')
    ans.cppflags.append('-D_GLFW_BUILD_DLL')

    with open(os.path.join(base, 'source-info.json')) as f:
        sinfo = json.load(f)
    module_sources = list(sinfo[module]['sources'])
    if module in ('x11', 'wayland'):
        remove = 'null_joystick.c' if is_linux else 'linux_joystick.c'
        module_sources.remove(remove)

    ans.sources = sinfo['common']['sources'] + module_sources
    ans.all_headers = [x for x in os.listdir(base) if x.endswith('.h')]

    if module in ('x11', 'wayland'):
        ans.cflags.append('-pthread')
        ans.ldpaths.extend('-pthread -lm'.split())
        if not is_openbsd:
            ans.ldpaths.extend('-lrt -ldl'.split())
        major, minor = pkg_version('xkbcommon')
        if (major, minor) < (0, 5):
            raise SystemExit('libxkbcommon >= 0.5 required')
        if major < 1:
            ans.cflags.append('-DXKB_HAS_NO_UTF32')

    if module == 'x11':
        for dep in 'x11 xrandr xinerama xcursor xkbcommon xkbcommon-x11 x11-xcb dbus-1'.split():
            ans.cflags.extend(pkg_config(dep, '--cflags-only-I'))
            ans.ldpaths.extend(pkg_config(dep, '--libs'))

    elif module == 'cocoa':
        ans.cppflags.append('-DGL_SILENCE_DEPRECATION')
        for f_ in 'Cocoa IOKit CoreFoundation CoreVideo UniformTypeIdentifiers'.split():
            ans.ldpaths.extend(('-framework', f_))

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
        for dep in 'wayland-client wayland-cursor xkbcommon dbus-1'.split():
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


def build_wayland_protocols(
    env: Env,
    parallel_run: Callable[[List[Command]], None],
    emphasis: Callable[[str], str],
    newer: Callable[..., bool],
    dest_dir: str
) -> None:
    items = []
    for protocol in env.wayland_protocols:
        if '/' in protocol:
            src = os.path.join(env.wayland_packagedir, protocol)
            if not os.path.exists(src):
                raise SystemExit(f'The wayland-protocols package on your system is missing the {protocol} protocol definition file')
        else:
            src = os.path.join(os.path.dirname(os.path.abspath(__file__)), protocol)
            if not os.path.exists(src):
                raise SystemExit(f'The local Wayland protocol {protocol} is missing from kitty sources')
        for ext in 'hc':
            dest = wayland_protocol_file_name(src, ext)
            dest = os.path.join(dest_dir, dest)
            if newer(dest, src):
                q = 'client-header' if ext == 'h' else env.wayland_scanner_code
                items.append(Command(
                    f'Generating {emphasis(os.path.basename(dest))} ...',
                    [env.wayland_scanner, q, src, dest], lambda: True))
    if items:
        parallel_run(items)


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
    GLFWcocoarenderframefun glfwCocoaSetWindowResizeCallback(GLFWwindow *w, GLFWcocoarenderframefun callback)
    void* glfwGetX11Display(void)
    unsigned long glfwGetX11Window(GLFWwindow* window)
    void glfwSetPrimarySelectionString(GLFWwindow* window, const char* string)
    void glfwCocoaSetWindowChrome(GLFWwindow* window, unsigned int color, bool use_system_color, unsigned int system_color,\
    int background_blur, unsigned int hide_window_decorations, bool show_text_in_titlebar, int color_space, float background_opacity, bool resizable)
    const char* glfwGetPrimarySelectionString(GLFWwindow* window, void)
    int glfwGetNativeKeyForName(const char* key_name, int case_sensitive)
    void glfwRequestWaylandFrameEvent(GLFWwindow *handle, unsigned long long id, GLFWwaylandframecallbackfunc callback)
    void glfwWaylandActivateWindow(GLFWwindow *handle, const char *activation_token)
    const char* glfwWaylandMissingCapabilities(void)
    void glfwWaylandRunWithActivationToken(GLFWwindow *handle, GLFWactivationcallback cb, void *cb_data)
    bool glfwWaylandSetTitlebarColor(GLFWwindow *handle, uint32_t color, bool use_system_color)
    void glfwWaylandRedrawCSDWindowTitle(GLFWwindow *handle)
    bool glfwWaylandIsWindowFullyCreated(GLFWwindow *handle)
    bool glfwWaylandBeep(GLFWwindow *handle)
    pid_t glfwWaylandCompositorPID(void)
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
