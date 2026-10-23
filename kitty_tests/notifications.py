#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>


import os
import re
import tempfile
from base64 import standard_b64encode
from unittest.mock import patch

from kitty.notifications import Channel, DesktopIntegration, FreeDesktopIntegration, IconDataCache, NotificationManager, UIState, Urgency

from .base import BaseTest


def n(
    title='title',
    body='',
    urgency=Urgency.Normal,
    desktop_notification_id=1,
    icon_names=(),
    icon_path='',
    application_name='',
    notification_types=(),
    timeout=-1,
    sound='system',
):
    return {
        'title': title,
        'body': body,
        'urgency': urgency,
        'id': desktop_notification_id,
        'icon_names': icon_names,
        'icon_path': icon_path,
        'application_name': application_name,
        'notification_types': notification_types,
        'timeout': timeout,
        'sound': sound,
    }


class DesktopIntegration(DesktopIntegration):
    def initialize(self):
        self.reset()

    def reset(self):
        self.notifications = []
        self.close_events = []
        self.new_version_activated = False
        self.close_succeeds = True
        self.counter = 0

    def query_live_notifications(self, channel_id, client_id):
        ids = [n['id'] for n in self.notifications]
        self.notification_manager.send_live_response(channel_id, client_id, tuple(ids))

    def on_new_version_notification_activation(self, cmd, which) -> None:
        self.new_version_activated = which + 1

    def close_notification(self, desktop_notification_id: int) -> bool:
        self.close_events.append(desktop_notification_id)
        if self.close_succeeds:
            self.notification_manager.notification_closed(desktop_notification_id)
        return self.close_succeeds

    def notify(self, cmd, existing_desktop_notification_id) -> int:
        if existing_desktop_notification_id:
            did = existing_desktop_notification_id
        else:
            self.counter += 1
            did = self.counter
        title, body, urgency = cmd.title, cmd.body, (Urgency.Normal if cmd.urgency is None else cmd.urgency)
        ans = n(
            title,
            body,
            urgency,
            did,
            cmd.icon_names,
            os.path.basename(cmd.icon_path),
            cmd.application_name,
            cmd.notification_types,
            timeout=cmd.timeout,
            sound=cmd.sound_name,
        )
        self.notifications.append(ans)
        return self.counter


class Channel(Channel):
    focused = visible = True

    def __init__(self, *a):
        super().__init__(*a)
        self.reset()

    def reset(self):
        self.responses = []
        self.focus_events = []

    def ui_state(self, channel_id):
        return UIState(self.focused, self.visible)

    def focus(self, channel_id: int, activation_token: str) -> None:
        self.focus_events.append(activation_token)

    def send(self, channel_id: int, osc_escape_code: str) -> bool:
        self.responses.append(osc_escape_code)


class NotificationManager(NotificationManager):
    @property
    def filter_rules(self):
        yield from ('title:filterme',)


