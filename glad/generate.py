#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex
import shutil
import subprocess

cmdline = (
    'glad --profile core --out-path {dest} --api gl=3.3 --generator {generator} --spec gl'
    ' --extensions GL_ARB_texture_storage,GL_ARB_copy_image,GL_ARB_multisample,GL_ARB_robustness,GL_KHR_debug'
)


def clean(x):
    if os.path.exists(x):
        shutil.rmtree(x)


def regenerate():
    clean('out')

    subprocess.check_call(
        shlex.split(cmdline.format(dest='out', generator='c-debug'))
    )


def strip_trailing_whitespace(c):
    return re.sub(r'\s+$', '', c, flags=re.MULTILINE) + '\n'


def export():
    c = open('out/src/glad.c', 'rb').read().decode('utf-8')
    functions = []

    def sub(m):
        functions.append(m.group(2))
        return m.group()

    c = re.sub(r'^([A-Z0-9]+) glad_debug_([a-zA-Z0-9]+) = glad_debug_impl_\2;$', sub, c, flags=re.M)
    switch = ['glad_debug_{0} = glad_{0}'.format(f) for f in functions]
    c = c.replace('<glad/glad.h>', '"gl-wrapper.h"', 1)
    c = '#pragma GCC diagnostic ignored "-Wpedantic"\n' + c
    c += '''
int
init_glad(GLADloadproc load, int debug) {
    int ret = gladLoadGLLoader(load);
    if (ret && !debug) {
        SUB;
    }
    return ret;
}'''.replace('SUB', ';\n        '.join(switch), 1)
    open('../kitty/gl-wrapper.c', 'w').write(strip_trailing_whitespace(c))
    raw = open('out/include/glad/glad.h').read()
    raw = raw.replace('<KHR/khrplatform.h>', '"khrplatform.h"')
    raw += '\nint init_glad(GLADloadproc, int);\n'
    open('../kitty/gl-wrapper.h', 'w').write(strip_trailing_whitespace(raw))
    raw = open('out/include/KHR/khrplatform.h', 'rb').read().decode('utf-8')
    open('../kitty/khrplatform.h', 'w').write(strip_trailing_whitespace(raw))


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    regenerate()
    export()
