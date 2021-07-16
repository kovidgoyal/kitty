#!/bin/bash

_ksi_main() {
    if [[ $- != *i* ]] ; then return; fi  # check in interactive mode
    if [[ -z "$KITTY_SHELL_INTEGRATION" ]]; then return; fi
    declare -A _ksi_prompt=( [cursor]='y' [title]='y' [mark]='y' [complete]='y' )
    set -f
    for i in ${KITTY_SHELL_INTEGRATION}; do
        set +f
        if [[ "$i" == "no-cursor" ]]; then _ksi_prompt[cursor]='n'; fi
        if [[ "$i" == "no-title" ]]; then _ksi_prompt[title]='n'; fi
        if [[ "$i" == "no-prompt-mark" ]]; then _ksi_prompt[mark]='n'; fi
        if [[ "$i" == "no-complete" ]]; then _ksi_prompt[complete]='n'; fi
    done
    set +f

    unset KITTY_SHELL_INTEGRATION

    _ksi_debug_print() {
        # print a line to STDOUT of parent kitty process
        local b=$(printf "%s\n" "$1" | base64 | tr -d \\n)
        printf "\eP@kitty-print|%s\e\\" "$b" 
        # "
    }

    if [[ "${_ksi_prompt[cursor]}" == "y" ]]; then 
        PS1="\[\e[5 q\]$PS1"  # blinking bar cursor
        PS0="\[\e[1 q\]$PS0"  # blinking block cursor
    fi

    if [[ "${_ksi_prompt[title]}" == "y" ]]; then 
        # see https://www.gnu.org/software/bash/manual/html_node/Controlling-the-Prompt.html#Controlling-the-Prompt
        PS1="\[\e]2;\w\a\]$PS1"
        if [[ "$HISTCONTROL" == *"ignoreboth"* ]] || [[ "$HISTCONTROL" == *"ignorespace"* ]]; then
            _ksi_debug_print "ignoreboth or ignorespace present in bash HISTCONTROL setting, showing running command in window title will not be robust"
        fi
        local orig_ps0="$PS0"
        PS0='$(printf "\e]2;%s\a" "$(HISTTIMEFORMAT= history 1 | sed -e "s/^[ ]*[0-9]*[ ]*//")")'
        PS0+="$orig_ps0"
    fi

    if [[ "${_ksi_prompt[mark]}" == "y" ]]; then 
        PS1="\[\e]133;A\a\]$PS1"
        PS0="\[\e]133;C\a\]$PS0"
    fi

    if [[ "${_ksi_prompt[complete]}" == "y" ]]; then 
        _ksi_completions() {
            local src
            local limit
            # Send all words up to the word the cursor is currently on
            let limit=1+$COMP_CWORD
            src=$(printf "%s\n" "${COMP_WORDS[@]: 0:$limit}" | kitty +complete bash)
            if [[ $? == 0 ]]; then
                eval ${src}
            fi
        }
        complete -o nospace -F _ksi_completions kitty
    fi
}
_ksi_main
