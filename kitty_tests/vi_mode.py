from kitty.fast_data_types import KeyEvent
from kitty.vi_mode import ViMode

from .base import BaseTest


class FakeWindow:
    def __init__(self, screen):
        self.screen = screen
        self.vi_mode = None
        self.copied = None

    def copy_to_clipboard(self):
        self.copied = ''.join(self.screen.text_for_selection(False, True))


def keys(vm, s):
    for ch in s:
        vm.handle_key(KeyEvent(key=ord(ch.lower()), text=ch))


class TestViMode(BaseTest):

    def test_vi_mode(self):
        s = self.create_screen(cols=20, lines=3, scrollback=10)
        for line in ('first line here', 'foo.bar baz', 'hello world', 'abc def', 'last one'):
            s.draw(line); s.carriage_return(); s.linefeed()
        # screen: 'abc def', 'last one', '' ; history: 'hello world','foo.bar baz','first line here'
        w = FakeWindow(s)
        vm = w.vi_mode = ViMode(w)
        self.ae((vm.x, vm.y), (0, 2))
        keys(vm, 'gg')
        self.ae((vm.x, vm.y), (0, -3))
        self.ae(s.scrolled_by, 3)
        keys(vm, 'w'); self.ae((vm.x, vm.y), (6, -3))
        keys(vm, 'w'); self.ae((vm.x, vm.y), (11, -3))
        keys(vm, 'w'); self.ae((vm.x, vm.y), (0, -2))
        keys(vm, 'w'); self.ae((vm.x, vm.y), (3, -2))  # '.'
        keys(vm, 'w'); self.ae((vm.x, vm.y), (4, -2))
        keys(vm, 'b'); self.ae((vm.x, vm.y), (3, -2))
        keys(vm, 'b'); self.ae((vm.x, vm.y), (0, -2))
        keys(vm, 'b'); self.ae((vm.x, vm.y), (11, -3))
        keys(vm, '$'); self.ae((vm.x, vm.y), (14, -3))
        keys(vm, '0vjl$y')
        self.ae(w.copied, 'first line here\nfoo.bar baz')
        self.assertIsNone(w.vi_mode)
        self.ae(s.scrolled_by, 0)
        # visual line, backwards, starting in history
        vm = w.vi_mode = ViMode(w)
        keys(vm, 'kkkllVky')
        self.ae(w.copied, 'foo.bar baz\nhello world')
        vm = w.vi_mode = ViMode(w)
        keys(vm, 'kllvhhy')
        self.ae(w.copied, 'las')
        vm = w.vi_mode = ViMode(w)
        keys(vm, 'G'); self.ae((vm.x, vm.y), (0, 2))
        keys(vm, 'kkkjhhhh'); self.ae((vm.x, vm.y), (0, 0))
