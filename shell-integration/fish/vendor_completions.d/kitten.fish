function __ksi_completions
    set --local ct (commandline --current-token)
    set --local tokens (commandline --tokenize --cut-at-cursor --current-process)
    printf "%s\n" $tokens $ct | command kitten __complete__ fish | source -
end

complete -f -c kitten -a "(__ksi_completions)"
