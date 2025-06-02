package choose_files

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

// TODO: Comboboxes, multifile selections, save file name, file/dir modes

var _ = fmt.Print
var debugprintln = tty.DebugPrintln

type ScorePattern struct {
	pat *regexp.Regexp
	op  func(float64, float64) float64
	val float64
}

type Mode int

const (
	SELECT_SINGLE_FILE Mode = iota
	SELECT_MULTIPLE_FILES
	SELECT_SAVE_FILE
	SELECT_SAVE_DIR
	SELECT_SINGLE_DIR
	SELECT_MULTIPLE_DIRS
	SELECT_SAVE_DIR_FOR_FILES // select a dir for saving one or more pre-sent filenames, must be an existing one
)

func (m Mode) AllowsMultipleSelection() bool {
	switch m {
	case SELECT_MULTIPLE_FILES, SELECT_MULTIPLE_DIRS:
		return true
	}
	return false
}

func (m Mode) OnlyDirs() bool {
	switch m {
	case SELECT_SINGLE_DIR, SELECT_MULTIPLE_DIRS, SELECT_SAVE_DIR, SELECT_SAVE_DIR_FOR_FILES:
		return true
	}
	return false
}

func (m Mode) WindowTitle() string {
	switch m {
	case SELECT_SINGLE_FILE:
		return "Choose an existing file"
	case SELECT_MULTIPLE_FILES:
		return "Choose one or more existing files"
	case SELECT_SAVE_FILE:
		return "Choose a file to save"
	case SELECT_SAVE_DIR:
		return "Choose a directory to save"
	case SELECT_SINGLE_DIR:
		return "Choose an existing directory"
	case SELECT_MULTIPLE_DIRS:
		return "Choose one or more directories"
	case SELECT_SAVE_DIR_FOR_FILES:
		return "Choose a directory to save multiple files in"
	}
	return ""
}

type State struct {
	base_dir       string
	current_dir    string
	select_dirs    bool
	multiselect    bool
	score_patterns []ScorePattern
	search_text    string
	mode           Mode
	window_title   string

	current_idx                            int
	num_of_matches_at_last_render          int
	num_of_slots_per_column_at_last_render int
}

func (s State) BaseDir() string    { return utils.IfElse(s.base_dir == "", default_cwd, s.base_dir) }
func (s State) SelectDirs() bool   { return s.select_dirs }
func (s State) Multiselect() bool  { return s.multiselect }
func (s State) String() string     { return utils.Repr(s) }
func (s State) SearchText() string { return s.search_text }
func (s *State) SetSearchText(val string) {
	if s.search_text != val {
		s.search_text = val
		s.current_idx = 0
	}
}
func (s *State) SetCurrentDir(val string) {
	if q, err := filepath.Abs(val); err == nil {
		val = q
	}
	if s.CurrentDir() != val {
		s.search_text = ""
		s.current_idx = 0
		s.current_dir = val
	}
}
func (s State) ScorePatterns() []ScorePattern { return s.score_patterns }
func (s State) CurrentIndex() int             { return s.current_idx }
func (s *State) SetCurrentIndex(val int)      { s.current_idx = max(0, val) }
func (s State) CurrentDir() string {
	return utils.IfElse(s.current_dir == "", s.BaseDir(), s.current_dir)
}
func (s State) WindowTitle() string {
	if s.window_title == "" {
		return s.mode.WindowTitle()
	}
	return s.window_title
}

type ScreenSize struct {
	width, height, cell_width, cell_height, width_px, height_px int
}

type Handler struct {
	state       State
	screen_size ScreenSize
	scan_cache  ScanCache
	lp          *loop.Loop
}

func (h *Handler) draw_screen() (err error) {
	matches, in_progress := h.get_results()
	h.lp.SetWindowTitle(h.state.WindowTitle())
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.lp.ClearScreen()
	defer func() { // so that the cursor ends up in the right place
		h.lp.MoveCursorTo(1, 1)
		h.draw_search_bar(0)
	}()
	y := SEARCH_BAR_HEIGHT
	y += h.draw_results(y, 2, matches, in_progress)
	return
}

func load_config(opts *Options) (ans *Config, err error) {
	ans = NewConfig()
	p := config.ConfigParser{LineHandler: ans.Parse}
	err = p.LoadConfig("choose-files.conf", opts.Config, opts.Override)
	if err != nil {
		return nil, err
	}
	// ans.KeyboardShortcuts = config.ResolveShortcuts(ans.KeyboardShortcuts)
	return ans, nil
}

func (h *Handler) init_sizes(new_size loop.ScreenSize) {
	h.screen_size.width = int(new_size.WidthCells)
	h.screen_size.height = int(new_size.HeightCells)
	h.screen_size.cell_width = int(new_size.CellWidth)
	h.screen_size.cell_height = int(new_size.CellHeight)
	h.screen_size.width_px = int(new_size.WidthPx)
	h.screen_size.height_px = int(new_size.HeightPx)
}

