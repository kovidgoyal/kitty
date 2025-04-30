#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import subprocess
import tempfile

from kitty.constants import kitty_exe
from kitty.fast_data_types import Color, test_cursor_blink_easing_function
from kitty.options.utils import DELETE_ENV_VAR, EasingFunction, to_color
from kitty.utils import log_error, shlex_split

from . import BaseTest


class TestConfParsing(BaseTest):

    def setUp(self):
        super().setUp()
        self.error_messages = []
        log_error.redirect = self.error_messages.append
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        del log_error.redirect
        shutil.rmtree(self.tdir)
        super().tearDown()

    def test_conf_parsing(self):
        conf_parsing(self)

    def test_launcher(self):
        launcher(self)

    def test_cli_parsing(self):
        cli_parsing(self)


def cli_parsing(self):
    from kitty.cli import CLIOptions, Options, parse_cmdline, parse_option_spec
    seq, disabled = parse_option_spec('''\
--simple-string -s
a simple string


--list -l
type=list
a list


--choice -c
choices=a,b,c
some choices


--bool-set -1
type=bool-set
set a bool


--bool-reset -0
type=bool-reset
unset a bool


--int -i
type=int
a integer


--float -f
type=float
a float


--version -v
type=bool-set
version
''')
    oc = Options(seq, usage='xxx', message='yyy', appname='test')
    oc.do_print = False

    def t(args, leftover=(), fails=False, version_called=False, help_called=False, **expected):
        oc.help_called = oc.version_called = False
        args = list(shlex_split(args))
        ans = CLIOptions()
        if fails:
            if isinstance(fails, str):
                with self.assertRaisesRegex(SystemExit, fails):
                    parse_cmdline(oc, disabled, ans, args=args)
            else:
                with self.assertRaises(SystemExit):
                    parse_cmdline(oc, disabled, ans, args=args)
        else:
            actual_leftover = parse_cmdline(oc, disabled, ans, args=args)
            self.assertEqual(tuple(leftover), tuple(actual_leftover), f'{args}\n{ans}')
            for dest, defval in oc.values_map.items():
                val = expected.get(dest, defval)
                self.assertEqual(val, getattr(ans, dest, BaseTest), f'Failed to parse {dest} correctly for: {args}\n{ans}')
        self.assertEqual(version_called, oc.version_called, f'Failed to call version for: {args}\n{ans}')
        self.assertEqual(help_called, oc.help_called, f'Failed to call help for: {args}\n{ans}')

    t('-1', bool_set=True)
    t('-01', bool_reset=False, bool_set=True)
    t('-01=y', bool_reset=False, bool_set=True)
    t('-01=n', bool_reset=False, bool_set=False)
    t('--simple-string xx moo -1', leftover=['moo', '-1'], simple_string='xx')
    t('--si -0 -- -1', leftover=['-1'], simple_string='-0')
    t('--simple-string=-0 -- -1', leftover=['-1'], simple_string='-0')
    t('--simple-string=--help -- -1', leftover=['-1'], simple_string='--help')
    t('--simple-string --help -- -1', leftover=['-1'], simple_string='--help')
    t('-1l=a --list=b -c b --list c', bool_set=True, choice='b', list=list('abc'))
    t('-1s= -l "" --list= x', leftover=['x'], bool_set=True, simple_string='', list=['', ''])
    t('--choice moo', fails=r'moo')
    t('--bool', fails='mbiguous')
    t('-1c moo', fails=r'moo')
    t('-10c=moo', fails=r'moo')
    t('-1 -h', fails=True, help_called=True)
    t('-1 --help', fails=True, help_called=True)
    t('-1 -0v', fails=True, version_called=True)
    t('-1 -v0', fails=True, version_called=True)
    t('-1 --version', fails=True, version_called=True)
    t('-f=3.142 --int 17', float=3.142, int=17)


