#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import kitty.fast_data_types as defines
from . import BaseTest


class TestKeys(BaseTest):

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
