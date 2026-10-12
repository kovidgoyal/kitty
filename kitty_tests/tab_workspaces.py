#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from kitty.launch import find_existing, launch, parse_launch_args
from kitty.options.utils import detach_window_parse
from kitty.rc.base import MatchError, PayloadGetter
from kitty.rc.detach_window import detach_window
from kitty.tabs import index_for_new_tab
from kitty.utils import natsort_ints, natsort_key
from kitty.window import Window

from .base import BaseTest


def fake_window(wid: int, title: str = '', tab: object = None) -> MagicMock:
    w = MagicMock(spec=Window)
    w.id, w.title = wid, title
    w.child, w.ignore_focus_changes = None, False
    w.tabref = Mock(return_value=tab)
    return w


class FakeTab:
    def __init__(self, tid: int, title: str, windows: tuple[MagicMock, ...] = ()):
        self.id, self.effective_title, self.windows = tid, title, windows
        self.active_window = windows[0] if windows else None
        self.tab_manager_ref = Mock(return_value=None)
        for w in windows:
            w.tabref.return_value = self

    def __iter__(self):
        return iter(self.windows)


class FakeBoss:
    def __init__(self, tabs: list[FakeTab], active_window: MagicMock | None = None):
        self.tabs = tabs
        self.active_window = self.active_window_for_cwd = active_window
        self.active_tab = tabs[0] if tabs else None
        # the tab bar of the active OS Window, shows all tabs unless a test hides some
        self.active_tab_manager = SimpleNamespace(tabs_to_be_shown_in_tab_bar=list(tabs))
        self.set_active_window = Mock()
        self.match_tabs = Mock(side_effect=lambda q: iter(()))
        self.match_windows = Mock(side_effect=lambda q, w=None: iter(()))
        self._move_window_to = Mock()

    @property
    def all_tabs(self):
        return iter(self.tabs)

    @property
    def all_windows(self):
        for t in self.tabs:
            yield from t.windows


