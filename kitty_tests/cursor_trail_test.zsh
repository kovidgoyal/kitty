#!/usr/bin/env zsh
# Exercise the animated cursor trail with frequent, large cursor jumps.
#
# Usage:
#   kitty_tests/cursor_trail_test.zsh [iterations] [delay-in-seconds] [shape]
#
# Run this from inside a kitty window built from this checkout.

iterations=${1:-250}
delay=${2:-0.06}
shape=${3:-}

case "$shape" in
    block)
        printf '\033[2 q'
        ;;
    beam)
        printf '\033[6 q'
        ;;
    underline)
        printf '\033[4 q'
        ;;
    '')
        ;;
    *)
        print -u2 "usage: $0 [iterations] [delay-in-seconds] [block|beam|underline]"
        exit 2
        ;;
esac

i=1

while (( i <= iterations )); do
    y=$((2 + (i * 11 % 28)))
    x=$((2 + (i * 23 % 110)))
    printf '\033[%d;%dH' "$y" "$x"
    sleep "$delay"
    (( i++ ))
done
