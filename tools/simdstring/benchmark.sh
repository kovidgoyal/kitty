#!/bin/sh
#
# test.sh
# Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the MIT license.
#

go run generate.go && go test -bench=.


