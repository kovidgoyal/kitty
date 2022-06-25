#!/bin/bash

LDFLAGS=-L/opt/homebrew/lib \
    python3 setup.py kitty.app \
    --extra-include-dirs /opt/homebrew/Cellar/librsync/2.3.2/include
rm -rf /Applications/kitty.app
cp -r kitty.app /Applications/kitty.app
