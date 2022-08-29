#!/bin/bash

if [[ "$-" != *i* ]] ; then builtin return; fi  # check in interactive mode
if [[ -z "$KITTY_SHELL_INTEGRATION" ]]; then builtin return; fi

# Load the normal bash startup files
if [[ -n "$KITTY_BASH_INJECT" ]]; then
    builtin declare kitty_bash_inject="$KITTY_BASH_INJECT"
    builtin declare ksi_val="$KITTY_SHELL_INTEGRATION"
    builtin unset KITTY_SHELL_INTEGRATION  # ensure manual sourcing of this file in bashrc does not have any effect
    builtin unset KITTY_BASH_INJECT ENV
    if [[ -z "$HOME" ]]; then HOME=~; fi
    if [[ -z "$KITTY_BASH_ETC_LOCATION" ]]; then KITTY_BASH_ETC_LOCATION="/etc"; fi

    _ksi_sourceable() {
        [[ -f "$1" && -r "$1" ]] && return 0; return 1;
    }

    if [[ "$kitty_bash_inject" == *"posix"* ]]; then
        _ksi_sourceable "$KITTY_BASH_POSIX_ENV" && {
            builtin source "$KITTY_BASH_POSIX_ENV"
            builtin export ENV="$KITTY_BASH_POSIX_ENV"
        }
    else
        builtin set +o posix
        builtin shopt -u inherit_errexit 2>/dev/null  # resetting posix does not clear this
        if [[ -n "$KITTY_BASH_UNEXPORT_HISTFILE" ]]; then
            builtin export -n HISTFILE
            builtin unset KITTY_BASH_UNEXPORT_HISTFILE
        fi

        # See run_startup_files() in shell.c in the Bash source code
        if builtin shopt -q login_shell; then
            if [[ "$kitty_bash_inject" != *"no-profile"* ]]; then
                _ksi_sourceable "$KITTY_BASH_ETC_LOCATION/profile" && builtin source "$KITTY_BASH_ETC_LOCATION/profile"
                for _ksi_i in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
                    _ksi_sourceable "$_ksi_i" && { builtin source "$_ksi_i"; break; }
                done
            fi
        else
            if [[ "$kitty_bash_inject" != *"no-rc"* ]]; then
                # Linux distros build bash with -DSYS_BASHRC. Unfortunately, there is
                # no way to to probe bash for it and different distros use different files
                # Arch, Debian, Ubuntu use /etc/bash.bashrc
                # Fedora uses /etc/bashrc sourced from ~/.bashrc instead of SYS_BASHRC
                # Void Linux uses /etc/bash/bashrc
                for _ksi_i in "$KITTY_BASH_ETC_LOCATION/bash.bashrc" "$KITTY_BASH_ETC_LOCATION/bash/bashrc" ; do
                    _ksi_sourceable "$_ksi_i" && { builtin source "$_ksi_i"; break; }
                done
                if [[ -z "$KITTY_BASH_RCFILE" ]]; then KITTY_BASH_RCFILE="$HOME/.bashrc"; fi
                _ksi_sourceable "$KITTY_BASH_RCFILE" && builtin source "$KITTY_BASH_RCFILE"
            fi
        fi
    fi
    builtin unset KITTY_BASH_RCFILE KITTY_BASH_POSIX_ENV KITTY_BASH_ETC_LOCATION
    builtin unset -f _ksi_sourceable
    builtin export KITTY_SHELL_INTEGRATION="$ksi_val"
    builtin unset _ksi_i ksi_val kitty_bash_inject
fi


if [ "${BASH_VERSINFO:-0}" -lt 4 ]; then
    builtin unset KITTY_SHELL_INTEGRATION
    builtin printf "%s\n" "Bash version ${BASH_VERSION} too old, kitty shell integration disabled" > /dev/stderr
    builtin return
fi

if [[ "${_ksi_prompt[sourced]}" == "y" ]]; then
    # we have already run
    builtin unset KITTY_SHELL_INTEGRATION
    builtin return
fi

# this is defined outside _ksi_main to make it global without using declare -g
# which is not available on older bash
builtin declare -A _ksi_prompt
_ksi_prompt=(
    [cursor]='y' [title]='y' [mark]='y' [complete]='y' [cwd]='y' [ps0]='' [ps0_suffix]='' [ps1]='' [ps1_suffix]='' [ps2]=''
    [hostname_prefix]='' [sourced]='y' [last_reported_cwd]=''
)

