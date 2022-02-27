#!/bin/sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
# Distributed under terms of the GPLv3 license.

# read the transmitted data from STDIN
cleanup_on_bootstrap_exit() {
    [ ! -z "$saved_tty_settings" ] && command stty "$saved_tty_settings"
}

die() { printf "\033[31m%s\033[m\n" "$*" > /dev/stderr; cleanup_on_bootstrap_exit; exit 1; }
dsc_to_kitty() { printf "\033P@kitty-$1|%s\033\\" "$(printf "%s" "$2" | base64 | tr -d \\n)" > /dev/tty; }
debug() { dsc_to_kitty "print" "debug $1"; }
echo_via_kitty() { dsc_to_kitty "echo" "$1"; }
saved_tty_settings=$(command stty -g)
command stty raw min 1 time 0 -echo || die "stty not available"
trap 'cleanup_on_bootstrap_exit' EXIT

data_started="n"
data_complete="n"
if [ -z "$HOSTNAME" ]; then
    hostname=$(hostname)
    if [ -z "$hostname" ]; then hostname="_"; fi
else
    hostname="$HOSTNAME"
fi
# ensure $HOME is set
if [ -z "$HOME" ]; then HOME=~; fi
# ensure $USER is set
if [ -z "$USER" ]; then USER=$(whoami); fi

# ask for the SSH data
data_password="DATA_PASSWORD"
password_filename="PASSWORD_FILENAME"
data_complete="n"
leading_data=""

dsc_to_kitty "ssh" "hostname=$hostname:pwfile=$password_filename:pw=$data_password"
size=""
record_separator=$(printf "\036")

untar() {
    command base64 -d | command tar xjf - --no-same-owner -C "$HOME" 
}

read_record() {
    # We need a way to read a single byte at a time and to read a specified number of bytes in one invocation.
    # The options are head -c, read -N and dd
    #
    # read -N is not in POSIX and dash/posh dont implement it. Also bash seems to read beyond
    # the specified number of bytes into an internal buffer.
    #
    # head -c reads beyond the specified number of bytes into an internal buffer on macOS
    #
    # POSIX dd works for one byte at a time but for reading X bytes it needs the GNU iflag=count_bytes
    # extension, and is anyway unsafe as it can lead to corrupt output when the read syscall is interrupted.
    record=""
    while :; do
        n=$(command dd bs=1 count=1 2> /dev/null < /dev/tty) 
        [ "$n" = "$record_separator" ] && break
        record="$record$n"
    done
    printf "%s" "$record"
}

get_data() {
    leading_data=$(read_record)
    size=$(read_record)
    case "$size" in
        ("!"*)
            die "$size"
            ;;
    esac
    data_dir=$(read_record)
    case "$data_dir" in 
        ("/"*)
            ;;
        (*)
            data_dir="$HOME/$data_dir"
            ;;
    esac
    # using dd with bs=1 is very slow on Linux, so use head 
    command head -c "$size" < /dev/tty | untar
    rc="$?";
}

get_data
command stty "$saved_tty_settings"
saved_tty_settings=""
if [ -n "$leading_data" ]; then
    # clear current line as it might have things echoed on it from leading_data
    # because we only turn off echo in this script whereas the leading bytes could 
    # have been sent before the script had a chance to run
    printf "\r\033[K"  
fi
if [ "$rc" != "0" ]; then die "Failed to extract data transmitted by ssh kitten over the TTY device"; fi
[ -f "$HOME/.terminfo/kitty.terminfo" ] || die "Incomplete extraction of ssh data, no kitty.terminfo found";
shell_integration_dir="$data_dir/shell-integration"
shell_integration_settings_file="$data_dir/settings/ksi_env_var"

# export TERMINFO
tname=".terminfo"
if [ -e "/usr/share/misc/terminfo.cdb" ]; then
    # NetBSD requires this see https://github.com/kovidgoyal/kitty/issues/4622
    tname=".terminfo.cdb"
fi
export TERMINFO="$HOME/$tname"

# compile terminfo for this system
if [ -x "$(command -v tic)" ]; then
    tic_out=$(command tic -x -o "$HOME/$tname" "$HOME/.terminfo/kitty.terminfo" 2>&1)
    rc=$?
    if [ "$rc" != "0" ]; then die "$tic_out"; fi
fi


login_shell_is_ok() {
    if [ -z "$login_shell" -o ! -x "$login_shell" ]; then return 1; fi
    case "$login_shell" in
        *sh) return 0;
    esac
    return 1;
}

