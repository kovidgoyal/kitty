#!/bin/sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
# Distributed under terms of the GPLv3 license.

tdir=""
shell_integration_dir=""
echo_on="ECHO_ON"

cleanup_on_bootstrap_exit() {
    [ "$echo_on" = "1" ] && command stty "echo" 2> /dev/null < /dev/tty
    echo_on="0"
    [ -n "$tdir" ] && command rm -rf "$tdir"
    tdir=""
}

die() { printf "\033[31m%s\033[m\n\r" "$*" > /dev/stderr; cleanup_on_bootstrap_exit; exit 1; }

python_detected="0"
detect_python() {
    if [ python_detected = "1" ]; then
        [ -n "$python" ] && return 0
        return 1
    fi
    python_detected="1"
    python=$(command -v python3)
    if [ -z "$python" ]; then python=$(command -v python2); fi
    if [ -z "$python" ]; then python=$(command -v python); fi
    if [ -z "$python" -o ! -x "$python" ]; then python=""; return 1; fi
    return 0
}

perl_detected="0"
detect_perl() {
    if [ perl_detected = "1" ]; then
        [ -n "$perl" ] && return 0
        return 1
    fi
    perl_detected="1"
    perl=$(command -v perl)
    if [ -z "$perl" -o ! -x "$perl" ]; then perl=""; return 1; fi
    return 0
}

if command -v base64 > /dev/null 2> /dev/null; then
    base64_encode() { command base64 | command tr -d \\n\\r; }
    base64_decode() { command base64 -d; }
elif command -v b64encode > /dev/null 2> /dev/null; then
    base64_encode() { command b64encode - | command sed '1d;$d' | command tr -d \\n\\r; }
    base64_decode() { command fold -w 76 | command b64decode -r; }
elif detect_python; then
    pybase64() { command "$python" -c "import sys, base64; getattr(sys.stdout, 'buffer', sys.stdout).write(base64.standard_b64$1(getattr(sys.stdin, 'buffer', sys.stdin).read()))"; }
    base64_encode() { pybase64 "encode"; }
    base64_decode() { pybase64 "decode"; }
elif detect_perl; then
    base64_encode() { command "$perl" -MMIME::Base64 -0777 -ne 'print encode_base64($_)'; }
    base64_decode() { command "$perl" -MMIME::Base64 -ne 'print decode_base64($_)'; }
else
    die "base64 executable not present on remote host, ssh kitten cannot function."
fi

dcs_to_kitty() { printf "\033P@kitty-$1|%s\033\134" "$(printf "%s" "$2" | base64_encode)" > /dev/tty; }
debug() { dcs_to_kitty "print" "debug: $1"; }
echo_via_kitty() { dcs_to_kitty "echo" "$1"; }

# ensure $HOME is set
[ -z "$HOME" ] && HOME=~
# ensure $USER is set
[ -z "$USER" ] && USER="$LOGNAME"
[ -z "$USER" ] && USER="$(command whoami 2> /dev/null)"

leading_data=""
login_cwd=""

request_data="REQUEST_DATA"
trap "cleanup_on_bootstrap_exit" EXIT
[ "$request_data" = "1" ] && {
    command stty "-echo" < /dev/tty
    dcs_to_kitty "ssh" "id="REQUEST_ID":pwfile="PASSWORD_FILENAME":pw="DATA_PASSWORD""
}

mv_files_and_dirs() {
    cwd="$PWD"
    cd "$1"
    command find . -type d -exec mkdir -p "$2/{}" ";"
    command find . -type l -exec sh -c "tgt=\$(command readlink -n \"{}\"); command ln -snf \"\$tgt\" \"$2/{}\"; command rm -f \"{}\"" ";"
    command find . -type f -exec mv "{}" "$2/{}" ";"
    cd "$cwd"
}

compile_terminfo() {
    # export TERMINFO
    tname=".terminfo"
    if [ -e "/usr/share/misc/terminfo.cdb" ]; then
        # NetBSD requires this see https://github.com/kovidgoyal/kitty/issues/4622
        tname=".terminfo.cdb"
    fi
    export TERMINFO="$HOME/$tname"

    # compile terminfo for this system
    if [ -x "$(command -v tic)" ]; then
        tic_out=$(command tic -x -o "$1/$tname" "$1/.terminfo/kitty.terminfo" 2>&1)
        [ $? = 0 ] || die "Failed to compile terminfo with err: $tic_out"
    fi

    # Ensure the 78 dir is present
    if [ ! -f "$1/$tname/78/xterm-kitty" ]; then
        command mkdir -p "$1/$tname/78"
        command ln -sf "../x/xterm-kitty" "$1/$tname/78/xterm-kitty"
    fi
}

read_base64_from_tty() {
    while IFS= read -r line; do
        [ "$line" = "KITTY_DATA_END" ] && return 0
        printf "%s" "$line"
    done
}

