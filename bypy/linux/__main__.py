#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import os
import shutil
import stat
import subprocess
import tarfile
import time

from bypy.constants import OUTPUT_DIR, PREFIX, python_major_minor_version
from bypy.freeze import extract_extension_modules, freeze_python, path_to_freeze_dir
from bypy.utils import get_dll_path, mkdtemp, py_compile, walk

j = os.path.join
machine = (os.uname()[4] or '').lower()
self_dir = os.path.dirname(os.path.abspath(__file__))
py_ver = '.'.join(map(str, python_major_minor_version()))
iv = globals()['init_env']
kitty_constants = iv['kitty_constants']


def binary_includes():
    return tuple(map(get_dll_path, (
            'expat', 'sqlite3', 'ffi', 'z', 'lzma', 'png16', 'lcms2', 'ssl', 'crypto', 'crypt',
            'iconv', 'pcre2-8', 'graphite2', 'glib-2.0', 'freetype', 'xxhash',
            'pixman-1', 'cairo', 'harfbuzz', 'xkbcommon', 'xkbcommon-x11',
            # fontconfig is not bundled because in typical brain dead Linux
            # distro fashion, different distros use different default config
            # paths for fontconfig.
            'ncursesw', 'readline', 'brotlicommon', 'brotlienc', 'brotlidec',
            'wayland-client', 'wayland-cursor',
        ))) + (
                get_dll_path('bz2', 2),
                get_dll_path(f'python{py_ver}', 2),
        )


class Env:

    def __init__(self, package_dir):
        self.base = package_dir
        self.lib_dir = j(self.base, 'lib')
        self.py_dir = j(self.lib_dir, f'python{py_ver}')
        os.makedirs(self.py_dir)
        self.bin_dir = j(self.base, 'bin')
        self.obj_dir = mkdtemp('launchers-')


def ignore_in_lib(base, items, ignored_dirs=None):
    ans = []
    if ignored_dirs is None:
        ignored_dirs = {'.svn', '.bzr', '.git', 'test', 'tests', 'testing'}
    for name in items:
        path = j(base, name)
        if os.path.isdir(path):
            if name in ignored_dirs or not os.path.exists(j(path, '__init__.py')):
                if name != 'plugins':
                    ans.append(name)
        else:
            if name.rpartition('.')[-1] not in ('so', 'py'):
                ans.append(name)
    return ans


def import_site_packages(srcdir, dest):
    if not os.path.exists(dest):
        os.mkdir(dest)
    for x in os.listdir(srcdir):
        ext = x.rpartition('.')[-1]
        f = j(srcdir, x)
        if ext in ('py', 'so'):
            shutil.copy2(f, dest)
        elif ext == 'pth' and x != 'setuptools.pth':
            for line in open(f):
                src = os.path.abspath(j(srcdir, line))
                if os.path.exists(src) and os.path.isdir(src):
                    import_site_packages(src, dest)
        elif os.path.exists(j(f, '__init__.py')):
            shutil.copytree(f, j(dest, x), ignore=ignore_in_lib)


def copy_libs(env):
    print('Copying libs...')

    for x in binary_includes():
        dest = env.bin_dir if '/bin/' in x else env.lib_dir
        shutil.copy2(x, dest)
        dest = os.path.join(dest, os.path.basename(x))
        subprocess.check_call(['chrpath', '-d', dest])


def add_ca_certs(env):
    print('Downloading CA certs...')
    from urllib.request import urlopen
    cdata = urlopen(kitty_constants['cacerts_url']).read()
    dest = os.path.join(env.lib_dir, 'cacert.pem')
    with open(dest, 'wb') as f:
        f.write(cdata)


def copy_python(env):
    print('Copying python...')
    srcdir = j(PREFIX, f'lib/python{py_ver}')

    for x in os.listdir(srcdir):
        y = j(srcdir, x)
        ext = os.path.splitext(x)[1]
        if os.path.isdir(y) and x not in ('test', 'hotshot', 'distutils', 'tkinter', 'turtledemo',
                                          'site-packages', 'idlelib', 'lib2to3', 'dist-packages'):
            shutil.copytree(y, j(env.py_dir, x), ignore=ignore_in_lib)
        if os.path.isfile(y) and ext in ('.py', '.so'):
            shutil.copy2(y, env.py_dir)

    srcdir = j(srcdir, 'site-packages')
    import_site_packages(srcdir, env.py_dir)

    pdir = os.path.join(env.lib_dir, 'kitty-extensions')
    os.makedirs(pdir, exist_ok=True)
    kitty_dir = os.path.join(env.lib_dir, 'kitty')
    bases = ('kitty', 'kittens', 'kitty_tests')
    for x in bases:
        dest = os.path.join(env.py_dir, x)
        os.rename(os.path.join(kitty_dir, x), dest)
        if x == 'kitty':
            shutil.rmtree(os.path.join(dest, 'launcher'))
    os.rename(os.path.join(kitty_dir, '__main__.py'), os.path.join(env.py_dir, 'kitty_main.py'))
    shutil.rmtree(os.path.join(kitty_dir, '__pycache__'))
    print('Extracting extension modules from', env.py_dir, 'to', pdir)
    ext_map = extract_extension_modules(env.py_dir, pdir)
    shutil.copy(os.path.join(os.path.dirname(self_dir), 'site.py'), os.path.join(env.py_dir, 'site.py'))
    for x in bases:
        iv['sanitize_source_folder'](os.path.join(env.py_dir, x))
    py_compile(env.py_dir)
    freeze_python(env.py_dir, pdir, env.obj_dir, ext_map, develop_mode_env_var='KITTY_DEVELOP_FROM', remove_pyc_files=True)
    shutil.rmtree(env.py_dir)


