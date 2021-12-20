# Don't use [[ -v ... ]] because it doesn't work in zsh < 5.4.
if (( ${+KITTY_ORIG_ZDOTDIR} )); then
    # Normally ZDOTDIR shouldn't be exported but it was in the environment
    # of Kitty, so we export it.
    export ZDOTDIR=$KITTY_ORIG_ZDOTDIR
    unset KITTY_ORIG_ZDOTDIR
else
    unset ZDOTDIR
fi

# Use try-always to have the right error code.
{
    # Zsh treats empty $ZDOTDIR as if it was "/". We do the same.
    #
    # Source the user's zshenv before sourcing kitty.zsh because the former
    # might set fpath and other things without which kitty.zsh won't work.
    #
    # Use typeset in case we are in a function with warn_create_global in
    # effect. Unlikely but better safe than sorry.
    typeset _ksi_source=${ZDOTDIR-~}/.zshenv
    # Zsh ignores unreadable rc files. We do the same.
    # Zsh ignores rc files that are directories, and so does source.
    [[ ! -r $_ksi_source ]] || source -- "$_ksi_source"
} always {
    if [[ -o interactive ]]; then
        # ${(%):-%x} is the path to the current file.
        # On top of it we add :a:h to get the directory.
        typeset _ksi_source=${${(%):-%x}:A:h}/kitty.zsh
        [[ ! -r $_ksi_source ]] || source -- "$_ksi_source"
    fi
    unset _ksi_source
}
