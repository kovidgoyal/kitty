#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Program Status Protocol (OSC 7501), revision 0.4
# https://www.superlogical.com/rex/docs/build/program-status

import re
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from enum import Enum
from itertools import count
from typing import Any, NamedTuple

from .fast_data_types import base64_decode

OSC_CODE = 7501
# The whole sequence, ESC ] through ST, assuming the longer ST of ESC \
MAX_SEQUENCE_BYTES = 4096
MAX_BODY_BYTES = MAX_SEQUENCE_BYTES - len(f'\x1b]{OSC_CODE};') - len('\x1b\\')
MAX_KEY_BYTES = 16
MAX_MSG_ENCODED_BYTES, MAX_MSG_BYTES = 2732, 2048
MAX_TITLE_ENCODED_BYTES, MAX_TITLE_BYTES = 256, 192
MAX_APP_BYTES = 32
MAX_ID_SEGMENT_BYTES, MAX_ID_DEPTH = 32, 8
# The spec says 128 but that is an error as it is less than the maximum length allowed by the segment and depth limits
MAX_ID_BYTES = MAX_ID_SEGMENT_BYTES * MAX_ID_DEPTH + MAX_ID_DEPTH - 1
MAX_RECORDS = 256

key_pat = re.compile(r'[a-z]+')
value_pat = re.compile(r'[A-Za-z0-9_.,+/=-]*')
name_pat = re.compile(r'[A-Za-z0-9_.+-]+')
progress_pat = re.compile(r'[0-9]+')
# C0, DEL and C1 control characters
control_chars_pat = re.compile('[\x00-\x1f\x7f-\x9f]')
WHITESPACE = ' \t\n\r\x0b\x0c'


class State(Enum):
    idle = 'idle'
    working = 'working'
    done = 'done'
    blocked = 'blocked'
    error = 'error'


class Kind(Enum):
    permission = 'permission'
    question = 'question'
    auth = 'auth'


# Sent by kittens that run a program before handing the terminal to something
# else, such as a shell for launch --hold, as kitty cannot otherwise see the
# program exit. It is not a valid report so other terminals ignore it.
PROCESS_EXITED = b'process-exited'
# Reply to the feature detection query, lists the states and kinds we accept
QUERY_REPLY = '{};?:states={}:kinds={}'.format(OSC_CODE, ','.join(s.value for s in State), ','.join(k.value for k in Kind))
# Records that are dropped when the process exits or a new shell prompt begins
TRANSIENT_STATES = frozenset((State.working, State.blocked, State.idle))
# Records that remain until the user has seen them
UNSEEN_STATES = frozenset((State.done, State.error))
# Higher is more urgent, used to pick the record to show for several records
URGENCY = {State.idle: 0, State.working: 1, State.done: 2, State.error: 3, State.blocked: 4}


# Orders updates across all windows, to find the most recently updated record
update_counter = count()


class InvalidReport(ValueError):
    pass


class Record(NamedTuple):
    id: str = ''  # empty for the root record
    state: State = State.idle
    kind: Kind | None = None
    progress: int | None = None
    app: str = ''
    title: str = ''
    msg: str = ''

    def as_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'state': self.state.value,
            'kind': self.kind.value if self.kind else None,
            'progress': self.progress,
            'app': self.app,
            'title': self.title,
            'msg': self.msg,
        }


class Clear(NamedTuple):
    id: str = ''  # empty means every record


def is_valid_id(val: str) -> bool:
    if len(val) > MAX_ID_BYTES:
        return False
    segments = val.split('/')
    return len(segments) <= MAX_ID_DEPTH and all(len(s) <= MAX_ID_SEGMENT_BYTES and name_pat.fullmatch(s) for s in segments)


def decode_text(encoded: str, max_encoded: int, max_decoded: int) -> str:
    if len(encoded) > max_encoded:
        raise InvalidReport('text value too long')
    if len(encoded) % 4 == 1:
        raise InvalidReport('invalid base64')
    try:
        raw = base64_decode(encoded + '=' * (-len(encoded) % 4), True)
        text = raw.decode('utf-8')
    except (ValueError, UnicodeDecodeError) as e:
        raise InvalidReport(f'invalid text value: {e}') from e
    if len(raw) > max_decoded:
        raise InvalidReport('decoded text value too long')
    if control_chars_pat.search(text) is not None:
        raise InvalidReport('text value contains control characters')
    return text


def parse_report(raw: str | bytes | memoryview) -> Record | Clear:
    "Parse the body of an OSC 7501 report, everything after 7501; Raises InvalidReport if the report must be discarded."
    if isinstance(raw, str):
        body, num_bytes = raw, len(raw.encode('utf-8'))
    else:
        # invalid UTF-8 is outside the value set and so is skipped, as a malformed pair
        body, num_bytes = str(raw, 'utf-8', 'replace'), len(raw)
    if num_bytes > MAX_BODY_BYTES:
        raise InvalidReport('report too long')
    values: dict[str, str] = {}
    for pair in body.split(':'):
        key, sep, val = pair.partition('=')
        if not sep:
            continue
        key, val = key.strip(WHITESPACE), val.strip(WHITESPACE)
        if len(key) > MAX_KEY_BYTES:
            raise InvalidReport('key too long')
        if not key_pat.fullmatch(key):
            continue
        if value_pat.fullmatch(val) is None:
            if key == 'id':  # never fall back to the root record because of a malformed id
                raise InvalidReport('invalid id')
            continue
        # Every value is checked against its limit, even if a later pair with the same key replaces it
        if key == 'id' and not is_valid_id(val):
            raise InvalidReport('invalid id')
        if key == 'app' and len(val) > MAX_APP_BYTES:
            raise InvalidReport('app too long')
        if key == 'msg' and len(val) > MAX_MSG_ENCODED_BYTES:
            raise InvalidReport('msg too long')
        if key == 'title' and len(val) > MAX_TITLE_ENCODED_BYTES:
            raise InvalidReport('title too long')
        values[key] = val
    title = decode_text(t, MAX_TITLE_ENCODED_BYTES, MAX_TITLE_BYTES) if (t := values.get('title')) else ''
    msg = decode_text(m, MAX_MSG_ENCODED_BYTES, MAX_MSG_BYTES) if (m := values.get('msg')) else ''
    rid = values.get('id', '')
    state_name = values.get('state', '')
    if state_name == 'clear':
        return Clear(rid)
    try:
        state = State(state_name)
    except ValueError:
        # an unknown state discards the report so that a state added later never turns into something else
        raise InvalidReport(f'unknown state: {state_name!r}') from None
    kind = None
    if state is State.blocked:
        try:
            kind = Kind(values.get('kind', ''))
        except ValueError:
            pass
    progress = None
    if state in (State.working, State.blocked) and progress_pat.fullmatch(p := values.get('progress', '')) and int(p) <= 100:
        progress = int(p)
    app = values.get('app', '')
    if not name_pat.fullmatch(app):
        app = ''
    return Record(id=rid, state=state, kind=kind, progress=progress, app=app, title=title, msg=msg)


