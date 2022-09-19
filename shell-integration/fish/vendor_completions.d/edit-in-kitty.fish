function __ksi_completions
    set --local ct (commandline --current-token)
    set --local tokens (commandline --tokenize --cut-at-cursor --current-process)
    printf "%s\n" $tokens $ct | command kitty-tool __complete__ fish
end

complete -f -c edit-in-kitty -a "(__ksi_completions)"
