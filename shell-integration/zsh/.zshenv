# This file can get sourced with aliases enabled. To avoid alias expansion
# we quote everything that can be quoted. Some aliases will still break us
# though.

# Don't use [[ -v ... ]] because it doesn't work in zsh < 5.4.
if [[ -n "${KITTY_ORIG_ZDOTDIR+X}" ]]; then
    # Normally ZDOTDIR shouldn't be exported but it was in the environment
    # of kitty, so we export it.
    'builtin' 'export' ZDOTDIR="$KITTY_ORIG_ZDOTDIR"
    'builtin' 'unset' 'KITTY_ORIG_ZDOTDIR'
else
    'builtin' 'unset' 'ZDOTDIR'
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
    'builtin' 'typeset' _ksi_file=${ZDOTDIR-~}"/.zshenv"
    # Zsh ignores unreadable rc files. We do the same.
    # Zsh ignores rc files that are directories, and so does source.
    [[ ! -r "$_ksi_file" ]] || 'builtin' 'source' '--' "$_ksi_file"
} always {
    if [[ -o 'interactive' && -n "${KITTY_SHELL_INTEGRATION-}" ]]; then
        'builtin' 'autoload' '--' 'is-at-least'
        'is-at-least' "5.1" || {
            builtin echo "ZSH ${ZSH_VERSION} is too old for kitty shell integration" > /dev/stderr
            return
        }
        # ${(%):-%x} is the path to the current file.
        # On top of it we add :A:h to get the directory.
        'builtin' 'typeset' _ksi_file="${${(%):-%x}:A:h}"/kitty-integration
        if [[ -r "$_ksi_file" ]]; then
            'builtin' 'autoload' '-Uz' '--' "$_ksi_file"
            "${_ksi_file:t}"
            'builtin' 'unfunction' '--' "${_ksi_file:t}"
        fi
    fi
    'builtin' 'unset' '_ksi_file'
}
