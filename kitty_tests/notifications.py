#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>


import re
from base64 import standard_b64encode
from typing import Optional

from kitty.notifications import Channel, DesktopIntegration, NotificationManager, UIState, Urgency

from . import BaseTest


def n(title='title', body='', urgency=Urgency.Normal, desktop_notification_id=1):
    return {'title': title, 'body': body, 'urgency': urgency, 'id': desktop_notification_id}


class DesktopIntegration(DesktopIntegration):
    def initialize(self):
        self.reset()

    def reset(self):
        self.notifications = []
        self.close_events = []
        self.new_version_activated = False
        self.close_succeeds = True
        self.counter = 0

    def on_new_version_notification_activation(self, cmd) -> None:
        self.new_version_activated = True

    def close_notification(self, desktop_notification_id: int) -> bool:
        self.close_events.append(desktop_notification_id)
        if self.close_succeeds:
            self.notification_manager.notification_closed(desktop_notification_id)
        return self.close_succeeds

    def notify(self,
        title: str,
        body: str,
        timeout: int = -1,
        application: str = 'kitty',
        icon: bool = True,
        subtitle: Optional[str] = None,
        urgency: Urgency = Urgency.Normal,
    ) -> int:
        self.counter += 1
        self.notifications.append(n(title, body, urgency, self.counter))
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


def do_test(self: 'TestNotifications') -> None:
    di = DesktopIntegration(None)
    ch = Channel()
    nm = NotificationManager(di, ch, lambda *a, **kw: None)
    di.notification_manager = nm

    def reset():
        di.reset()
        ch.reset()
        nm.reset()

    def h(raw_data, osc_code=99, channel_id=1):
        nm.handle_notification_cmd(channel_id, osc_code, raw_data)

    def activate(which=0):
        n = di.notifications[which]
        nm.notification_activated(n['id'])

    def close(which=0):
        n = di.notifications[which]
        di.close_notification(n['id'])

    def assert_events(focus=True, close=0, report='', close_response=''):
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

    h(';title')
    self.ae(di.notifications, [n()])
    activate()
    assert_events()
    reset()

    # Test querying
    h('i=xyz:p=?')
    self.assertFalse(di.notifications)
    qr = 'a=focus,report:o=always,unfocused,invisible:u=0,1,2:p=title,body,?,close:c=1'
    self.ae(ch.responses, [f'99;i=xyz:p=?;{qr}'])
    reset()
    h('p=?')
    self.assertFalse(di.notifications)
    self.ae(ch.responses, [f'99;i=0:p=?;{qr}'])


class TestNotifications(BaseTest):

    def test_desktop_notify(self):
        do_test(self)

