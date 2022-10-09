// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package markup

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"kitty"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
)

var _ = fmt.Print

type Context struct {
	fmt_ctx style.Context

	Cyan, Green, Blue, BrightRed, Yellow, Italic, Bold, Title, Exe, Opt, Emph, Err, Code func(args ...interface{}) string
	Url                                                                                  func(string, string) string
}

var (
	fmt_ctx = style.Context{}
)

func New(allow_escape_codes bool) *Context {
	ans := Context{}
	ans.fmt_ctx.AllowEscapeCodes = allow_escape_codes
	fmt_ctx := &ans.fmt_ctx

	ans.Cyan = fmt_ctx.SprintFunc("fg=bright-cyan")
	ans.Green = fmt_ctx.SprintFunc("fg=green")
	ans.Blue = fmt_ctx.SprintFunc("fg=blue")
	ans.BrightRed = fmt_ctx.SprintFunc("fg=bright-red")
	ans.Yellow = fmt_ctx.SprintFunc("fg=bright-yellow")
	ans.Italic = fmt_ctx.SprintFunc("italic")
	ans.Bold = fmt_ctx.SprintFunc("bold")
	ans.Title = fmt_ctx.SprintFunc("bold fg=blue")
	ans.Exe = fmt_ctx.SprintFunc("bold fg=bright-yellow")
	ans.Opt = ans.Green
	ans.Emph = ans.BrightRed
	ans.Err = fmt_ctx.SprintFunc("bold fg=bright-red")
	ans.Code = ans.Cyan
	ans.Url = fmt_ctx.UrlFunc("u=curly uc=cyan")

	return &ans
}

func replace_all_rst_roles(str string, repl func(rst_format_match) string) string {
	var m rst_format_match
	rf := func(full_match string, groupdict map[string]utils.SubMatch) string {
		m.payload = groupdict["payload"].Text
		m.role = groupdict["role"].Text
		return repl(m)
	}
	return utils.ReplaceAll(":(?P<role>[a-z]+):(?:(?:`(?P<payload>[^`]+)`)|(?:'(?P<payload>[^']+)'))", str, rf)
}

func (self *Context) hyperlink_for_url(url string, text string) string {
	return self.Url(url, text)
}

func (self *Context) hyperlink_for_path(path string, text string) string {
	if !fmt_ctx.AllowEscapeCodes {
		return text
	}
	path = strings.ReplaceAll(utils.Abspath(path), string(os.PathSeparator), "/")
	fi, err := os.Stat(path)
	if err == nil && fi.IsDir() {
		path = strings.TrimSuffix(path, "/") + "/"
	}
	host := utils.CachedHostname()
	url := "file://" + host + path
	return self.hyperlink_for_url(url, text)
}

func text_and_target(x string) (text string, target string) {
	parts := strings.SplitN(x, "<", 2)
	text = strings.TrimSpace(parts[0])
	target = strings.TrimRight(parts[len(parts)-1], ">")
	return
}

type rst_format_match struct {
	role, payload string
}

func (self *Context) ref_hyperlink(x string, prefix string) string {
	text, target := text_and_target(x)
	url := "kitty+doc://" + utils.CachedHostname() + "/#ref=" + prefix + target
	text = replace_all_rst_roles(text, func(group rst_format_match) string {
		return group.payload
	})
	return self.hyperlink_for_url(url, text)
}

func (self *Context) Prettify(text string) string {
	return replace_all_rst_roles(text, func(group rst_format_match) string {
		val := group.payload
		switch group.role {
		case "file":
			if val == "kitty.conf" && self.fmt_ctx.AllowEscapeCodes {
				path := filepath.Join(utils.ConfigDir(), val)
				val = self.hyperlink_for_path(path, val)
			}
			return self.Italic(val)
		case "env", "envvar":
			return self.ref_hyperlink(val, "envvar-")
		case "doc":
			text, target := text_and_target(val)
			if text == target {
				target = strings.Trim(target, "/")
				if title, ok := kitty.DocTitleMap[target]; ok {
					val = title + " <" + target + ">"
				}
			}
			return self.ref_hyperlink(val, "doc-")
		case "iss":
			return self.ref_hyperlink(val, "issues-")
		case "pull":
			return self.ref_hyperlink(val, "pull-")
		case "disc":
			return self.ref_hyperlink(val, "discussions-")
		case "ref":
			return self.ref_hyperlink(val, "")
		case "ac":
			return self.ref_hyperlink(val, "action-")
		case "term":
			return self.ref_hyperlink(val, "term-")
		case "code":
			return self.Code(val)
		case "option":
			idx := strings.LastIndex(val, "--")
			if idx < 0 {
				idx = strings.Index(val, "-")
			}
			if idx > -1 {
				val = val[idx:]
			}
			return self.Bold(val)
		case "opt":
			return self.Bold(val)
		case "yellow":
			return self.Yellow(val)
		case "blue":
			return self.Blue(val)
		case "green":
			return self.Green(val)
		case "cyan":
			return self.Cyan(val)
		case "emph":
			return self.Italic(val)
		default:
			return val
		}

	})
}

func (self *Context) SetAllowEscapeCodes(allow_escape_codes bool) {
	self.fmt_ctx.AllowEscapeCodes = allow_escape_codes
}

func (self *Context) EscapeCodesAllowed() bool {
	return self.fmt_ctx.AllowEscapeCodes
}