untar_and_read_env() {
    # extract the tar file atomically, in the sense that any file from the
    # tarfile is only put into place after it has been fully written to disk
    tdir=$(command mktemp -d "$HOME/.kitty-ssh-kitten-untar-XXXXXXXXXXXX")
    [ $? = 0 ] || die "Creating temp directory failed"
    # suppress STDERR for tar as tar prints various warnings if for instance, timestamps are in the future
    read_base64_from_tty | base64_decode | command tar "xpzf" "-" "-C" "$tdir" 2> /dev/null
    data_file="$tdir/data.sh"
    [ -f "$data_file" ] && . "$data_file"
    [ -z "$KITTY_SSH_KITTEN_DATA_DIR" ] && die "Failed to read SSH data from tty"
    data_dir="$HOME/$KITTY_SSH_KITTEN_DATA_DIR"
    shell_integration_dir="$data_dir/shell-integration"
    unset KITTY_SSH_KITTEN_DATA_DIR
    login_cwd="$KITTY_LOGIN_CWD"
    unset KITTY_LOGIN_CWD
    compile_terminfo "$tdir/home"
    mv_files_and_dirs "$tdir/home" "$HOME"
    [ -e "$tdir/root" ] && mv_files_and_dirs "$tdir/root" ""
    command rm -rf "$tdir"
    tdir=""
}

get_data() {
    started="n"
    while IFS= read -r line; do
        if [ "$started" = "y" ]; then
            [ "$line" = "OK" ] && break
            die "$line"
        else
            if [ "$line" = "KITTY_DATA_START" ]; then
                started="y"
            else
                leading_data="$leading_data$line"
            fi
        fi
    done
    untar_and_read_env
}

# ask for the SSH data
get_data
cleanup_on_bootstrap_exit
if [ -n "$leading_data" ]; then
    # clear current line as it might have things echoed on it from leading_data
    # because we only turn off echo in this script whereas the leading bytes could
    # have been sent before the script had a chance to run
    printf "\r\033[K" > /dev/tty
fi
[ -f "$HOME/.terminfo/kitty.terminfo" ] || die "Incomplete extraction of ssh data"

login_shell_is_ok() {
    if [ -n "$login_shell" -a -x "$login_shell" ]; then return 0; fi
    return 1
}

parse_passwd_record() {
    printf "%s" "$(command grep -o '[^:]*$')"
}

using_getent() {
    cmd=$(command -v getent)
    if [ -n "$cmd" ]; then
        output=$(command "$cmd" passwd "$USER" 2>/dev/null)
        if [ $? = 0 ]; then
            login_shell=$(echo $output | parse_passwd_record)
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
}

using_id() {
    cmd=$(command -v id)
    if [ -n "$cmd" ]; then
        output=$(command "$cmd" -P "$USER" 2>/dev/null)
        if [ $? = 0 ]; then
            login_shell=$(echo $output | parse_passwd_record)
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
}

using_python() {
    if detect_python; then
        output=$(command "$python" -c "import pwd, os; print(pwd.getpwuid(os.geteuid()).pw_shell)")
        if [ $? = 0 ]; then
            login_shell="$output"
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
}

using_perl() {
    if detect_perl; then
        output=$(command "$perl" -e 'my $shell = (getpwuid($<))[8]; print $shell')
        if [ $? = 0 ]; then
            login_shell="$output"
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
}

using_passwd() {
    if [ -f "/etc/passwd" -a -r "/etc/passwd" ]; then
        output=$(command grep "^$USER:" /etc/passwd 2>/dev/null)
        if [ $? = 0 ]; then
            login_shell=$(echo $output | parse_passwd_record)
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
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

if [ -n "$KITTY_LOGIN_SHELL" ]; then
    login_shell="$KITTY_LOGIN_SHELL"
    unset KITTY_LOGIN_SHELL
else
    using_getent || using_id || using_python || using_perl || using_passwd || die "Could not detect login shell"
fi
shell_name=$(command basename $login_shell)
[ -n "$login_cwd" ] && cd "$login_cwd"

# If a command was passed to SSH execute it here
EXEC_CMD

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
    unset KITTY_ORIG_ZDOTDIR  # ensure this is not propagated
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
    exec "$login_shell" "--posix"
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
    [ "$shell_name" = "sh" ] || return  # only for sh as that is likely to be POSIX compliant
    command "$login_shell" -l -c ":" > /dev/null 2> /dev/null && return  # sh supports -l so use that
    [ -z "$shell_integration_dir" ] && die "Could not read data over tty ssh kitten cannot function"
    sh_dir="$shell_integration_dir/sh"
    command mkdir -p "$sh_dir" || die "Creating $sh_dir failed"
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

# Used in the tests
TEST_SCRIPT

case "$KITTY_SHELL_INTEGRATION" in
    ("")
        # only blanks or unset
        unset KITTY_SHELL_INTEGRATION
        ;;
    (*)
        # not blank
        printf "%s" "$KITTY_SHELL_INTEGRATION" | command grep '\bno-rc\b' || exec_with_shell_integration
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
