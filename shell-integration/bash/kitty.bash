#!/bin/bash

if [[ $- != *i* ]] ; then builtin return; fi  # check in interactive mode
if [[ -z "$KITTY_SHELL_INTEGRATION" ]]; then builtin return; fi

# this is defined outside _ksi_main to make it global without using declare -g
# which is not available on older bash
builtin declare -A _ksi_prompt
_ksi_prompt=( 
    [cursor]='y' [title]='y' [mark]='y' [complete]='y' [ps0]='' [ps0_suffix]='' [ps1]='' [ps1_suffix]='' [ps2]='' 
    [hostname_prefix]='' 
)

_ksi_main() {
    for i in ${KITTY_SHELL_INTEGRATION[@]}; do
        if [[ "$i" == "no-cursor" ]]; then _ksi_prompt[cursor]='n'; fi
        if [[ "$i" == "no-title" ]]; then _ksi_prompt[title]='n'; fi
        if [[ "$i" == "no-prompt-mark" ]]; then _ksi_prompt[mark]='n'; fi
        if [[ "$i" == "no-complete" ]]; then _ksi_prompt[complete]='n'; fi
    done

    builtin unset KITTY_SHELL_INTEGRATION

    _ksi_debug_print() {
        # print a line to STDOUT of parent kitty process
        builtin local b
        b=$(builtin command base64 <<< "${@}")
        builtin printf "\eP@kitty-print|%s\e\\" "${b//\\n}"
    }

    _ksi_safe_source() {
        if [[ -f "$1" && -r "$1" ]]; then
            builtin source "$1";
            builtin return 0;
        fi
        builtin return 1;
    }

    if [[ -n "$KITTY_BASH_INJECT" ]]; then
        builtin unset ENV;
        if [[ -z "$HOME" ]]; then HOME=~; fi
        if [[ -z "$KITTY_BASH_ETC_LOCATION" ]]; then KITTY_BASH_ETC_LOCATION="/etc"; fi
        if [[ "$KITTY_BASH_INJECT" == *"posix"* ]]; then
            _ksi_safe_source "$KITTY_BASH_POSIX_ENV" && builtin export ENV="$KITTY_BASH_POSIX_ENV";
        else
            builtin set +o posix;
            if [[ -n "$KITTY_BASH_UNEXPORT_HISTFILE" ]]; then
                export -n HISTFILE;
                unset KITTY_BASH_UNEXPORT_HISTFILE;
            fi

            # See run_startup_files() in shell.c in the Bash source code
            if builtin shopt -q login_shell; then
                if [[ "$KITTY_BASH_INJECT" != *"no-profile"* ]]; then
                    _ksi_safe_source "$KITTY_BASH_ETC_LOCATION/profile";
                    _ksi_safe_source "$HOME/.bash_profile" || _ksi_safe_source "$HOME/.bash_login" || _ksi_safe_source "$HOME/.profile";
                fi
            else
                if [[ "$KITTY_BASH_INJECT" != *"no-rc"* ]]; then
                    # Linux distros build bash with -DSYS_BASHRC. Unfortunately, there is
                    # no way to to probe bash for it and different distros use different files
                    _ksi_safe_source "$KITTY_BASH_ETC_LOCATION/bash.bashrc"  # Arch, Debian, Ubuntu
                    # Fedora uses /etc/bashrc sourced from ~/.bashrc instead of SYS_BASHRC
                    if [[ -z "$KITTY_BASH_RCFILE" ]]; then KITTY_BASH_RCFILE="$HOME/.bashrc"; fi
                    _ksi_safe_source "$KITTY_BASH_RCFILE";
                fi
            fi
        fi
        builtin unset KITTY_BASH_RCFILE;
        builtin unset KITTY_BASH_POSIX_ENV;
        builtin unset KITTY_BASH_INJECT;
        builtin unset KITTY_BASH_ETC_LOCATION;
    fi
    builtin unset -f _ksi_safe_source

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
                PS1=${PS1%@('\n'|$'\n')*}${_ksi_prompt[secondary_prompt]}${PS1##*@('\n'|$'\n')};
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
    }

    if [[ "${_ksi_prompt[cursor]}" == "y" ]]; then
        _ksi_prompt[ps1_suffix]+="\[\e[5 q\]"  # blinking bar cursor
        _ksi_prompt[ps0_suffix]+="\[\e[0 q\]"  # blinking default cursor
    fi

    if [[ "${_ksi_prompt[title]}" == "y" ]]; then
        [[ "$(builtin command who -m 2> /dev/null)" =~ "\([a-fA-F.:0-9]+\)$" ]] && _ksi_prompt[hostname_prefix]="\h: "
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
                builtin eval ${src}
            fi
        }
        builtin complete -o nospace -F _ksi_completions kitty
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
    builtin unset _ksi_prompt[start_mark]
    builtin unset _ksi_prompt[end_mark]
    builtin unset _ksi_prompt[start_suffix_mark]
    builtin unset _ksi_prompt[end_suffix_mark]
    builtin unset _ksi_prompt[start_secondary_mark]
    builtin unset _ksi_prompt[end_secondary_mark]

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
        PROMPT_COMMAND="${PROMPT_COMMAND%% }"
        PROMPT_COMMAND="${PROMPT_COMMAND%%;}"
        PROMPT_COMMAND+="; $pc"
    fi
}
_ksi_main
builtin unset -f _ksi_main
# freeze _ksi_prompt to prevent it from being changed
builtin declare -r _ksi_prompt
