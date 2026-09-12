#!/bin/sh

: "${KITTY_MATRIX_GO:?KITTY_MATRIX_GO is required}"

printf '\033[?25h\033[2J\033[H'
printf '\033[8;12H'

while [ ! -e "$KITTY_MATRIX_GO" ]; do
    sleep 0.01
done

printf '\033[20;58H'
sleep 2
