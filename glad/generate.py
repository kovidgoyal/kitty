#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex
import shutil
import subprocess

cmdline = (
    'glad --out-path {dest} --api gl:core=3.1 '
    ' --extensions GL_ARB_texture_storage,GL_ARB_copy_image,GL_ARB_multisample,GL_ARB_robustness,GL_ARB_instanced_arrays,GL_KHR_debug '
    'c --header-only --debug'
)


def clean(x):
    if os.path.exists(x):
        shutil.rmtree(x)


def regenerate():
    clean('out')

    subprocess.check_call(
        shlex.split(cmdline.format(dest='out'))
    )


def strip_trailing_whitespace(c):
    return re.sub(r'\s+$', '', c, flags=re.MULTILINE) + '\n'


def export():
    with open('out/include/glad/gl.h', 'r', encoding='utf-8') as source:
        data = source.read()
        data = strip_trailing_whitespace(data)

        with open('../kitty/gl-wrapper.h', 'w', encoding='utf-8') as dest:
            dest.write(data)


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    regenerate()
    export()
