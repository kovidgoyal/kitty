#!/bin/fish

function _ksi_main
    test -z "$KITTY_SHELL_INTEGRATION" && return
    if set -q XDG_DATA_DIRS KITTY_FISH_XDG_DATA_DIR
        set --global --export --path XDG_DATA_DIRS "$XDG_DATA_DIRS"
        if set -l index (contains -i "$KITTY_FISH_XDG_DATA_DIR" $XDG_DATA_DIRS)
            set --erase --global XDG_DATA_DIRS[$index]
            test -z "$XDG_DATA_DIRS" && set --erase --global XDG_DATA_DIRS
        end
        if set -q XDG_DATA_DIRS
            set --global --export --unpath XDG_DATA_DIRS "$XDG_DATA_DIRS"
        end
    end
    set --local _ksi (string split " " -- "$KITTY_SHELL_INTEGRATION")
    set --erase KITTY_SHELL_INTEGRATION
    set --erase KITTY_FISH_XDG_DATA_DIR

    function _ksi_osc
        printf "\e]%s\a" "$argv[1]"
    end

    if not contains "no-complete" $_ksi
        function _ksi_completions
            set --local ct (commandline --current-token)
            set --local tokens (commandline --tokenize --cut-at-cursor --current-process)
            printf "%s\n" $tokens $ct | kitty +complete fish2
        end
    end

    if not contains "no-cursor" $_ksi
        function _ksi_set_cursor --on-variable fish_key_bindings
            if test "$fish_key_bindings" = fish_default_key_bindings
                function _ksi_bar_cursor --on-event fish_prompt
                    printf "\e[5 q"
                end
                function _ksi_block_cursor --on-event fish_preexec
                    printf "\e[2 q"
                end
            else
                functions -q _ksi_bar_cursor && functions --erase _ksi_bar_cursor
                functions -q _ksi_block_cursor && functions --erase _ksi_block_cursor
            end
        end

        _ksi_set_cursor
        set -q fish_cursor_default     || set --global fish_cursor_default block blink
        set -q fish_cursor_insert      || set --global fish_cursor_insert line blink
        set -q fish_cursor_replace_one || set --global fish_cursor_replace_one underscore blink
        set -q fish_cursor_visual      || set --global fish_cursor_visual block blink

        # Change the cursor shape on the first run
        if functions -q _ksi_bar_cursor
            _ksi_bar_cursor
        else if contains "$fish_key_bindings" fish_vi_key_bindings fish_hybrid_key_bindings
            if functions -q fish_vi_cursor_handle
                fish_vi_cursor_handle
            else if test "$fish_bind_mode" = "insert"
                printf "\e[5 q"
            end
        end
    end

    if not contains "no-title" $_ksi
        function _ksi_function_is_not_overridden -d "Check if the specified function is not overridden"
            string match -q -- "$__fish_data_dir/functions/*" (functions --details $argv[1])
        end

        if _ksi_function_is_not_overridden fish_title
            function fish_title
                if set -q argv[1]
                    echo $argv[1]
                else
                    prompt_pwd
                end
            end
        end

        functions --erase _ksi_function_is_not_overridden
    end

    if not contains "no-prompt-mark" $_ksi
        set --global _ksi_prompt_state "first-run"

        function _ksi_function_is_not_empty -d "Check if the specified function exists and is not empty"
            functions $argv[1] | string match -qnvr '^ *(#|function |end$|$)'
        end

        function _ksi_mark -d "tell kitty to mark the current cursor position using OSC 133"
            _ksi_osc "133;$argv[1]"
        end

        function _ksi_start_prompt
            set --local cmd_status "$status"
            if test "$_ksi_prompt_state" != "postexec" -a "$_ksi_prompt_state" != "first-run"
                _ksi_mark "D"
            end
            set --global _ksi_prompt_state "prompt_start"
            _ksi_mark "A"
            return "$cmd_status" # preserve the value of $status
        end

        function _ksi_end_prompt
            set --local cmd_status "$status"
            # fish trims one trailing newline from the output of fish_prompt, so
            # we need to do the same. See https://github.com/kovidgoyal/kitty/issues/4032
            set --local op (_ksi_original_fish_prompt) # op is an array because fish splits on newlines in command substitution
            if set -q op[2]
                printf '%s\n' $op[1..-2] # print all but last element of array, each followed by a new line
            end
            printf '%s' $op[-1] # print the last component without a newline
            set --global _ksi_prompt_state "prompt_end"
            _ksi_mark "B"
            return "$cmd_status" # preserve the value of $status
        end

        functions -c fish_prompt _ksi_original_fish_prompt

        if _ksi_function_is_not_empty fish_mode_prompt
            # see https://github.com/starship/starship/issues/1283
            # for why we have to test for a non-empty fish_mode_prompt
            functions -c fish_mode_prompt _ksi_original_fish_mode_prompt
            function fish_mode_prompt
                _ksi_start_prompt
                _ksi_original_fish_mode_prompt
            end
            function fish_prompt
                _ksi_end_prompt
            end
        else
            function fish_prompt
                _ksi_start_prompt
                _ksi_end_prompt
            end
        end

        function _ksi_mark_output_start --on-event fish_preexec
            set --global _ksi_prompt_state "preexec"
            _ksi_mark "C"
        end

        function _ksi_mark_output_end --on-event fish_postexec
            set --global _ksi_prompt_state "postexec"
            _ksi_mark "D;$status"
        end
        # with prompt marking kitty clears the current prompt on resize so we need
        # fish to redraw it
        set --global fish_handle_reflow 1

        functions --erase _ksi_function_is_not_empty
    end
    functions --erase _ksi_main _ksi_schedule
end

if status --is-interactive
    function _ksi_schedule --on-event fish_prompt -d "Setup kitty integration after other scripts have run, we hope"
        _ksi_main
    end
else
    functions --erase _ksi_main
end
