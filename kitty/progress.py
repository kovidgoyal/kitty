#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>


from enum import Enum

from .fast_data_types import monotonic
from .utils import log_error


class ProgressState(Enum):
    unset = 0
    set = 1
    error = 2
    indeterminate = 3
    paused = 4


class Progress:

    state: ProgressState = ProgressState.unset
    percent: int = 0
    last_update_at: float = 0.
    clear_timeout: float = 60.0
    finished_clear_timeout: float = 5.0

    def update(self, st: int, percent: int = -1) -> None:
        self.last_update_at = monotonic()
        if st == 0:
            self.state = ProgressState.unset
            self.percent = 0
        elif st == 1:
            self.state = ProgressState.set
            self.percent = max(0, min(percent, 100))
        elif st == 2:
            self.state = ProgressState.error
            self.percent = 0
        elif st == 3:
            self.state = ProgressState.indeterminate
            self.percent = 0
        elif st == 4:
            self.state = ProgressState.paused
            if percent > -1:
                self.percent = max(0, min(percent, 100))
        else:
            log_error(f'Unknown OSC 9;4 state: {st}')

    def clear_progress(self) -> bool:
        time_since_last_update = monotonic() - self.last_update_at
        threshold = self.finished_clear_timeout if self.percent == 100 and self.state is ProgressState.set else self.clear_timeout
        if time_since_last_update >= threshold:
            self.state = ProgressState.unset
            self.percent = 0
            return True
        return False
