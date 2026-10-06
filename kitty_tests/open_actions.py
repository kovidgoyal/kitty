#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


import os
from contextlib import contextmanager

from kitty.utils import get_editor

from .base import BaseTest


@contextmanager
def patch_env(**kw):
    orig = os.environ.copy()
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    yield
    os.environ.clear()
    os.environ.update(orig)


class TestOpenActions(BaseTest):
    def test_parsing_of_open_actions(self):
        from kitty.open_actions import KeyAction, actions_for_url

        self.set_options()
        spec = """
protocol file
mime text/*
fragment_matches .
AcTion launch $EDITOR $FILE_PATH $FRAGMENT
action

protocol file
mime text/*
action ignored

ext py,txt
action one
action two
"""

        def actions(url):
            with patch_env(FILE_PATH='notgood'):
                return tuple(actions_for_url(url, spec))

        def single(url, func, *args):
            acts = actions(url)
            self.ae(len(acts), 1)
            self.ae(acts[0].func, func)
            self.ae(acts[0].args, args)

        single('file://hostname/tmp/moo.txt#23', 'launch', *get_editor(), '/tmp/moo.txt', '23')
        single('some thing.txt', 'ignored')
        self.ae(actions('x:///a.txt'), (KeyAction('one', ()), KeyAction('two', ())))

    def test_mime_cache(self):
        import shutil
        import subprocess
        import tempfile

        from kitty.fast_data_types import clear_mime_cache_data, mime_type_aliases, mime_type_for_filename
        from kitty.guess_mime_type import guess_type, mime_types_for_matching
        from kitty.open_actions import KeyAction, actions_for_url

        if not shutil.which('update-mime-database'):
            self.skipTest('update-mime-database not available')

        def build_cache(data_dir: str, xml: str) -> None:
            pkgs = os.path.join(data_dir, 'mime', 'packages')
            os.makedirs(pkgs)
            with open(os.path.join(pkgs, 'kitty-test.xml'), 'w') as f:
                f.write(MIME_CACHE_TEST_PACKAGE.replace('MIME_TYPES', xml))
            with patch_env(PKGSYSTEM_ENABLE_FSYNC='0'):
                subprocess.run(['update-mime-database', os.path.join(data_dir, 'mime')], check=True, capture_output=True)

        with tempfile.TemporaryDirectory() as tdir:
            user, system = os.path.join(tdir, 'user'), os.path.join(tdir, 'system')
            build_cache(system, MIME_CACHE_TEST_TYPES)
            build_cache(
                user,
                (
                    '<mime-type type="text/x-kt-user"><glob pattern="*.kuser"/><glob pattern="*.kext.override"/></mime-type>'
                    '<mime-type type="text/x-kt-ext"><alias type="text/x-kt-user-alias"/></mime-type>'
                ),
            )
            build_cache(os.path.join(tdir, 'ignored'), '<mime-type type="text/x-kt-ignored"><glob pattern="*.kuser"/></mime-type>')
            try:
                with patch_env(XDG_DATA_HOME=user, XDG_DATA_DIRS=f'relative/dir:{system}/:{tdir}/missing:{tdir}/ignored'):
                    clear_mime_cache_data()
                    for name, expected in MIME_CACHE_TEST_EXPECTATIONS.items():
                        self.ae(mime_type_for_filename(name), expected, name)
                    self.ae(guess_type('/a/b.kext'), 'text/x-kt-ext')
                    self.ae(guess_type('/a/b.kjson'), 'text/json')
                    self.assertRaises(TypeError, mime_type_for_filename, b'a.kext')

                    # aliases
                    ext_names = ('text/x-kt-ext', 'text/x-kt-user-alias', 'application/x-kt-older', 'text/x-kt-old')
                    self.ae(mime_type_aliases('text/x-kt-ext'), ext_names)
                    self.ae(mime_type_aliases('text/x-kt-old'), ext_names)
                    self.ae(mime_type_aliases('unknown/x-kt'), ('unknown/x-kt',))
                    self.assertRaises(TypeError, mime_type_aliases, b'text/x-kt-ext')
                    self.ae(mime_types_for_matching('b.kjson', 'text/json'), {'text/json', 'application/json', 'application/x-kt-json'})
                    self.ae(guess_type('/a/Makefile'), 'text/x-kt-make')
                    self.ae(mime_types_for_matching('/a/Makefile', 'text/x-kt-make'), {'text/x-kt-make', 'text/makefile'})
                    self.set_options()
                    spec = """
mime text/x-kt-old
action old

mime text/MakeFile
action make

mime image/*, application/x-kt-j*
action json
"""
                    for url, action in {'/tmp/b.kext': 'old', 'file:///tmp/Makefile': 'make', 'b.kjson': 'json', 'b.kuser': ''}.items():
                        self.ae(tuple(actions_for_url(url, spec)), (KeyAction(action, ()),) if action else (), url)
                truncated = os.path.join(tdir, 'truncated')
                os.makedirs(os.path.join(truncated, 'mime'))
                with open(os.path.join(system, 'mime', 'mime.cache'), 'rb') as src, open(os.path.join(truncated, 'mime', 'mime.cache'), 'wb') as dest:
                    dest.write(src.read()[:48])
                with patch_env(XDG_DATA_HOME=truncated, XDG_DATA_DIRS=f'{tdir}/missing'):
                    clear_mime_cache_data()
                    self.assertIsNone(mime_type_for_filename('a.kext'))

                # strings in the cache that are not valid UTF-8 are ignored
                invalid = os.path.join(tdir, 'invalid')
                os.makedirs(os.path.join(invalid, 'mime'))
                with open(os.path.join(system, 'mime', 'mime.cache'), 'rb') as src, open(os.path.join(invalid, 'mime', 'mime.cache'), 'wb') as dest:
                    data = src.read()
                    self.assertIn(b'text/x-kt-ext\0', data)
                    dest.write(data.replace(b'text/x-kt-ext\0', b'text/x-kt-\xffxt\0'))
                with patch_env(XDG_DATA_HOME=invalid, XDG_DATA_DIRS=f'{tdir}/missing'):
                    clear_mime_cache_data()
                    self.assertIsNone(mime_type_for_filename('a.kext'))
                    self.ae(mime_type_for_filename('a.kjson'), 'application/json')
                    self.ae(mime_type_aliases('text/x-kt-old'), ('application/x-kt-older', 'text/x-kt-old'))
                    guess_type('/a/b.kext')

                # lone surrogates cannot be encoded and so do not match
                with patch_env(XDG_DATA_HOME=user, XDG_DATA_DIRS=system):
                    clear_mime_cache_data()
                    self.assertIsNone(mime_type_for_filename('a\ud800.kext'))
                    self.ae(mime_type_for_filename('a\udcff.kext'), 'text/x-kt-ext')
                    self.ae(mime_type_aliases('text/\ud800'), ('text/\ud800',))
                    guess_type('/a/b\ud800.kext')
            finally:
                clear_mime_cache_data()


