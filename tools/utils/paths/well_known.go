// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package paths

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type Ctx struct {
	home, cwd string
}

func (ctx *Ctx) SetHome(val string) {
	ctx.home = val
}

func (ctx *Ctx) SetCwd(val string) {
	ctx.cwd = val
}

func (ctx *Ctx) HomePath() (ans string) {
	ans = ctx.home
	if ans == "" {
		ans = utils.Expanduser("~")
	}
	return
}

func (ctx *Ctx) CwdPath() (ans string) {
	ans = ctx.cwd
	if ans == "" {
		var err error
		ans, err = os.Getwd()
		if err != nil {
			ans = "."
		}
	}
	return
}

func abspath(path, base string) (ans string) {
	return filepath.Join(base, path)
}

func (ctx *Ctx) Abspath(path string) (ans string) {
	return abspath(path, ctx.CwdPath())
}

func (ctx *Ctx) AbspathFromHome(path string) (ans string) {
	return abspath(path, ctx.HomePath())
}

func (ctx *Ctx) ExpandHome(path string) (ans string) {
	if strings.HasPrefix(path, "~/") {
		return ctx.AbspathFromHome(path)
	}
	return path
}
