#!/bin/sh
#
# benchmark.sh
# Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the MIT license.
#
# Benchmark with every vector size supported by the CPU. Pass extra arguments
# to go test, for example: -bench=IndexByte2

export GOEXPERIMENT=simd
go test -c -o simdstring.test . || exit 1
for size in 128 256 512; do
    echo -e "\x1b[32mvector size: $size\x1b[m"
    GODEBUG=simd=+$size ./simdstring.test -test.run XXX -test.bench=. "$@" || break
done
rm -f simdstring.test
