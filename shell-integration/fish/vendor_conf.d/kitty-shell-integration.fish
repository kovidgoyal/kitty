#!/bin/fish

status is-interactive || exit 0
not functions -q __ksi_schedule || exit 0

function __ksi_schedule --on-event fish_prompt -d "Setup kitty integration after other scripts have run, we hope"
    functions --erase __ksi_schedule
    test -n "$KITTY_SHELL_INTEGRATION" || return 0

    # kitty exports the vendored integration script directory to XDG_DATA_DIRS
    # the original paths needs to be restored here to not affect other programs
    if set -q XDG_DATA_DIRS KITTY_FISH_XDG_DATA_DIR
        set --global --export --path XDG_DATA_DIRS "$XDG_DATA_DIRS"
        if set -l index (contains -i "$KITTY_FISH_XDG_DATA_DIR" $XDG_DATA_DIRS)
            set --erase --global XDG_DATA_DIRS[$index]
            test -n "$XDG_DATA_DIRS" || set --erase --global XDG_DATA_DIRS
        end
        if set -q XDG_DATA_DIRS
            set --global --export --unpath XDG_DATA_DIRS "$XDG_DATA_DIRS"
        end
    end
    set --local _ksi (string split " " -- "$KITTY_SHELL_INTEGRATION")
    set --erase KITTY_SHELL_INTEGRATION KITTY_FISH_XDG_DATA_DIR

    # Enable cursor shape changes for default mode and vi mode
    #
    # For vi mode, the prompt marking feature needs to be enabled,
    # otherwise it falls back to fish's default fish_vi_cursor.
    #
    # Custom cursor shapes can be configured via global variables.
    #
    # For normal mode prompt:
    #     kitty_fish_prompt_cursor
    # For programs running in fish:
    #     kitty_fish_external_cursor
    # For vi modes:
    #     fish_{default,insert,replace_one,visual}_cursor
    # 
    # Cursor shape values:
    #     block, underscore (underline), line (bar, beam)
    #
    # To make the cursor blink, add `blink` at the end.
    #
    # Example:
    #     set -g kitty_fish_prompt_cursor line blink
    #
    if not contains "no-cursor" $_ksi
        and not functions -q __ksi_set_cursor

        # Set cursor shape escape sequence `ESC [ Ps SPACE q`
        # Ps:
        # blinking: block 1, underline 3, bar 5
        # steady:   block 2, underline 4, bar 6
        function __ksi_init_cursor_var -d "Initialize cursor shape CSI escape sequence"
            set --local varname kitty_fish_$argv[1]_cursor
            set --local val 0
            if contains $argv[1] default insert replace_one visual
                and test -n "fish_$argv[1]_cursor"
                set varname fish_$argv[1]_cursor
            end
            if test -n "$$varname"
                set --local shape (string split " " -- "$$varname")
                switch $shape[1]
                    case block
                        set val 2
                    case underline underscore
                        set val 4
                    case bar beam line
                        set val 6
                end
                test $val -gt 0 && test "$shape[2]" = blink
                and set val (math $val - 1)
                set --global __ksi_cursor_$argv[1] "\e[$val q"
            end
            test $val -gt 0
            or set --global __ksi_cursor_$argv[1] "\e[$argv[2] q"
        end

        function __ksi_init_vi_cursor -d "Initialize the vi cursor shapes"
            # Set default cursor shapes
            # Use bar in insert mode, underline in replace mode, block in default and visual mode,
            # all with a blinking cursor.
            set --local _modes default insert replace_one visual
            set --local _shapes 1 5 3 1
            for i in 1 2 3 4
                __ksi_init_cursor_var $_modes[$i] $_shapes[$i]
            end

            # The cursor shapes will be frozen after initialization and will not be read during runtime
            printf "
                function __ksi_vi_prompt_cursor -d 'Set cursor shape for current vi mode'
                    switch \$fish_bind_mode
                        case default; printf \"%s\"
                        case insert; printf \"%s\"
                        case replace_one; printf \"%s\"
                        case visual; printf \"%s\"
                    end
                end
            " $__ksi_cursor_default $__ksi_cursor_insert $__ksi_cursor_replace_one $__ksi_cursor_visual | source

            if not functions -q __ksi_init_vi_cursor_fallback
                # Clean up fish_vi_cursor again to make sure it is not being used
                functions --erase fish_vi_cursor fish_vi_cursor_handle fish_vi_cursor_handle_preexec
                function fish_vi_cursor; end
            end

            # Clean up
            for i in 1 2 3 4
                set --erase --global __ksi_cursor_$_modes[$i]
            end
            functions --erase __ksi_init_cursor_var __ksi_init_vi_cursor
        end

        if contains "no-prompt-mark" $_ksi
            function __ksi_init_vi_cursor_fallback -d "Initialize the vi cursor shapes, using fish's built-in fish_vi_cursor"
                # Fallback to fish's built-in vi cursor when prompt marking is not enabled
                set --local _vi_modes fish_cursor_{default,insert,replace_one,visual}
                set --local _vi_cursor_shapes block line underscore block
                # Set the vi mode cursor shapes only when none of them are configured
                set -q $_vi_modes
                if test "$status" -eq 4
                    for i in 1 2 3 4
                        set --global $_vi_modes[$i] $_vi_cursor_shapes[$i] blink
                    end
                end
                functions --erase __ksi_init_vi_cursor_fallback
            end
        end

        # Set default cursor shapes
        # Blinking bar for command line editing, steady block for executing programs.
        __ksi_init_cursor_var prompt 5
        __ksi_init_cursor_var external 2

        printf "
            function __ksi_external_cursor --on-event fish_preexec -d 'Set cursor shape before executing command'
                printf \"%s\"
            end
        " $__ksi_cursor_external | source
        set --erase --global __ksi_cursor_external

        # Enable the cursor shape function after switching to different key bindings
        function __ksi_set_cursor --on-variable fish_key_bindings -d "Setup cursor shape functions for fish default mode and vi mode"
            if test "$fish_key_bindings" = fish_default_key_bindings
                set --erase --global __ksi_vi_cursor_enabled
                not functions -q __ksi_prompt_cursor || return
                printf "
                    function __ksi_prompt_cursor --on-event fish_prompt -d 'Set cursor shape on prompt'
                        printf \"%s\"
                    end
                " $__ksi_cursor_prompt | source
            else
                functions --erase __ksi_prompt_cursor
                if contains "$fish_key_bindings" fish_vi_key_bindings fish_hybrid_key_bindings
                    set --global __ksi_vi_cursor_enabled 1
                    functions -q __ksi_vi_prompt_cursor
                    or __ksi_init_vi_cursor
                    not functions -q __ksi_init_vi_cursor_fallback
                    or __ksi_init_vi_cursor_fallback
                end
            end
        end
        __ksi_set_cursor

        # Change the cursor shape on the first run
        functions -q __ksi_prompt_cursor
        and __ksi_prompt_cursor

        set -q __ksi_vi_cursor_enabled
        and __ksi_vi_prompt_cursor
    end

    # Enable prompt marking with OSC 133
    if not contains "no-prompt-mark" $_ksi
        and not set -q __ksi_prompt_state
        set --global __ksi_prompt_state post-exec

        function __ksi_function_is_not_empty -d "Check if the specified function exists and is not empty"
            functions --no-details $argv[1] | string match -qnvr '^ *(#|function |end$|$)'
        end

        function __ksi_mark -d "Tell kitty to mark the current cursor position using OSC 133"
            printf "\e]133;%s\a" "$argv[1]"
        end

        function __ksi_prompt_start
            # Preserve the command exit code from $status
            set --local cmd_status $status
            if test "$__ksi_prompt_state" = post-exec
                __ksi_mark D
            end
            set --global __ksi_prompt_state prompt-start
            __ksi_mark A
            set -q __ksi_vi_cursor_enabled
            and __ksi_vi_prompt_cursor
            return $cmd_status
        end

        function __ksi_prompt_end
            set --local cmd_status $status
            # fish trims one trailing newline from the output of fish_prompt, so
            # we need to do the same. See https://github.com/kovidgoyal/kitty/issues/4032
            set --local op (__ksi_original_fish_prompt) # op is a list because fish splits on newlines in command substitution
            if set -q op[2]
                printf '%s\n' $op[1..-2] # print all but last element of the list, each followed by a new line
            end
            printf '%s' $op[-1] # print the last component without a newline
            set --global __ksi_prompt_state prompt-end
            __ksi_mark B
            return $cmd_status
        end

        functions -c fish_prompt __ksi_original_fish_prompt

        if __ksi_function_is_not_empty fish_mode_prompt
            # See https://github.com/starship/starship/issues/1283
            # for why we have to test for a non-empty fish_mode_prompt
            functions -c fish_mode_prompt __ksi_original_fish_mode_prompt
            function fish_mode_prompt
                __ksi_prompt_start
                __ksi_original_fish_mode_prompt
            end
            function fish_prompt
                __ksi_prompt_end
            end
        else
            function fish_prompt
                __ksi_prompt_start
                __ksi_prompt_end
            end
        end

        function __ksi_mark_output_start --on-event fish_preexec
            set --global __ksi_prompt_state pre-exec
            __ksi_mark C
        end

        function __ksi_mark_output_end --on-event fish_postexec
            set --global __ksi_prompt_state post-exec
            __ksi_mark "D;$status"
        end
        # With prompt marking kitty clears the current prompt on resize so we need
        # fish to redraw it
        set --global fish_handle_reflow 1

        functions --erase __ksi_function_is_not_empty
    end
end

# fish's built-in vi cursor function does not work well with multi-line prompts, so we provide our own.
# fish_vi_cursor will create the event functions, it needs to be cleared earlier.
# see https://github.com/fish-shell/fish-shell/issues/3481
set --local _ksi (string split " " -- "$KITTY_SHELL_INTEGRATION")
contains "no-cursor" $_ksi || contains "no-prompt-mark" $_ksi
or function fish_vi_cursor; end
