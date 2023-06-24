#!/bin/sh
#
# bootstrap-utils.sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the MIT license.
#

mv_files_and_dirs() {
    cwd="$PWD"
    cd "$1"
    command find . -type d -exec mkdir -p "$2/{}" ";"
    command find . -type l -exec sh -c "tgt=\$(command readlink -n \"{}\"); command ln -snf \"\$tgt\" \"$2/{}\"; command rm -f \"{}\"" ";"
    command find . -type f -exec mv "{}" "$2/{}" ";"
    cd "$cwd"
}

compile_terminfo() {
    tname=".terminfo"
    # Ensure the 78 dir is present
    if [ ! -f "$1/$tname/78/xterm-kitty" ]; then
        command mkdir -p "$1/$tname/78"
        command ln -sf "../x/xterm-kitty" "$1/$tname/78/xterm-kitty"
    fi

    if [ -e "/usr/share/misc/terminfo.cdb" ]; then
        # NetBSD requires this file, see https://github.com/kovidgoyal/kitty/issues/4622
        # Also compile terminfo using tic installed via pkgsrc,
        # so that programs that depend on the new version of ncurses automatically fall back to this one.
        if [ -x "/usr/pkg/bin/tic" ]; then
            /usr/pkg/bin/tic -x -o "$1/$tname" "$1/.terminfo/kitty.terminfo" 2>/dev/null
        fi
        if [ ! -e "$1/$tname/x/xterm-kitty" ]; then
            command ln -sf "../../.terminfo.cdb" "$1/$tname/x/xterm-kitty"
        fi
        tname=".terminfo.cdb"
    fi

    # export TERMINFO
    export TERMINFO="$HOME/$tname"

    # compile terminfo for this system
    if [ -x "$(command -v tic)" ]; then
        tic_out=$(command tic -x -o "$1/$tname" "$1/.terminfo/kitty.terminfo" 2>&1)
        [ $? = 0 ] || die "Failed to compile terminfo with err: $tic_out"
    fi
}

parse_passwd_record() {
    printf "%s" "$(command grep -o '[^:]*$')"
}

login_shell_is_ok() {
    [ -n "$1" ] && login_shell=$(echo $1 | parse_passwd_record)
    [ -n "$login_shell" -a -x "$login_shell" ] && return 0
    return 1
}

using_getent() {
    cmd=$(command -v getent) && [ -n "$cmd" ] && output=$(command "$cmd" passwd "$USER" 2>/dev/null) \
    && login_shell_is_ok "$output"
}

using_id() {
    cmd=$(command -v id) && [ -n "$cmd" ] && output=$(command "$cmd" -P "$USER" 2>/dev/null) \
    && login_shell_is_ok "$output"
}

using_python() {
    detect_python && output=$(command "$python" -c "import pwd, os; print(pwd.getpwuid(os.geteuid()).pw_shell)" 2>/dev/null) \
    && login_shell="$output" && login_shell_is_ok
}

using_perl() {
    detect_perl && output=$(command "$perl" -e 'my $shell = (getpwuid($<))[8]; print $shell' 2>/dev/null) \
    && login_shell="$output" && login_shell_is_ok
}

using_passwd() {
    [ -f "/etc/passwd" -a -r "/etc/passwd" ] && output=$(command grep "^$USER:" /etc/passwd 2>/dev/null) \
    && login_shell_is_ok "$output"
}

using_shell_env() {
    [ -n "$SHELL" ] && login_shell="$SHELL" && login_shell_is_ok
}

execute_with_python() {
    if detect_python; then
        exec "$python" "-c" "import os; os.execlp('$login_shell', '-' '$shell_name')"
    fi
    return 1
}

execute_with_perl() {
    if detect_perl; then
        exec "$perl" "-e" "exec {'$login_shell'} '-$shell_name'"
    fi
    return 1
}

exec_zsh_with_integration() {
    zdotdir="$ZDOTDIR"
    if [ -z "$zdotdir" ]; then
        zdotdir=~
    else
        export KITTY_ORIG_ZDOTDIR="$zdotdir"
    fi
    # dont prevent zsh-newuser-install from running
    if [ -f "$zdotdir/.zshrc" -o -f "$zdotdir/.zshenv" -o -f "$zdotdir/.zprofile" -o -f "$zdotdir/.zlogin" ]; then
        export ZDOTDIR="$shell_integration_dir/zsh"
        exec "$login_shell" "-l"
    fi
    # ensure this is not propagated
    unset KITTY_ORIG_ZDOTDIR
}

exec_fish_with_integration() {
    if [ -z "$XDG_DATA_DIRS" ]; then
        export XDG_DATA_DIRS="$shell_integration_dir"
    else
        export XDG_DATA_DIRS="$shell_integration_dir:$XDG_DATA_DIRS"
    fi
    export KITTY_FISH_XDG_DATA_DIR="$shell_integration_dir"
    exec "$login_shell" "-l"
}