def do_test(self: 'TestNotifications', tdir: str) -> None:
    di = DesktopIntegration(None)
    ch = Channel()
    nm = NotificationManager(di, ch, lambda *a, **kw: None, base_cache_dir=tdir)
    di.notification_manager = nm

    def reset():
        di.reset()
        ch.reset()
        nm.reset()

    def h(raw_data, osc_code=99, channel_id=1):
        nm.handle_notification_cmd(channel_id, osc_code, raw_data)

    def activate(which=0, button=0):
        n = di.notifications[which]
        nm.notification_activated(n['id'], button)

    def close(which=0):
        n = di.notifications[which]
        di.close_notification(n['id'])

    def assert_events(focus=True, close=0, report='', close_response='', live=''):
        self.ae(ch.focus_events, [''] if focus else [])
        if report:
            self.assertIn(f'99;i={report};', ch.responses)
        else:
            for r in ch.responses:
                m = re.match(r'99;i=[a-z0-9]+;', r)
                self.assertIsNone(m, f'Unexpectedly found report response: {r}')
        if close_response:
            self.assertIn(f'99;i={close_response}:p=close;', ch.responses)
        else:
            for r in ch.responses:
                m = re.match(r'99;i=[a-z0-9]+:p=close;', r)
                self.assertIsNone(m, f'Unexpectedly found close response: {r}')
        if live:
            self.assertIn(f'99;i=live:p=alive;{live}', ch.responses)
        else:
            for r in ch.responses:
                m = re.match(r'99;i=[a-z0-9]+:p=alive;', r)
                self.assertIsNone(m, f'Unexpectedly found alive response: {r}')
        self.ae(di.close_events, [close] if close else [])

    h('test it', osc_code=9)
    self.ae(di.notifications, [n(title='test it')])
    activate()
    assert_events()
    reset()

    h('d=0:u=2:i=x;title')
    h('d=1:i=x:p=body;body')
    self.ae(di.notifications, [n(body='body', urgency=Urgency.Critical)])
    activate()
    assert_events()
    reset()

    h('i=x:p=body:a=-focus;body')
    self.ae(di.notifications, [n(title='body')])
    activate()
    assert_events(focus=False)
    reset()

    nm.send_new_version_notification('moose')
    self.ae(di.notifications, [n('kitty update available!', 'kitty version moose released')])
    activate()
    self.assertTrue(di.new_version_activated)
    reset()

    h('i=x:e=1;' + standard_b64encode(b'title').decode('ascii'))
    self.ae(di.notifications, [n()])
    activate()
    assert_events()
    reset()

    h('e=1;' + standard_b64encode(b'title').decode('ascii'))
    self.ae(di.notifications, [n()])
    activate()
    assert_events()
    reset()

    h('d=0:i=x:a=-report;title')
    h('d=1:i=x:a=report;body')
    self.ae(di.notifications, [n(title='titlebody')])
    activate()
    assert_events(report='x')
    reset()

    h('a=report;title')
    self.ae(di.notifications, [n()])
    activate()
    assert_events(report='0')
    reset()

    h('d=0:i=y;title')
    h('d=1:i=y:p=xxx;title')
    self.ae(di.notifications, [n()])
    reset()

    # test filtering
    h(';title')
    h(';filterme please')
    self.ae(di.notifications, [n()])
    reset()

    # test closing interactions with reporting and activation
    h('i=c;title')
    self.ae(di.notifications, [n()])
    close()
    assert_events(focus=False, close=True)
    reset()
    h('i=c:c=1;title')
    self.ae(di.notifications, [n()])
    h('i=c:p=close')
    self.ae(di.notifications, [n()])
    assert_events(focus=False, close=True, close_response='c')
    reset()
    h('i=c:c=1;title')
    h('i=c:p=close')
    self.ae(di.notifications, [n()])
    assert_events(focus=False, close=True, close_response='c')
    reset()
    h('i=c;title')
    activate()
    close()
    h('i=c:p=close')
    self.ae(di.notifications, [n()])
    assert_events(focus=True, close=True)
    reset()
    h('i=c:a=report:c=1;title')
    activate()
    h('i=c:p=close')
    self.ae(di.notifications, [n()])
    assert_events(focus=True, report='c', close=True, close_response='c')
    reset()

    h('i=a[;title')
    h('i=b;title')
    h('i=live:p=alive;')
    assert_events(focus=False, live='a,b')
    reset()

    h(';title')
    self.ae(di.notifications, [n()])
    activate()
    assert_events()
    reset()

    # test sounds
    def enc(x):
        return standard_b64encode(x.encode()).decode()

    h(f's={enc("silent")};title')
    self.ae(di.notifications, [n(sound='silent')])
    h(f's={enc("custom")};title')
    self.ae(di.notifications[-1], n(desktop_notification_id=2, sound='custom'))
    reset()

    # Test querying
    h('i=xyz:p=?')
    self.assertFalse(di.notifications)
    qr = 'a=focus,report:o=always,unfocused,invisible:u=0,1,2:p=title,body,?,close,icon,alive,buttons:c=1:w=1:s=system,silent,error,info,question,warn,warning'
    self.ae(ch.responses, [f'99;i=xyz:p=?;{qr}'])
    reset()
    h('p=?')
    self.assertFalse(di.notifications)
    self.ae(ch.responses, [f'99;i=0:p=?;{qr}'])

    # Test MIME streaming
    for padding in (True, False):
        for extra in ('a', 'ab', 'abc', 'abcd'):
            text = 'some reasonably long text to test MIME streaming with: '
            encoded = standard_b64encode(text.encode()).decode()
            if not padding:
                encoded = encoded.rstrip('=')
            for t in encoded:
                h(f'i=s:e=1:d=0;{t}')
            h(f'i=s:e=1:d=0:p=body;{encoded[:13]}')
            h(f'i=s:e=1:d=0:p=body;{encoded[13:]}')
            h('i=s')
            self.ae(di.notifications, [n(text, text)])
            reset()

    # Test application name and notification type
    def e(x):
        return standard_b64encode(x.encode()).decode()

    h(f'i=t:d=0:f={e("app")}:t={e("1")};title')
    h(f'i=t:t={e("test")}')
    self.ae(
        di.notifications,
        [
            n(
                application_name='app',
                notification_types=(
                    '1',
                    'test',
                ),
            )
        ],
    )
    reset()

    # Test timeout
    h('w=3;title')
    self.ae(di.notifications, [n(timeout=3)])
    reset()

    # Test Disk Cache
    dc = IconDataCache(base_cache_dir=tdir, max_cache_size=4)
    cache_dir = dc._ensure_state()
    for i in range(5):
        dc.add_icon(str(i), str(i).encode())
    self.ae(set(dc.keys()), set(map(str, range(1, 5))))
    del dc
    self.assertFalse(os.path.exists(cache_dir))

    # Test icons
    def send_with_icon(data='', n='', g=''):
        m = ''
        if n:
            for x in n.split(','):
                m += f'n={standard_b64encode(x.encode()).decode()}:'
        if g:
            m += f'g=({g}:'
        h(f'i=9:d=0:{m};title')
        h(f'i=9:p=icon;{data}')

    dc = nm.icon_data_cache
    send_with_icon(n='mycon,ic2')
    self.ae(di.notifications, [n(icon_names=('mycon', 'ic2'))])
    reset()
    send_with_icon(g='gid')
    self.ae(di.notifications, [n()])
    reset()
    send_with_icon(g='gid', data='1')
    self.ae(di.notifications, [n(icon_path=dc.hash(b'1'))])
    send_with_icon(g='gid', n='moose')
    self.ae(di.notifications[-1], n(icon_names=('moose',), icon_path=dc.hash(b'1')))
    send_with_icon(g='gid2', data='2')
    self.ae(di.notifications[-1], n(icon_path=dc.hash(b'2')))
    send_with_icon(data='3')
    self.ae(di.notifications[-1], n(icon_path=dc.hash(b'3')))
    reset()


