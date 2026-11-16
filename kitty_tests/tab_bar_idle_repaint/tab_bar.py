#!/usr/bin/env python
# Minimal reproducer for "custom tab bar refreshed from add_timer stops repainting
# on an idle window". Not collected by ./test.py, it needs a real OS window.
#
# Run it with:
#   cd kitty_tests/tab_bar_idle_repaint
#   KITTY_CONFIG_DIRECTORY=$PWD kitty
# kitty only loads tab_bar.py from its config directory, so --config alone would
# silently draw the default bar. Leave the window focused and untouched: without
# the fix the number on the right of the tab stays at its first value; with the
# fix it advances once per second.
from kitty.fast_data_types import add_timer, get_boss

counter = 0
timer_id = None


def tick(callback_timer_id: int) -> None:
    global counter
    counter += 1
    # Clear the per-OS-window dirty flag; the next render pass repaints the bar.
    for tm in get_boss().os_window_map.values():
        tm.mark_tab_bar_dirty()


def draw_tab(draw_data, screen, tab, before, max_tab_length, index, is_last, extra_data):
    global timer_id
    if timer_id is None:
        timer_id = add_timer(tick, 1.0, True)
    if is_last:
        screen.draw(f' tick {counter} ')
    return screen.cursor.x
