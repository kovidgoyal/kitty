#!/bin/sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
# Distributed under terms of the GPLv3 license.

saved_tty_settings=""
tdir=""
shell_integration_dir=""
cleanup_on_bootstrap_exit() {
    [ -n "$saved_tty_settings" ] && command stty "$saved_tty_settings" 2> /dev/null < /dev/tty
    [ -n "$tdir" ] && command rm -rf "$tdir"
    saved_tty_settings=""
    tdir=""
}

die() { printf "\033[31m%s\033[m\n\r" "$*" > /dev/stderr; cleanup_on_bootstrap_exit; exit 1; }

python_detected="0"
detect_python() {
    if [ python_detected = "1" ]; then
        [ -n "$python" ] && return 0;
        return 1;
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
        [ -n "$perl" ] && return 0;
        return 1;
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

init_tty() {
    saved_tty_settings=$(command stty -g 2> /dev/null < /dev/tty)
    tty_ok="n"
    [ -n "$saved_tty_settings" ] && tty_ok="y"

    if [ "$tty_ok" = "y" ]; then
        command stty raw min 1 time 0 -echo 2> /dev/null < /dev/tty || die "stty failed to set raw mode"
        return 0
    fi
    return 1
}

# try to use zsh's builtin sysread function for reading to TTY
# as it is superior to the POSIX variants. The builtin read function doesn't work
# as it hangs reading N bytes on macOS
tty_fd=-1
if [ -n "$ZSH_VERSION" ] && builtin zmodload zsh/system 2> /dev/null; then
    builtin sysopen -o cloexec -rwu tty_fd -- "$TTY" 2> /dev/null
    [ $tty_fd = -1 ] && builtin sysopen -o cloexec -rwu tty_fd -- /dev/tty 2> /dev/null
fi
if [ $tty_fd -gt -1 ]; then
    dcs_to_kitty() {
        builtin local b64data
        b64data=$(builtin printf "%s" "$2" | base64_encode)
        builtin print -nu "$tty_fd" '\eP@kitty-'"${1}|${b64data//[[:space:]]}"'\e\\'
    }
    read_one_byte_from_tty() {
        builtin sysread -s "1" -i "$tty_fd" n 2> /dev/null
        return $?
    }
    read_n_bytes_from_tty() {
        builtin let num_left=$1
        while [ $num_left -gt 0 ]; do
            builtin sysread -c num_read -s "$num_left" -i "$tty_fd" -o "1" 2> /dev/null || die "Failed to read $num_left bytes from TTY using sysread"
            builtin let num_left=$num_left-$num_read
        done
    }
else
    dcs_to_kitty() { printf "\033P@kitty-$1|%s\033\134" "$(printf "%s" "$2" | base64_encode)" > /dev/tty; }

    read_one_byte_from_tty() {
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
        n=$(command dd bs=1 count=1 2> /dev/null < /dev/tty)
        return $?
    }

    if [ "$(printf "%s" "test" | command head -c 3 2> /dev/null)" = "tes" ]; then
        # Using dd with ibs=1 is very slow, so use head. On non GNU coreutils head
        # does not limit itself to reading -c bytes only from the pipe so we can potentially lose
        # some trailing data, for instance if the user starts typing. Cant be helped.
        read_n_bytes_from_tty() {
            command head -c "$1" < /dev/tty
        }
    elif detect_python; then
        read_n_bytes_from_tty() {
            command "$python" "-c" "
import sys, os, errno
def eintr_retry(func, *args):
    while True:
        try:
            return func(*args)
        except EnvironmentError as e:
            if e.errno != errno.EINTR:
                raise
n = $1
in_fd = sys.stdin.fileno()
out_fd = sys.stdout.fileno()
while n > 0:
    d = memoryview(eintr_retry(os.read, in_fd, n))
    n -= len(d)
    while d:
        nw = eintr_retry(os.write, out_fd, d)
        d = d[nw:]
" < /dev/tty
        }
    elif detect_perl; then
        read_n_bytes_from_tty() {
            command "$perl" -MList::Util=min -e \
'open(my $fh,"</dev/tty"); binmode($fh); my ($n,$buf)=(@ARGV[0],"");'\
'while($n){my $rv=sysread($fh,$buf,min(65536,$n)); die($!) if !defined($rv); die() if !$rv; $n-=$rv; print $buf;}' "$1" 2> /dev/null
        }
    else
        read_n_bytes_from_tty() {
            command dd ibs=1 count="$1" < /dev/tty 2> /dev/null
        }
    fi
fi

debug() { dcs_to_kitty "print" "debug: $1"; }
echo_via_kitty() { dcs_to_kitty "echo" "$1"; }

hostname="$HOSTNAME"
[ -z "$hostname" ] && hostname="$(command hostname 2> /dev/null)"
[ -z "$hostname" ] && hostname="$(command hostnamectl hostname 2> /dev/null)"
[ -z "$hostname" ] && hostname="$(command uname -m 2> /dev/null)"
[ -z "$hostname" ] && hostname="_"
# ensure $HOME is set
[ -z "$HOME" ] && HOME=~
# ensure $USER is set
[ -z "$USER" ] && USER="$(command whoami 2> /dev/null)"

leading_data=""
login_cwd=""

init_tty && trap "cleanup_on_bootstrap_exit" EXIT
if [ "$tty_ok" = "y" ]; then
    compression="gz"
    command -v "bzip2" > /dev/null 2> /dev/null && compression="bz2"
    dcs_to_kitty "ssh" "id="REQUEST_ID":hostname="$hostname":pwfile="PASSWORD_FILENAME":user="$USER":compression="$compression":pw="DATA_PASSWORD""
fi
record_separator=$(printf "\036")

mv_files_and_dirs() {
    cwd="$PWD"
    cd "$1"
    command find . -type d -exec mkdir -p "$2/{}" ";"
    command find . -type l -exec sh -c "tgt=\$(command readlink -n \"{}\"); command ln -sf \"\$tgt\" \"$2/{}\"; command rm -f \"{}\"" ";"
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
        [ $? = 0 ] || die "Failed to compile terminfo with err: $tic_out";
    fi
}

untar_and_read_env() {
    # extract the tar file atomically, in the sense that any file from the
    # tarfile is only put into place after it has been fully written to disk

    tdir=$(command mktemp -d "$HOME/.kitty-ssh-kitten-untar-XXXXXXXXXXXX")
    [ $? = 0 ] || die "Creating temp directory failed"
    cflag="j"
    [ "$compression" = "gz" ] && cflag="z"
    read_n_bytes_from_tty "$1" | base64_decode | command tar "x${cflag}pf" - -C "$tdir"
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

read_record() {
    record=""
    while :; do
        read_one_byte_from_tty || die "Reading a byte from the TTY failed"
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
    untar_and_read_env "$size"
}

if [ "$tty_ok" = "y" ]; then
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
fi

login_shell_is_ok() {
    if [ -z "$login_shell" -o ! -x "$login_shell" ]; then return 1; fi
    case "$login_shell" in
        *sh) return 0;
    esac
    return 1
}

parse_passwd_record() {
    printf "%s" "$(command grep -o '[^:]*$')"
}

using_getent() {
    cmd=$(command -v getent)
    if [ -n "$cmd" ]; then
        output=$(command $cmd passwd $USER 2>/dev/null)
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
        output=$(command $cmd -P $USER 2>/dev/null)
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
            login_shell=$output
            if login_shell_is_ok; then return 0; fi
        fi
    fi
    return 1
}

using_perl() {
    if detect_perl; then
        output=$(command "$perl" -e 'my $shell = (getpwuid($<))[8]; print $shell')
        if [ $? = 0 ]; then
            login_shell=$output
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

if [ "$tty_ok" = "n" ]; then
    if [ -z "$(command -v stty)" ]; then
        printf "%s\n" "stty missing ssh kitten cannot function" > /dev/stderr
    else
        printf "%s\n" "stty failed ssh kitten cannot function" > /dev/stderr
    fi
fi

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
    command mkdir -p "$sh_dir" || die "Creating $sh_dir failed";
    sh_script="$sh_dir/login_shell_env.sh"
    # Source /etc/profile, ~/.profile, and then check and source ENV
    printf "%s" '
if [ -n "$KITTY_SH_INJECT" ]; then
    unset ENV; unset KITTY_SH_INJECT
    _ksi_safe_source() { if [ -f "$1" -a -r "$1" ]; then . "$1"; return 0; fi; return 1; }
    if [ -n "$KITTY_SH_POSIX_ENV" ]; then export ENV="$KITTY_SH_POSIX_ENV"; fi
    unset KITTY_SH_POSIX_ENV
    _ksi_safe_source "/etc/profile"; _ksi_safe_source "${HOME-}/.profile"
    if [ -n "$ENV" ]; then _ksi_safe_source "$ENV"; fi
fi' > "$sh_script"
    export KITTY_SH_INJECT=1
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
[ "$(exec -a echo echo OK 2> /dev/null)" = "OK" ] && exec -a "-$shell_name" $login_shell
execute_with_python
execute_with_perl
execute_sh_with_posix_env
exec $login_shell "-l"
