// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"fmt"
	"kitty/tools/utils"
	"strconv"
	"strings"
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
		ans = utils.Max(0, ans)
	}
	return
}

func UnitFloat(val string) (ans float64, err error) {
	ans, err = strconv.ParseFloat(val, 64)
	if err == nil {
		ans = utils.Max(0, utils.Min(ans, 1))
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
		num, _ := strconv.ParseUint(text, base, 32)
		ans.WriteRune(rune(num))
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
