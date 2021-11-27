if [[ -o interactive && -v ZDOTDIR && -r "$ZDOTDIR/kitty.zsh" ]]; then source "$ZDOTDIR/kitty.zsh"; fi
if [[ -v KITTY_ORIG_ZDOTDIR ]]; then
    export ZDOTDIR="$KITTY_ORIG_ZDOTDIR"
    unset KITTY_ORIG_ZDOTDIR
else
    unset ZDOTDIR
fi
if [[ -v KITTY_ZSH_BASE && -r "$KITTY_ZSH_BASE/.zshenv" ]]; then source "$KITTY_ZSH_BASE/.zshenv"; fi
unset KITTY_ZSH_BASE
