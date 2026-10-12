#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from base64 import standard_b64encode

from kitty.program_status import (
    MAX_RECORDS,
    QUERY_REPLY,
    Clear,
    InvalidReport,
    Kind,
    ProgramStatus,
    Record,
    State,
    parse_report,
    status_symbol,
)

from .base import BaseTest


def b64(text: str, pad: bool = True) -> str:
    ans = standard_b64encode(text.encode()).decode()
    return ans if pad else ans.rstrip('=')


class TestProgramStatus(BaseTest):
    def test_program_status_parsing(self):
        def p(body: str) -> Record | Clear:
            return parse_report(body)

        def bad(body: str) -> None:
            with self.assertRaises(InvalidReport, msg=body):
                parse_report(body)

        self.ae(QUERY_REPLY, '7501;?:states=idle,working,done,blocked,error:kinds=permission,question,auth')
        msg = 'Apply 3 to add, 1 to change, 0 to destroy?'
        self.ae(p(f'state=blocked:kind=permission:app=terraform:msg={b64(msg)}'), Record(state=State.blocked, kind=Kind.permission, app='terraform', msg=msg))
        # padding is optional
        self.ae(p(f'state=done:msg={b64("ab", pad=False)}:title={b64("x", pad=False)}'), Record(state=State.done, msg='ab', title='x'))
        # whitespace, malformed pairs, unknown keys and repeated keys
        self.ae(p(' state = idle :oops:=x:future=yes:Bad=1:app=a*b:state=working'), Record(state=State.working))
        # kind and progress only apply to some states, invalid values are absent
        self.ae(p('state=done:kind=auth:progress=10'), Record(state=State.done))
        self.ae(p('state=blocked:kind=other:progress=101'), Record(state=State.blocked))
        self.ae(p('state=working:progress=100'), Record(state=State.working, progress=100))
        self.ae(p('state=working:progress=-1'), Record(state=State.working))
        self.ae(p('state=working:app=a/b'), Record(state=State.working))
        self.ae(p('state=working:id=a/b-c.d_e+f'), Record(id='a/b-c.d_e+f', state=State.working))
        self.ae(p('state=clear'), Clear())
        self.ae(p('state=clear:id=x/y'), Clear('x/y'))
        # an unknown or missing state discards the report
        bad('state=paused')
        bad('app=x')
        bad('')
        # invalid ids discard the report rather than fall back to the root record
        for rid in ('a//b', '/a', 'a/', 'a b', 'a*b', 'a,b', 'x' * 33, '/'.join('a' * 9), '/'.join(['x' * 32] * 4) + '/x'):
            bad(f'state=clear:id={rid}')
        bad('state=idle:id=a:id=a*b')
        # limits, checked even for values that are later replaced
        bad(f'state=idle:{"k" * 17}=1')
        bad(f'state=idle:app={"a" * 33}:app=b')
        bad(f'state=idle:title={b64("x" * 193)}')
        bad(f'state=idle:msg={b64("x" * 2049)}')
        bad(f'state=idle:msg={"QUFB" * 684}:msg=QQ')
        bad('state=idle:' + 'x=y:' * 1100)
        p(f'state=idle:title={b64("x" * 192)}:msg={b64("y" * 2048)}')
        # invalid base64, utf-8 or control characters
        bad('state=idle:msg=Q')
        bad('state=idle:msg=QQ=Q')
        bad(f'state=idle:msg={standard_b64encode(b"\xff").decode()}')
        for cc in '\x00\t\n\x1b\x7f\x85\x9b':
            bad(f'state=idle:msg={b64("a" + cc)}')
        bad(f'state=idle:title={b64("a\nb")}')

    def test_program_status_records(self):
        ps = ProgramStatus()

        def apply(body: str) -> bool:
            return ps.apply(parse_report(body))

        def ids() -> list[str]:
            return [r.id for r in ps]

        self.assertTrue(apply('state=working:app=deploy'))
        self.assertFalse(apply('state=working:app=deploy'))
        self.assertTrue(apply('state=working:id=us-east:progress=40'))
        self.assertTrue(apply('state=blocked:kind=permission:id=eu-west'))
        self.assertTrue(apply('state=working:id=eu-west/db:app=psql'))
        self.ae(ids(), ['', 'us-east', 'eu-west', 'eu-west/db'])
        # app is inherited from the nearest ancestor
        self.ae({d['id']: d['app'] for d in ps.as_list()}, {'': 'deploy', 'us-east': 'deploy', 'eu-west': 'deploy', 'eu-west/db': 'psql'})
        self.ae(ps.most_urgent(), ps.records['eu-west'])
        # a report replaces its record completely
        apply('state=working')
        self.ae(ps.records[''], Record(state=State.working))
        self.ae(ps.as_list()[0]['app'], '')
        # clear removes the record and every record beneath it
        apply('state=clear:id=eu')
        self.ae(len(ps.records), 4)
        apply('state=clear:id=eu-west')
        self.ae(ids(), ['us-east', ''])
        apply('state=clear')
        self.assertFalse(ps)
        # lifetime
        apply('state=working')
        apply('state=blocked:id=a')
        apply('state=idle:id=b')
        apply('state=done:id=c')
        apply('state=error:id=d')
        self.ae(ps.most_urgent(), ps.records['a'])
        self.assertTrue(ps.on_process_exit_or_prompt())
        self.ae(ids(), ['c', 'd'])
        self.ae(ps.most_urgent(), ps.records['d'])
        self.assertFalse(ps.on_process_exit_or_prompt())
        self.assertTrue(ps.on_seen_by_user())
        self.assertFalse(ps)
        # the least recently updated record is removed past the cap
        for i in range(MAX_RECORDS):
            apply(f'state=idle:id=r{i}')
        apply('state=working:id=r0')
        apply('state=idle:id=new')
        self.ae(len(ps.records), MAX_RECORDS)
        self.assertNotIn('r1', ps.records)
        self.assertIn('r0', ps.records)

    def test_program_status_symbol(self):
        self.ae(status_symbol(None), '')
        self.ae(status_symbol(Record(state=State.idle)), '')
        self.assertIn('40%', status_symbol(Record(state=State.working, progress=40)))
        syms = {status_symbol(Record(state=s)) for s in State if s is not State.idle}
        self.ae(len(syms), 4)
