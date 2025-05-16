// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shortcuts

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"strings"
)

var _ = fmt.Print

type ShortcutMap[T comparable] struct {
	leaves   map[string]T
	children map[string]*ShortcutMap[T]
}

func (self *ShortcutMap[T]) ResolveKeyEvent(k *loop.KeyEvent, pending_keys ...string) (ac T, pending string) {
	q := self
	for _, pk := range pending_keys {
		q = self.children[pk]
		if q == nil {
			return
		}
	}
	for c, ans := range q.leaves {
		if k.MatchesPressOrRepeat(c) {
			ac = ans
			return
		}
	}
	for c := range q.children {
		if k.MatchesPressOrRepeat(c) {
			pending = c
			return
		}
	}
	return
}

func (self *ShortcutMap[T]) Add(ac T, keys ...string) (conflict T) {
	return self.add(ac, keys)
}

func (self *ShortcutMap[T]) AddOrPanic(ac T, keys ...string) {
	var zero T
	c := self.add(ac, keys)
	if c != zero {
		panic(fmt.Sprintf("The shortcut for %#v (%s) conflicted with the shortcut for %#v (%s)",
			ac, strings.Join(keys, " "), c, strings.Join(self.shortcut_for(c), " ")))
	}
}

func New[T comparable]() *ShortcutMap[T] {
	return &ShortcutMap[T]{leaves: make(map[string]T), children: make(map[string]*ShortcutMap[T])}
}
