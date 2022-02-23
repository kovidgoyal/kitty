#!/bin/sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
# Distributed under terms of the GPLv3 license.

# read the transmitted data from STDIN
saved_tty_settings=$(command stty -g)
command stty raw -echo
encoded_data_file=$(mktemp)

cleanup_on_bootstrap_exit() {
    [ ! -z "$encoded_data_file" ] && command rm -f "$encoded_data_file"
    [ ! -z "$saved_tty_settings" ] && command stty "$saved_tty_settings"
}
trap 'cleanup_on_bootstrap_exit' EXIT
die() { echo "$*" >/dev/stderr; cleanup_on_bootstrap_exit; exit 1; }

data_started="n"
data_complete="n"
pending_data=""
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
pending_data=""
data_complete="n"
printf "\033P@kitty-ssh|%s:%s:%s\033\\" "$hostname" "$password_filename" "$data_password"

while [ "$data_complete" = "n" ]; do
    IFS= read -r line || die "Incomplete ssh data";
    case "$line" in
        *"KITTY_SSH_DATA_START")
            prefix=$(command expr "$line" : "\(.*\)KITTY_SSH_DATA_START")
            pending_data="$pending_data$prefix"
            data_started="y";
            ;;
        "KITTY_SSH_DATA_END")
            data_complete="y";
            ;;
        *)
            if [ "$data_started" = "y" ]; then
                echo -n "$line" >> "$encoded_data_file"
            else
                pending_data="$pending_data$line\n"
            fi
            ;;
    esac
done
command stty "$saved_tty_settings"
saved_tty_settings=""
if [ -n "$pending_data" ]; then
    printf "\033P@kitty-echo|%s\033\\" "$(echo -n "$pending_data" | base64)"
fi
command base64 -d < "$encoded_data_file" | command tar xjf - --no-same-owner -C "$HOME"
rc=$?
command rm -f "$encoded_data_file"
encoded_data_file=""
if [ "$rc" != "0" ]; then die "Failed to extract data transmitted by ssh kitten over the TTY device"; fi

# export TERMINFO
tname=".terminfo"
if [ -e "/usr/share/misc/terminfo.cdb" ]; then
    # NetBSD requires this see https://github.com/kovidgoyal/kitty/issues/4622
    tname=".terminfo.cdb"
fi
export TERMINFO="$HOME/$tname"

# compile terminfo for this system
if [ -x "$(command -v tic)" ]; then
    tic_out=$(command tic -x -o "$HOME/$tname" ".terminfo/kitty.terminfo" 2>&1)
    rc=$?
    if [ "$rc" != "0" ]; then die "$tic_out"; fi
fi

# If a command was passed to SSH execute it here
EXEC_CMD
