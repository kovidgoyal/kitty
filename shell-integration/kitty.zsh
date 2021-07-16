#!/bin/zsh

() {
    if [[ ! -o interactive ]]; then return; fi
    if [[ -z "$KITTY_SHELL_INTEGRATION" ]]; then return; fi
    typeset -g -A _ksi_prompt=([state]='first-run' [cursor]='y' [title]='y' [mark]='y' [complete]='y')
    for i in ${=KITTY_SHELL_INTEGRATION}; do
        if [[ "$i" == "no-cursor" ]]; then _ksi_prompt[cursor]='n'; fi
        if [[ "$i" == "no-title" ]]; then _ksi_prompt[title]='n'; fi
        if [[ "$i" == "no-prompt-mark" ]]; then _ksi_prompt[mark]='n'; fi
        if [[ "$i" == "no-complete" ]]; then _ksi_prompt[complete]='n'; fi
    done
    unset KITTY_SHELL_INTEGRATION

    function _ksi_debug_print() {
        # print a line to STDOUT of parent kitty process
        local b=$(printf "%s\n" "$1" | base64 | tr -d \\n)
        printf "\eP@kitty-print|%s\e\\" "$b"
    }

    function _ksi_change_cursor_shape () {
        # change cursor shape depending on mode
        if [[ "$_ksi_prompt[cursor]" == "y" ]]; then
            case $KEYMAP in
                vicmd | visual)
                    # the command mode for vi
                    printf "\e[1 q"  # blinking block cursor
                ;;
                *)
                    printf "\e[5 q"  # blinking bar cursor
                ;;
            esac
        fi
    }

    function _ksi_zle_keymap_select() { 
        _ksi_change_cursor_shape
    }
    function _ksi_zle_keymap_select_with_original() { zle kitty-zle-keymap-select-original; _ksi_zle_keymap_select }
    zle -A zle-keymap-select kitty-zle-keymap-select-original 2>/dev/null
    if [[ $? == 0 ]]; then 
        zle -N zle-keymap-select _ksi_zle_keymap_select_with_original
    else
        zle -N zle-keymap-select _ksi_zle_keymap_select
    fi

    function _ksi_osc() {
        printf "\e]%s\a" "$1"
    }

    function _ksi_mark() {
        # tell kitty to mark the current cursor position using OSC 133
        if [[ "$_ksi_prompt[mark]" == "y" ]]; then _ksi_osc "133;$1"; fi
    }
    _ksi_prompt[start_mark]="%{$(_ksi_mark A)%}"

    function _ksi_set_title() {
        if [[ "$_ksi_prompt[title]" == "y" ]]; then _ksi_osc "2;$1"; fi
    }

    function _ksi_install_completion() {
        if [[ "$_ksi_prompt[complete]" == "y" ]]; then
            # compdef is only defined if compinit has been called
            if whence compdef > /dev/null; then 
                compdef _ksi_complete kitty 
            fi
        fi
    }

    function _ksi_precmd() { 
        local cmd_status=$?
        if [[ "$_ksi_prompt[state]" == "first-run" ]]; then
            _ksi_install_completion
        fi
        # Set kitty window title to the cwd
        _ksi_set_title "${PWD/$HOME/~}" 

        # Prompt marking
        if [[ "$_ksi_prompt[mark]" == "y" ]]; then
            if [[ "$_ksi_prompt[state]" == "preexec" ]]; then
                _ksi_mark "D;$cmd_status"
            else
                if [[ "$_ksi_prompt[state]" != "first-run" ]]; then _ksi_mark "D"; fi
            fi
            # we must use PS1 to set the prompt start mark as precmd functions are 
            # not called when the prompt is redrawn after a window resize or when a background
            # job finishes
            if [[ "$PS1" != *"$_ksi_prompt[start_mark]"* ]]; then PS1="$_ksi_prompt[start_mark]$PS1" fi
        fi
        _ksi_prompt[state]="precmd"
    }

    function _ksi_zle_line_init() { 
        if [[ "$_ksi_prompt[mark]" == "y" ]]; then _ksi_mark "B"; fi
        _ksi_change_cursor_shape
        _ksi_prompt[state]="line-init"
    }
    function _ksi_zle_line_init_with_orginal() { zle kitty-zle-line-init-original; _ksi_zle_line_init }
    zle -A zle-line-init kitty-zle-line-init-original 2>/dev/null
    if [[ $? == 0 ]]; then 
        zle -N zle-line-init _ksi_zle_line_init_with_orginal
    else
        zle -N zle-line-init _ksi_zle_line_init
    fi

    function _ksi_zle_line_finish() { 
        _ksi_change_cursor_shape
        _ksi_prompt[state]="line-finish"
    }
    function _ksi_zle_line_finish_with_orginal() { zle kitty-zle-line-finish-original; _ksi_zle_line_finish }
    zle -A zle-line-finish kitty-zle-line-finish-original 2>/dev/null
    if [[ $? == 0 ]]; then 
        zle -N zle-line-finish _ksi_zle_line_finish_with_orginal
    else
        zle -N zle-line-finish _ksi_zle_line_finish
    fi

    function _ksi_preexec() { 
        if [[ "$_ksi_prompt[mark]" == "y" ]]; then 
            _ksi_mark "C"; 
            # remove the prompt mark sequence while the command is executing as it could read/modify the value of PS1
            PS1="${PS1//$_ksi_prompt[start_mark]/}"
        fi
        # Set kitty window title to the currently executing command
        _ksi_set_title "$1"
        _ksi_prompt[state]="preexec"
    }

    typeset -a -g precmd_functions
    precmd_functions=($precmd_functions _ksi_precmd)
    typeset -a -g preexec_functions
    preexec_functions=($preexec_functions _ksi_preexec)

    # Completion for kitty
    _ksi_complete() {
        local src
        # Send all words up to the word the cursor is currently on
        src=$(printf "%s\n" "${(@)words[1,$CURRENT]}" | kitty +complete zsh)
        if [[ $? == 0 ]]; then
            eval ${src}
        fi
    }
}