detect_python() {
    python=$(command -v python3)
    if [ -z "$python" ]; then python=$(command -v python2); fi
    if [ -z "$python" ]; then python=$(command -v python); fi
    if [ -z "$python" -o ! -x "$python" ]; then return 1; fi
    return 0;
}

parse_passwd_record() {
    printf "%s" "$(grep -o '[^:]*$')"
}

using_getent() {
    cmd=$(command -v getent)
    if [ -n "$cmd" ]; then 
        output=$($cmd passwd $USER 2>/dev/null)
        if [ $? = 0 ]; then 
            login_shell=$(echo $output | parse_passwd_record);
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1;
}

using_id() {
    cmd=$(command -v id)
    if [ -n "$cmd" ]; then 
        output=$($cmd -P $USER 2>/dev/null)
        if [ $? = 0 ]; then 
            login_shell=$(echo $output | parse_passwd_record);
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1;
}

using_passwd() {
    cmd=$(command -v grep)
    if [ -n "$cmd" ]; then 
        output=$($cmd "^$USER:" /etc/passwd 2>/dev/null)
        if [ $? = 0 ]; then 
            login_shell=$(echo $output | parse_passwd_record);
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1;
}

using_python() {
    if detect_python; then
        output=$($python -c "import pwd, os; print(pwd.getpwuid(os.geteuid()).pw_shell)")
        if [ $? = 0 ]; then 
            login_shell=$output; 
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
}

execute_with_python() {
    if detect_python; then
        exec $python -c "import os; os.execl('$login_shell', '-' '$shell_name')"
    fi
    return 1;
}

# If a command was passed to SSH execute it here
EXEC_CMD

LOGIN_SHELL="OVERRIDE_LOGIN_SHELL"
if [ -n "$LOGIN_SHELL" ]; then
    login_shell="$LOGIN_SHELL"
else
    using_getent || using_id || using_python || using_passwd || die "Could not detect login shell";
fi
shell_name=$(basename $login_shell)

# read the variable and remove all leading and trailing spaces and collapse multiple spaces using xargs
if [  -f "$shell_integration_settings_file" ]; then 
    export KITTY_SHELL_INTEGRATION="$(cat $shell_integration_settings_file | xargs echo)"
else
    unset KITTY_SHELL_INTEGRATION
fi

exec_bash_with_integration() {
    export ENV="$shell_integration_dir/bash/kitty.bash"
    export KITTY_BASH_INJECT="1"
    exec "$login_shell" "--posix"
}

exec_zsh_with_integration() {
    zdotdir="$ZDOTDIR"
    if [ -z "$zdotdir" ]; then 
        zdotdir=~; 
        unset KITTY_ORIG_ZDOTDIR  # ensure this is not propagated
    else
        export KITTY_ORIG_ZDOTDIR="$zdotdir"
    fi
    # dont prevent zsh-new-user from running
    if [ -f "$zdotdir/.zshrc" -o -f "$zdotdir/.zshenv" -o -f "$zdotdir/.zprofile" -o -f "$zdotdir/.zlogin" ]; then
        export ZDOTDIR="$shell_integration_dir/zsh"
        exec "$login_shell" "-l"
    fi
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

exec_with_shell_integration() {
    case "$shell_name" in
        "zsh")
            exec_zsh_with_integration
            ;;
        "bash")
            exec_bash_with_integration
            ;;
        "fish")
            exec_fish_with_integration
            ;;
    esac
}

case "$KITTY_SHELL_INTEGRATION" in
    ("") 
        # only blanks or unset
        unset KITTY_SHELL_INTEGRATION
        ;;
    (*) 
        # not blank
        q=$(printf "%s" "$KITTY_SHELL_INTEGRATION" | grep '\bno-rc\b')
        if [ -z "$q"  ]; then
            exec_with_shell_integration
            # exec failed, unset 
            unset KITTY_SHELL_INTEGRATION
        fi
        ;;
esac

# We need to pass the first argument to the executed program with a leading -
# to make sure the shell executes as a login shell. Note that not all shells
# support exec -a so we use the below to try to detect such shells
if [ -z "$PIPESTATUS" ]; then
    # the dash shell does not support exec -a and also does not define PIPESTATUS
    execute_with_python
    exec $login_shell "-l"
fi
exec -a "-$shell_name" $login_shell