class TestNotifications(BaseTest):
    def test_desktop_notify(self):
        with tempfile.TemporaryDirectory() as tdir:
            do_test(self, tdir)

    def test_freedesktop_close_before_created(self):
        import kitty.fast_data_types as fdt

        sent: list[int] = []
        closed: list[int] = []
        replaces: list[object] = []

        def send_notification(**kw: object) -> int:
            replaces.append(kw['replaces'])
            sent.append(len(sent) + 1)
            return sent[-1]

        def close_notification(dbus_id: int) -> bool:
            closed.append(dbus_id)
            return True

        with (
            tempfile.TemporaryDirectory() as tdir,
            patch.multiple(
                fdt,
                create=True,
                dbus_set_notification_callback=lambda *a: None,
                dbus_send_notification=send_notification,
                dbus_close_notification=close_notification,
            ),
        ):
            di = FreeDesktopIntegration(None)
            ch = Channel()
            nm = NotificationManager(di, ch, lambda *a, **kw: None, base_cache_dir=tdir)
            di.notification_manager = nm

            # close requested before the notification daemon replies to Notify
            nm.handle_notification_cmd(1, 99, 'i=x:c=1;title')
            nm.handle_notification_cmd(1, 99, 'i=x:p=close;')
            self.ae(closed, [])
            self.assertIn('x', nm.in_progress_notification_commands_by_client_id)
            self.ae(ch.responses, [])
            di.dispatch_event_from_desktop('created', sent[-1], 101)
            self.ae(closed, [101])
            di.dispatch_event_from_desktop('closed', 101, 0)
            self.assertNotIn('x', nm.in_progress_notification_commands_by_client_id)
            self.ae(ch.responses, ['99;i=x:p=close;'])
            self.ae(di.pending_closes, set())

            # replacement sent before the notification being replaced is created
            closed.clear(), ch.reset()
            nm.handle_notification_cmd(1, 99, 'i=r;first')
            first = sent[-1]
            nm.handle_notification_cmd(1, 99, 'i=r;second')
            second = sent[-1]
            self.ae(nm.in_progress_notification_commands_by_client_id['r'].title, 'second')
            di.dispatch_event_from_desktop('created', first, 201)
            self.ae(closed, [201])
            di.dispatch_event_from_desktop('closed', 201, 0)
            di.dispatch_event_from_desktop('created', second, 202)
            self.ae(closed, [201])
            self.ae(nm.in_progress_notification_commands_by_client_id['r'].title, 'second')
            self.ae(ch.responses, [])
            nm.handle_notification_cmd(1, 99, 'i=r;third')
            self.ae(closed, [201])  # replaced via the replaces argument to Notify, not closed
            self.ae(replaces[-3:], [0, 0, 202])

            # normal close after creation
            closed.clear(), ch.reset()
            nm.handle_notification_cmd(1, 99, 'i=y;title')
            di.dispatch_event_from_desktop('created', sent[-1], 102)
            self.ae(closed, [])
            nm.handle_notification_cmd(1, 99, 'i=y:p=close;')
            self.ae(closed, [102])

    def test_freedesktop_desktop_entry(self):
        import kitty.fast_data_types as fdt
        from kitty.xdg import desktop_file_id_for_appname, kitty_desktop_entry, xdg_data_dirs, xdg_data_home

        desktop_entries: list[object] = []

        def send_notification(**kw: object) -> int:
            desktop_entries.append(kw['desktop_entry'])
            return len(desktop_entries)

        kitty_desktop_entry.set_override('net.kovidgoyal.kitty')
        try:
            with (
                tempfile.TemporaryDirectory() as tdir,
                patch.multiple(
                    fdt,
                    create=True,
                    dbus_set_notification_callback=lambda *a: None,
                    dbus_send_notification=send_notification,
                    dbus_close_notification=lambda *a: True,
                ),
            ):
                di = FreeDesktopIntegration(None)
                nm = NotificationManager(di, Channel(), lambda *a, **kw: None, base_cache_dir=tdir)
                di.notification_manager = nm
                nm.handle_notification_cmd(1, 99, 'i=a;title')
                nm.handle_notification_cmd(1, 99, f'i=b:f={standard_b64encode(b"kitty").decode()};title')
                nm.handle_notification_cmd(1, 99, f'i=c:f={standard_b64encode(b"nvim").decode()};title')
                self.ae(desktop_entries, ['net.kovidgoyal.kitty', 'net.kovidgoyal.kitty', ''])
        finally:
            kitty_desktop_entry.clear_override()

        with tempfile.TemporaryDirectory() as tdir:
            home, sysdir = os.path.join(tdir, 'home'), os.path.join(tdir, 'sys')
            for x in (os.path.join(home, 'applications', 'sub'), os.path.join(sysdir, 'applications')):
                os.makedirs(x)

            def touch(*parts: str) -> None:
                open(os.path.join(*parts), 'w').close()

            xdg_data_home.set_override(home)
            xdg_data_dirs.set_override((sysdir,))
            try:
                self.ae(desktop_file_id_for_appname('kitty'), '')
                touch(sysdir, 'applications', 'other.desktop')
                touch(home, 'applications', 'sub', 'net.kovidgoyal.kitty.desktop')
                self.ae(desktop_file_id_for_appname('kitty'), 'sub-net.kovidgoyal.kitty')
                touch(sysdir, 'applications', 'kitty.desktop')
                self.ae(desktop_file_id_for_appname('kitty'), 'kitty')
            finally:
                xdg_data_home.clear_override()
                xdg_data_dirs.clear_override()
