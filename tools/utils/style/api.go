// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"strings"
)

type Context struct {
	AllowEscapeCodes bool
}

func (self *Context) SprintFunc(spec string) func(args ...interface{}) string {
	p := prefix_for_spec(spec)
	s := suffix_for_spec(spec)

	return func(args ...interface{}) string {
		body := fmt.Sprint(args...)
		if !self.AllowEscapeCodes {
			return body
		}
		b := strings.Builder{}
		b.Grow(len(p) + len(body) + len(s))
		b.WriteString(p)
		b.WriteString(body)
		b.WriteString(s)
		return b.String()
	}
}