def launcher(self):
    kexe = kitty_exe()
    cfgdir = None
    def get_report(cmdline: str, launch_services= False):
        nonlocal cfgdir
        args = list(shlex_split(cmdline))
        env = dict(os.environ)
        if launch_services:
            env['KITTY_LAUNCHED_BY_LAUNCH_SERVICES'] = '1'
        cp = subprocess.run([kexe, "+testing-launcher-code"] + args, env=env, stdout=subprocess.PIPE)
        self.assertEqual(cp.returncode, 0)
        ans = {}
        for line in cp.stdout.decode().split('\n'):
            if not line:
                continue
            try:
                key, val = line.split(':')
            except ValueError:
                raise AssertionError(f'Unexpected output from launcher: {line!r}\n{cp.stdout.decode()}')
            if '\x1e' in val:
                val = [x for x in val.split('\x1e') if x]
            else:
                val = val.strip()
            ans[key] = val
            if key == 'config_dir':
                cfgdir = val
        return ans, cp.stdout.decode().replace('\x1e', ' ')
    def test(cmdline, assertions):
        r, output = get_report(cmdline, launch_services=assertions.get('launched_by_launch_services', '0') != '0')
        for key, expected in assertions.items():
            self.assertEqual(expected, r.get(key), f'Failed for {key} with command line: {cmdline}\nOutput:\n{output}')
        return output

    def t(cmdline, **assertions):
        assertions['is_quick_access_terminal'] = '0'
        if cfgdir:
            assertions['config_dir'] = cfgdir
        assertions.setdefault('launched_by_launch_services', '0')
        test(cmdline, assertions)

    def si(cmdline, **assertions):
        assertions['single_instance'] = '1'
        test(cmdline, assertions)

    def dt(cmdline, **assertions):
        assertions['detach'] = 'true'
        test(cmdline, assertions)

    def k(cmdline):
        assertions = {}
        assertions['argv'] = ['kitten'] + cmdline.split()
        for prefix in ('+kitten', '+ kitten'):
            output = test(prefix + ' ' + cmdline, assertions)
            self.assertIn('kitten_exe:', output)

    def pn(cmdline, **assertions):
        ig = assertions.get('instance_group')
        assertions['instance_group'] = f'panel-{ig}' if ig else 'panel'
        assertions['single_instance'] = '1'
        assertions['session'] = ''
        test(cmdline, assertions)

    t('', original_argv=[kexe], argv=[])
    t('--title=xxx --start-as maximized -c=a -c b cat', title='xxx', start_as='maximized', config=['a', 'b'], original_argv=[
        kexe, '--title=xxx', '--start-as', 'maximized', '-c=a', '-c', 'b', 'cat'], argv=['cat'])
    k('icat abc xyz')
    t('+kitten unwrapped xyz', argv=['+kitten', 'unwrapped', 'xyz'])
    t('+ kitten unwrapped xyz', original_argv=[kexe, '+', 'kitten', 'unwrapped', 'xyz'])
    si('--single-instance --instance-group=g -T 3', argv=[kexe, '--single-instance', '--instance-group=g', '-T', '3'])
    t('+open --help', argv=['+open', '--help'])
    t('+open -1 --help', argv=['+open', '-1', '--help'])
    si('+open -1 moose', argv=[kexe, '+open', '-1', 'moose'], open_urls=['moose'])
    si('+open -1 --instance-group=g x y', instance_group='g', open_urls=['x', 'y'])
    dt('--detach --session=moose --detached-log=xyz', detached_log='xyz', session='moose')
    pn('+kitten panel -1 --edge=left', edge='left')


