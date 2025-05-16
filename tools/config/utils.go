// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"unicode/utf8"
)

var _ = fmt.Print

func ParseStrDict(val, record_sep, field_sep string) (map[string]string, error) {
	ans := make(map[string]string)
	for _, record := range strings.Split(val, record_sep) {
		key, val, found := strings.Cut(record, field_sep)
		if found {
			ans[key] = val
		}
	}
	return ans, nil
}

func PositiveFloat(val string) (ans float64, err error) {
	ans, err = strconv.ParseFloat(val, 64)
	if err == nil {
		ans = max(0, ans)
	}
	return
}

func UnitFloat(val string) (ans float64, err error) {
	ans, err = strconv.ParseFloat(val, 64)
	if err == nil {
		ans = max(0, min(ans, 1))
	}
	return
}

func StringLiteral(val string) (string, error) {
	ans := strings.Builder{}
	ans.Grow(len(val))
	var buf [8]rune
	bufcount := 0
	buflimit := 0
	var prefix rune
	type State int
	const (
		normal State = iota
		backslash
		octal
		hex
	)
	var state State
	decode := func(base int) {
		text := string(buf[:bufcount])
		if num, err := strconv.ParseUint(text, base, 32); err == nil && num <= utf8.MaxRune {
			ans.WriteRune(rune(num))
		}
		state = normal
		bufcount = 0
		buflimit = 0
		prefix = 0
	}

	write_invalid_buf := func() {
		ans.WriteByte('\\')
		ans.WriteRune(prefix)
		for _, r := range buf[:bufcount] {
			ans.WriteRune(r)
		}
		state = normal
		bufcount = 0
		buflimit = 0
		prefix = 0
	}

	var dispatch_ch_recurse func(rune)

	dispatch_ch := func(ch rune) {
		switch state {
		case normal:
			switch ch {
			case '\\':
				state = backslash
			default:
				ans.WriteRune(ch)
			}
		case octal:
			switch ch {
			case '0', '1', '2', '3', '4', '5', '6', '7':
				if bufcount >= buflimit {
					decode(8)
					dispatch_ch_recurse(ch)
				} else {
					buf[bufcount] = ch
					bufcount++
				}
			default:
				decode(8)
				dispatch_ch_recurse(ch)
			}
		case hex:
			switch ch {
			case '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'A', 'b', 'B', 'c', 'C', 'd', 'D', 'e', 'E', 'f', 'F':
				buf[bufcount] = ch
				bufcount++
				if bufcount >= buflimit {
					decode(16)
				}
			default:
				write_invalid_buf()
				dispatch_ch_recurse(ch)
			}
		case backslash:
			switch ch {
			case '\n':
			case '\\':
				ans.WriteRune('\\')
				state = normal
			case '\'', '"':
				ans.WriteRune(ch)
				state = normal
			case 'a':
				ans.WriteRune('\a')
				state = normal
			case 'b':
				ans.WriteRune('\b')
				state = normal
			case 'f':
				ans.WriteRune('\f')
				state = normal
			case 'n':
				ans.WriteRune('\n')
				state = normal
			case 'r':
				ans.WriteRune('\r')
				state = normal
			case 't':
				ans.WriteRune('\t')
				state = normal
			case 'v':
				ans.WriteRune('\v')
				state = normal
			case '0', '1', '2', '3', '4', '5', '6', '7':
				buf[0] = ch
				bufcount = 1
				buflimit = 3
				state = octal
			case 'x':
				bufcount = 0
				buflimit = 2
				state = hex
				prefix = ch
			case 'u':
				bufcount = 0
				buflimit = 4
				state = hex
				prefix = ch
			case 'U':
				bufcount = 0
				buflimit = 8
				state = hex
				prefix = ch
			default:
				ans.WriteByte('\\')
				ans.WriteRune(ch)
				state = normal
			}
		}
	}
	dispatch_ch_recurse = dispatch_ch
	for _, ch := range val {
		dispatch_ch(ch)
	}
	switch state {
	case octal:
		decode(8)
	case hex:
		write_invalid_buf()
	case backslash:
		ans.WriteRune('\\')
	}
	return ans.String(), nil
}

