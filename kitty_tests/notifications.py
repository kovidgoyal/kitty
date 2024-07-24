#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>


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
        self.counter = 0

    def close_notification(self, desktop_notification_id: int) -> bool:
        self.close_events.append(desktop_notification_id)

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

    h('test it', osc_code=9)
    self.ae(di.notifications, [n(title='test it')])
    activate()
    assert_events()
    reset()

    h('d=0:u=2:i=x;title')
    h('d=1:i=x:p=body;body')
    self.ae(notifications, [n(client_id='x', body='body', urgency=Urgency.Critical)])
    activate()
    assert_events('x')
    reset()

    h('i=x:p=body:a=-focus;body')
    self.ae(notifications, [n(client_id='x', title='body')])
    activate()
    assert_events('x', focus=False)
    reset()

    h('i=x:e=1;' + standard_b64encode(b'title').decode('ascii'))
    self.ae(notifications, [n(client_id='x', )])
    activate()
    assert_events('x')
    reset()

    h('e=1;' + standard_b64encode(b'title').decode('ascii'))
    self.ae(notifications, [n()])
    activate()
    assert_events()
    reset()

    h('d=0:i=x:a=-report;title')
    h('d=1:i=x:a=report;body')
    self.ae(notifications, [n(client_id='x', title='titlebody')])
    activate()
    assert_events('x', report=True)
    reset()

    h('d=0:i=y;title')
    h('d=1:i=y:p=xxx;title')
    self.ae(notifications, [n(client_id='y')])
    reset()

    # test closing interactions with reporting and activation
    h('i=c;title')
    self.ae(notifications, [n(client_id='c')])
    close()
    assert_events('c', focus=False, close=True)
    reset()
    h('i=c;title')
    self.ae(notifications, [n(client_id='c')])
    h('i=c:p=close')
    self.ae(notifications, [n(client_id='c')])
    assert_events('c', focus=False, close=True)
    reset()
    h('i=c;title')
    h('i=c:p=close;notify')
    assert_events('c', focus=False, close=True, close_response=True)
    reset()

    h(';title')
    self.ae(notifications, [n()])
    activate()
    assert_events()
    reset()

    # Test querying
    h('i=xyz:p=?')
    self.assertFalse(notifications)
    qr = 'a=focus,report:o=always,unfocused,invisible:u=0,1,2:p=title,body,?,close'
    self.ae(query_responses, [f'99;i=xyz:p=?;{qr}'])
    reset()
    h('p=?')
    self.assertFalse(notifications)
    self.ae(query_responses, [f'99;i=0:p=?;{qr}'])


class TestNotifications(BaseTest):

    def test_desktop_notify(self):
        do_test(self)

