#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial

import kitty.fast_data_types as defines
from kitty.key_encoding import (
    EventType, KeyEvent, decode_key_event, encode_key_event
)

from . import BaseTest


class TestKeys(BaseTest):

    def test_encode_key_event(self):
        enc = defines.encode_key_for_tty
        ae = self.assertEqual
        shift, alt, ctrl, super, hyper, meta = defines.GLFW_MOD_SHIFT, defines.GLFW_MOD_ALT, defines.GLFW_MOD_CONTROL, defines.GLFW_MOD_SUPER, defines.GLFW_MOD_HYPER, defines.GLFW_MOD_META  # noqa
        num_lock, caps_lock = defines.GLFW_MOD_NUM_LOCK, defines.GLFW_MOD_CAPS_LOCK
        press, repeat, release = defines.GLFW_PRESS, defines.GLFW_REPEAT, defines.GLFW_RELEASE  # noqa

        def csi(mods=0, num=1, action=1, shifted_key=0, alternate_key=0, text=None, trailer='u'):
            ans = '\033['
            if isinstance(num, str):
                num = ord(num)
            if num != 1 or mods or shifted_key or alternate_key or text:
                ans += f'{num}'
            if shifted_key or alternate_key:
                if isinstance(shifted_key, str):
                    shifted_key = ord(shifted_key)
                ans += ':' + (f'{shifted_key}' if shifted_key else '')
                if alternate_key:
                    if isinstance(alternate_key, str):
                        alternate_key = ord(alternate_key)
                    ans += f':{alternate_key}'
            if mods or action > 1 or text:
                m = 0
                if mods & shift:
                    m |= 1
                if mods & alt:
                    m |= 2
                if mods & ctrl:
                    m |= 4
                if mods & super:
                    m |= 8
                if mods & hyper:
                    m |= 16
                if mods & meta:
                    m |= 32
                if action > 1 or m:
                    ans += f';{m+1}'
                    if action > 1:
                        ans += f':{action}'
                elif text:
                    ans += ';'
            if text:
                ans += ';' + ':'.join(map(str, map(ord, text)))
            return ans + trailer

        def mods_test(key, plain=None, shift=None, ctrl=None, alt=None, calt=None, cshift=None, ashift=None, csi_num=None, trailer='u'):
            c = partial(csi, num=csi_num or key, trailer=trailer)
            e = partial(enc, key=key)

            def a(a, b):
                ae(a, b, f"{a.encode('ascii')} != {b.encode('ascii')}")

            def w(a, b):
                return c(b) if a is None else a

            a(e(), plain or c())
            a(e(mods=defines.GLFW_MOD_SHIFT), w(shift, defines.GLFW_MOD_SHIFT))
            a(e(mods=defines.GLFW_MOD_CONTROL), w(ctrl, defines.GLFW_MOD_CONTROL))
            a(e(mods=defines.GLFW_MOD_ALT | defines.GLFW_MOD_CONTROL), w(calt, defines.GLFW_MOD_ALT | defines.GLFW_MOD_CONTROL))
            a(e(mods=defines.GLFW_MOD_SHIFT | defines.GLFW_MOD_CONTROL), w(cshift, defines.GLFW_MOD_CONTROL | defines.GLFW_MOD_SHIFT))
            a(e(mods=defines.GLFW_MOD_SHIFT | defines.GLFW_MOD_ALT), w(ashift, defines.GLFW_MOD_ALT | defines.GLFW_MOD_SHIFT))

        def mkp(name, *a, **kw):
            for x in (f'GLFW_FKEY_{name}', f'GLFW_FKEY_KP_{name}'):
                k = getattr(defines, x)
                mods_test(k, *a, **kw)

        mkp('ENTER', '\x0d', alt='\033\x0d', ctrl='\x0d', shift='\x0d', ashift='\033\x0d', calt='\033\x0d', cshift='\x0d')
        mods_test(defines.GLFW_FKEY_ESCAPE, '\x1b', alt='\033\033', ctrl='\x1b', shift='\x1b', calt='\x1b\x1b', cshift='\x1b', ashift='\x1b\x1b')
        mods_test(defines.GLFW_FKEY_BACKSPACE, '\x7f', alt='\033\x7f', ctrl='\x08', shift='\x7f', ashift='\033\x7f', cshift='\x08', calt='\x1b\x08')
        mods_test(defines.GLFW_FKEY_TAB, '\t', alt='\033\t', shift='\x1b[Z', ctrl='\t', ashift='\x1b\x1b[Z', cshift='\x1b[Z', calt='\x1b\t')
        mkp('INSERT', csi_num=2, trailer='~')
        mkp('DELETE', csi_num=3, trailer='~')
        mkp('PAGE_UP', csi_num=5, trailer='~')
        mkp('PAGE_DOWN', csi_num=6, trailer='~')
        mkp('HOME', csi_num=1, trailer='H')
        mkp('END', csi_num=1, trailer='F')
        mods_test(defines.GLFW_FKEY_F1, '\x1bOP', csi_num=1, trailer='P')
        mods_test(defines.GLFW_FKEY_F2, '\x1bOQ', csi_num=1, trailer='Q')
        mods_test(defines.GLFW_FKEY_F3, '\x1bOR', csi_num=1, trailer='R')
        mods_test(defines.GLFW_FKEY_F4, '\x1bOS', csi_num=1, trailer='S')
        mods_test(defines.GLFW_FKEY_F5, csi_num=15, trailer='~')
        mods_test(defines.GLFW_FKEY_F6, csi_num=17, trailer='~')
        mods_test(defines.GLFW_FKEY_F7, csi_num=18, trailer='~')
        mods_test(defines.GLFW_FKEY_F8, csi_num=19, trailer='~')
        mods_test(defines.GLFW_FKEY_F9, csi_num=20, trailer='~')
        mods_test(defines.GLFW_FKEY_F10, csi_num=21, trailer='~')
        mods_test(defines.GLFW_FKEY_F11, csi_num=23, trailer='~')
        mods_test(defines.GLFW_FKEY_F12, csi_num=24, trailer='~')
        mkp('UP', csi_num=1, trailer='A')
        mkp('DOWN', csi_num=1, trailer='B')
        mkp('RIGHT', csi_num=1, trailer='C')
        mkp('LEFT', csi_num=1, trailer='D')

        # legacy key tests {{{
        # start legacy letter tests (auto generated by gen-key-constants.py do not edit)
        ae(enc(ord('`'), shifted_key=ord('~')), '`')
        ae(enc(ord('`'), shifted_key=ord('~'), mods=shift), '~')
        ae(enc(ord('`'), shifted_key=ord('~'), mods=alt), "\x1b" + '`')
        ae(enc(ord('`'), shifted_key=ord('~'), mods=shift | alt), "\x1b" + '~')
        ae(enc(ord('`'), shifted_key=ord('~'), mods=ctrl), '`')
        ae(enc(ord('`'), shifted_key=ord('~'), mods=ctrl | alt), "\x1b" + '`')
        ae(enc(ord('1'), shifted_key=ord('!')), '1')
        ae(enc(ord('1'), shifted_key=ord('!'), mods=shift), '!')
        ae(enc(ord('1'), shifted_key=ord('!'), mods=alt), "\x1b" + '1')
        ae(enc(ord('1'), shifted_key=ord('!'), mods=shift | alt), "\x1b" + '!')
        ae(enc(ord('1'), shifted_key=ord('!'), mods=ctrl), '1')
        ae(enc(ord('1'), shifted_key=ord('!'), mods=ctrl | alt), "\x1b" + '1')
        ae(enc(ord('2'), shifted_key=ord('@')), '2')
        ae(enc(ord('2'), shifted_key=ord('@'), mods=shift), '@')
        ae(enc(ord('2'), shifted_key=ord('@'), mods=alt), "\x1b" + '2')
        ae(enc(ord('2'), shifted_key=ord('@'), mods=shift | alt), "\x1b" + '@')
        ae(enc(ord('2'), shifted_key=ord('@'), mods=ctrl), '\x00')
        ae(enc(ord('2'), shifted_key=ord('@'), mods=ctrl | alt), "\x1b" + '\x00')
        ae(enc(ord('3'), shifted_key=ord('#')), '3')
        ae(enc(ord('3'), shifted_key=ord('#'), mods=shift), '#')
        ae(enc(ord('3'), shifted_key=ord('#'), mods=alt), "\x1b" + '3')
        ae(enc(ord('3'), shifted_key=ord('#'), mods=shift | alt), "\x1b" + '#')
        ae(enc(ord('3'), shifted_key=ord('#'), mods=ctrl), '\x1b')
        ae(enc(ord('3'), shifted_key=ord('#'), mods=ctrl | alt), "\x1b" + '\x1b')
        ae(enc(ord('4'), shifted_key=ord('$')), '4')
        ae(enc(ord('4'), shifted_key=ord('$'), mods=shift), '$')
        ae(enc(ord('4'), shifted_key=ord('$'), mods=alt), "\x1b" + '4')
        ae(enc(ord('4'), shifted_key=ord('$'), mods=shift | alt), "\x1b" + '$')
        ae(enc(ord('4'), shifted_key=ord('$'), mods=ctrl), '\x1c')
        ae(enc(ord('4'), shifted_key=ord('$'), mods=ctrl | alt), "\x1b" + '\x1c')
        ae(enc(ord('5'), shifted_key=ord('%')), '5')
        ae(enc(ord('5'), shifted_key=ord('%'), mods=shift), '%')
        ae(enc(ord('5'), shifted_key=ord('%'), mods=alt), "\x1b" + '5')
        ae(enc(ord('5'), shifted_key=ord('%'), mods=shift | alt), "\x1b" + '%')
        ae(enc(ord('5'), shifted_key=ord('%'), mods=ctrl), '\x1d')
        ae(enc(ord('5'), shifted_key=ord('%'), mods=ctrl | alt), "\x1b" + '\x1d')
        ae(enc(ord('6'), shifted_key=ord('^')), '6')
        ae(enc(ord('6'), shifted_key=ord('^'), mods=shift), '^')
        ae(enc(ord('6'), shifted_key=ord('^'), mods=alt), "\x1b" + '6')
        ae(enc(ord('6'), shifted_key=ord('^'), mods=shift | alt), "\x1b" + '^')
        ae(enc(ord('6'), shifted_key=ord('^'), mods=ctrl), '\x1e')
        ae(enc(ord('6'), shifted_key=ord('^'), mods=ctrl | alt), "\x1b" + '\x1e')
        ae(enc(ord('7'), shifted_key=ord('&')), '7')
        ae(enc(ord('7'), shifted_key=ord('&'), mods=shift), '&')
        ae(enc(ord('7'), shifted_key=ord('&'), mods=alt), "\x1b" + '7')
        ae(enc(ord('7'), shifted_key=ord('&'), mods=shift | alt), "\x1b" + '&')
        ae(enc(ord('7'), shifted_key=ord('&'), mods=ctrl), '\x1f')
        ae(enc(ord('7'), shifted_key=ord('&'), mods=ctrl | alt), "\x1b" + '\x1f')
        ae(enc(ord('8'), shifted_key=ord('*')), '8')
        ae(enc(ord('8'), shifted_key=ord('*'), mods=shift), '*')
        ae(enc(ord('8'), shifted_key=ord('*'), mods=alt), "\x1b" + '8')
        ae(enc(ord('8'), shifted_key=ord('*'), mods=shift | alt), "\x1b" + '*')
        ae(enc(ord('8'), shifted_key=ord('*'), mods=ctrl), '\x7f')
        ae(enc(ord('8'), shifted_key=ord('*'), mods=ctrl | alt), "\x1b" + '\x7f')
        ae(enc(ord('9'), shifted_key=ord('(')), '9')
        ae(enc(ord('9'), shifted_key=ord('('), mods=shift), '(')
        ae(enc(ord('9'), shifted_key=ord('('), mods=alt), "\x1b" + '9')
        ae(enc(ord('9'), shifted_key=ord('('), mods=shift | alt), "\x1b" + '(')
        ae(enc(ord('9'), shifted_key=ord('('), mods=ctrl), '9')
        ae(enc(ord('9'), shifted_key=ord('('), mods=ctrl | alt), "\x1b" + '9')
        ae(enc(ord('0'), shifted_key=ord(')')), '0')
        ae(enc(ord('0'), shifted_key=ord(')'), mods=shift), ')')
        ae(enc(ord('0'), shifted_key=ord(')'), mods=alt), "\x1b" + '0')
        ae(enc(ord('0'), shifted_key=ord(')'), mods=shift | alt), "\x1b" + ')')
        ae(enc(ord('0'), shifted_key=ord(')'), mods=ctrl), '0')
        ae(enc(ord('0'), shifted_key=ord(')'), mods=ctrl | alt), "\x1b" + '0')
        ae(enc(ord('-'), shifted_key=ord('_')), '-')
        ae(enc(ord('-'), shifted_key=ord('_'), mods=shift), '_')
        ae(enc(ord('-'), shifted_key=ord('_'), mods=alt), "\x1b" + '-')
        ae(enc(ord('-'), shifted_key=ord('_'), mods=shift | alt), "\x1b" + '_')
        ae(enc(ord('-'), shifted_key=ord('_'), mods=ctrl), '-')
        ae(enc(ord('-'), shifted_key=ord('_'), mods=ctrl | alt), "\x1b" + '-')
        ae(enc(ord('='), shifted_key=ord('+')), '=')
        ae(enc(ord('='), shifted_key=ord('+'), mods=shift), '+')
        ae(enc(ord('='), shifted_key=ord('+'), mods=alt), "\x1b" + '=')
        ae(enc(ord('='), shifted_key=ord('+'), mods=shift | alt), "\x1b" + '+')
        ae(enc(ord('='), shifted_key=ord('+'), mods=ctrl), '=')
        ae(enc(ord('='), shifted_key=ord('+'), mods=ctrl | alt), "\x1b" + '=')
        ae(enc(ord('['), shifted_key=ord('{')), '[')
        ae(enc(ord('['), shifted_key=ord('{'), mods=shift), '{')
        ae(enc(ord('['), shifted_key=ord('{'), mods=alt), "\x1b" + '[')
        ae(enc(ord('['), shifted_key=ord('{'), mods=shift | alt), "\x1b" + '{')
        ae(enc(ord('['), shifted_key=ord('{'), mods=ctrl), '\x1b')
        ae(enc(ord('['), shifted_key=ord('{'), mods=ctrl | alt), "\x1b" + '\x1b')
        ae(enc(ord(']'), shifted_key=ord('}')), ']')
        ae(enc(ord(']'), shifted_key=ord('}'), mods=shift), '}')
        ae(enc(ord(']'), shifted_key=ord('}'), mods=alt), "\x1b" + ']')
        ae(enc(ord(']'), shifted_key=ord('}'), mods=shift | alt), "\x1b" + '}')
        ae(enc(ord(']'), shifted_key=ord('}'), mods=ctrl), '\x1d')
        ae(enc(ord(']'), shifted_key=ord('}'), mods=ctrl | alt), "\x1b" + '\x1d')
        ae(enc(ord('\\'), shifted_key=ord('|')), '\\')
        ae(enc(ord('\\'), shifted_key=ord('|'), mods=shift), '|')
        ae(enc(ord('\\'), shifted_key=ord('|'), mods=alt), "\x1b" + '\\')
        ae(enc(ord('\\'), shifted_key=ord('|'), mods=shift | alt), "\x1b" + '|')
        ae(enc(ord('\\'), shifted_key=ord('|'), mods=ctrl), '\x1c')
        ae(enc(ord('\\'), shifted_key=ord('|'), mods=ctrl | alt), "\x1b" + '\x1c')
        ae(enc(ord(';'), shifted_key=ord(':')), ';')
        ae(enc(ord(';'), shifted_key=ord(':'), mods=shift), ':')
        ae(enc(ord(';'), shifted_key=ord(':'), mods=alt), "\x1b" + ';')
        ae(enc(ord(';'), shifted_key=ord(':'), mods=shift | alt), "\x1b" + ':')
        ae(enc(ord(';'), shifted_key=ord(':'), mods=ctrl), ';')
        ae(enc(ord(';'), shifted_key=ord(':'), mods=ctrl | alt), "\x1b" + ';')
        ae(enc(ord("'"), shifted_key=ord('"')), "'")
        ae(enc(ord("'"), shifted_key=ord('"'), mods=shift), '"')
        ae(enc(ord("'"), shifted_key=ord('"'), mods=alt), "\x1b" + "'")
        ae(enc(ord("'"), shifted_key=ord('"'), mods=shift | alt), "\x1b" + '"')
        ae(enc(ord("'"), shifted_key=ord('"'), mods=ctrl), "'")
        ae(enc(ord("'"), shifted_key=ord('"'), mods=ctrl | alt), "\x1b" + "'")
        ae(enc(ord(','), shifted_key=ord('<')), ',')
        ae(enc(ord(','), shifted_key=ord('<'), mods=shift), '<')
        ae(enc(ord(','), shifted_key=ord('<'), mods=alt), "\x1b" + ',')
        ae(enc(ord(','), shifted_key=ord('<'), mods=shift | alt), "\x1b" + '<')
        ae(enc(ord(','), shifted_key=ord('<'), mods=ctrl), ',')
        ae(enc(ord(','), shifted_key=ord('<'), mods=ctrl | alt), "\x1b" + ',')
        ae(enc(ord('.'), shifted_key=ord('>')), '.')
        ae(enc(ord('.'), shifted_key=ord('>'), mods=shift), '>')
        ae(enc(ord('.'), shifted_key=ord('>'), mods=alt), "\x1b" + '.')
        ae(enc(ord('.'), shifted_key=ord('>'), mods=shift | alt), "\x1b" + '>')
        ae(enc(ord('.'), shifted_key=ord('>'), mods=ctrl), '.')
        ae(enc(ord('.'), shifted_key=ord('>'), mods=ctrl | alt), "\x1b" + '.')
        ae(enc(ord('/'), shifted_key=ord('?')), '/')
        ae(enc(ord('/'), shifted_key=ord('?'), mods=shift), '?')
        ae(enc(ord('/'), shifted_key=ord('?'), mods=alt), "\x1b" + '/')
        ae(enc(ord('/'), shifted_key=ord('?'), mods=shift | alt), "\x1b" + '?')
        ae(enc(ord('/'), shifted_key=ord('?'), mods=ctrl), '\x1f')
        ae(enc(ord('/'), shifted_key=ord('?'), mods=ctrl | alt), "\x1b" + '\x1f')
        ae(enc(ord('a'), shifted_key=ord('A')), 'a')
        ae(enc(ord('a'), shifted_key=ord('A'), mods=shift), 'A')
        ae(enc(ord('a'), shifted_key=ord('A'), mods=alt), "\x1b" + 'a')
        ae(enc(ord('a'), shifted_key=ord('A'), mods=shift | alt), "\x1b" + 'A')
        ae(enc(ord('a'), shifted_key=ord('A'), mods=ctrl), '\x01')
        ae(enc(ord('a'), shifted_key=ord('A'), mods=ctrl | alt), "\x1b" + '\x01')
        ae(enc(ord('b'), shifted_key=ord('B')), 'b')
        ae(enc(ord('b'), shifted_key=ord('B'), mods=shift), 'B')
        ae(enc(ord('b'), shifted_key=ord('B'), mods=alt), "\x1b" + 'b')
        ae(enc(ord('b'), shifted_key=ord('B'), mods=shift | alt), "\x1b" + 'B')
        ae(enc(ord('b'), shifted_key=ord('B'), mods=ctrl), '\x02')
        ae(enc(ord('b'), shifted_key=ord('B'), mods=ctrl | alt), "\x1b" + '\x02')
        ae(enc(ord('c'), shifted_key=ord('C')), 'c')
        ae(enc(ord('c'), shifted_key=ord('C'), mods=shift), 'C')
        ae(enc(ord('c'), shifted_key=ord('C'), mods=alt), "\x1b" + 'c')
        ae(enc(ord('c'), shifted_key=ord('C'), mods=shift | alt), "\x1b" + 'C')
        ae(enc(ord('c'), shifted_key=ord('C'), mods=ctrl), '\x03')
        ae(enc(ord('c'), shifted_key=ord('C'), mods=ctrl | alt), "\x1b" + '\x03')
        ae(enc(ord('d'), shifted_key=ord('D')), 'd')
        ae(enc(ord('d'), shifted_key=ord('D'), mods=shift), 'D')
        ae(enc(ord('d'), shifted_key=ord('D'), mods=alt), "\x1b" + 'd')
        ae(enc(ord('d'), shifted_key=ord('D'), mods=shift | alt), "\x1b" + 'D')
        ae(enc(ord('d'), shifted_key=ord('D'), mods=ctrl), '\x04')
        ae(enc(ord('d'), shifted_key=ord('D'), mods=ctrl | alt), "\x1b" + '\x04')
        ae(enc(ord('e'), shifted_key=ord('E')), 'e')
        ae(enc(ord('e'), shifted_key=ord('E'), mods=shift), 'E')
        ae(enc(ord('e'), shifted_key=ord('E'), mods=alt), "\x1b" + 'e')
        ae(enc(ord('e'), shifted_key=ord('E'), mods=shift | alt), "\x1b" + 'E')
        ae(enc(ord('e'), shifted_key=ord('E'), mods=ctrl), '\x05')
        ae(enc(ord('e'), shifted_key=ord('E'), mods=ctrl | alt), "\x1b" + '\x05')
        ae(enc(ord('f'), shifted_key=ord('F')), 'f')
        ae(enc(ord('f'), shifted_key=ord('F'), mods=shift), 'F')
        ae(enc(ord('f'), shifted_key=ord('F'), mods=alt), "\x1b" + 'f')
        ae(enc(ord('f'), shifted_key=ord('F'), mods=shift | alt), "\x1b" + 'F')
        ae(enc(ord('f'), shifted_key=ord('F'), mods=ctrl), '\x06')
        ae(enc(ord('f'), shifted_key=ord('F'), mods=ctrl | alt), "\x1b" + '\x06')
        ae(enc(ord('g'), shifted_key=ord('G')), 'g')
        ae(enc(ord('g'), shifted_key=ord('G'), mods=shift), 'G')
        ae(enc(ord('g'), shifted_key=ord('G'), mods=alt), "\x1b" + 'g')
        ae(enc(ord('g'), shifted_key=ord('G'), mods=shift | alt), "\x1b" + 'G')
        ae(enc(ord('g'), shifted_key=ord('G'), mods=ctrl), '\x07')
        ae(enc(ord('g'), shifted_key=ord('G'), mods=ctrl | alt), "\x1b" + '\x07')
        ae(enc(ord('h'), shifted_key=ord('H')), 'h')
        ae(enc(ord('h'), shifted_key=ord('H'), mods=shift), 'H')
        ae(enc(ord('h'), shifted_key=ord('H'), mods=alt), "\x1b" + 'h')
        ae(enc(ord('h'), shifted_key=ord('H'), mods=shift | alt), "\x1b" + 'H')
        ae(enc(ord('h'), shifted_key=ord('H'), mods=ctrl), '\x08')
        ae(enc(ord('h'), shifted_key=ord('H'), mods=ctrl | alt), "\x1b" + '\x08')
        ae(enc(ord('i'), shifted_key=ord('I')), 'i')
        ae(enc(ord('i'), shifted_key=ord('I'), mods=shift), 'I')
        ae(enc(ord('i'), shifted_key=ord('I'), mods=alt), "\x1b" + 'i')
        ae(enc(ord('i'), shifted_key=ord('I'), mods=shift | alt), "\x1b" + 'I')
        ae(enc(ord('i'), shifted_key=ord('I'), mods=ctrl), '\t')
        ae(enc(ord('i'), shifted_key=ord('I'), mods=ctrl | alt), "\x1b" + '\t')
        ae(enc(ord('j'), shifted_key=ord('J')), 'j')
        ae(enc(ord('j'), shifted_key=ord('J'), mods=shift), 'J')
        ae(enc(ord('j'), shifted_key=ord('J'), mods=alt), "\x1b" + 'j')
        ae(enc(ord('j'), shifted_key=ord('J'), mods=shift | alt), "\x1b" + 'J')
        ae(enc(ord('j'), shifted_key=ord('J'), mods=ctrl), '\n')
        ae(enc(ord('j'), shifted_key=ord('J'), mods=ctrl | alt), "\x1b" + '\n')
        ae(enc(ord('k'), shifted_key=ord('K')), 'k')
        ae(enc(ord('k'), shifted_key=ord('K'), mods=shift), 'K')
        ae(enc(ord('k'), shifted_key=ord('K'), mods=alt), "\x1b" + 'k')
        ae(enc(ord('k'), shifted_key=ord('K'), mods=shift | alt), "\x1b" + 'K')
        ae(enc(ord('k'), shifted_key=ord('K'), mods=ctrl), '\x0b')
        ae(enc(ord('k'), shifted_key=ord('K'), mods=ctrl | alt), "\x1b" + '\x0b')
        ae(enc(ord('l'), shifted_key=ord('L')), 'l')
        ae(enc(ord('l'), shifted_key=ord('L'), mods=shift), 'L')
        ae(enc(ord('l'), shifted_key=ord('L'), mods=alt), "\x1b" + 'l')
        ae(enc(ord('l'), shifted_key=ord('L'), mods=shift | alt), "\x1b" + 'L')
        ae(enc(ord('l'), shifted_key=ord('L'), mods=ctrl), '\x0c')
        ae(enc(ord('l'), shifted_key=ord('L'), mods=ctrl | alt), "\x1b" + '\x0c')
        ae(enc(ord('m'), shifted_key=ord('M')), 'm')
        ae(enc(ord('m'), shifted_key=ord('M'), mods=shift), 'M')
        ae(enc(ord('m'), shifted_key=ord('M'), mods=alt), "\x1b" + 'm')
        ae(enc(ord('m'), shifted_key=ord('M'), mods=shift | alt), "\x1b" + 'M')
        ae(enc(ord('m'), shifted_key=ord('M'), mods=ctrl), '\r')
        ae(enc(ord('m'), shifted_key=ord('M'), mods=ctrl | alt), "\x1b" + '\r')
        ae(enc(ord('n'), shifted_key=ord('N')), 'n')
        ae(enc(ord('n'), shifted_key=ord('N'), mods=shift), 'N')
        ae(enc(ord('n'), shifted_key=ord('N'), mods=alt), "\x1b" + 'n')
        ae(enc(ord('n'), shifted_key=ord('N'), mods=shift | alt), "\x1b" + 'N')
        ae(enc(ord('n'), shifted_key=ord('N'), mods=ctrl), '\x0e')
        ae(enc(ord('n'), shifted_key=ord('N'), mods=ctrl | alt), "\x1b" + '\x0e')
        ae(enc(ord('o'), shifted_key=ord('O')), 'o')
        ae(enc(ord('o'), shifted_key=ord('O'), mods=shift), 'O')
        ae(enc(ord('o'), shifted_key=ord('O'), mods=alt), "\x1b" + 'o')
        ae(enc(ord('o'), shifted_key=ord('O'), mods=shift | alt), "\x1b" + 'O')
        ae(enc(ord('o'), shifted_key=ord('O'), mods=ctrl), '\x0f')
        ae(enc(ord('o'), shifted_key=ord('O'), mods=ctrl | alt), "\x1b" + '\x0f')
        ae(enc(ord('p'), shifted_key=ord('P')), 'p')
        ae(enc(ord('p'), shifted_key=ord('P'), mods=shift), 'P')
        ae(enc(ord('p'), shifted_key=ord('P'), mods=alt), "\x1b" + 'p')
        ae(enc(ord('p'), shifted_key=ord('P'), mods=shift | alt), "\x1b" + 'P')
        ae(enc(ord('p'), shifted_key=ord('P'), mods=ctrl), '\x10')
        ae(enc(ord('p'), shifted_key=ord('P'), mods=ctrl | alt), "\x1b" + '\x10')
        ae(enc(ord('q'), shifted_key=ord('Q')), 'q')
        ae(enc(ord('q'), shifted_key=ord('Q'), mods=shift), 'Q')
        ae(enc(ord('q'), shifted_key=ord('Q'), mods=alt), "\x1b" + 'q')
        ae(enc(ord('q'), shifted_key=ord('Q'), mods=shift | alt), "\x1b" + 'Q')
        ae(enc(ord('q'), shifted_key=ord('Q'), mods=ctrl), '\x11')
        ae(enc(ord('q'), shifted_key=ord('Q'), mods=ctrl | alt), "\x1b" + '\x11')
        ae(enc(ord('r'), shifted_key=ord('R')), 'r')
        ae(enc(ord('r'), shifted_key=ord('R'), mods=shift), 'R')
        ae(enc(ord('r'), shifted_key=ord('R'), mods=alt), "\x1b" + 'r')
        ae(enc(ord('r'), shifted_key=ord('R'), mods=shift | alt), "\x1b" + 'R')
        ae(enc(ord('r'), shifted_key=ord('R'), mods=ctrl), '\x12')
        ae(enc(ord('r'), shifted_key=ord('R'), mods=ctrl | alt), "\x1b" + '\x12')
        ae(enc(ord('s'), shifted_key=ord('S')), 's')
        ae(enc(ord('s'), shifted_key=ord('S'), mods=shift), 'S')
        ae(enc(ord('s'), shifted_key=ord('S'), mods=alt), "\x1b" + 's')
        ae(enc(ord('s'), shifted_key=ord('S'), mods=shift | alt), "\x1b" + 'S')
        ae(enc(ord('s'), shifted_key=ord('S'), mods=ctrl), '\x13')
        ae(enc(ord('s'), shifted_key=ord('S'), mods=ctrl | alt), "\x1b" + '\x13')
        ae(enc(ord('t'), shifted_key=ord('T')), 't')
        ae(enc(ord('t'), shifted_key=ord('T'), mods=shift), 'T')
        ae(enc(ord('t'), shifted_key=ord('T'), mods=alt), "\x1b" + 't')
        ae(enc(ord('t'), shifted_key=ord('T'), mods=shift | alt), "\x1b" + 'T')
        ae(enc(ord('t'), shifted_key=ord('T'), mods=ctrl), '\x14')
        ae(enc(ord('t'), shifted_key=ord('T'), mods=ctrl | alt), "\x1b" + '\x14')
        ae(enc(ord('u'), shifted_key=ord('U')), 'u')
        ae(enc(ord('u'), shifted_key=ord('U'), mods=shift), 'U')
        ae(enc(ord('u'), shifted_key=ord('U'), mods=alt), "\x1b" + 'u')
        ae(enc(ord('u'), shifted_key=ord('U'), mods=shift | alt), "\x1b" + 'U')
        ae(enc(ord('u'), shifted_key=ord('U'), mods=ctrl), '\x15')
        ae(enc(ord('u'), shifted_key=ord('U'), mods=ctrl | alt), "\x1b" + '\x15')
        ae(enc(ord('v'), shifted_key=ord('V')), 'v')
        ae(enc(ord('v'), shifted_key=ord('V'), mods=shift), 'V')
        ae(enc(ord('v'), shifted_key=ord('V'), mods=alt), "\x1b" + 'v')
        ae(enc(ord('v'), shifted_key=ord('V'), mods=shift | alt), "\x1b" + 'V')
        ae(enc(ord('v'), shifted_key=ord('V'), mods=ctrl), '\x16')
        ae(enc(ord('v'), shifted_key=ord('V'), mods=ctrl | alt), "\x1b" + '\x16')
        ae(enc(ord('w'), shifted_key=ord('W')), 'w')
        ae(enc(ord('w'), shifted_key=ord('W'), mods=shift), 'W')
        ae(enc(ord('w'), shifted_key=ord('W'), mods=alt), "\x1b" + 'w')
        ae(enc(ord('w'), shifted_key=ord('W'), mods=shift | alt), "\x1b" + 'W')
        ae(enc(ord('w'), shifted_key=ord('W'), mods=ctrl), '\x17')
        ae(enc(ord('w'), shifted_key=ord('W'), mods=ctrl | alt), "\x1b" + '\x17')
        ae(enc(ord('x'), shifted_key=ord('X')), 'x')
        ae(enc(ord('x'), shifted_key=ord('X'), mods=shift), 'X')
        ae(enc(ord('x'), shifted_key=ord('X'), mods=alt), "\x1b" + 'x')
        ae(enc(ord('x'), shifted_key=ord('X'), mods=shift | alt), "\x1b" + 'X')
        ae(enc(ord('x'), shifted_key=ord('X'), mods=ctrl), '\x18')
        ae(enc(ord('x'), shifted_key=ord('X'), mods=ctrl | alt), "\x1b" + '\x18')
        ae(enc(ord('y'), shifted_key=ord('Y')), 'y')
        ae(enc(ord('y'), shifted_key=ord('Y'), mods=shift), 'Y')
        ae(enc(ord('y'), shifted_key=ord('Y'), mods=alt), "\x1b" + 'y')
        ae(enc(ord('y'), shifted_key=ord('Y'), mods=shift | alt), "\x1b" + 'Y')
        ae(enc(ord('y'), shifted_key=ord('Y'), mods=ctrl), '\x19')
        ae(enc(ord('y'), shifted_key=ord('Y'), mods=ctrl | alt), "\x1b" + '\x19')
        ae(enc(ord('z'), shifted_key=ord('Z')), 'z')
        ae(enc(ord('z'), shifted_key=ord('Z'), mods=shift), 'Z')
        ae(enc(ord('z'), shifted_key=ord('Z'), mods=alt), "\x1b" + 'z')
        ae(enc(ord('z'), shifted_key=ord('Z'), mods=shift | alt), "\x1b" + 'Z')
        ae(enc(ord('z'), shifted_key=ord('Z'), mods=ctrl), '\x1a')
        ae(enc(ord('z'), shifted_key=ord('Z'), mods=ctrl | alt), "\x1b" + '\x1a')