def conf_parsing(self):
    from kitty.config import defaults, load_config
    from kitty.constants import is_macos
    from kitty.fonts import FontModification, ModificationType, ModificationUnit, ModificationValue
    from kitty.options.utils import to_modifiers
    bad_lines = []

    def p(*lines, bad_line_num=0, num_err=None):
        del bad_lines[:]
        del self.error_messages[:]
        ans = load_config(overrides=lines, accumulate_bad_lines=bad_lines)
        if bad_line_num:
            self.ae(len(bad_lines), bad_line_num)
        else:
            self.assertFalse(bad_lines)
        if num_err is not None:
            self.ae(len(self.error_messages), num_err, '\n'.join(self.error_messages))
        return ans

    def keys_for_func(opts, name):
        for key, defns in opts.keyboard_modes[''].keymap.items():
            for action in opts.alias_map.resolve_aliases(defns[0].definition):
                if action.func == name:
                    yield key

    opts = p('font_size 11.37', 'clear_all_shortcuts y', 'color23 red')
    self.ae(opts.font_size, 11.37)
    self.ae(opts.mouse_hide_wait[0], 0 if is_macos else 3)
    self.ae(opts.mouse_hide_wait[1], 0)
    self.ae(opts.mouse_hide_wait[2], 40)
    self.ae(opts.mouse_hide_wait[3], True)
    self.ae(opts.color23, Color(255, 0, 0))
    self.assertFalse(opts.keyboard_modes[''].keymap)
    opts = p('clear_all_shortcuts y', 'map f1 next_window')
    self.ae(len(opts.keyboard_modes[''].keymap), 1)
    opts = p('clear_all_mouse_actions y', 'mouse_map left click ungrabbed mouse_click_url_or_select')
    self.ae(len(opts.mousemap), 1)
    opts = p('strip_trailing_spaces always')
    self.ae(opts.strip_trailing_spaces, 'always')
    self.assertFalse(bad_lines)
    opts = p('pointer_shape_when_grabbed XXX', bad_line_num=1)
    self.ae(opts.pointer_shape_when_grabbed, defaults.pointer_shape_when_grabbed)
    opts = p('modify_font underline_position -2', 'modify_font underline_thickness 150%', 'modify_font size Test -1px')
    self.ae(opts.modify_font, {
        'underline_position': FontModification(ModificationType.underline_position, ModificationValue(-2., ModificationUnit.pt)),
        'underline_thickness': FontModification(ModificationType.underline_thickness, ModificationValue(150, ModificationUnit.percent)),
        'size:Test': FontModification(ModificationType.size, ModificationValue(-1., ModificationUnit.pixel), 'Test'),
    })

    # test the aliasing options
    opts = p('env A=1', 'env B=x$A', 'env C=', 'env D', 'clear_all_shortcuts y', 'kitten_alias a b --moo', 'map f1 kitten a arg')
    self.ae(opts.env, {'A': '1', 'B': 'x1', 'C': '', 'D': DELETE_ENV_VAR})

    def ac(which=0):
        ka = tuple(opts.keyboard_modes[''].keymap.values())[0][0]
        acs = opts.alias_map.resolve_aliases(ka.definition)
        return acs[which]

    ka = ac()
    self.ae(ka.func, 'kitten')
    self.ae(ka.args, ('b', '--moo', 'arg'))

    opts = p('clear_all_shortcuts y', 'kitten_alias hints hints --hi', 'map f1 kitten hints XXX')
    ka = ac()
    self.ae(ka.func, 'kitten')
    self.ae(ka.args, ('hints', '--hi', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias la launch --moo', 'map f1 la XXX')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('--moo', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias one launch --moo', 'action_alias two one recursive', 'map f1 two XXX')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('--moo', 'recursive', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias launch two 1', 'action_alias two launch 2', 'map f1 launch 3')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('2', '1', '3'))

    opts = p('clear_all_shortcuts y', 'action_alias launch launch --moo', 'map f1 launch XXX')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('--moo', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias cfs change_font_size current', 'map f1 cfs +2')
    ka = ac()
    self.ae(ka.func, 'change_font_size')
    self.ae(ka.args, (False, '+', 2.0))

    opts = p('clear_all_shortcuts y', 'action_alias la launch --moo', 'map f1 combine : new_window : la ')
    self.ae((ac().func, ac(1).func), ('new_window', 'launch'))

    opts = p('clear_all_shortcuts y', 'action_alias cc combine : new_window : launch --moo', 'map f1 cc XXX')
    self.ae((ac().func, ac(1).func), ('new_window', 'launch'))
    self.ae(ac(1).args, ('--moo', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias ss kitten "space 1"', 'map f1 ss "space 2"')
    self.ae(ac().args, ('space 1', 'space 2'))

    opts = p('kitty_mod alt')
    self.ae(opts.kitty_mod, to_modifiers('alt'))
    self.ae(next(keys_for_func(opts, 'next_layout')).mods, opts.kitty_mod)

    # deprecation handling
    opts = p('clear_all_shortcuts y', 'send_text all f1 hello')
    self.ae(len(opts.keyboard_modes[''].keymap), 1)
    opts = p('macos_hide_titlebar y' if is_macos else 'x11_hide_window_decorations y')
    self.assertTrue(opts.hide_window_decorations)
    self.ae(len(self.error_messages), 1)

    # line breaks
    opts = p("    font",
                " \t  \t    \\_size",
                "    \\ 12",
                "\\.35",
                "col",
                "\\o",
                "\t \t\\r",
                "\\25",
                " \\ blue")
    self.ae(opts.font_size, 12.35)
    self.ae(opts.color25, Color(0, 0, 255))

    # cursor_blink_interval
    def cb(src, interval=-1, first=EasingFunction(), second=EasingFunction()):
        opts = p('cursor_blink_interval ' + src)
        self.ae((float(interval), first, second), (float(opts.cursor_blink_interval[0]), opts.cursor_blink_interval[1], opts.cursor_blink_interval[2]))
    cb('3', 3)
    cb('-2.3', -2.3)
    cb('linear', first=EasingFunction('cubic-bezier', cubic_bezier_points=(0, 0.0, 1.0, 1.0)))
    cb('linear 19', 19, EasingFunction('cubic-bezier', cubic_bezier_points=(0, 0.0, 1.0, 1.0)))
    cb('ease-in-out cubic-bezier(0.1, 0.2, 0.3, 0.4) 11', 11,
        EasingFunction('cubic-bezier', cubic_bezier_points=(0.42, 0, 0.58, 1)),
        EasingFunction('cubic-bezier', cubic_bezier_points=(0.1, 0.2, 0.3, 0.4))
    )
    cb('step-start', first=EasingFunction('steps', num_steps=1, jump_type='start'))
    cb('steps(7, jump-none)', first=EasingFunction('steps', num_steps=7, jump_type='none'))
    cb('linear(0, 0.25, 1)', first=EasingFunction('linear', linear_x=(0.0, 0.5, 1.0), linear_y=(0, 0.25, 1.0)))
    cb('linear(0, 0.25 75%, 1)', first=EasingFunction('linear', linear_x=(0.0, 0.75, 1.0), linear_y=(0, 0.25, 1.0)))
    cb('linear(0, 0.25 25% 75%, 1)', first=EasingFunction('linear', linear_x=(0.0, 0.25, 0.75, 1.0), linear_y=(0, 0.25, 0.25, 1.0)))

    # test that easing functions give expected values
    def ef(spec, tests, only_single=True, duration=0.5, accuracy=0):
        cfv = p('cursor_blink_interval ' + spec).cursor_blink_interval
        self.set_options({'cursor_blink_interval': cfv})
        for t, expected in tests.items():
            actual = test_cursor_blink_easing_function(t, only_single, duration)
            if abs(actual - expected) > accuracy:
                self.ae(expected, actual, f'Failed for {spec=} with {t=}: {expected} != {actual}')

    ef('linear', {0:1, 0.25: 0.5, 0.5: 0, 0.75: 0.5, 1: 1}, only_single=False)

    ef('linear(0, 0.25 25% 75%, 1)', {0: 0, 0.25: 0.25, 0.3: 0.25, 0.75: 0.25, 1:1})
    linear_vals = {0: 0, 1: 1, 0.1234: 0.1234, 0.6453: 0.6453}
    for spec in ('linear', 'linear(0, 1)', 'cubic-bezier(0, 0, 1, 1)', 'cubic-bezier(0.2, 0.2, 0.7, 0.7)'):
        ef(spec, linear_vals)
    # test an almost linear function to test cubic bezier implementation
    ef('cubic-bezier(0.2, 0.2, 0.7, 0.71)', linear_vals, accuracy=0.01)
    ef('cubic-bezier(0.23, 0.2, 0.7, 0.71)', linear_vals, accuracy=0.01)

    ef('steps(5)', {0: 0, 0.1: 0, 0.3: 0.2, 0.9:0.8})
    ef('steps(5, start)', {0: 0.2, 0.1: 0.2, 0.3: 0.4, 0.9:1})
    ef('steps(4, jump-both)', {0: 0.2, 0.1: 0.2, 0.3: 0.4, 0.9:1})
    ef('steps(6, jump-none)', {0: 0, 0.1: 0.0, 0.3: 0.2, 0.9:1})

    # test various include modes
    base = os.path.join(self.tdir, 'glob')
    os.mkdir(base)
    with open(os.path.join(base, 'fg'), 'w') as f:
        print('foreground red', file=f)
    opts = p(f'include {f.name}', num_err=0)
    self.ae(opts.foreground, to_color('red'))
    with open(os.path.join(self.tdir, 'bg'), 'w') as f:
        print('background white', file=f)
        print('globinclude glob/*', file=f)
        print('envinclude ENVINCLUDE', file=f)
        print('geninclude g.py', file=f)
        print('geninclude g', file=f)
    with open(os.path.join(self.tdir, 'g.py'), 'w') as g:
        print('print("background_opacity .77")', file=g)
        print('print("background_blur 77")', file=g)
    with open(os.path.join(self.tdir, 'g'), 'w') as g:
        print('#!/bin/sh', file=g)
        print('echo background_image_linear y', file=g)
        print('echo background_image_layout clamped', file=g)
        os.chmod(g.fileno(), 0o700)
    os.environ['ENVINCLUDE'] = 'cursor yellow'
    opts = p(f'include {f.name}', num_err=0)
    os.environ.pop('ENVINCLUDE')
    self.ae(opts.foreground, to_color('red'))
    self.ae(opts.background, to_color('white'))
    self.ae(opts.cursor, to_color('yellow'))
    self.ae(opts.background_opacity, .77)
    self.ae(opts.background_blur, 77)
    self.ae(opts.background_image_linear, True)
    self.ae(opts.background_image_layout, 'clamped')
    with open(os.path.join(self.tdir, 'a'), 'w') as a:
        print('background red', file=a)
        print('include b', file=a)
    with open(os.path.join(self.tdir, 'b'), 'w') as a:
        print('foreground red', file=a)
        print('include a', file=a)
    opts = p(f'include {a.name}', num_err=0, bad_line_num=1)
    self.ae(opts.foreground, to_color('red'))
    self.ae(opts.background, to_color('red'))