def is_descendant_or_self(rid: str, ancestor: str) -> bool:
    return not ancestor or rid == ancestor or rid.startswith(ancestor + '/')


class ProgramStatus:
    "The records reported by the programs running in one window"

    def __init__(self) -> None:
        # ordered from least to most recently changed
        self.records: OrderedDict[str, Record] = OrderedDict()
        # when each record last changed, used to break ties between equally urgent records
        self.update_seq: dict[str, int] = {}
        # when each record was last reported, even identically, used for eviction
        self.report_seq: dict[str, int] = {}

    def __bool__(self) -> bool:
        return bool(self.records)

    def __iter__(self) -> Iterator[Record]:
        return iter(self.records.values())

    def handle_escape_code(self, raw: memoryview | bytes) -> tuple[str, bool]:
        """
        Handle the body of an OSC 7501 escape code, returns the reply to send
        to the child, empty if none, and whether the records changed. Raises
        InvalidReport if the report must be discarded.
        """
        if raw == b'?':
            return QUERY_REPLY, False
        if raw == PROCESS_EXITED:
            return '', self.on_process_exit_or_prompt()
        return '', self.apply(parse_report(raw))

    def apply(self, report: Record | Clear) -> bool:
        "Apply a report, returns True if the records changed"
        if isinstance(report, Clear):
            return self.remove(lambda r: is_descendant_or_self(r.id, report.id))
        seq = next(update_counter)
        self.report_seq[report.id] = seq
        if self.records.get(report.id) == report:
            # an identical report changes nothing that is displayed, so only its recency for eviction is updated
            return False
        self.update_seq[report.id] = seq
        self.records[report.id] = report
        self.records.move_to_end(report.id)
        while len(self.records) > MAX_RECORDS:  # drop the least recently reported record
            self.discard(min(self.report_seq, key=self.report_seq.__getitem__))
        return True

    def discard(self, rid: str) -> None:
        del self.records[rid], self.update_seq[rid], self.report_seq[rid]

    def remove(self, predicate: Callable[[Record], bool]) -> bool:
        remove = tuple(rid for rid, r in self.records.items() if predicate(r))
        for rid in remove:
            self.discard(rid)
        return bool(remove)

    def clear(self) -> bool:
        ans = bool(self.records)
        self.records.clear()
        self.update_seq.clear()
        self.report_seq.clear()
        return ans

    def on_process_exit_or_prompt(self) -> bool:
        return self.remove(lambda r: r.state in TRANSIENT_STATES)

    def on_seen_by_user(self) -> bool:
        return self.remove(lambda r: r.state in UNSEEN_STATES)

    def app_for(self, record: Record) -> str:
        "The app of a record, inherited from its nearest ancestor if absent"
        if record.app:
            return record.app
        rid = record.id
        while rid:
            rid = rid.rpartition('/')[0]
            if (a := self.records.get(rid)) is not None and a.app:
                return a.app
        return ''

    def rank(self, record: Record) -> tuple[int, int]:
        "The sort key for display: the most urgent record wins, ties are broken by the most recently changed record"
        return URGENCY[record.state], self.update_seq[record.id]

    def most_urgent(self) -> Record | None:
        return max(self.records.values(), key=self.rank, default=None)

    def as_list(self) -> list[dict[str, Any]]:
        ans = []
        for r in self.records.values():
            d = r.as_dict()
            d['app'] = self.app_for(r)
            ans.append(d)
        return ans


def status_symbol(record: Record | None, num: int = 1) -> str:
    "A short indicator for use in tab and window titles, num is the number of windows in this state"
    if record is None or record.state is State.idle:
        return ''
    if record.state is State.blocked:
        sym = '\uf071'
    elif record.state is State.error:
        sym = '\ue654'
    elif record.state is State.done:
        sym = '\uf00c'
    else:
        sym = '\uf110'
    ans = f'{sym}  {num} ' if num > 1 else f'{sym}  '
    if record.state is State.working and record.progress is not None:
        ans += f'{record.progress}% '
    return ans


def combined_status_symbol(statuses: Iterable[ProgramStatus]) -> str:
    """
    The most urgent status of several windows, along with the number of
    windows in that status. Ties are broken by the most recently updated record.
    """
    items = [(r, ps.rank(r)) for ps in statuses if (r := ps.most_urgent()) is not None]
    if not items:
        return ''
    best = max(items, key=lambda x: x[1])[0]
    return status_symbol(best, sum(1 for r, _ in items if r.state is best.state))
