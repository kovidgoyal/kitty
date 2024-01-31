#!/bin/sh
#
# generate.sh
# Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
#
# Distributed under terms of the MIT license.
#
go run generate.go && GOARCH=amd64 go vet ./... && GOARCH=arm64 go vet ./...