# end legacy letter tests
        # }}}

        ae(enc(key=ord(':'), shifted_key=ord('/'), mods=shift | alt), '\x1b/')
        for key in '~!@#$%^&*()_+{}|:"<>?':
            ae(enc(key=ord(key), mods=alt), '\x1b' + key)
        ae(enc(key=ord(' ')), ' ')
        ae(enc(key=ord(' '), mods=ctrl | num_lock | caps_lock), '\0')
        ae(enc(key=ord(' '), mods=ctrl), '\0')
        ae(enc(key=ord(' '), mods=alt), '\x1b ')
        ae(enc(key=ord(' '), mods=shift), ' ')
        ae(enc(key=ord(' '), mods=ctrl | alt), '\x1b\0')
        ae(enc(key=ord(' '), mods=ctrl | shift), '\0')
        ae(enc(key=ord(' '), mods=alt | shift), '\x1b ')
        ae(enc(key=ord('i'), mods=ctrl | shift), csi(ctrl | shift, ord('i')))
        ae(enc(key=defines.GLFW_FKEY_LEFT_SHIFT), '')
        ae(enc(key=defines.GLFW_FKEY_CAPS_LOCK), '')

        q = partial(enc, key=ord('a'))
        ae(q(), 'a')
        ae(q(text='a'), 'a')
        ae(q(action=repeat), 'a')
        ae(q(action=release), '')

        # test disambiguate
        dq = partial(enc, key_encoding_flags=0b1)
        ae(dq(ord('a')), 'a')
        ae(dq(defines.GLFW_FKEY_ESCAPE), csi(num=27))
        ae(dq(defines.GLFW_FKEY_ENTER), '\r')
        ae(dq(defines.GLFW_FKEY_ENTER, mods=shift), csi(shift, 13))
        ae(dq(defines.GLFW_FKEY_TAB), '\t')
        ae(dq(defines.GLFW_FKEY_BACKSPACE), '\x7f')
        ae(dq(defines.GLFW_FKEY_TAB, mods=shift), csi(shift, 9))
        for mods in (ctrl, alt, ctrl | shift, alt | shift):
            ae(dq(ord('a'), mods=mods), csi(mods, ord('a')))
        ae(dq(ord(' '), mods=ctrl), csi(ctrl, ord(' ')))
        for k in (defines.GLFW_FKEY_KP_PAGE_UP, defines.GLFW_FKEY_KP_0):
            ae(dq(k), csi(num=k))
            ae(dq(k, mods=ctrl), csi(ctrl, num=k))
        ae(dq(defines.GLFW_FKEY_UP), '\x1b[A')
        ae(dq(defines.GLFW_FKEY_UP, mods=ctrl), csi(ctrl, 1, trailer='A'))

        # test event type reporting
        tq = partial(enc, key_encoding_flags=0b10)
        ae(tq(ord('a')), 'a')
        ae(tq(ord('a'), action=defines.GLFW_REPEAT), csi(num='a', action=2))
        ae(tq(ord('a'), action=defines.GLFW_RELEASE), csi(num='a', action=3))
        ae(tq(ord('a'), action=defines.GLFW_RELEASE, mods=shift), csi(shift, num='a', action=3))

        # test alternate key reporting
        aq = partial(enc, key_encoding_flags=0b100)
        ae(aq(ord('a')), 'a')
        ae(aq(ord('a'), shifted_key=ord('A')), 'a')
        ae(aq(ord('a'), mods=shift, shifted_key=ord('A')), csi(shift, 'a', shifted_key='A'))
        ae(aq(ord('a'), alternate_key=ord('A')), csi(num='a', alternate_key='A'))
        ae(aq(ord('a'), mods=shift, shifted_key=ord('A'), alternate_key=ord('b')), csi(shift, 'a', shifted_key='A', alternate_key='b'))

        # test report all keys
        kq = partial(enc, key_encoding_flags=0b1000)
        ae(kq(ord('a')), csi(num='a'))
        ae(kq(ord('a'), action=defines.GLFW_REPEAT), csi(num='a'))
        ae(kq(ord('a'), mods=ctrl), csi(ctrl, num='a'))
        ae(kq(defines.GLFW_FKEY_UP), '\x1b[A')
        ae(kq(defines.GLFW_FKEY_LEFT_SHIFT), csi(num=defines.GLFW_FKEY_LEFT_SHIFT))
        ae(kq(defines.GLFW_FKEY_ENTER), '\x1b[13u')
        ae(kq(defines.GLFW_FKEY_TAB), '\x1b[9u')
        ae(kq(defines.GLFW_FKEY_BACKSPACE), '\x1b[127u')

        # test embed text
        eq = partial(enc, key_encoding_flags=0b11000)
        ae(eq(ord('a'), text='a'), csi(num='a', text='a'))
        ae(eq(ord('a'), mods=shift, text='A'), csi(shift, num='a', text='A'))
        ae(eq(ord('a'), mods=shift, text='AB'), csi(shift, num='a', text='AB'))

        # test roundtripping via KeyEvent
        for mods in range(64):
            for action in EventType:
                for key in ('ENTER', 'a', 'TAB', 'F3'):
                    for shifted_key in ('', 'X'):
                        for alternate_key in ('', 'Y'):
                            for text in ('', 'moose'):
                                ev = KeyEvent(
                                    type=action, mods=mods, key=key, text=text, shifted_key=shifted_key, alternate_key=alternate_key,
                                    shift=bool(mods & 1), alt=bool(mods & 2), ctrl=bool(mods & 4), super=bool(mods & 8),
                                    hyper=bool(mods & 16), meta=bool(mods & 32)
                                )
                                ec = encode_key_event(ev)
                                q = decode_key_event(ec[2:-1], ec[-1])
                                self.ae(ev, q)

    def test_encode_mouse_event(self):
        NORMAL_PROTOCOL, UTF8_PROTOCOL, SGR_PROTOCOL, URXVT_PROTOCOL = range(4)
        L, M, R = 1, 2, 3
        protocol = SGR_PROTOCOL

        def enc(button=L, action=defines.PRESS, mods=0, x=1, y=1):
            return defines.test_encode_mouse(x, y, protocol, button, action, mods)

        self.ae(enc(), '<0;1;1M')
        self.ae(enc(action=defines.RELEASE), '<0;1;1m')
        self.ae(enc(action=defines.MOVE), '<35;1;1M')
        self.ae(enc(action=defines.DRAG), '<32;1;1M')

        self.ae(enc(R), '<2;1;1M')
        self.ae(enc(R, action=defines.RELEASE), '<2;1;1m')
        self.ae(enc(R, action=defines.DRAG), '<34;1;1M')

        self.ae(enc(M), '<1;1;1M')
        self.ae(enc(M, action=defines.RELEASE), '<1;1;1m')
        self.ae(enc(M, action=defines.DRAG), '<33;1;1M')

        self.ae(enc(x=1234, y=5678), '<0;1234;5678M')
        self.ae(enc(mods=defines.GLFW_MOD_SHIFT), '<4;1;1M')
        self.ae(enc(mods=defines.GLFW_MOD_ALT), '<8;1;1M')
        self.ae(enc(mods=defines.GLFW_MOD_CONTROL), '<16;1;1M')
