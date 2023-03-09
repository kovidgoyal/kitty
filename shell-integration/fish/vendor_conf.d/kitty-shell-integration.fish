#!/bin/fish

# To use fish's autoloading feature, kitty prepends the vendored integration script directory to XDG_DATA_DIRS.
# The original paths needs to be restored here to not affect other programs.
# In particular, if the original XDG_DATA_DIRS does not exist, it needs to be removed.
if set -q KITTY_FISH_XDG_DATA_DIR
    if set -q XDG_DATA_DIRS
        set --global --export --path XDG_DATA_DIRS "$XDG_DATA_DIRS"
        if set --local index (contains --index "$KITTY_FISH_XDG_DATA_DIR" $XDG_DATA_DIRS)
            set --erase --global XDG_DATA_DIRS[$index]
            test -n "$XDG_DATA_DIRS" || set --erase --global XDG_DATA_DIRS
        end
        if set -q XDG_DATA_DIRS
            set --global --export --unpath XDG_DATA_DIRS "$XDG_DATA_DIRS"
        end
    end
    set --erase KITTY_FISH_XDG_DATA_DIR
end

status is-interactive || exit 0
not functions -q __ksi_schedule || exit 0
# Check fish version 3.3.0+ efficiently and fallback to check the minimum working version 3.2.0, exit on outdated versions.
# "Warning: Update fish to version 3.3.0+ to enable kitty shell integration.\n"
set -q fish_killring || set -q status_generation || string match -qnv "3.1.*" "$version"
or echo -en \eP@kitty-print\|V2FybmluZzogVXBkYXRlIGZpc2ggdG8gdmVyc2lvbiAzLjMuMCsgdG8gZW5hYmxlIGtpdHR5IHNoZWxsIGludGVncmF0aW9uLgo=\e\\ && exit 0 || exit 0

