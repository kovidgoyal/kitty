#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.cli import parse_args


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
choices=window,tab,os-window
Where to launch the child process, in a new kitty window in the current tab,
a new tab, or a new OS window.


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
already has existing windows in it.


--allow-remote-control
type=bool-set
Programs running in this window can control kitty (if remote control is
enabled). Note that any program with the right level of permissions can still
write to the pipes of any other program on the same computer and therefore can
control kitty. It can, however, be useful to block programs running on other
computers (for example, over ssh) or as other users.


'''
        options_spec.ans = OPTIONS
    return options_spec.ans


def parse_launch_args(args):
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


def launch(boss, opts, args):
    if opts.type == 'tab':
        tm = boss.active_tab_manager
        tab = tm.new_tab(empty_tab=True)
        if opts.tab_title:
            tab.set_title(opts.tab_title)
    elif opts.type == 'os-window':
        oswid = boss.add_os_window()
        tm = boss.os_window_map[oswid]
        tab = tm.new_tab(empty_tab=True)
        if opts.tab_title:
            tab.set_title(opts.tab_title)
    else:
        tab = boss.active_tab
    active = boss.active_window_for_cwd
    active_child = getattr(active, 'child', None)
    kw = {
        'env': get_env(opts, active_child) or None,
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
        kw['cmd'] = cmd

    return tab.new_window(**kw)