def build_launcher(env):
    iv['build_frozen_launcher']([path_to_freeze_dir(), env.obj_dir])


def is_elf(path):
    with open(path, 'rb') as f:
        return f.read(4) == b'\x7fELF'


def fix_permissions(files):
    for path in files:
        os.chmod(path, 0o755)


STRIPCMD = ['strip']


def find_binaries(env):
    files = {j(env.bin_dir, x) for x in os.listdir(env.bin_dir)} | {
        x for x in {
            j(os.path.dirname(env.bin_dir), x) for x in os.listdir(env.bin_dir)} if os.path.exists(x)}
    for x in walk(env.lib_dir):
        x = os.path.realpath(x)
        if x not in files and is_elf(x):
            files.add(x)
    return files


def strip_files(files, argv_max=(256 * 1024)):
    """ Strip a list of files """
    while files:
        cmd = list(STRIPCMD)
        pathlen = sum(len(s) + 1 for s in cmd)
        while pathlen < argv_max and files:
            f = files.pop()
            cmd.append(f)
            pathlen += len(f) + 1
        if len(cmd) > len(STRIPCMD):
            all_files = cmd[len(STRIPCMD):]
            unwritable_files = tuple(filter(None, (None if os.access(x, os.W_OK) else (x, os.stat(x).st_mode) for x in all_files)))
            [os.chmod(x, stat.S_IWRITE | old_mode) for x, old_mode in unwritable_files]
            subprocess.check_call(cmd)
            [os.chmod(x, old_mode) for x, old_mode in unwritable_files]


def strip_binaries(files):
    print(f'Stripping {len(files)} files...')
    before = sum(os.path.getsize(x) for x in files)
    strip_files(files)
    after = sum(os.path.getsize(x) for x in files)
    print('Stripped {:.1f} MB'.format((before - after) / (1024 * 1024.)))


def create_tarfile(env, compression_level='9'):
    print('Creating archive...')
    base = OUTPUT_DIR
    arch = 'arm64' if 'arm64' in os.environ['BYPY_ARCH'] else ('i686' if 'i386' in os.environ['BYPY_ARCH'] else 'x86_64')
    try:
        shutil.rmtree(base)
    except OSError as err:
        if err.errno not in (errno.ENOENT, errno.EBUSY):  # EBUSY when the directory is mountpoint
            raise
    os.makedirs(base, exist_ok=True)
    dist = os.path.join(base, f'{kitty_constants["appname"]}-{kitty_constants["version"]}-{arch}.tar')
    with tarfile.open(dist, mode='w', format=tarfile.PAX_FORMAT) as tf:
        cwd = os.getcwd()
        os.chdir(env.base)
        try:
            for x in os.listdir('.'):
                tf.add(x)
        finally:
            os.chdir(cwd)
    print('Compressing archive...')
    ans = f'{dist.rpartition(".")[0]}.txz'
    start_time = time.time()
    threads = 4 if arch == 'i686' else 0
    subprocess.check_call(['xz', '--verbose', f'--threads={threads}', '-f', f'-{compression_level}', dist])
    secs = time.time() - start_time
    print('Compressed in {} minutes {} seconds'.format(secs // 60, secs % 60))
    os.rename(f'{dist}.xz', ans)
    print('Archive {} created: {:.2f} MB'.format(
        os.path.basename(ans), os.stat(ans).st_size / (1024.**2)))


def main():
    args = globals()['args']
    ext_dir = globals()['ext_dir']
    env = Env(os.path.join(ext_dir, kitty_constants['appname']))
    copy_libs(env)
    copy_python(env)
    build_launcher(env)
    files = find_binaries(env)
    fix_permissions(files)
    add_ca_certs(env)
    kitty_exe = os.path.join(env.base, 'bin', 'kitty')
    iv['build_frozen_tools'](kitty_exe)
    if not args.dont_strip:
        strip_binaries(files)
    if not args.skip_tests:
        iv['run_tests'](kitty_exe)
    create_tarfile(env, args.compression_level)


if __name__ == '__main__':
    main()