var ModMap = sync.OnceValue(func() map[string]string {
	return map[string]string{
		"shift":     "shift",
		"⇧":         "shift",
		"alt":       "alt",
		"option":    "alt",
		"opt":       "alt",
		"⌥":         "alt",
		"super":     "super",
		"command":   "super",
		"cmd":       "super",
		"⌘":         "super",
		"control":   "ctrl",
		"ctrl":      "ctrl",
		"⌃":         "ctrl",
		"hyper":     "hyper",
		"meta":      "meta",
		"num_lock":  "num_lock",
		"caps_lock": "caps_lock",
	}
})

var ShortcutSpecPat = sync.OnceValue(func() *regexp.Regexp {
	return regexp.MustCompile(`([^+])>`)
})

func NormalizeShortcut(spec string) string {
	parts := strings.Split(strings.ToLower(spec), "+")
	key := parts[len(parts)-1]
	if len(parts) == 1 {
		return key
	}
	mods := parts[:len(parts)-1]
	mmap := ModMap()
	mods = utils.Map(func(x string) string {
		ans := mmap[x]
		if ans == "" {
			ans = x
		}
		return ans
	}, mods)
	slices.Sort(mods)
	return strings.Join(mods, "+") + "+" + key
}

func NormalizeShortcuts(spec string) []string {
	if strings.HasSuffix(spec, "+") {
		spec = spec[:len(spec)-1] + "plus"
	}
	spec = strings.ReplaceAll(spec, "++", "+plus")
	spec = ShortcutSpecPat().ReplaceAllString(spec, "$1\x00")
	return utils.Map(NormalizeShortcut, strings.Split(spec, "\x00"))
}

type KeyAction struct {
	Normalized_keys []string
	Name            string
	Args            string
}

func (self *KeyAction) String() string {
	return fmt.Sprintf("map %#v %#v %#v\n", strings.Join(self.Normalized_keys, ">"), self.Name, self.Args)
}

func ParseMap(val string) (*KeyAction, error) {
	spec, action, found := strings.Cut(val, " ")
	if !found {
		return nil, fmt.Errorf("No action specified for shortcut %s", val)
	}
	action = strings.TrimSpace(action)
	action_name, action_args, _ := strings.Cut(action, " ")
	action_args = strings.TrimSpace(action_args)
	return &KeyAction{Name: action_name, Args: action_args, Normalized_keys: NormalizeShortcuts(spec)}, nil
}

type ShortcutTracker struct {
	partial_matches      []*KeyAction
	partial_num_consumed int
}

func (self *ShortcutTracker) Match(ev *loop.KeyEvent, all_actions []*KeyAction) *KeyAction {
	if self.partial_num_consumed > 0 {
		ev.Handled = true
		self.partial_matches = utils.Filter(self.partial_matches, func(ac *KeyAction) bool {
			return self.partial_num_consumed < len(ac.Normalized_keys) && ev.MatchesPressOrRepeat(ac.Normalized_keys[self.partial_num_consumed])
		})
		if len(self.partial_matches) == 0 {
			self.partial_num_consumed = 0
			return nil
		}
	} else {
		self.partial_matches = utils.Filter(all_actions, func(ac *KeyAction) bool {
			return ev.MatchesPressOrRepeat(ac.Normalized_keys[0])
		})
		if len(self.partial_matches) == 0 {
			return nil
		}
		ev.Handled = true
	}
	self.partial_num_consumed++
	for _, x := range self.partial_matches {
		if self.partial_num_consumed >= len(x.Normalized_keys) {
			self.partial_num_consumed = 0
			return x
		}
	}
	return nil
}

func ResolveShortcuts(actions []*KeyAction) []*KeyAction {
	action_map := make(map[string]*KeyAction, len(actions))
	for _, ac := range actions {
		key := strings.Join(ac.Normalized_keys, "\x00")
		if ac.Name == "no_op" || ac.Name == "no-op" {
			delete(action_map, key)
		} else {
			action_map[key] = ac
		}
	}
	return utils.Values(action_map)
}