func (h *Handler) OnInitialize() (ans string, err error) {
	if sz, err := h.lp.ScreenSize(); err != nil {
		return "", err
	} else {
		h.init_sizes(sz)
	}
	h.lp.AllowLineWrapping(false)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.draw_screen()
	return
}

func (h *Handler) OnKeyEvent(ev *loop.KeyEvent) (err error) {
	switch {
	case h.handle_edit_keys(ev), h.handle_result_list_keys(ev):
		h.draw_screen()
	case ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("ctrl+c"):
		h.lp.Quit(1)
	case ev.MatchesPressOrRepeat("tab"):
		matches, in_progress := h.get_results()
		if len(matches) > 0 && !in_progress {
			if idx := h.state.CurrentIndex(); idx < len(matches) {
				m := matches[idx].abspath
				if st, err := os.Stat(m); err == nil {
					if !st.IsDir() {
						m = filepath.Dir(m)
					}
					h.state.SetCurrentDir(m)
					return h.draw_screen()
				}
			}
		}
		h.lp.Beep()
	case ev.MatchesPressOrRepeat("shift+tab"):
		curr := h.state.CurrentDir()
		switch curr {
		case "/":
		case ".":
			if curr, err = os.Getwd(); err == nil && curr != "/" {
				h.state.SetCurrentDir(filepath.Dir(curr))
				return h.draw_screen()
			}
		default:
			h.state.SetCurrentDir(filepath.Dir(curr))
			return h.draw_screen()
		}
		h.lp.Beep()
	}
	return
}

func (h *Handler) OnText(text string, from_key_event, in_bracketed_paste bool) (err error) {
	h.state.search_text += text
	return h.draw_screen()
}

func mult(a, b float64) float64 { return a * b }
func sub(a, b float64) float64  { return a - b }
func add(a, b float64) float64  { return a + b }
func div(a, b float64) float64  { return a / b }

func (h *Handler) set_state_from_config(conf *Config, opts *Options) (err error) {
	h.state = State{}
	fmap := map[string]func(float64, float64) float64{
		"*=": mult, "+=": add, "-=": sub, "/=": div}
	h.state.score_patterns = make([]ScorePattern, len(conf.Modify_score))
	for i, x := range conf.Modify_score {
		p, rest, _ := strings.Cut(x, " ")
		if h.state.score_patterns[i].pat, err = regexp.Compile(p); err == nil {
			op, val, _ := strings.Cut(rest, " ")
			if h.state.score_patterns[i].val, err = strconv.ParseFloat(val, 64); err != nil {
				return fmt.Errorf("The modify score value %#v is invalid: %w", val, err)
			}
			if h.state.score_patterns[i].op = fmap[op]; h.state.score_patterns[i].op == nil {
				return fmt.Errorf("The modify score operator %#v is unknown", op)
			}

		} else {
			return fmt.Errorf("The modify score pattern %#v is invalid: %w", x, err)
		}

	}
	switch opts.Mode {
	case "file":
		h.state.mode = SELECT_SINGLE_FILE
	case "files":
		h.state.mode = SELECT_MULTIPLE_FILES
	case "save-file":
		h.state.mode = SELECT_SAVE_FILE
	case "dir":
		h.state.mode = SELECT_SINGLE_DIR
	case "dirs":
		h.state.mode = SELECT_MULTIPLE_DIRS
	case "save-dir":
		h.state.mode = SELECT_SAVE_DIR
	case "dir-for-files":
		h.state.mode = SELECT_SAVE_DIR_FOR_FILES
	default:
		h.state.mode = SELECT_SINGLE_FILE
	}
	return
}

var default_cwd string

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	conf, err := load_config(opts)
	if err != nil {
		return 1, err
	}
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	handler := Handler{lp: lp}
	if err = handler.set_state_from_config(conf, opts); err != nil {
		return 1, err
	}
	switch len(args) {
	case 0:
		if default_cwd, err = os.Getwd(); err != nil {
			return
		}
	case 1:
		default_cwd = args[0]
	default:
		return 1, fmt.Errorf("Can only specify one directory to search in")
	}
	default_cwd = utils.Expanduser(default_cwd)
	if default_cwd, err = filepath.Abs(default_cwd); err != nil {
		return
	}
	lp.OnInitialize = handler.OnInitialize
	lp.OnResize = func(old, new_size loop.ScreenSize) (err error) {
		handler.init_sizes(new_size)
		return handler.draw_screen()
	}
	lp.OnKeyEvent = handler.OnKeyEvent
	lp.OnText = handler.OnText
	lp.OnWakeup = func() error { return handler.draw_screen() }
	err = lp.Run()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return 1, nil
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
