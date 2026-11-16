# Reproducer for the idle custom tab bar repaint bug
#
# Not part of ./test.py: the bug only shows up in a real OS window with an idle
# main loop, which the headless suite cannot provide. The automated regression
# test lives in kitty_tests/tab_bar.py::test_dirty_mark_requests_a_main_loop_tick.
#
# Manual procedure:
#   1. cd into this directory
#   2. KITTY_CONFIG_DIRECTORY=$PWD kitty
#   3. leave the window focused and do not touch it, mouse or keyboard
#   4. watch the `tick N` text at the right of the tab
#
# Broken: N stays at the value it had when the window went idle, and jumps only
# when some other event wakes the main loop (move the mouse over the window, a
# bell, new output in the shell, another timer doing real work).
#
# Fixed: N advances once per second while the window sits idle.
#
# kitty.conf only sets what the reproducer needs: the custom bar, a bar that is
# shown with one tab, and no cursor blink timer to add unrelated ticks.
