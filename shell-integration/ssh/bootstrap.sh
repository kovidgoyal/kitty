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
    . "$tdir/bootstrap-utils.sh"
    . "$tdir/data.sh"
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

if [ -n "$KITTY_LOGIN_SHELL" ]; then
    login_shell="$KITTY_LOGIN_SHELL"
    unset KITTY_LOGIN_SHELL
else
    using_getent || using_id || using_python || using_perl || using_passwd || using_shell_env || login_shell="sh"
fi
shell_name=$(command basename $login_shell)
[ -n "$login_cwd" ] && cd "$login_cwd"

# If a command was passed to SSH execute it here
EXEC_CMD

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
