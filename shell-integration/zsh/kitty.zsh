#!/bin/zsh
#
# This file can get sourced with aliases enabled. Moreover, it be sourced from
# zshrc, so the chance of having some aliases already defined is high. To avoid
# alias expansion we quote everything that can be quoted. Some aliases will
# still break us. For example:
#
#   alias -g -- -r='$RANDOM'
#
# For this reason users are discouraged from sourcing kitty.zsh in favor of
# invoking kitty-integration directly.

# ${(%):-%x} is the path to the current file.
# On top of it we add :A:h to get the directory.
'builtin' 'typeset' _ksi_file="${${(%):-%x}:A:h}"/kitty-integration
if [[ -r "$_ksi_file" ]]; then
    'builtin' 'autoload' '-Uz' '--' "$_ksi_file"
    "${_ksi_file:t}"
    'builtin' 'unfunction' '--' "${_ksi_file:t}"
fi
'builtin' 'unset' '_ksi_file'
