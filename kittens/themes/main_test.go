// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"reflect"
	"testing"

	"github.com/kovidgoyal/kitty/kittens/unicode_input"
	"github.com/kovidgoyal/kitty/tools/utils"
)

func TestPickerCachesAreIndependent(t *testing.T) {
	original_cache_dir := utils.CacheDir
	t.Cleanup(func() { utils.CacheDir = original_cache_dir })
	for _, themes_last := range []bool{false, true} {
		name := "unicode_after_themes"
		if themes_last {
			name = "themes_after_unicode"
		}
		t.Run(name, func(t *testing.T) {
			cache_dir := t.TempDir()
			utils.CacheDir = func() string { return cache_dir }
			want_themes := &CachedData{Category: "dark", Recent: []string{"Gruvbox Dark"}}
			want_unicode := &unicode_input.CachedData{Mode: "NAME", Recent: []rune{'π', '♥'}}
			themes_cache := new_cached_values()
			unicode_cache := utils.NewCachedValues("unicode-input", &unicode_input.CachedData{Mode: unicode_input.DEFAULT_MODE})
			if themes_last {
				unicode_cache.Opts = want_unicode
				unicode_cache.Save()
				themes_cache.Load()
				themes_cache.Opts = want_themes
				themes_cache.Save()
			} else {
				themes_cache.Opts = want_themes
				themes_cache.Save()
				unicode_cache.Load()
				unicode_cache.Opts = want_unicode
				unicode_cache.Save()
			}
			if got := new_cached_values().Load(); !reflect.DeepEqual(got, want_themes) {
				t.Errorf("theme preferences changed: got %#v, want %#v", got, want_themes)
			}
			got_unicode := utils.NewCachedValues("unicode-input", &unicode_input.CachedData{Mode: unicode_input.DEFAULT_MODE}).Load()
			if !reflect.DeepEqual(got_unicode, want_unicode) {
				t.Errorf("Unicode input preferences changed: got %#v, want %#v", got_unicode, want_unicode)
			}
		})
	}
}
