// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shortcuts

import (
	"fmt"
)

var _ = fmt.Print

func (self *ShortcutMap[T]) first_action() (ans T) {
	for _, ac := range self.leaves {
		return ac
	}
	for _, child := range self.children {
		return child.first_action()
	}
	return
}

func (self *ShortcutMap[T]) shortcut_for(ac T) (keys []string) {
	keys = []string{}
	for key, q := range self.leaves {
		if ac == q {
			return append(keys, key)
		}
	}
	for key, child := range self.children {
		ckeys := child.shortcut_for(ac)
		if len(ckeys) > 0 {
			return append(append(keys, key), ckeys...)
		}
	}
	return
}

func (self *ShortcutMap[T]) add(ac T, keys []string) (conflict T) {
	sm := self
	last := len(keys) - 1
	for i, key := range keys {
		if i == last {
			if c, found := sm.leaves[key]; found {
				conflict = c
			}
			sm.leaves[key] = ac
			if c, found := sm.children[key]; found {
				conflict = c.first_action()
				delete(sm.children, key)
			}
		} else {
			if c, found := sm.leaves[key]; found {
				conflict = c
				delete(sm.leaves, key)
			}
			q := sm.children[key]
			if q == nil {
				q = &ShortcutMap[T]{leaves: map[string]T{}, children: map[string]*ShortcutMap[T]{}}
				sm.children[key] = q
			}
			sm = q
		}
	}
	return
}
