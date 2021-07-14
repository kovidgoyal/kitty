local args
typeset -a args
args=($@)
() {
    if [[ ! -o interactive ]]; then return; fi

    typeset -g kitty_prompt_state="first-run"
    typeset -g kitty_prompt_cursor="y"
    typeset -g kitty_prompt_title="y"

    (( ${args[(I)no-cursor]} )) && kitty_prompt_cursor="n"
    (( ${args[(I)no-title]} )) && kitty_prompt_title="n"

    function debug() {
        # print a line to STDOUT of parent kitty process
        local b=$(printf "%s\n" "$1" | base64)
        printf "\eP@kitty-print|%s\e\\" "$b"
    }

    function change-cursor-shape () {
        # change cursor shape depending on mode
        if [[ "$kitty_prompt_cursor" == "y" ]]; then
            if [[ "$KEYMAP" == vicmd ]]; then
                # the command mode for vi
                printf "\e[2 q"  # blinking block cursor
            else
                # the insert mode for vi
                printf "\e[5 q"  # blinking bar cursor
            fi
        fi
    }

    function kitty_zle_keymap_select() { 
        change-cursor-shape 
    }
    function kitty_zle_keymap_select_with_original() { zle kitty-zle-keymap-select-original; kitty_zle_keymap_select }
    zle -A zle-keymap-select kitty-zle-keymap-select-original 2>/dev/null
    if [[ $? == 0 ]]; then 
        zle -N zle-keymap-select kitty_zle_keymap_select_with_original
    else
        zle -N zle-keymap-select kitty_zle_keymap_select
    fi

    function osc() {
        printf "\e]%s\a" "$1"
    }

    function mark() {
        # tell kitty to mark the current cursor position using OSC 133
        osc "133;$1"
    }
    typeset -g kitty_prompt_start_mark="%{$(mark A)%}"

    function set_title() {
        if [[ "$kitty_prompt_title" == "y" ]]; then osc "2;$1"; fi
    }

    function kitty_precmd() { 
        local cmd_status=$?
        if [[ "$kitty_prompt_state" == "first-run" ]]; then
            # compdef is only defined if compinit has been called
            if whence compdef > /dev/null; then 
                compdef _kitty kitty 
            fi
        fi
        # Set kitty window title to the cwd
        set_title "${PWD/$HOME/~}" 
        if [[ "$kitty_prompt_state" == "preexec" ]]; then
            mark "D;$cmd_status"
        else
            if [[ "$kitty_prompt_state" != "first-run" ]]; then mark "D"; fi
        fi
        # we must use PS1 to set the prompt start mark as precmd functions are 
        # not called when the prompt is redrawn after a window resize or when a background
        # job finishes
        if [[ "$PS1" != *"$kitty_prompt_start_mark"* ]]; then PS1="$kitty_prompt_start_mark$PS1" fi
        kitty_prompt_state="precmd"
    }

    function kitty_zle_line_init() { 
        mark "B"
        change-cursor-shape; 
        kitty_prompt_state="line-init"
    }
    function kitty_zle_line_init_with_orginal() { zle kitty-zle-line-init-original; kitty_zle_line_init }
    zle -A zle-line-init kitty-zle-line-init-original 2>/dev/null
    if [[ $? == 0 ]]; then 
        zle -N zle-line-init kitty_zle_line_init_with_orginal
    else
        zle -N zle-line-init kitty_zle_line_init
    fi

    function kitty_zle_line_finish() { 
        change-cursor-shape;
        kitty_prompt_state="line-finish"
    }
    function kitty_zle_line_finish_with_orginal() { zle kitty-zle-line-finish-original; kitty_zle_line_finish }
    zle -A zle-line-finish kitty-zle-line-finish-original 2>/dev/null
    if [[ $? == 0 ]]; then 
        zle -N zle-line-finish kitty_zle_line_finish_with_orginal
    else
        zle -N zle-line-finish kitty_zle_line_finish
    fi

    function kitty_preexec() { 
        mark "C"
        # Set kitty window title to the currently executing command
        set_title "$1"
        kitty_prompt_state="preexec"
        # remove the prompt mark sequence while the command is executing as it could read/modify the value of PS1
        PS1="${PS1//$kitty_prompt_start_mark/}"
    }

    typeset -a -g precmd_functions
    precmd_functions=($precmd_functions kitty_precmd)
    typeset -a -g preexec_functions
    preexec_functions=($preexec_functions kitty_preexec)

    # Completion for kitty
    _kitty() {
        local src
        # Send all words up to the word the cursor is currently on
        src=$(printf "%s\n" "${(@)words[1,$CURRENT]}" | kitty +complete zsh)
        if [[ $? == 0 ]]; then
            eval ${src}
        fi
    }
}
