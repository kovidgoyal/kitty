function __ksi_completions
    set --local ct (commandline --current-token)
    set --local tokens (commandline --tokenize --cut-at-cursor --current-process)
    printf "%s\n" $tokens $ct | KITTY_SHELL_INTEGRATION_COMPLETION=1 command kitten __complete__ fish | source -
end

complete -f -c kitten -a "(__ksi_completions)"
