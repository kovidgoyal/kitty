function __ksi_completions
    set --local ct (commandline --current-token)
    set --local tokens (commandline --tokenize --cut-at-cursor --current-process)
    printf "%s\n" $tokens $ct | command daddy __complete__ fish | source -
end

complete -f -c daddy -a "(__ksi_completions)"
