#!/bin/sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
# Distributed under terms of the GPLv3 license.

{ \unalias command; \unset -f command; } >/dev/null 2>&1
tdir=""
shell_integration_dir=""
echo_on="ECHO_ON"

cleanup_on_bootstrap_exit() {
    [ "$echo_on" = "1" ] && command stty "echo" 2> /dev/null < /dev/tty
    echo_on="0"
    [ -n "$tdir" ] && command rm -rf "$tdir"
    tdir=""
}

die() {
    if [ -e /dev/stderr ]; then
        printf "\033[31m%s\033[m\n\r" "$*" > /dev/stderr;
    elif [ -e /dev/fd/2 ]; then
        printf "\033[31m%s\033[m\n\r" "$*" > /dev/fd/2;
    else
        printf "\033[31m%s\033[m\n\r" "$*";
    fi
    cleanup_on_bootstrap_exit;
    exit 1;
}

python_detected="0"
detect_python() {
    if [ python_detected = "1" ]; then
        [ -n "$python" ] && return 0
        return 1
    fi
    python_detected="1"
    python=$(command -v python3)
    [ -z "$python" ] && python=$(command -v python2)
    [ -z "$python" ] && python=$(command -v python)
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
elif command -v openssl > /dev/null 2> /dev/null; then
    base64_encode() { command openssl enc -A -base64; }
    base64_decode() { command openssl enc -A -d -base64; }
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

# If $HOME is configured set it here
EXPORT_HOME_CMD
# ensure $HOME is set
[ -z "$HOME" ] && HOME=~
# ensure $USER is set
[ -z "$USER" ] && USER="$LOGNAME"
[ -z "$USER" ] && USER="$(command whoami 2> /dev/null)"

leading_data=""
login_shell=""
login_cwd=""

request_data="REQUEST_DATA"
trap "cleanup_on_bootstrap_exit" EXIT
[ "$request_data" = "1" ] && {
    command stty "-echo" < /dev/tty
    dcs_to_kitty "ssh" "id="REQUEST_ID":pwfile="PASSWORD_FILENAME":pw="DATA_PASSWORD""
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
    command -v tar > /dev/null 2> /dev/null || die "tar is not available on this server. The ssh kitten requires tar."
    tdir=$(command mktemp -d "$HOME/.kitty-ssh-kitten-untar-XXXXXXXXXXXX")
    [ $? = 0 ] || die "Creating temp directory failed"
    # suppress STDERR for tar as tar prints various warnings if for instance, timestamps are in the future
    old_umask=$(umask)
    umask 000
    read_base64_from_tty | base64_decode | command tar "xpzf" "-" "-C" "$tdir" 2> /dev/null
    umask "$old_umask"
    . "$tdir/bootstrap-utils.sh"
    . "$tdir/data.sh"
    [ -z "$KITTY_SSH_KITTEN_DATA_DIR" ] && die "Failed to read SSH data from tty"
    case "$KITTY_SSH_KITTEN_DATA_DIR" in
        /*) data_dir="$KITTY_SSH_KITTEN_DATA_DIR" ;;
        *) data_dir="$HOME/$KITTY_SSH_KITTEN_DATA_DIR"
    esac
    shell_integration_dir="$data_dir/shell-integration"
    unset KITTY_SSH_KITTEN_DATA_DIR
    login_shell="$KITTY_LOGIN_SHELL"
    unset KITTY_LOGIN_SHELL
    login_cwd="$KITTY_LOGIN_CWD"
    unset KITTY_LOGIN_CWD
    kitty_remote="$KITTY_REMOTE"
    unset KITTY_REMOTE
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
prepare_for_exec
# If a command was passed to SSH execute it here
EXEC_CMD

# Used in the tests
TEST_SCRIPT

exec_login_shell
