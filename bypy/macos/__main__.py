#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import glob
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from bypy.constants import PREFIX, PYTHON, SW, python_major_minor_version
from bypy.freeze import extract_extension_modules, freeze_python, path_to_freeze_dir
from bypy.macos_sign import codesign, create_entitlements_file, make_certificate_useable, notarize_app, verify_signature
from bypy.utils import current_dir, mkdtemp, py_compile, run_shell, timeit, walk

iv = globals()['init_env']
kitty_constants = iv['kitty_constants']
self_dir = os.path.dirname(os.path.abspath(__file__))
join = os.path.join
basename = os.path.basename
dirname = os.path.dirname
abspath = os.path.abspath
APPNAME = kitty_constants['appname']
VERSION = kitty_constants['version']
py_ver = '.'.join(map(str, python_major_minor_version()))


def flush(func):
    def ff(*args, **kwargs):
        sys.stdout.flush()
        sys.stderr.flush()
        ret = func(*args, **kwargs)
        sys.stdout.flush()
        sys.stderr.flush()
        return ret

    return ff


def flipwritable(fn, mode=None):
    """
    Flip the writability of a file and return the old mode. Returns None
    if the file is already writable.
    """
    if os.access(fn, os.W_OK):
        return None
    old_mode = os.stat(fn).st_mode
    os.chmod(fn, stat.S_IWRITE | old_mode)
    return old_mode


STRIPCMD = ('/usr/bin/strip', '-x', '-S', '-')


def strip_files(files, argv_max=(256 * 1024)):
    """
    Strip a list of files
    """
    tostrip = [(fn, flipwritable(fn)) for fn in files if os.path.exists(fn)]
    while tostrip:
        cmd = list(STRIPCMD)
        flips = []
        pathlen = sum(len(s) + 1 for s in cmd)
        while pathlen < argv_max:
            if not tostrip:
                break
            added, flip = tostrip.pop()
            pathlen += len(added) + 1
            cmd.append(added)
            flips.append((added, flip))
        else:
            cmd.pop()
            tostrip.append(flips.pop())
        os.spawnv(os.P_WAIT, cmd[0], cmd)
        for args in flips:
            flipwritable(*args)


def files_in(folder):
    for record in os.walk(folder):
        for f in record[-1]:
            yield join(record[0], f)


def expand_dirs(items, exclude=lambda x: x.endswith('.so')):
    items = set(items)
    dirs = set(x for x in items if os.path.isdir(x))
    items.difference_update(dirs)
    for x in dirs:
        items.update({y for y in files_in(x) if not exclude(y)})
    return items



def do_sign(app_dir: str) -> None:
    with current_dir(join(app_dir, 'Contents')):
        # Sign all .so files
        so_files = {x for x in files_in('.') if x.endswith('.so')}
        codesign(so_files)
        # Sign everything else in Frameworks
        with current_dir('Frameworks'):
            fw = set(glob.glob('*.framework'))
            codesign(fw)
            items = set(os.listdir('.')) - fw
            codesign(expand_dirs(items))
        # Sign kitten
        with current_dir('MacOS'):
            codesign('kitten')
        # Sign sub-apps
        for x in os.listdir('.'):
            if x.endswith('.app'):
                codesign(x)

    # Now sign the main app
    codesign(app_dir)
    verify_signature(app_dir)


def sign_app(app_dir, notarize):
    # Copied from iTerm2: https://github.com/gnachman/iTerm2/blob/master/iTerm2.entitlements
    create_entitlements_file({
        'com.apple.security.automation.apple-events': True,
        'com.apple.security.cs.allow-jit': True,
        'com.apple.security.device.audio-input': True,
        'com.apple.security.device.camera': True,
        'com.apple.security.personal-information.addressbook': True,
        'com.apple.security.personal-information.calendars': True,
        'com.apple.security.personal-information.location': True,
        'com.apple.security.personal-information.photos-library': True,
    })
    with make_certificate_useable():
        do_sign(app_dir)
        if notarize:
            notarize_app(app_dir, 'kitty')