_ksi_main() {
    builtin local ifs="$IFS"
    IFS=" "
    for i in ${KITTY_SHELL_INTEGRATION[@]}; do
        case "$i" in
            "no-cursor") _ksi_prompt[cursor]='n';;
            "no-title") _ksi_prompt[title]='n';;
            "no-prompt-mark") _ksi_prompt[mark]='n';;
            "no-complete") _ksi_prompt[complete]='n';;
            "no-cwd") _ksi_prompt[cwd]='n';;
        esac
    done
    IFS="$ifs"

    builtin unset KITTY_SHELL_INTEGRATION

    _ksi_debug_print() {
        # print a line to STDERR of parent kitty process
        builtin local b
        b=$(builtin command base64 <<< "${@}")
        builtin printf "\eP@kitty-print|%s\e\\" "${b//[[:space:]]}}"
    }

    _ksi_set_mark() {
        _ksi_prompt["${1}_mark"]="\[\e]133;k;${1}_kitty\a\]"
    }

    _ksi_set_mark start
    _ksi_set_mark end
    _ksi_set_mark start_secondary
    _ksi_set_mark end_secondary
    _ksi_set_mark start_suffix
    _ksi_set_mark end_suffix
    builtin unset -f _ksi_set_mark
    _ksi_prompt[secondary_prompt]="\n${_ksi_prompt[start_secondary_mark]}\[\e]133;A;k=s\a\]${_ksi_prompt[end_secondary_mark]}"

    _ksi_prompt_command() {
        # we first remove any previously added kitty code from the prompt variables and then add
        # it back, to ensure we have only a single instance
        if [[ -n "${_ksi_prompt[ps0]}" ]]; then
            PS0=${PS0//\\\[\\e\]133;k;start_kitty\\a\\\]*end_kitty\\a\\\]}
            PS0="${_ksi_prompt[ps0]}$PS0"
        fi
        if [[ -n "${_ksi_prompt[ps0_suffix]}" ]]; then
            PS0=${PS0//\\\[\\e\]133;k;start_suffix_kitty\\a\\\]*end_suffix_kitty\\a\\\]}
            PS0="${PS0}${_ksi_prompt[ps0_suffix]}"
        fi
        # restore PS1 to its pristine state without our additions
        if [[ -n "${_ksi_prompt[ps1]}" ]]; then
            PS1=${PS1//\\\[\\e\]133;k;start_kitty\\a\\\]*end_kitty\\a\\\]}
            PS1=${PS1//\\\[\\e\]133;k;start_secondary_kitty\\a\\\]*end_secondary_kitty\\a\\\]}
        fi
        if [[ -n "${_ksi_prompt[ps1_suffix]}" ]]; then
            PS1=${PS1//\\\[\\e\]133;k;start_suffix_kitty\\a\\\]*end_suffix_kitty\\a\\\]}
        fi
        if [[ -n "${_ksi_prompt[ps1]}" ]]; then
            if [[ "${_ksi_prompt[mark]}" == "y" && ( "${PS1}" == *"\n"* || "${PS1}" == *$'\n'* ) ]]; then
                builtin local oldval
                oldval=$(builtin shopt -p extglob)
                builtin shopt -s extglob
                # bash does not redraw the leading lines in a multiline prompt so
                # mark the last line as a secondary prompt. Otherwise on resize the
                # lines before the last line will be erased by kitty.
                # the first part removes everything from the last \n onwards
                # the second part appends a newline with the secondary marking
                # the third part appends everything after the last newline
                PS1=${PS1%@('\n'|$'\n')*}${_ksi_prompt[secondary_prompt]}${PS1##*@('\n'|$'\n')}
                builtin eval "$oldval"
            fi
            PS1="${_ksi_prompt[ps1]}$PS1"
        fi
        if [[ -n "${_ksi_prompt[ps1_suffix]}" ]]; then
            PS1="${PS1}${_ksi_prompt[ps1_suffix]}"
        fi
        if [[ -n "${_ksi_prompt[ps2]}" ]]; then
            PS2=${PS2//\\\[\\e\]133;k;start_kitty\\a\\\]*end_kitty\\a\\\]}
            PS2="${_ksi_prompt[ps2]}$PS2"
        fi

        if [[ "${_ksi_prompt[cwd]}" == "y" ]]; then
            # unfortunately bash provides no hooks to detect cwd changes
            # in particular this means cwd reporting will not happen for a
            # command like cd /test && cat. PS0 is evaluated before cd is run.
            if [[ "${_ksi_prompt[last_reported_cwd]}" != "$PWD" ]]; then
                _ksi_prompt[last_reported_cwd]="$PWD"
                builtin printf "\e]7;kitty-shell-cwd://%s%s\a" "$HOSTNAME" "$PWD"
            fi
        fi
    }

    if [[ "${_ksi_prompt[cursor]}" == "y" ]]; then
        _ksi_prompt[ps1_suffix]+="\[\e[5 q\]"  # blinking bar cursor
        _ksi_prompt[ps0_suffix]+="\[\e[0 q\]"  # blinking default cursor
    fi

    if [[ "${_ksi_prompt[title]}" == "y" ]]; then
        if [[ -z "$KITTY_PID" ]]; then
            if [[ -n "$SSH_TTY" || -n "$SSH2_TTY$KITTY_WINDOW_ID" ]]; then
                # connected to most SSH servers
                # or use ssh kitten to connected to some SSH servers that do not set SSH_TTY
                _ksi_prompt[hostname_prefix]="\h: "
            elif [[ -n "$(builtin command -v who)" && "$(builtin command who -m 2> /dev/null)" =~ "\([a-fA-F.:0-9]+\)$" ]]; then
                # the shell integration script is installed manually on the remote system
                # the environment variables are cleared after sudo
                # OpenSSH's sshd creates entries in utmp for every login so use those
                _ksi_prompt[hostname_prefix]="\h: "
            fi
        fi
        # see https://www.gnu.org/software/bash/manual/html_node/Controlling-the-Prompt.html#Controlling-the-Prompt
        # we use suffix here because some distros add title setting to their bashrc files by default
        _ksi_prompt[ps1_suffix]+="\[\e]2;${_ksi_prompt[hostname_prefix]}\w\a\]"
        if [[ "$HISTCONTROL" == *"ignoreboth"* ]] || [[ "$HISTCONTROL" == *"ignorespace"* ]]; then
            _ksi_debug_print "ignoreboth or ignorespace present in bash HISTCONTROL setting, showing running command in window title will not be robust"
        fi
        _ksi_get_current_command() {
            builtin local last_cmd
            last_cmd=$(HISTTIMEFORMAT= builtin history 1)
            last_cmd="${last_cmd#*[[:digit:]]*[[:space:]]}"  # remove leading history number
            last_cmd="${last_cmd#"${last_cmd%%[![:space:]]*}"}"  # remove remaining leading whitespace
            builtin printf "\e]2;%s%s\a" "${_ksi_prompt[hostname_prefix]@P}" "${last_cmd//[[:cntrl:]]}"  # remove any control characters
        }
        _ksi_prompt[ps0_suffix]+='$(_ksi_get_current_command)'
    fi

    if [[ "${_ksi_prompt[mark]}" == "y" ]]; then
        _ksi_prompt[ps1]+="\[\e]133;A\a\]"
        _ksi_prompt[ps2]+="\[\e]133;A;k=s\a\]"
        _ksi_prompt[ps0]+="\[\e]133;C\a\]"
    fi

    if [[ "${_ksi_prompt[complete]}" == "y" ]]; then
        _ksi_completions() {
            builtin local src
            builtin local limit
            # Send all words up to the word the cursor is currently on
            builtin let limit=1+$COMP_CWORD
            src=$(builtin printf "%s\n" "${COMP_WORDS[@]:0:$limit}" | builtin command kitty +complete bash)
            if [[ $? == 0 ]]; then
                builtin eval "${src}"
            fi
        }
        builtin complete -o nospace -F _ksi_completions kitty
        builtin complete -o nospace -F _ksi_completions edit-in-kitty
        builtin complete -o nospace -F _ksi_completions clone-in-kitty
    fi

    # wrap our prompt additions in markers we can use to remove them using
    # bash's anemic pattern substitution
    if [[ -n "${_ksi_prompt[ps0]}" ]]; then
        _ksi_prompt[ps0]="${_ksi_prompt[start_mark]}${_ksi_prompt[ps0]}${_ksi_prompt[end_mark]}"
    fi
    if [[ -n "${_ksi_prompt[ps0_suffix]}" ]]; then
        _ksi_prompt[ps0_suffix]="${_ksi_prompt[start_suffix_mark]}${_ksi_prompt[ps0_suffix]}${_ksi_prompt[end_suffix_mark]}"
    fi
    if [[ -n "${_ksi_prompt[ps1]}" ]]; then
        _ksi_prompt[ps1]="${_ksi_prompt[start_mark]}${_ksi_prompt[ps1]}${_ksi_prompt[end_mark]}"
    fi
    if [[ -n "${_ksi_prompt[ps1_suffix]}" ]]; then
        _ksi_prompt[ps1_suffix]="${_ksi_prompt[start_suffix_mark]}${_ksi_prompt[ps1_suffix]}${_ksi_prompt[end_suffix_mark]}"
    fi
    if [[ -n "${_ksi_prompt[ps2]}" ]]; then
        _ksi_prompt[ps2]="${_ksi_prompt[start_mark]}${_ksi_prompt[ps2]}${_ksi_prompt[end_mark]}"
    fi
    builtin unset _ksi_prompt[start_mark] _ksi_prompt[end_mark] _ksi_prompt[start_suffix_mark] _ksi_prompt[end_suffix_mark] _ksi_prompt[start_secondary_mark] _ksi_prompt[end_secondary_mark]

    # install our prompt command, using an array if it is unset or already an array,
    # otherwise append a string. We check if _ksi_prompt_command exists as some shell
    # scripts stupidly export PROMPT_COMMAND making it inherited by all programs launched
    # from the shell
    builtin local pc
    pc='builtin declare -F _ksi_prompt_command > /dev/null 2> /dev/null && _ksi_prompt_command'
    if [[ -z "${PROMPT_COMMAND}" ]]; then
        PROMPT_COMMAND=([0]="$pc")
    elif [[ $(builtin declare -p PROMPT_COMMAND 2> /dev/null) =~ 'declare -a PROMPT_COMMAND' ]]; then
        PROMPT_COMMAND+=("$pc")
    else
        builtin local oldval
        oldval=$(builtin shopt -p extglob)
        builtin shopt -s extglob
        PROMPT_COMMAND="${PROMPT_COMMAND%%+([[:space:]])}"
        PROMPT_COMMAND="${PROMPT_COMMAND%%+(;)}"
        builtin eval "$oldval"
        PROMPT_COMMAND+="; $pc"
    fi
    if [ -n "${KITTY_IS_CLONE_LAUNCH}" ]; then
        builtin local orig_conda_env="$CONDA_DEFAULT_ENV"
        builtin eval "${KITTY_IS_CLONE_LAUNCH}"
        builtin hash -r 2> /dev/null 1> /dev/null
        builtin local venv="${VIRTUAL_ENV}/bin/activate"
        builtin local sourced=""
        _ksi_s_is_ok() {
            [[ -z "$sourced" && "$KITTY_CLONE_SOURCE_STRATEGIES" == *",$1,"* ]] && return 0
            return 1
        }

        if _ksi_s_is_ok "venv" && [ -n "${VIRTUAL_ENV}" -a -r "$venv" ]; then
            sourced="y"
            builtin unset VIRTUAL_ENV
            builtin source "$venv"
        fi; if _ksi_s_is_ok "conda" && [ -n "${CONDA_DEFAULT_ENV}" ] && builtin command -v conda >/dev/null 2>/dev/null && [ "${CONDA_DEFAULT_ENV}" != "$orig_conda_env" ]; then
            sourced="y"
            conda activate "${CONDA_DEFAULT_ENV}"
        fi; if _ksi_s_is_ok "env_var" && [[ -n "${KITTY_CLONE_SOURCE_CODE}" ]]; then
            sourced="y"
            builtin eval "${KITTY_CLONE_SOURCE_CODE}"
        fi; if _ksi_s_is_ok "path" && [[ -r "${KITTY_CLONE_SOURCE_PATH}" ]]; then
            sourced="y"
            builtin source "${KITTY_CLONE_SOURCE_PATH}"
        fi
        builtin unset -f _ksi_s_is_ok
        # Ensure PATH has no duplicate entries
        if [ -n "$PATH" ]; then
            builtin local old_PATH=$PATH:; PATH=
            while [ -n "$old_PATH" ]; do
                builtin local x
                x=${old_PATH%%:*}
                case $PATH: in
                    *:"$x":*) ;;
                    *) PATH=$PATH:$x;;
                esac
                old_PATH=${old_PATH#*:}
            done
            PATH=${PATH#:}
        fi
    fi
    builtin unset KITTY_IS_CLONE_LAUNCH KITTY_CLONE_SOURCE_STRATEGIES
}
_ksi_main
builtin unset -f _ksi_main

case :$SHELLOPTS: in
  *:posix:*) ;;
  *)

_ksi_transmit_data() {
    builtin local data
    data="${1//[[:space:]]}"
    builtin local pos=0
    builtin local chunk_num=0
    while [ $pos -lt ${#data} ]; do
        builtin local chunk="${data:$pos:2048}"
        pos=$(($pos+2048))
        builtin printf '\eP@kitty-%s|%s:%s\e\\' "${2}" "${chunk_num}" "${chunk}"
        chunk_num=$(($chunk_num+1))
    done
    # save history so it is available in new shell
    [ "$3" = "save_history" ] && builtin history -a
    builtin printf '\eP@kitty-%s|\e\\' "${2}"
}

clone-in-kitty() {
    builtin local data="shell=bash,pid=$$,cwd=$(builtin printf "%s" "$PWD" | builtin command base64),envfmt=bash,env=$(builtin export | builtin command base64)"
    while :; do
        case "$1" in
            "") break;;
            -h|--help)
                builtin printf "%s\n\n%s\n" "Clone the current bash session into a new kitty window." "For usage instructions see: https://sw.kovidgoyal.net/kitty/shell-integration/#clone-shell"
                return
                ;;
            *) data="$data,a=$(builtin printf "%s" "$1" | builtin command base64)";;
        esac
        shift
    done
    _ksi_transmit_data "$data" "clone" "save_history"
}

edit-in-kitty() {
    builtin local data=""
    builtin local ed_filename=""
    builtin local usage="Usage: edit-in-kitty [OPTIONS] FILE"
    data="cwd=$(builtin printf "%s" "$PWD" | builtin command base64)"
    while :; do
        case "$1" in
            "") break;;
            -h|--help)
                builtin printf "%s\n\n%s\n\n%s\n" "$usage" "Edit the specified file in a kitty overlay window. Works over SSH as well." "For usage instructions see: https://sw.kovidgoyal.net/kitty/shell-integration/#edit-file"
                return
                ;;
            *) data="$data,a=$(builtin printf "%s" "$1" | builtin command base64)"; ed_filename="$1";;
        esac
        shift
    done
    [ -z "$ed_filename" ] && {
        builtin echo "$usage" > /dev/stderr
        return 1
    }
    [ -r "$ed_filename" -a -w "$ed_filename" ] || {
        builtin echo "$ed_filename is not readable and writable" > /dev/stderr
        return 1
    }
    [ ! -f "$ed_filename" ] && {
        builtin echo "$ed_filename is not a file" > /dev/stderr
        return 1
    }
    builtin local stat_result=""
    stat_result=$(builtin command stat -L --format '%d:%i:%s' "$ed_filename" 2> /dev/null)
    [ $? != 0 ] && stat_result=$(builtin command stat -L -f '%d:%i:%z' "$ed_filename" 2> /dev/null)
    [ -z "$stat_result" ] && { builtin echo "Failed to stat the file: $ed_filename" > /dev/stderr; return 1; }
    data="$data,file_inode=$stat_result"
    builtin local file_size=$(builtin echo "$stat_result" | builtin command cut -d: -f3)
    [ "$file_size" -gt $((8 * 1024 * 1024)) ] && { builtin echo "File is too large for performant editing"; return 1; }
    data="$data,file_data=$(builtin command base64 < "$ed_filename")"
    _ksi_transmit_data "$data" "edit"
    data=""
    builtin echo "Waiting for editing to be completed..."
    _ksi_wait_for_complete() {
        builtin local started="n"
        builtin local line=""
        builtin local old_tty_settings=$(builtin command stty -g)
        builtin command stty "-echo"
        builtin trap -- "builtin command stty '$old_tty_settings'" RETURN
        builtin trap -- "builtin command stty '$old_tty_settings'; _ksi_transmit_data 'abort_signaled=interrupt' 'edit'; builtin exit 1;" SIGINT SIGTERM
        while :; do
            started="n"
            while IFS= builtin read -r line; do
                if [ "$started" = "y" ]; then
                    [ "$line" = "UPDATE" ] && break
                    [ "$line" = "DONE" ] && { started="done"; break; }
                    builtin printf "%s\n" "$line" > /dev/stderr
                    return 1
                else
                    [ "$line" = "KITTY_DATA_START" ] && started="y"
                fi
            done
            [ "$started" = "n" ] && continue
            data=""
            while IFS= builtin read -r line; do
                [ "$line" = "KITTY_DATA_END" ] && break
                data="$data$line"
            done
            [ -n "$data" -a "$started" != "done" ] && {
                builtin echo "Updating $ed_filename..."
                builtin printf "%s" "$data" | builtin command base64 -d > "$ed_filename"
            }
            [ "$started" = "done" ] && break
        done
    }
    $(_ksi_wait_for_complete > /dev/tty)
    builtin local rc=$?
    builtin unset -f _ksi_wait_for_complete
    return $rc
}
      ;;
esac