function __ksi_schedule --on-event fish_prompt -d "Setup kitty integration after other scripts have run, we hope"
    functions --erase __ksi_schedule
    test -n "$KITTY_SHELL_INTEGRATION" || return 0
    set --local _ksi (string split " " -- "$KITTY_SHELL_INTEGRATION")
    set --erase KITTY_SHELL_INTEGRATION

    # Enable cursor shape changes for default mode and vi mode
    if not contains "no-cursor" $_ksi
        function __ksi_set_cursor --on-variable fish_key_bindings -d "Set the cursor shape for different modes when switching key bindings"
            if test "$fish_key_bindings" = fish_default_key_bindings
                function __ksi_bar_cursor --on-event fish_prompt -d "Set cursor shape to blinking bar on prompt"
                    echo -en "\e[5 q"
                end
                # Change the cursor shape on first run
                set -q argv[1]
                and __ksi_bar_cursor
            else
                functions --erase __ksi_bar_cursor
                contains "$fish_key_bindings" fish_vi_key_bindings fish_hybrid_key_bindings
                and __ksi_set_vi_cursor
            end
        end

        function __ksi_set_vi_cursor -d "Set the vi mode cursor shapes"
            # Set the vi mode cursor shapes only when none of them are configured
            set --local vi_modes fish_cursor_{default,insert,replace_one,visual}
            set -q $vi_modes
            test "$status" -eq 4 || return

            set --local vi_cursor_shapes block line underscore block
            for i in 1 2 3 4
                set --global $vi_modes[$i] $vi_cursor_shapes[$i] blink
            end

            # Change the cursor shape for current mode
            test "$fish_bind_mode" = "insert" && echo -en "\e[5 q" || echo -en "\e[1 q"
        end

        function __ksi_default_cursor --on-event fish_preexec -d "Set cursor shape to blinking default shape before executing command"
            echo -en "\e[0 q"
        end

        __ksi_set_cursor init
    end

    # Enable prompt marking with OSC 133
    if not contains "no-prompt-mark" $_ksi
        and not set -q __ksi_prompt_state
        function __ksi_mark_prompt_start --on-event fish_prompt --on-event fish_cancel --on-event fish_posterror
            test "$__ksi_prompt_state" != prompt-start
            and echo -en "\e]133;D\a"
            set --global __ksi_prompt_state prompt-start
            echo -en "\e]133;A\a"
        end
        __ksi_mark_prompt_start

        function __ksi_mark_output_start --on-event fish_preexec
            set --global __ksi_prompt_state pre-exec
            echo -en "\e]133;C\a"
        end

        function __ksi_mark_output_end --on-event fish_postexec
            set --global __ksi_prompt_state post-exec
            echo -en "\e]133;D;$status\a"
        end

        # With prompt marking, kitty clears the current prompt on resize,
        # so we need fish to redraw it.
        set --global fish_handle_reflow 1
    end

    # Enable CWD reporting
    if not contains "no-cwd" $_ksi
        # This function name is from fish and will override the builtin one, which is enabled by default for kitty in fish 3.5.0+.
        # We provide this to ensure that fish 3.2.0 and above will work.
        # https://github.com/fish-shell/fish-shell/blob/3.2.0/share/functions/__fish_config_interactive.fish#L275
        # An executed program could change cwd and report the changed cwd, so also report cwd at each new prompt
        function __update_cwd_osc --on-variable PWD --on-event fish_prompt -d "Report PWD changes to kitty"
            status is-command-substitution
            or echo -en "\e]7;kitty-shell-cwd://$hostname$PWD\a"
        end
        __update_cwd_osc
    end

    # Handle clone launches
    if test -n "$KITTY_IS_CLONE_LAUNCH"
        set --local orig_conda_env "$CONDA_DEFAULT_ENV"
        eval "$KITTY_IS_CLONE_LAUNCH"
        set --local venv "$VIRTUAL_ENV/bin/activate.fish"
        set --global _ksi_sourced
        function _ksi_s_is_ok
            test -z "$_ksi_sourced"
            and string match -q -- "*,$argv[1],*" "$KITTY_CLONE_SOURCE_STRATEGIES"
            and return 0
            return 1
        end
        if _ksi_s_is_ok "venv" 
            and test -n "$VIRTUAL_ENV" -a -r "$venv" 
            set _ksi_sourced "y"
            set --erase VIRTUAL_ENV _OLD_FISH_PROMPT_OVERRIDE  # activate.fish stupidly exports _OLD_FISH_PROMPT_OVERRIDE
            source "$venv"
        end
        if _ksi_s_is_ok "conda"
            and test -n "$CONDA_DEFAULT_ENV" -a "$CONDA_DEFAULT_ENV" != "$orig_conda_env"
            and functions -q conda
            set _ksi_sourced "y"
            conda activate "$CONDA_DEFAULT_ENV"
        end
        if _ksi_s_is_ok "env_var"
            and test -n "$KITTY_CLONE_SOURCE_CODE"
            set _ksi_sourced "y"
            eval "$KITTY_CLONE_SOURCE_CODE"
        end
        if _ksi_s_is_ok "path"
            and test -r "$KITTY_CLONE_SOURCE_PATH"
            set _ksi_sourced "y"
            source "$KITTY_CLONE_SOURCE_PATH"
        end
        set --erase KITTY_IS_CLONE_LAUNCH KITTY_CLONE_SOURCE_STRATEGIES _ksi_sourced
        functions --erase _ksi_s_is_ok

        # Ensure PATH has no duplicate entries
        set --local --path new_path
        for p in $PATH
            contains -- "$p" $new_path
            or set --append new_path "$p"
        end
        test (count $new_path) -eq (count $PATH)
        or set --global --export --path PATH $new_path
    end
end

function edit-in-kitty --wraps "kitten edit-in-kitty" -d "Edit the specified file in a kitty overlay window with your locally installed editor"
    kitten edit-in-kitty $argv
end

function __ksi_transmit_data -d "Transmit data to kitty using chunked DCS escapes"
    set --local data (string replace --regex --all -- "\s" "" "$argv[1]")
    set --local data_len (string length -- "$data")
    set --local pos 1
    set --local chunk_num 0
    while test "$pos" -le $data_len
        printf \eP@kitty-%s\|%s:%s\e\\ "$argv[2]" "$chunk_num" (string sub --start $pos --length 2048 -- "$data")
        set pos (math $pos + 2048)
        set chunk_num (math $chunk_num + 1)
    end
    printf \eP@kitty-%s\|\e\\ "$argv[2]"
end

function clone-in-kitty -d "Clone the current fish session into a new kitty window"
    set --local data
    for a in $argv
        if contains -- "$a" -h --help
            echo "Clone the current fish session into a new kitty window."
            echo
            echo "For usage instructions see: https://sw.kovidgoyal.net/kitty/shell-integration/#clone-shell"
            return
        end
        set --local ea (printf "%s" "$a" | base64)
        set --append data "a=$ea"
    end
    set --local envs
    for e in (set --export --names)
        set --append envs "$e=$$e"
    end
    set --local b64_envs (string join0 -- $envs | base64)
    set --local b64_cwd (printf "%s" "$PWD" | base64)
    set --prepend data "shell=fish" "pid=$fish_pid" "cwd=$b64_cwd" "env=$b64_envs"
    __ksi_transmit_data (string join "," -- $data) "clone"
end