exec_bash_with_integration() {
    export ENV="$shell_integration_dir/bash/kitty.bash"
    export KITTY_BASH_INJECT="1"
    if [ -z "$HISTFILE" ]; then
        export HISTFILE="$HOME/.bash_history"
        export KITTY_BASH_UNEXPORT_HISTFILE="1"
    fi
    exec "$login_shell" "--login" "--posix"
}

exec_with_shell_integration() {
    [ -z "$shell_integration_dir" ] && return
    case "$shell_name" in
        "zsh")
            exec_zsh_with_integration
            ;;
        "fish")
            exec_fish_with_integration
            ;;
        "bash")
            exec_bash_with_integration
            ;;
    esac
}

execute_sh_with_posix_env() {
    # only for sh as that is likely to be POSIX compliant
    [ "$shell_name" = "sh" ] || return
    # sh supports -l so use that
    command "$login_shell" -l -c ":" > /dev/null 2> /dev/null && return
    [ -z "$shell_integration_dir" ] && die "Could not read data over tty ssh kitten cannot function"
    sh_dir="$shell_integration_dir/sh"
    command mkdir -p "$sh_dir" || die "Creating directory $sh_dir failed"
    sh_script="$sh_dir/login_shell_env.sh"
    # Source /etc/profile, ~/.profile, and then check and source ENV
    printf "%s" '
if [ -n "$KITTY_SH_INJECT" ]; then
    unset ENV; unset KITTY_SH_INJECT
    _ksi_safe_source() { [ -f "$1" -a -r "$1" ] || return 1; . "$1"; return 0; }
    [ -n "$KITTY_SH_POSIX_ENV" ] && export ENV="$KITTY_SH_POSIX_ENV"
    unset KITTY_SH_POSIX_ENV
    _ksi_safe_source "/etc/profile"; _ksi_safe_source "${HOME-}/.profile"
    [ -n "$ENV" ] && _ksi_safe_source "$ENV"
    unset -f _ksi_safe_source
fi' > "$sh_script"
    export KITTY_SH_INJECT="1"
    [ -n "$ENV" ] && export KITTY_SH_POSIX_ENV="$ENV"
    export ENV="$sh_script"
    exec "$login_shell"
}

install_kitty_bootstrap() {
    kitty_exists="n"
    command -v kitty 2> /dev/null > /dev/null && kitty_exists="y"
    if [ "$kitty_remote" = "yes" -o "$kitty_remote-$kitty_exists" = "if-needed-n" ]; then
        kitty_dir="$data_dir/kitty/bin"
        if [ "$kitty_exists" = "y" ]; then
            export PATH="$kitty_dir:$PATH"
        else
            export PATH="$PATH:$kitty_dir"
        fi
    fi
}

prepare_for_exec() {
    if [ -n "$leading_data" ]; then
        # clear current line as it might have things echoed on it from leading_data
        # because we only turn off echo in this script whereas the leading bytes could
        # have been sent before the script had a chance to run
        printf "\r\033[K" > /dev/tty
    fi
    [ -f "$HOME/.terminfo/kitty.terminfo" ] || die "Incomplete extraction of ssh data"
    install_kitty_bootstrap

    [ -n "$login_shell" ] || using_getent || using_id || using_python || using_perl || using_passwd || using_shell_env || login_shell="sh"
    case "$login_shell" in
        /*) ;;
        *)
            if ! command -v "$login_shell" > /dev/null 2> /dev/null; then
                for i in /opt/homebrew/bin /opt/homebrew/sbin /opt/local/bin /opt/local/sbin /usr/local/bin /usr/bin /bin /usr/sbin /sbin
                do
                    if [ -x "$i/$login_shell" ]; then
                        login_shell="$i/$login_shell"
                        break
                    fi
                done
            fi
            ;;
    esac
    shell_name=$(command basename $login_shell)
    [ -n "$login_cwd" ] && cd "$login_cwd"
}

exec_login_shell() {
    case "$KITTY_SHELL_INTEGRATION" in
        ("")
            # only blanks or unset
            unset KITTY_SHELL_INTEGRATION
            ;;
        (*)
            # not blank
            printf "%s" "$KITTY_SHELL_INTEGRATION" | command grep -q '\bno-rc\b' || exec_with_shell_integration
            # either no-rc or exec failed
            unset KITTY_SHELL_INTEGRATION
            ;;
    esac

    # We need to pass the first argument to the executed program with a leading -
    # to make sure the shell executes as a login shell. Note that not all shells
    # support exec -a so we use the below to try to detect such shells
    [ "$(exec -a echo echo OK 2> /dev/null)" = "OK" ] && exec -a "-$shell_name" "$login_shell"
    execute_with_python
    execute_with_perl
    execute_sh_with_posix_env
    exec "$login_shell" "-l"
    printf "%s\n" "Could not execute the shell $login_shell as a login shell" > /dev/stderr
    exec "$login_shell"
}
