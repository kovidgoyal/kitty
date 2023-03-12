// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"fmt"
	"io"
	"kitty/tools/themes"
	"kitty/tools/tui/loop"
	"time"
)

var _ = fmt.Print

type State int

const (
	FETCHING State = iota
	BROWSING
	SEARCHING
	ACCEPTING
)

type CachedData struct {
	Recent   []string `json:"recent"`
	Category string   `json:"category"`
}

type fetch_data struct {
	themes *themes.Themes
	err    error
	closer io.Closer
}

type handler struct {
	lp          *loop.Loop
	opts        *Options
	cached_data *CachedData

	state         State
	fetch_result  chan fetch_data
	all_themes    *themes.Themes
	themes_closer io.Closer
}

func (self *handler) fetch_themes() {
	r := fetch_data{}
	r.themes, r.closer, r.err = themes.LoadThemes(time.Duration(self.opts.CacheAge * float64(time.Hour*24)))
	self.lp.WakeupMainThread()
	self.fetch_result <- r
}

func (self *handler) on_wakeup() error {
	r := <-self.fetch_result
	if r.err != nil {
		return r.err
	}
	self.state = BROWSING
	self.all_themes = r.themes
	self.themes_closer = r.closer
	self.redraw_after_category_change()
	return nil
}

func (self *handler) finalize() {
	t := self.themes_closer
	if t != nil {
		t.Close()
	}
}

func (self *handler) initialize() {
	self.fetch_result = make(chan fetch_data)
	go self.fetch_themes()
	self.draw_screen()
}

func (self *handler) draw_screen() {
	// TODO: Implement me
}

func (self *handler) redraw_after_category_change() {
	// TODO: Implement me
}