class TestTabWorkspaces(BaseTest):
    def test_index_for_new_tab(self):
        titles = ('a', 'c', 'e')
        for location, active, title, expected in (
            ('last', 1, '', 3),
            ('default', 1, '', 3),
            ('first', 1, '', 0),
            ('before', 1, '', 1),
            ('after', 1, '', 2),
            ('neighbor', 2, '', 3),
            ('by-title', 0, 'b', 1),
            ('by-title', 0, '0', 0),
            ('by-title', 0, 'c', 2),
            ('by-title', 0, 'z', 3),
            ('by-title', 0, '', 3),
        ):
            with self.subTest(location=location, active=active, title=title):
                self.ae(index_for_new_tab(titles, active, location, title), expected)
        self.ae(index_for_new_tab((), 0, 'by-title', 'x'), 0)
        self.ae(index_for_new_tab((), 0, 'after'), 0)
        # natural, case insensitive ordering
        titles = ('1', '2', '9', '10', 'apple', 'Banana', 'tab 2', 'tab 10')
        for title, expected in (('3', 2), ('11', 4), ('0', 0), ('avocado', 5), ('blueberry', 6), ('tab 3', 7), ('tab 11', 8), ('Apple', 4)):
            with self.subTest(title=title):
                self.ae(index_for_new_tab(titles, 0, 'by-title', title), expected)

    def test_natsort(self):
        self.ae(natsort_ints(['10', '9', 'a2', 'a10', 'a1b', '²', '']), ['', '9', '10', 'a1b', 'a2', 'a10', '²'])
        self.ae(sorted(['b', 'A', 'a', 'B'], key=lambda x: (natsort_key(x, case_sensitive=False), x)), ['A', 'a', 'B', 'b'])

    def test_find_existing(self):
        w1, w2 = fake_window(1, 'one'), fake_window(2, 'two')
        t1, t2 = FakeTab(1, 'x', (w1,)), FakeTab(2, 'y', (w2,))
        boss = FakeBoss([t1, t2], w1)

        tm = boss.active_tab_manager

        def opts(*args: str):
            return parse_launch_args(list(args))[0]

        def find(*args: str):
            return find_existing(boss, opts(*args), None, tm)  # type: ignore[arg-type]

        self.assertIs(find('--type=tab', '--tab-title=y', '--focus-existing=@title'), t2)
        self.assertIsNone(find('--type=tab', '--tab-title=z', '--focus-existing=@title'))
        self.assertIs(find('--window-title=two', '--focus-existing=@title'), w2)
        self.assertIsNone(find('--window-title=tw', '--focus-existing=@title'))
        with self.assertRaises(ValueError):
            find('--type=tab', '--focus-existing=@title')
        with self.assertRaises(ValueError):
            find('--type=overlay', '--focus-existing=@title')
        # @title ignores tabs not shown in the tab bar, for example, ones hidden by tab_bar_filter
        tm.tabs_to_be_shown_in_tab_bar = [t1]
        self.assertIsNone(find('--type=tab', '--tab-title=y', '--focus-existing=@title'))
        self.assertIsNone(find('--window-title=two', '--focus-existing=@title'))
        # but os-window considers windows everywhere
        self.assertIs(find('--type=os-window', '--window-title=two', '--focus-existing=@title'), w2)
        tm.tabs_to_be_shown_in_tab_bar = [t1, t2]
        boss.match_tabs.side_effect = lambda q: iter((t1,))
        self.assertIs(find_existing(boss, opts('--type=tab', '--focus-existing=title:x')), t1)
        boss.match_tabs.assert_called_with('title:x')
        boss.match_windows.side_effect = lambda q, w=None: iter((w2,))
        self.assertIs(find_existing(boss, opts('--type=os-window', '--focus-existing=title:two')), w2)

    def test_launch_focus_existing(self):
        w1, w2 = fake_window(1, 'one'), fake_window(2, 'two')
        t1, t2 = FakeTab(1, 'x', (w1,)), FakeTab(2, 'y', (w2,))
        boss = FakeBoss([t1, t2], w1)

        def run(*args: str):
            boss.set_active_window.reset_mock()
            o, a = parse_launch_args(list(args))
            return launch(boss, o, a)  # type: ignore[arg-type]

        self.assertIs(run('--type=tab', '--tab-title=y', '--focus-existing=@title'), w2)
        boss.set_active_window.assert_called_once_with(w2, switch_os_window_if_needed=True)
        self.assertIs(run('--type=window', '--window-title=two', '--focus-existing=@title'), w2)
        boss.set_active_window.assert_called_once_with(w2, switch_os_window_if_needed=True)
        self.assertIs(run('--type=tab', '--tab-title=y', '--focus-existing=@title', '--keep-focus'), w2)
        boss.set_active_window.assert_not_called()
        # tab hidden from the tab bar is not focused, a new tab would be created instead
        boss.active_tab_manager.tabs_to_be_shown_in_tab_bar = [t1]
        o, _ = parse_launch_args(['--type=tab', '--tab-title=y', '--focus-existing=@title'])
        self.assertIsNone(find_existing(boss, o, None, boss.active_tab_manager))  # type: ignore[arg-type]

    def test_detach_window_parse(self):
        self.ae(detach_window_parse('detach_window', 'new-tab'), ('detach_window', ('new-tab',)))
        self.ae(
            detach_window_parse('detach_window', '--target-tab=@title --tab-title="a b" --create-if-missing'),
            ('detach_window', ['--target-tab=@title', '--tab-title=a b', '--create-if-missing']),
        )

    def test_rc_detach_window_to_named_tab(self):
        w1, w2, w3 = fake_window(1), fake_window(2), fake_window(3)
        t1, t2 = FakeTab(1, 'x', (w1, w3)), FakeTab(2, 'y', (w2,))
        boss = FakeBoss([t1, t2], w1)

        def run(**payload: object) -> None:
            boss._move_window_to.reset_mock()
            detach_window.response_from_kitty(boss, w1, PayloadGetter(detach_window, payload))  # type: ignore[arg-type]

        run(target_tab='@title', tab_title='y')
        boss._move_window_to.assert_called_once_with(window=w1, target_tab_id=2, new_tab_title='y', new_tab_location='default')
        # tabs hidden from the tab bar are not targets for @title
        boss.active_tab_manager.tabs_to_be_shown_in_tab_bar = [t1]
        with self.assertRaisesRegex(MatchError, "No tab with the title 'y' exists"):
            run(target_tab='@title', tab_title='y')
        boss.active_tab_manager.tabs_to_be_shown_in_tab_bar = [t1, t2]
        # moving into the tab the window is already in is a no-op
        run(target_tab='@title', tab_title='x')
        boss._move_window_to.assert_not_called()
        with self.assertRaisesRegex(MatchError, "No tab with the title 'z' exists. Use --create-if-missing"):
            run(target_tab='@title', tab_title='z')
        with self.assertRaisesRegex(MatchError, "No tab matches the expression 'title:q'"):
            run(target_tab='title:q')
        with self.assertRaises(ValueError):
            run(target_tab='@title')
        run(target_tab='@title', tab_title='z', create_if_missing=True, location='by-title')
        boss._move_window_to.assert_called_once_with(window=w1, target_tab_id='new', new_tab_title='z', new_tab_location='by-title')

        # when creating, later windows go into the newly created tab
        t3 = FakeTab(3, 'z')

        def move(window, **kw):
            window.tabref.return_value = t3

        boss._move_window_to.side_effect = move
        boss.match_windows.side_effect = lambda q, w=None: iter((w1, w3))
        run(match='all', target_tab='@title', tab_title='z', create_if_missing=True)
        self.ae([c.kwargs['target_tab_id'] for c in boss._move_window_to.call_args_list], ['new', 3])