class Freeze(object):

    FID = '@executable_path/../Frameworks'

    def __init__(self, build_dir, dont_strip=False, sign_installers=False, notarize=False, skip_tests=False):
        self.build_dir = build_dir
        self.skip_tests = skip_tests
        self.sign_installers = sign_installers
        self.notarize = notarize
        self.dont_strip = dont_strip
        self.contents_dir = join(self.build_dir, 'Contents')
        self.resources_dir = join(self.contents_dir, 'Resources')
        self.frameworks_dir = join(self.contents_dir, 'Frameworks')
        self.to_strip = []
        self.warnings = []
        self.py_ver = py_ver
        self.python_stdlib = join(self.resources_dir, 'Python', 'lib', f'python{self.py_ver}')
        self.site_packages = self.python_stdlib  # hack to avoid needing to add site-packages to path
        self.obj_dir = mkdtemp('launchers-')

        self.run()

    def run_shell(self):
        with current_dir(self.contents_dir):
            run_shell()

    def run(self):
        ret = 0
        self.add_python_framework()
        self.add_site_packages()
        self.add_stdlib()
        self.add_misc_libraries()
        self.freeze_python()
        self.add_ca_certs()
        self.build_frozen_tools()
        self.complete_sub_bundles()
        if not self.dont_strip:
            self.strip_files()
        if not self.skip_tests:
            self.run_tests()
        # self.run_shell()

        ret = self.makedmg(self.build_dir, f'{APPNAME}-{VERSION}')

        return ret

    @flush
    def complete_sub_bundles(self):
        count = 0
        for qapp in glob.glob(join(self.contents_dir, '*.app')):
            for exe in glob.glob(join(self.contents_dir, 'MacOS', '*')):
                os.symlink(f'../../../MacOS/{os.path.basename(exe)}', os.path.join(qapp, 'Contents', 'MacOS', os.path.basename(exe)))
                count += 1
        if count < 2:
            raise SystemExit(f'Could not complete sub-bundles in {self.contents_dir}')

    @flush
    def add_ca_certs(self):
        print('\nDownloading CA certs...')
        from urllib.request import urlopen
        cdata = None
        for i in range(5):
            try:
                cdata = urlopen(kitty_constants['cacerts_url']).read()
                break
            except Exception as e:
                print(f'Downloading CA certs failed with error: {e}, retrying...')

        if cdata is None:
            raise SystemExit('Downloading C certs failed, giving up')
        dest = join(self.contents_dir, 'Resources', 'cacert.pem')
        with open(dest, 'wb') as f:
            f.write(cdata)

    @flush
    def strip_files(self):
        print('\nStripping files...')
        strip_files(self.to_strip)

    @flush
    def run_tests(self):
        iv['run_tests'](join(self.contents_dir, 'MacOS', 'kitty'))

    @flush
    def set_id(self, path_to_lib, new_id):
        old_mode = flipwritable(path_to_lib)
        subprocess.check_call(
            ['install_name_tool', '-id', new_id, path_to_lib])
        if old_mode is not None:
            flipwritable(path_to_lib, old_mode)

    @flush
    def get_dependencies(self, path_to_lib):
        install_name = subprocess.check_output(
            ['otool', '-D', path_to_lib]).decode('utf-8').splitlines()[-1].strip()
        raw = subprocess.check_output(['otool', '-L', path_to_lib]).decode('utf-8')
        for line in raw.splitlines():
            if 'compatibility' not in line or line.strip().endswith(':'):
                continue
            idx = line.find('(')
            path = line[:idx].strip()
            yield path, path == install_name

    @flush
    def get_local_dependencies(self, path_to_lib):
        for x, is_id in self.get_dependencies(path_to_lib):
            for y in (f'{PREFIX}/lib/', f'{PREFIX}/python/Python.framework/', '@rpath/'):
                if x.startswith(y):
                    if y == f'{PREFIX}/python/Python.framework/':
                        y = f'{PREFIX}/python/'
                    yield x, x[len(y):], is_id
                    break

    @flush
    def change_dep(self, old_dep, new_dep, is_id, path_to_lib):
        cmd = ['-id', new_dep] if is_id else ['-change', old_dep, new_dep]
        subprocess.check_call(['install_name_tool'] + cmd + [path_to_lib])

    @flush
    def fix_dependencies_in_lib(self, path_to_lib):
        self.to_strip.append(path_to_lib)
        old_mode = flipwritable(path_to_lib)
        for dep, bname, is_id in self.get_local_dependencies(path_to_lib):
            ndep = f'{self.FID}/{bname}'
            self.change_dep(dep, ndep, is_id, path_to_lib)
        ldeps = list(self.get_local_dependencies(path_to_lib))
        if ldeps:
            print('\nFailed to fix dependencies in', path_to_lib)
            print('Remaining local dependencies:', ldeps)
            raise SystemExit(1)
        if old_mode is not None:
            flipwritable(path_to_lib, old_mode)

    @flush
    def add_python_framework(self):
        print('\nAdding Python framework')
        src = join(f'{PREFIX}/python', 'Python.framework')
        x = join(self.frameworks_dir, 'Python.framework')
        curr = os.path.realpath(join(src, 'Versions', 'Current'))
        currd = join(x, 'Versions', basename(curr))
        rd = join(currd, 'Resources')
        os.makedirs(rd)
        shutil.copy2(join(curr, 'Resources', 'Info.plist'), rd)
        shutil.copy2(join(curr, 'Python'), currd)
        self.set_id(
            join(currd, 'Python'),
            f'{self.FID}/Python.framework/Versions/{basename(curr)}/Python')
        # The following is needed for codesign
        with current_dir(x):
            os.symlink(basename(curr), 'Versions/Current')
            for y in ('Python', 'Resources'):
                os.symlink(f'Versions/Current/{y}', y)

    @flush
    def install_dylib(self, path, set_id=True):
        shutil.copy2(path, self.frameworks_dir)
        if set_id:
            self.set_id(
                join(self.frameworks_dir, basename(path)),
                f'{self.FID}/{basename(path)}')
        self.fix_dependencies_in_lib(join(self.frameworks_dir, basename(path)))

    @flush
    def add_misc_libraries(self):
        for x in (
                'sqlite3.0',
                'z.1',
                'harfbuzz.0',
                'png16.16',
                'lcms2.2',
                'crypto.3',
                'ssl.3',
                'xxhash.0',
        ):
            print('\nAdding', x)
            x = f'lib{x}.dylib'
            src = join(PREFIX, 'lib', x)
            shutil.copy2(src, self.frameworks_dir)
            dest = join(self.frameworks_dir, x)
            self.set_id(dest, f'{self.FID}/{x}')
            self.fix_dependencies_in_lib(dest)

    @flush
    def add_package_dir(self, x, dest=None):
        def ignore(root, files):
            ans = []
            for y in files:
                ext = os.path.splitext(y)[1]
                if ext not in ('', '.py', '.so') or \
                        (not ext and not os.path.isdir(join(root, y))):
                    ans.append(y)

            return ans

        if dest is None:
            dest = self.site_packages
        dest = join(dest, basename(x))
        shutil.copytree(x, dest, symlinks=True, ignore=ignore)
        for f in walk(dest):
            if f.endswith('.so'):
                self.fix_dependencies_in_lib(f)

    @flush
    def add_stdlib(self):
        print('\nAdding python stdlib')
        src = f'{PREFIX}/python/Python.framework/Versions/Current/lib/python{self.py_ver}'
        dest = self.python_stdlib
        if not os.path.exists(dest):
            os.makedirs(dest)
        for x in os.listdir(src):
            if x in ('site-packages', 'config', 'test', 'lib2to3', 'lib-tk',
                     'lib-old', 'idlelib', 'plat-mac', 'plat-darwin',
                     'site.py', 'distutils', 'turtledemo', 'tkinter'):
                continue
            x = join(src, x)
            if os.path.isdir(x):
                self.add_package_dir(x, dest)
            elif os.path.splitext(x)[1] in ('.so', '.py'):
                shutil.copy2(x, dest)
                dest2 = join(dest, basename(x))
                if dest2.endswith('.so'):
                    self.fix_dependencies_in_lib(dest2)

    @flush
    def freeze_python(self):
        print('\nFreezing python')
        kitty_dir = join(self.resources_dir, 'kitty')
        bases = ('kitty', 'kittens', 'kitty_tests')
        for x in bases:
            dest = join(self.python_stdlib, x)
            os.rename(join(kitty_dir, x), dest)
            if x == 'kitty':
                shutil.rmtree(join(dest, 'launcher'))
        os.rename(join(kitty_dir, '__main__.py'), join(self.python_stdlib, 'kitty_main.py'))
        shutil.rmtree(join(kitty_dir, '__pycache__'))
        pdir = join(dirname(self.python_stdlib), 'kitty-extensions')
        os.mkdir(pdir)
        print('Extracting extension modules from', self.python_stdlib, 'to', pdir)
        ext_map = extract_extension_modules(self.python_stdlib, pdir)
        shutil.copy(join(os.path.dirname(self_dir), 'site.py'), join(self.python_stdlib, 'site.py'))
        for x in bases:
            iv['sanitize_source_folder'](join(self.python_stdlib, x))
        self.compile_py_modules()
        freeze_python(self.python_stdlib, pdir, self.obj_dir, ext_map, develop_mode_env_var='KITTY_DEVELOP_FROM', remove_pyc_files=True)
        shutil.rmtree(self.python_stdlib)
        iv['build_frozen_launcher']([path_to_freeze_dir(), self.obj_dir])
        os.rename(join(dirname(self.contents_dir), 'bin', 'kitty'), join(self.contents_dir, 'MacOS', 'kitty'))
        shutil.rmtree(join(dirname(self.contents_dir), 'bin'))
        self.fix_dependencies_in_lib(join(self.contents_dir, 'MacOS', 'kitty'))
        for f in glob.glob(join(self.contents_dir, '*.app', 'Contents', 'MacOS', '*')):
            if not os.path.islink(f):
                self.fix_dependencies_in_lib(f)
        for f in walk(pdir):
            if f.endswith('.so') or f.endswith('.dylib'):
                self.fix_dependencies_in_lib(f)

    @flush
    def build_frozen_tools(self):
        iv['build_frozen_tools'](join(self.contents_dir, 'MacOS', 'kitty'))

    @flush
    def add_site_packages(self):
        print('\nAdding site-packages')
        os.makedirs(self.site_packages)
        sys_path = json.loads(subprocess.check_output([
            PYTHON, '-c', 'import sys, json; json.dump(sys.path, sys.stdout)']))
        paths = reversed(tuple(map(abspath, [x for x in sys_path if x.startswith('/') and not x.startswith('/Library/')])))
        upaths = []
        for x in paths:
            if x not in upaths and (x.endswith('.egg') or x.endswith('/site-packages')):
                upaths.append(x)
        for x in upaths:
            print('\t', x)
            tdir = None
            try:
                if not os.path.isdir(x):
                    zf = zipfile.ZipFile(x)
                    tdir = tempfile.mkdtemp()
                    zf.extractall(tdir)
                    x = tdir
                self.add_modules_from_dir(x)
                self.add_packages_from_dir(x)
            finally:
                if tdir is not None:
                    shutil.rmtree(tdir)
        self.remove_bytecode(self.site_packages)

    @flush
    def add_modules_from_dir(self, src):
        for x in glob.glob(join(src, '*.py')) + glob.glob(join(src, '*.so')):
            shutil.copy2(x, self.site_packages)
            if x.endswith('.so'):
                self.fix_dependencies_in_lib(x)

    @flush
    def add_packages_from_dir(self, src):
        for x in os.listdir(src):
            x = join(src, x)
            if os.path.isdir(x) and os.path.exists(join(x, '__init__.py')):
                if self.filter_package(basename(x)):
                    continue
                self.add_package_dir(x)

    @flush
    def filter_package(self, name):
        return name in ('Cython', 'modulegraph', 'macholib', 'py2app',
                        'bdist_mpkg', 'altgraph')

    @flush
    def remove_bytecode(self, dest):
        for x in os.walk(dest):
            root = x[0]
            for f in x[-1]:
                if os.path.splitext(f) == '.pyc':
                    os.remove(join(root, f))

    @flush
    def compile_py_modules(self):
        self.remove_bytecode(join(self.resources_dir, 'Python'))
        py_compile(join(self.resources_dir, 'Python'))

    @flush
    def makedmg(self, d, volname, format='ULMO'):
        ''' Copy a directory d into a dmg named volname '''
        print('\nMaking dmg...')
        sys.stdout.flush()
        destdir = join(SW, 'dist')
        try:
            shutil.rmtree(destdir)
        except FileNotFoundError:
            pass
        os.mkdir(destdir)
        dmg = join(destdir, f'{volname}.dmg')
        if os.path.exists(dmg):
            os.unlink(dmg)
        tdir = tempfile.mkdtemp()
        appdir = join(tdir, os.path.basename(d))
        shutil.copytree(d, appdir, symlinks=True)
        if self.sign_installers:
            with timeit() as times:
                sign_app(appdir, self.notarize)
            print('Signing completed in {} minutes {} seconds'.format(*times))
        os.symlink('/Applications', join(tdir, 'Applications'))
        size_in_mb = int(
            subprocess.check_output(['du', '-s', '-k', tdir]).decode('utf-8')
            .split()[0]) / 1024.
        cmd = [
            '/usr/bin/hdiutil', 'create', '-srcfolder', tdir, '-volname',
            volname, '-format', format
        ]
        if 190 < size_in_mb < 250:
            # We need -size 255m because of a bug in hdiutil. When the size of
            # srcfolder is close to 200MB hdiutil fails with
            # diskimages-helper: resize request is above maximum size allowed.
            cmd += ['-size', '255m']
        print('\nCreating dmg...')
        with timeit() as times:
            subprocess.check_call(cmd + [dmg])
        print('dmg created in {} minutes and {} seconds'.format(*times))
        shutil.rmtree(tdir)
        size = os.stat(dmg).st_size / (1024 * 1024.)
        print(f'\nInstaller size: {size:.2f}MB\n')
        return dmg


def main():
    args = globals()['args']
    ext_dir = globals()['ext_dir']
    Freeze(
        join(ext_dir, f'{kitty_constants["appname"]}.app'),
        dont_strip=args.dont_strip,
        sign_installers=args.sign_installers,
        notarize=args.notarize,
        skip_tests=args.skip_tests
    )


if __name__ == '__main__':
    main()
