#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import shutil
import sys

_plat = sys.platform.lower()
isosx = 'darwin' in _plat
base = os.path.dirname(os.path.abspath(__file__))


def init_env(env, pkg_config, at_least_version, module='x11'):
    ans = env.copy()
    ans.cflags = [
        x for x in ans.cflags
        if x not in '-Wpedantic -Wextra -pedantic-errors'.split()
    ]
    ans.cflags.append('-pthread')
    ans.cflags.append('-fpic')
    ans.ldpaths.append('-pthread')
    ans.cflags.append('-D_GLFW_' + module.upper())
    ans.cflags.append('-D_GLFW_BUILD_DLL')

    if not isosx:
        ans.ldpaths.extend('-lrt -lm -ldl'.split())

    if module == 'x11':
        for dep in 'x11 xrandr xinerama xcursor xkbcommon-x11'.split():
            ans.cflags.extend(pkg_config(dep, '--cflags-only-I'))
            ans.ldpaths.extend(pkg_config(dep, '--libs'))

    elif module == 'cocoa':
        for f in 'Cocoa IOKit CoreFoundation CoreVideo'.split():
            ans.ldpaths.extend(('-framework', f))

    sinfo = json.load(open(os.path.join(base, 'source-info.json')))
    ans.sources = sinfo['common']['sources'] + sinfo[module]['sources']
    ans.all_headers = [x for x in os.listdir(base) if x.endswith('.h')]
    return ans


def collect_source_information():
    raw = open('src/CMakeLists.txt').read()

    def extract_sources(group, start_pos=0):
        for which in 'HEADERS SOURCES'.split():
            yield which.lower(), filter(
                lambda x: x[0] not in '"$',
                re.search(
                    r'{0}_{1}\s+([^)]+?)[)]'.format(group, which),
                    raw[start_pos:]
                ).group(1).strip().split()
            )

    ans = {
        'common': dict(extract_sources('common')),
    }
    for group in 'cocoa win32 x11 wayland osmesa'.split():
        m = re.search('_GLFW_' + group.upper(), raw)
        ans[group] = dict(extract_sources('glfw', m.start()))
        if group == 'x11':
            ans[group]['headers'].append('linux_joystick.h')
            ans[group]['sources'].append('linux_joystick.c')
    return ans


def patch_in_file(path, pfunc):
    with open(path, 'r+') as f:
        raw = f.read()
        nraw = pfunc(raw)
        if raw == nraw:
            raise SystemExit('Patching of {} failed'.format(path))
        f.seek(0), f.truncate()
        f.write(nraw)


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

    def __init__(self, declaration):
        m = re.match(
            r'(.+?)\s+(glfw[A-Z][a-zA-Z0-9]+)[(](.+)[)]$', declaration
        )
        if m is None:
            raise SystemExit('Failed to parse ' + declaration)
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
    declarations = [f.declaration() for f in functions]
    p = src.find(' * GLFW API tokens')
    p = src.find('*/', p)
    preamble = src[p + 2:first]
    header = '''\
#pragma once
#include <stddef.h>
#include <stdint.h>
{}

{}

const char* load_glfw(const char* path);
'''.format(preamble, '\n\n'.join(declarations))
    with open('../kitty/glfw-wrapper.h', 'w') as f:
        f.write(header)

    code = '''
#include <dlfcn.h>
#include "data-types.h"
#include "glfw-wrapper.h"

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


def main():
    os.chdir(sys.argv[-1])
    sinfo = collect_source_information()
    files_to_copy = set()
    for x in sinfo.values():
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
    patch_in_file('internal.h', lambda x: x.replace('../include/GLFW/', ''))
    json.dump(
        sinfo,
        open('source-info.json', 'w'),
        indent=2,
        ensure_ascii=False,
        sort_keys=True
    )
    generate_wrappers(glfw_header, glfw_native_header)


if __name__ == '__main__':
    main()
