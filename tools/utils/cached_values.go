// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

var _ = fmt.Print

type CachedValues[T any] struct {
	Name string
	Opts T
}

func (self *CachedValues[T]) Path() string {
	return filepath.Join(CacheDir(), self.Name+".json")
}

func (self *CachedValues[T]) Load() T {
	raw, err := os.ReadFile(self.Path())
	if err == nil {
		json.Unmarshal(raw, self.Opts)
	}
	return self.Opts
}

func (self *CachedValues[T]) Save() {
	raw, err := json.Marshal(self.Opts)
	if err == nil {
		AtomicUpdateFile(self.Path(), bytes.NewReader(raw), 0o600)
	}
}

func NewCachedValues[T any](name string, initial_val T) *CachedValues[T] {
	return &CachedValues[T]{Name: name, Opts: initial_val}
}
