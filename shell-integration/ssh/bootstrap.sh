#!/bin/sh
# Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
# Distributed under terms of the GPLv3 license.

# read the transmitted data from STDIN
saved_tty_settings=$(command stty -g)
command stty -echo
encoded_data_file=$(mktemp)

cleanup_on_bootstrap_exit() {
    [[ ! -z "$encoded_data_file" ]] && command rm -f "$encoded_data_file"
    [[ ! -z "$saved_tty_settings" ]] && command stty "$saved_tty_settings"
}
trap 'cleanup_on_bootstrap_exit' EXIT

data_started="n"
data_complete="n"
pending_data=""
if [[ -z "$HOSTNAME" ]]; then
    hostname=$(hostname)
    if [[ -z "$hostname" ]]; then hostname="_"; fi
else
    hostname=$(HOSTNAME)
fi
# ensure $HOME is set
if [[ -z "$HOME" ]]; then HOME=~; fi
# ensure $USER is set
if [[ -z "$USER" ]]; then USER=$(whoami); fi

# ask for the SSH data
data_password="DATA_PASSWORD"
password_filename="PASSWORD_FILENAME"
printf "\eP@kitty-ssh|$hostname:$password_filename:$data_password\e\\"

while IFS= read -r line; do
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
            if [[ "$data_started" == "y" ]]; then
                echo -n "$line" >> "$encoded_data_file"
            else
                pending_data="$pending_data$line\n"
            fi
            ;;
    esac
    if [[ "$data_complete" == "y" ]]; then break; fi
done
command stty "$saved_tty_settings"
saved_tty_settings=""
if [[ ! -z "$pending_data" ]]; then
    printf "\eP@kitty-echo|$(echo -n "$pending_data" | base64)\e\\"
fi
command base64 -d < "$encoded_data_file" | command tar xjf - --no-same-owner -C "$HOME"
rc=$?
command rm -f "$encoded_data_file"
encoded_data_file=""
if [[ "$rc" != "0" ]]; then echo "Failed to extract data transmitted by ssh kitten over the TTY device" > /dev/stderr; exit 1; fi

# compile terminfo for this system
if [[ -x "$(command -v tic)" ]]; then
    tname=".terminfo"
    if [[ -e "/usr/share/misc/terminfo.cdb" ]]; then
        # NetBSD requires this see https://github.com/kovidgoyal/kitty/issues/4622
        tname=".terminfo.cdb"
    fi
    tic_out=$(command tic -x -o "$HOME/$tname" ".terminfo/kitty.terminfo" 2>&1)
    rc=$?
    if [[ "$rc" != "0" ]]; then echo "$tic_out"; exit 1; fi
    export TERMINFO="$HOME/$tname"
fi

# If a command was passed to SSH execute it here
EXEC_CMD


