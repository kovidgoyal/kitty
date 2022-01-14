#!/bin/bash

# this is defined outside _ksi_main to make it global without using declare -g
# which is not available on older bash
builtin declare -A _ksi_prompt
_ksi_prompt=( [cursor]='y' [title]='y' [mark]='y' [complete]='y' [ps0]='' [ps1]='' [ps2]='' )

_ksi_main() {
    if [[ $- != *i* ]] ; then builtin return; fi  # check in interactive mode
    if [[ -z "$KITTY_SHELL_INTEGRATION" ]]; then builtin return; fi
    builtin set -f
    for i in ${KITTY_SHELL_INTEGRATION[@]}; do
        builtin set +f
        if [[ "$i" == "no-cursor" ]]; then _ksi_prompt[cursor]='n'; fi
        if [[ "$i" == "no-title" ]]; then _ksi_prompt[title]='n'; fi
        if [[ "$i" == "no-prompt-mark" ]]; then _ksi_prompt[mark]='n'; fi
        if [[ "$i" == "no-complete" ]]; then _ksi_prompt[complete]='n'; fi
    done
    builtin set +f

    builtin unset KITTY_SHELL_INTEGRATION

    _ksi_debug_print() {
        # print a line to STDOUT of parent kitty process
        builtin local b=$(command base64 <<< "${@}" | tr -d \\n)
        builtin printf "\eP@kitty-print|%s\e\\" "$b" 
        # "
    }

    _ksi_set_mark() { 
        _ksi_prompt["${1}_mark"]="\[\e]133;k;${1}_kitty\a\]" 
    }

    _ksi_set_mark start
    _ksi_set_mark end
    _ksi_set_mark start_secondary
    _ksi_set_mark end_secondary
    builtin unset -f _ksi_set_mark
    _ksi_prompt[secondary_prompt]="\n${_ksi_prompt[start_secondary_mark]}\[\e]133;A;k=s\a\]${_ksi_prompt[end_secondary_mark]}"

    _ksi_prompt_command() {
        # we first remove any previously added kitty code from the prompt variables and then add
        # it back, to ensure we have only a single instance
        if [[ -n "${_ksi_prompt[ps0]}" ]]; then
            PS0=${PS0//\\\[\\e\]133;k;start_kitty\\a\\\]*end_kitty\\a\\\]}
            PS0="${_ksi_prompt[ps0]}$PS0"
        fi
        if [[ -n "${_ksi_prompt[ps1]}" ]]; then
            PS1=${PS1//\\\[\\e\]133;k;start_kitty\\a\\\]*end_kitty\\a\\\]}
            PS1="${_ksi_prompt[ps1]}$PS1"
            if [[ "${_ksi_prompt[mark]}" == "y" ]]; then 
                # bash does not redraw the leading lines in a multiline prompt so
                # mark them as secondary prompts
                PS1=${PS1//\\\[\\e\]133;k;start_secondary_kitty\\a\\\]*end_secondary_kitty\\a\\\]}
                PS1=${PS1//"\n"/${_ksi_prompt[secondary_prompt]}}
            fi
        fi
        if [[ -n "${_ksi_prompt[ps2]}" ]]; then
            PS2=${PS2//\\\[\\e\]133;k;start_kitty\\a\\\]*end_kitty\\a\\\]}
            PS2="${_ksi_prompt[ps2]}$PS2"
        fi
    }

    if [[ "${_ksi_prompt[cursor]}" == "y" ]]; then 
        _ksi_prompt[ps1]+="\[\e[5 q\]"  # blinking bar cursor
        _ksi_prompt[ps0]+="\[\e[5 q\]"  # blinking block cursor
    fi

    if [[ "${_ksi_prompt[title]}" == "y" ]]; then 
        # see https://www.gnu.org/software/bash/manual/html_node/Controlling-the-Prompt.html#Controlling-the-Prompt
        _ksi_prompt[ps1]+="\[\e]2;\w\a\]"
        if [[ "$HISTCONTROL" == *"ignoreboth"* ]] || [[ "$HISTCONTROL" == *"ignorespace"* ]]; then
            _ksi_debug_print "ignoreboth or ignorespace present in bash HISTCONTROL setting, showing running command in window title will not be robust"
        fi
        _ksi_prompt[ps0]+='$(printf "\e]2;%s\a" "$(HISTTIMEFORMAT= history 1 | sed -e "s/^[ ]*[0-9]*[ ]*//")")'
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
            src=$(builtin printf "%s\n" "${COMP_WORDS[@]:0:$limit}" | command kitty +complete bash)
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
    if [[ -n "${_ksi_prompt[ps1]}" ]]; then 
        _ksi_prompt[ps1]="${_ksi_prompt[start_mark]}${_ksi_prompt[ps1]}${_ksi_prompt[end_mark]}"
    fi
    if [[ -n "${_ksi_prompt[ps2]}" ]]; then 
        _ksi_prompt[ps2]="${_ksi_prompt[start_mark]}${_ksi_prompt[ps2]}${_ksi_prompt[end_mark]}"
    fi
    builtin unset _ksi_prompt[start_mark]
    builtin unset _ksi_prompt[end_mark]
    builtin unset _ksi_prompt[start_secondary_mark]
    builtin unset _ksi_prompt[end_secondary_mark]

    # install our prompt command, using an array if it is unset or already an array,
    # otherwise append a string
    if [[ -z "${PROMPT_COMMAND}" ]]; then
        PROMPT_COMMAND=([0]="_ksi_prompt_command")
    elif [[ $(declare -p PROMPT_COMMAND 2> /dev/null) =~ 'declare -a PROMPT_COMMAND' ]]; then
        PROMPT_COMMAND+=("_ksi_prompt_command")
    else
        PROMPT_COMMAND+="; _ksi_prompt_command"
    fi
}
_ksi_main
builtin unset -f _ksi_main
# freeze _ksi_prompt to prevent it from being changed
builtin declare -r _ksi_prompt
