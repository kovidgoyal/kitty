#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from functools import partial

from . import BaseTest


class TestBuild(BaseTest):

    def test_exe(self) -> None:
        from kitty.constants import kitten_exe, kitty_exe, str_version
        exe = kitty_exe()
        self.assertTrue(os.access(exe, os.X_OK))
        self.assertTrue(os.path.isfile(exe))
        self.assertIn('kitty', os.path.basename(exe))
        exe = kitten_exe()
        self.assertTrue(os.access(exe, os.X_OK))
        self.assertTrue(os.path.isfile(exe))
        self.assertIn(str_version, subprocess.check_output([exe, '--version']).decode())

    def test_loading_extensions(self) -> None:
        import kitty.fast_data_types as fdt
        from kittens.transfer import rsync
        del fdt, rsync

    def test_loading_shaders(self) -> None:
        from kitty.shaders import Program
        for name in 'cell border bgimage tint graphics'.split():
            Program(name)

    def test_macos_dictation_forwarding(self) -> None:
        from kitty.constants import glfw_path, is_macos
        if not is_macos or not shutil.which('clang'):
                self.skipTest('Dictation smoke test is macOS only and requires clang')
        cocoa_module = glfw_path('cocoa')
        probe = textwrap.dedent('''\
            #import <AppKit/AppKit.h>
            #import <dlfcn.h>
            #import <objc/runtime.h>
            #import <objc/message.h>

            static int start_calls = 0;
            static int stop_calls = 0;
            static id last_sender = nil;

            static void fake_start_dictation(id self, SEL _cmd, id sender) {
                (void)self; (void)_cmd;
                start_calls++;
                last_sender = sender;
            }

            static void fake_stop_dictation(id self, SEL _cmd, id sender) {
                (void)self; (void)_cmd;
                stop_calls++;
                last_sender = sender;
            }

            static void require_true(BOOL condition, const char *message) {
                if (!condition) {
                    fprintf(stderr, "FAIL: %s\\n", message);
                    exit(1);
                }
            }

            int main(void) {
                @autoreleasepool {
                    [NSApplication sharedApplication];
                    void *handle = dlopen(@@COCOA_MODULE@@, RTLD_NOW | RTLD_GLOBAL);
                    require_true(handle != NULL, dlerror());

                    SEL start = NSSelectorFromString(@"startDictation:");
                    SEL stop = NSSelectorFromString(@"stopDictation:");
                    Method start_method = class_getInstanceMethod([NSApplication class], start);
                    Method stop_method = class_getInstanceMethod([NSApplication class], stop);
                    require_true(start_method != NULL, "NSApplication startDictation: missing");
                    require_true(stop_method != NULL, "NSApplication stopDictation: missing");
                    method_setImplementation(start_method, (IMP)fake_start_dictation);
                    method_setImplementation(stop_method, (IMP)fake_stop_dictation);

                    Class view_cls = NSClassFromString(@"GLFWContentView");
                    Class context_cls = NSClassFromString(@"GLFWTextInputContext");
                    require_true(view_cls != Nil, "GLFWContentView class not loaded");
                    require_true(context_cls != Nil, "GLFWTextInputContext class not loaded");

                    SEL init_with_glfw_window = NSSelectorFromString(@"initWithGlfwWindow:");
                    id view = ((id (*)(id, SEL, void *)) objc_msgSend)([view_cls alloc], init_with_glfw_window, NULL);
                    require_true(view != nil, "GLFWContentView initWithGlfwWindow: failed");
                    require_true([view respondsToSelector:start], "GLFWContentView does not expose startDictation:");
                    require_true([view respondsToSelector:stop], "GLFWContentView does not expose stopDictation:");

            #pragma clang diagnostic push
            #pragma clang diagnostic ignored "-Warc-performSelector-leaks"
                    [view performSelector:start withObject:@"menu sender"];
            #pragma clang diagnostic pop
                    require_true(start_calls == 1, "startDictation: action was not forwarded to NSApplication");
                    require_true([(id)last_sender isEqual:@"menu sender"], "startDictation: forwarded wrong sender");

                    [view doCommandBySelector:start];
                    require_true(start_calls == 2, "doCommandBySelector:startDictation: was swallowed");
                    require_true(last_sender == view, "doCommandBySelector:startDictation: should forward self as sender");

                    id context = [view inputContext];
                    require_true(context != nil, "GLFWContentView inputContext missing");
                    require_true([context isKindOfClass:context_cls], "GLFWContentView inputContext has wrong class");
                    [context doCommandBySelector:stop];
                    require_true(stop_calls == 1, "GLFWTextInputContext did not forward stopDictation:");
                    require_true(last_sender == nil, "GLFWTextInputContext should forward nil sender");

                    printf("dictation forwarding probe passed\\n");
                }
                return 0;
            }
        ''').replace('@@COCOA_MODULE@@', json.dumps(cocoa_module))
        with tempfile.TemporaryDirectory() as tdir:
            src = os.path.join(tdir, 'dictation_probe.m')
            exe = os.path.join(tdir, 'dictation_probe')
            with open(src, 'w') as f:
                f.write(probe)
            cp = subprocess.run(
                ['clang', '-framework', 'AppKit', src, '-o', exe],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            self.assertEqual(cp.returncode, 0, cp.stdout)
            cp = subprocess.run([exe], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(cp.returncode, 0, cp.stdout)
            self.assertIn('dictation forwarding probe passed', cp.stdout)

    def test_glfw_modules(self) -> None:
        from kitty.constants import glfw_path, is_macos
        linux_backends = ['x11']
        if not self.is_ci:
            linux_backends.append('wayland')
        modules = ['cocoa'] if is_macos else linux_backends
        for name in modules:
            path = glfw_path(name)
            self.assertTrue(os.path.isfile(path), f'{path} is not a file')
            self.assertTrue(os.access(path, os.X_OK), f'{path} is not executable')

    def test_all_kitten_names(self) -> None:
        from kittens.runner import all_kitten_names
        names = all_kitten_names()
        self.assertIn('diff', names)
        self.assertIn('hints', names)
        self.assertGreater(len(names), 8)

    def test_filesystem_locations(self) -> None:
        from kitty.constants import fonts_dir, local_docs, logo_png_file, shell_integration_dir, terminfo_dir
        zsh = os.path.join(shell_integration_dir, 'zsh')
        self.assertTrue(os.path.isdir(terminfo_dir), f'Terminfo dir: {terminfo_dir}')
        self.assertTrue(os.path.exists(logo_png_file), f'Logo file: {logo_png_file}')
        self.assertTrue(os.path.exists(zsh), f'Shell integration: {zsh}')
        nsfm = os.path.join(fonts_dir, 'SymbolsNerdFontMono-Regular.ttf')
        self.assertTrue(os.path.exists(nsfm), f'Logo file: {nsfm}')

        def is_executable(x):
            mode = os.stat(x).st_mode
            q = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            return mode & q == q

        for x in ('kitty', 'kitten'):
            x = os.path.join(shell_integration_dir, 'ssh', x)
            self.assertTrue(is_executable(x), f'{x} is not executable')
        if getattr(sys, 'frozen', False):
            self.assertTrue(os.path.isdir(local_docs()), f'Local docs: {local_docs()}')

    def test_ca_certificates(self):
        import ssl
        if not getattr(sys, 'frozen', False):
            self.skipTest('CA certificates are only tested on frozen builds')
        c = ssl.create_default_context()
        self.assertGreater(c.cert_store_stats()['x509_ca'], 2)

    def test_docs_url(self):
        from kitty.constants import website_url
        from kitty.utils import docs_url

        def run_tests(p, base, suffix='.html'):
            def t(x, e):
                self.ae(p(x), base + e)
            t('', 'index.html' if suffix == '.html' else '')
            t('conf', f'conf{suffix}')
            t('kittens/ssh#frag', f'kittens/ssh{suffix}#frag')
            t('#ref=confloc', f'conf{suffix}#confloc')
            t('#ref=conf-kitty-fonts', f'conf{suffix}#conf-kitty-fonts')
            t('#ref=conf-kitten-ssh-xxx', f'kittens/ssh{suffix}#conf-kitten-ssh-xxx')
            t('#ref=at_close_tab', f'remote-control{suffix}#at-close-tab')
            t('#ref=at-close-tab', f'remote-control{suffix}#at-close-tab')
            t('#ref=action-copy', f'actions{suffix}#copy')
            t('#ref=doc-/marks', f'marks{suffix}')

        run_tests(partial(docs_url, local_docs_root='/docs'), 'file:///docs/')
        w = website_url()
        run_tests(partial(docs_url, local_docs_root=None), w, '/')
        self.ae(docs_url('#ref=issues-123'), 'https://github.com/kovidgoyal/kitty/issues/123')

    def test_launcher_ensures_stdio(self):
        import subprocess

        from kitty.constants import kitty_exe
        exe = kitty_exe()
        cp = subprocess.run([exe, '+runpy', f'''\
import os, sys
if sys.stdin:
    os.close(sys.stdin.fileno())
if sys.stdout:
    os.close(sys.stdout.fileno())
if sys.stderr:
    os.close(sys.stderr.fileno())
os.execlp({exe!r}, 'kitty', '+runpy', 'import sys; raise SystemExit(1 if sys.stdout is None or sys.stdin is None or sys.stderr is None else 0)')
'''])
        self.assertEqual(cp.returncode, 0)


def main() -> None:
    tests = unittest.defaultTestLoader.loadTestsFromTestCase(TestBuild)
    r = unittest.TextTestRunner(verbosity=4)
    result = r.run(tests)
    if result.errors or result.failures:
        raise SystemExit(1)
