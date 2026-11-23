#!/bin/sh
#
# test.sh
# Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the MIT license.
#

export GOEXPERIMENT=simd
echo -e "\x1b[32mtesting amd64\x1b[m" && go test -v &&
    echo -e "\x1b[32mtesting arm64\x1b[m" && GOARCH=arm64 go test -v -exec qemu-aarch64-static &&
    echo -e "\x1b[32mtesting without the simd experiment\x1b[m" && GOEXPERIMENT=nosimd go test -v
