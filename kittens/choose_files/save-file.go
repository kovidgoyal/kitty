package choose_files

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func (h *Handler) complete_save_prompt(before_cursor, after_cursor string) *cli.Completions {
	path := before_cursor
	prefix := ""
	if idx := strings.Index(path, string(os.PathSeparator)); idx > -1 {
		prefix = filepath.Dir(path) + string(os.PathSeparator)
	}
	if !filepath.IsAbs(path) {
		path = filepath.Join(h.state.CurrentDir(), path)
	}
	dir := filepath.Dir(path)
	if strings.HasSuffix(before_cursor, string(os.PathSeparator)) {
		dir = path
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	ans := cli.NewCompletions()
	dirs := ans.AddMatchGroup("Directories")
	dirs.IsFiles = true
	dirs.NoTrailingSpace = true
	files := ans.AddMatchGroup("Files")
	files.IsFiles = true
	files.NoTrailingSpace = true
	leading, _ := filepath.Rel(dir, path)
	if leading == "." {
		leading = ""
	}
	for _, e := range entries {
		word := e.Name()
		if leading == "" || strings.HasPrefix(word, leading) {
			collection := utils.IfElse(e.Type().IsDir(), dirs, files)
			if prefix != "" {
				word = prefix + word
			}
			collection.Matches = append(collection.Matches, &cli.Match{Word: word})
		}
	}
	return ans
}

func (h *Handler) current_save_file_path() string {
	ans := h.rl.AllText()
	if ans != "" {
		ans = utils.Expanduser(ans)
		if !filepath.IsAbs(ans) {
			ans = filepath.Join(h.state.save_file_cdir, ans)
		}
	}
	return ans
}

func (h *Handler) save_file_name_handle_key(ev *loop.KeyEvent) (err error) {
	switch {
	case ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("ctrl+c"):
		h.state.selections = nil
		h.state.screen = NORMAL
		err = h.draw_screen()
	case ev.MatchesPressOrRepeat("enter"):
		if p := h.current_save_file_path(); p != "" {
			h.state.selections = []string{p}
			h.lp.Quit(0)
		} else {
			h.lp.Beep()
		}
	default:
		if err = h.rl.OnKeyEvent(ev); err == nil {
			err = h.draw_screen()
		}
	}
	return
}

func (h *Handler) initialize_save_file_name(use_fname_when_no_selections string) {
	h.state.screen = SAVE_FILE
	h.rl.ResetText()
	cdir := h.state.CurrentDir()
	fname := use_fname_when_no_selections
	if len(h.state.selections) > 0 {
		if q, err := filepath.Abs(h.state.selections[0]); err == nil {
			if s, err := os.Stat(q); err == nil {
				if s.IsDir() == h.state.mode.OnlyDirs() {
					cdir = filepath.Dir(q)
					fname = filepath.Base(q)
				}
			}
		}
	}
	h.rl.SetText(fname)
	h.state.save_file_cdir = cdir
}

func (h *Handler) draw_save_file_name_screen() (err error) {
	desc := utils.IfElse(h.state.mode == SELECT_SAVE_FILE, "file", "directory")
	h.lp.Println("Enter the name of the", desc, "below, relative to:")
	h.lp.Println(h.lp.SprintStyled("fg=green", h.state.save_file_cdir))
	h.lp.Println()
	h.rl.RedrawNonAtomic()
	return
}