MIME_CACHE_TEST_PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
MIME_TYPES
</mime-info>
"""

# Keep in sync with tools/utils/mime_cache_test.go
MIME_CACHE_TEST_TYPES = """
<mime-type type="text/x-kt-literal"><glob pattern="KittyLiteral"/></mime-type>
<mime-type type="text/x-kt-cs"><glob pattern="*.KCS" case-sensitive="true"/></mime-type>
<mime-type type="text/x-kt-ext"><glob pattern="*.kext"/><alias type="text/x-kt-old"/><alias type="application/x-kt-older"/></mime-type>
<mime-type type="text/x-kt-long"><glob pattern="*.long.kext"/></mime-type>
<mime-type type="text/x-kt-light"><glob pattern="*.kw" weight="40"/></mime-type>
<mime-type type="text/x-kt-heavy"><glob pattern="*.kw" weight="80"/></mime-type>
<mime-type type="text/x-kt-glob"><glob pattern="kglob[0-9].*"/></mime-type>
<mime-type type="text/x-kt-negated-glob"><glob pattern="kneg[!0-9].*"/></mime-type>
<mime-type type="text/x-kt-unicode"><glob pattern="*.kü"/></mime-type>
<mime-type type="application/json"><glob pattern="*.kjson"/><alias type="application/x-kt-json"/></mime-type>
<mime-type type="text/x-kt-make"><glob pattern="Makefile" case-sensitive="true"/></mime-type>
<mime-type type="text/x-kt-system"><glob pattern="*.kuser"/></mime-type>
"""

MIME_CACHE_TEST_EXPECTATIONS = {
    'KittyLiteral': 'text/x-kt-literal',
    'kittyliteral': 'text/x-kt-literal',
    'KITTYLITERAL': 'text/x-kt-literal',
    'xKittyLiteral': None,
    'a.KCS': 'text/x-kt-cs',
    'a.kcs': None,
    'a.kext': 'text/x-kt-ext',
    'A.KEXT': 'text/x-kt-ext',
    '/some/dir/a.kext': 'text/x-kt-ext',
    'dir.kext/noext': None,
    'x.long.kext': 'text/x-kt-long',
    'x.LONG.KEXT': 'text/x-kt-long',
    'xlong.kext': 'text/x-kt-ext',
    'a.kw': 'text/x-kt-heavy',
    'kglob1.txt': 'text/x-kt-glob',
    'KGLOB1.TXT': 'text/x-kt-glob',
    'kglobx.txt': None,
    'knegx.txt': 'text/x-kt-negated-glob',
    'kneg1.txt': None,
    'a.kü': 'text/x-kt-unicode',
    'a.KÜ': 'text/x-kt-unicode',
    'a.kuser': 'text/x-kt-user',
    'a.kext.override': 'text/x-kt-user',
    '': None,
    'a\0.kext': None,
    'notmatched': None,
}
