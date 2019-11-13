#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.cli import parse_args
from kitty.fast_data_types import set_clipboard_string
from kitty.utils import set_primary_selection


def options_spec():
    if not hasattr(options_spec, 'ans'):
        OPTIONS = '''
--window-title --title
The title to set for the new window. By default, title is controlled by the
child process.


--tab-title
The title for the new tab if launching in a new tab. By default, the title
of the actie window in the tab is used as the tab title.


--type
type=choices
default=window
choices=window,tab,os-window,overlay,background,clipboard,primary
Where to launch the child process, in a new kitty window in the current tab,
a new tab, or a new OS window or an overlay over the current window.
Note that if the current window already has an overlay, then it will
open a new window. The value of none means the process will be
run in the background. The values clipboard and primary are meant
to work with :option:`launch --stdin-source` to copy data to the system
clipboard or primary selection.


--keep-focus
type=bool-set
Keep the focus on the currently active window instead of switching
to the newly opened window.


--cwd
The working directory for the newly launched child. Use the special value
:code:`current` to use the working directory of the currently active window.


--env
type=list
Environment variables to set in the child process. Can be specified multiple
times to set different environment variables.
Syntax: :italic:`name=value`.


--copy-colors
type=bool-set
Set the colors of the newly created window to be the same as the colors in the
currently active window.


--copy-cmdline
type=bool-set
Ignore any specified command line and instead use the command line from the
currently active window.


--copy-env
type=bool-set
Copy the environment variables from the currently active window into the
newly launched child process.


--location
type=choices
default=last
choices=first,neighbor,last
Where to place the newly created window when it is added to a tab which
already has existing windows in it. Also applies to creating a new tab,
where the value of neighbor will cause the new tab to be placed next to
the current tab instead of at the end.


--allow-remote-control
type=bool-set
Programs running in this window can control kitty (if remote control is
enabled). Note that any program with the right level of permissions can still
write to the pipes of any other program on the same computer and therefore can
control kitty. It can, however, be useful to block programs running on other
computers (for example, over ssh) or as other users.


--stdin-source
type=choices
default=none
choices=none,@selection,@screen,@screen_scrollback,@alternate,@alternate_scrollback
Pass the screen contents as :code:`STDIN` to the child process. @selection is
the currently selected text. @screen is the contents of the currently active
window. @screen_scrollback is the same as @screen, but includes the scrollback
buffer as well. @alternate is the secondary screen of the current active
window. For example if you run a full screen terminal application, the
secondary screen will be the screen you return to when quitting the
application.


--stdin-add-formatting
type=bool-set
When using :option:`launch --stdin-source` add formatting escape codes, without this
only plain text will be sent.


--stdin-add-line-wrap-markers
type=bool-set
When using :option:`launch --stdin-source` add a carriage return at every line wrap
location (where long lines are wrapped at screen edges). This is useful if you
want to pipe to program that wants to duplicate the screen layout of the
screen.


'''
        options_spec.ans = OPTIONS
    return options_spec.ans


def parse_launch_args(args=None):
    args = list(args or ())
    try:
        opts, args = parse_args(args=args, ospec=options_spec)
    except SystemExit as e:
        raise ValueError from e
    return opts, args


def get_env(opts, active_child):
    env = {}
    if opts.copy_env and active_child:
        env.update(active_child.foreground_environ)
    for x in opts.env:
        parts = x.split('=', 1)
        if len(parts) == 2:
            env[parts[0]] = parts[1]
    return env


def tab_for_window(boss, opts, target_tab=None):
    if opts.type == 'tab':
        tm = boss.active_tab_manager
        tab = tm.new_tab(empty_tab=True, as_neighbor=opts.location == 'neighbor')
        if opts.tab_title:
            tab.set_title(opts.tab_title)
    elif opts.type == 'os-window':
        oswid = boss.add_os_window()
        tm = boss.os_window_map[oswid]
        tab = tm.new_tab(empty_tab=True)
        if opts.tab_title:
            tab.set_title(opts.tab_title)
    else:
        tab = target_tab or boss.active_tab

    return tab


def launch(boss, opts, args, target_tab=None):
    active = boss.active_window_for_cwd
    active_child = getattr(active, 'child', None)
    env = get_env(opts, active_child)
    kw = {
        'allow_remote_control': opts.allow_remote_control
    }
    if opts.cwd:
        if opts.cwd == 'current':
            if active_child:
                kw['cwd_from'] = active_child.pid_for_cwd
        else:
            kw['cwd'] = opts.cwd
    if opts.location != 'last':
        kw['location'] = opts.location
    if opts.window_title:
        kw['override_title'] = opts.window_title
    if opts.copy_colors and active:
        kw['copy_colors_from'] = active
    cmd = args or None
    if opts.copy_cmdline and active_child:
        cmd = active_child.foreground_cmdline
    if cmd:
        final_cmd = []
        for x in cmd:
            if x == '@selection' and active and not opts.copy_cmdline:
                s = boss.data_for_at(active, x)
                if s:
                    x = s
            final_cmd.append(x)
        kw['cmd'] = final_cmd
    if opts.type == 'overlay' and active and not active.overlay_window_id:
        kw['overlay_for'] = active.id
    if opts.stdin_source and opts.stdin_source != 'none':
        q = opts.stdin_source
        if opts.stdin_add_line_wrap_markers:
            q += '_wrap'
        penv, stdin = boss.process_stdin_source(window=active, stdin=q)
        if stdin:
            kw['stdin'] = stdin
            if penv:
                env.update(penv)

    if opts.type == 'background':
        boss.run_background_process(kw['cmd'], cwd=kw.get('cwd'), cwd_from=kw.get('cwd_from'), env=env or None, stdin=kw.get('stdin'))
    elif opts.type in ('clipboard', 'primary'):
        if 'stdin' in kw:
            func = set_clipboard_string if opts.type == 'clipboard' else set_primary_selection
            func(kw['stdin'])
    else:
        tab = tab_for_window(boss, opts, target_tab)
        new_window = tab.new_window(env=env or None, **kw)
        if opts.keep_focus and active:
            boss.set_active_window(active, switch_os_window_if_needed=True)
        return new_window
