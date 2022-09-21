// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"strings"
)

type Context struct {
	AllowEscapeCodes bool
}

func (self *Context) SprintFunc(spec string) func(args ...any) string {
	p := prefix_for_spec(spec)
	s := suffix_for_spec(spec)

	return func(args ...any) string {
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

func (self *Context) UrlFunc(spec string) func(string, string) string {
	p := prefix_for_spec(spec)
	s := suffix_for_spec(spec)

	return func(url, text string) string {
		if !self.AllowEscapeCodes {
			return text
		}
		uc := url_code{url: url}
		up, us := uc.prefix(), uc.suffix()
		b := strings.Builder{}
		b.Grow(len(p) + len(up) + len(text) + len(s) + len(us))
		b.WriteString(p)
		b.WriteString(up)
		b.WriteString(text)
		b.WriteString(us)
		b.WriteString(s)
		return b.String()
	}
}
