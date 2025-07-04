package choose_files

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
)

// TODO: multifile selections, save file name completion

var _ = fmt.Print
var debugprintln = tty.DebugPrintln

type Screen int

const (
	NORMAL Screen = iota
	SAVE_FILE
)

type Mode int

const (
	SELECT_SINGLE_FILE Mode = iota
	SELECT_MULTIPLE_FILES
	SELECT_SAVE_FILE
	SELECT_SAVE_FILES
	SELECT_SAVE_DIR
	SELECT_SINGLE_DIR
	SELECT_MULTIPLE_DIRS
)

func (m Mode) CanSelectNonExistent() bool {
	switch m {
	case SELECT_SAVE_FILE, SELECT_SAVE_DIR, SELECT_SAVE_FILES:
		return true
	}
	return false
}

func (m Mode) AllowsMultipleSelection() bool {
	switch m {
	case SELECT_MULTIPLE_FILES, SELECT_MULTIPLE_DIRS, SELECT_SAVE_FILES:
		return true
	}
	return false
}

func (m Mode) OnlyDirs() bool {
	switch m {
	case SELECT_SINGLE_DIR, SELECT_MULTIPLE_DIRS, SELECT_SAVE_DIR:
		return true
	}
	return false
}

func (m Mode) SelectFiles() bool {
	switch m {
	case SELECT_SINGLE_FILE, SELECT_MULTIPLE_FILES, SELECT_SAVE_FILE, SELECT_SAVE_FILES:
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
	case SELECT_SAVE_FILES:
		return "Choose files to save"
	}
	return ""
}

type render_state struct {
	num_matches, num_of_slots, num_before, num_per_column, num_columns int
}

type State struct {
	base_dir                 string
	current_dir              string
	select_dirs              bool
	multiselect              bool
	search_text              string
	mode                     Mode
	suggested_save_file_name string
	window_title             string
	screen                   Screen
	current_filter           string
	filter_map               map[string]Filter
	filter_names             []string

	save_file_cdir string
	selections     []string
	current_idx    CollectionIndex
	last_render    render_state
}

func (s State) BaseDir() string    { return utils.IfElse(s.base_dir == "", default_cwd, s.base_dir) }
func (s State) Filter() Filter     { return s.filter_map[s.current_filter] }
func (s State) SelectDirs() bool   { return s.select_dirs }
func (s State) Multiselect() bool  { return s.multiselect }
func (s State) String() string     { return utils.Repr(s) }
func (s State) SearchText() string { return s.search_text }
func (s State) OnlyDirs() bool     { return s.mode.OnlyDirs() }
func (s *State) SetSearchText(val string) {
	if s.search_text != val {
		s.search_text = val
		s.current_idx = CollectionIndex{}
	}
}
func (s *State) SetCurrentDir(val string) {
	if q, err := filepath.Abs(val); err == nil {
		val = q
	}
	if s.CurrentDir() != val {
		s.search_text = ""
		s.current_idx = CollectionIndex{}
		s.current_dir = val
	}
}
func (s State) CurrentIndex() CollectionIndex        { return s.current_idx }
func (s *State) SetCurrentIndex(val CollectionIndex) { s.current_idx = val }
func (s State) CurrentDir() string {
	return utils.IfElse(s.current_dir == "", s.BaseDir(), s.current_dir)
}
func (s State) WindowTitle() string {
	if s.window_title == "" {
		return s.mode.WindowTitle()
	}
	return s.window_title
}
func (s *State) AddSelection(abspath string) bool {
	if !slices.Contains(s.selections, abspath) {
		s.selections = append(s.selections, abspath)
		return true
	}
	return false
}

func (s *State) ToggleSelection(abspath string) {
	before := len(s.selections)
	s.selections = slices.DeleteFunc(s.selections, func(x string) bool { return x == abspath })
	if len(s.selections) == before {
		s.selections = append(s.selections, abspath)
	}
}

type ScreenSize struct {
	width, height, cell_width, cell_height, width_px, height_px int
}

type Handler struct {
	state          State
	screen_size    ScreenSize
	result_manager *ResultManager
	lp             *loop.Loop
	rl             *readline.Readline
	err_chan       chan error
}

func (h *Handler) draw_screen() (err error) {
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.lp.ClearScreen()
	switch h.state.screen {
	case NORMAL:
		matches, is_complete := h.get_results()
		h.lp.SetWindowTitle(h.state.WindowTitle())
		defer func() { // so that the cursor ends up in the right place
			h.lp.MoveCursorTo(1, 1)
			h.draw_search_bar(0)
		}()
		y := SEARCH_BAR_HEIGHT
		footer_height, err := h.draw_footer()
		if err != nil {
			return err
		}
		y += h.draw_results(y, footer_height, matches, !is_complete)
	case SAVE_FILE:
		err = h.draw_save_file_name_screen()
	}
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
	h.rl.ClearCachedScreenSize()
}

func (h *Handler) OnInitialize() (ans string, err error) {
	if sz, err := h.lp.ScreenSize(); err != nil {
		return "", err
	} else {
		h.init_sizes(sz)
	}
	h.lp.AllowLineWrapping(false)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.lp.StartBracketedPaste()
	h.result_manager.set_root_dir(h.state.CurrentDir(), h.state.Filter())
	h.draw_screen()
	return
}

func (h *Handler) current_abspath() string {
	matches, _ := h.get_results()
	if r := matches.At(h.state.CurrentIndex()); r != nil {
		return filepath.Join(h.state.CurrentDir(), r.text)
	}
	return ""

}

func (h *Handler) add_selection_if_possible() bool {
	m := h.current_abspath()
	if m != "" {
		return h.state.AddSelection(m)
	}
	return false
}

func (h *Handler) toggle_selection() bool {
	m := h.current_abspath()
	if m != "" {
		h.state.ToggleSelection(m)
		return true
	}
	return false
}

func (h *Handler) change_current_dir(dir string) {
	if dir != h.state.CurrentDir() {
		h.state.SetCurrentDir(dir)
		h.result_manager.set_root_dir(h.state.CurrentDir(), h.state.Filter())
		h.state.last_render = render_state{}
	}
}

func (h *Handler) set_query(q string) {
	if q != h.state.SearchText() {
		h.state.SetSearchText(q)
		h.result_manager.set_query(h.state.SearchText(), h.state.Filter())
		h.state.last_render = render_state{}
	}
}

func (h *Handler) set_filter(filter_name string) {
	if filter_name != h.state.current_filter {
		h.state.current_filter = filter_name
		h.result_manager.set_filter(h.state.Filter())
		h.state.last_render = render_state{}
	}
}

func (h *Handler) change_to_current_dir_if_possible() error {
	if m := h.current_abspath(); m != "" {
		if st, err := os.Stat(m); err == nil {
			if !st.IsDir() {
				m = filepath.Dir(m)
			}
			h.change_current_dir(m)
			return h.draw_screen()
		}
	}
	h.lp.Beep()
	return nil
}

func (h *Handler) finish_selection() error {
	if h.state.mode.CanSelectNonExistent() {
		h.initialize_save_file_name(h.state.suggested_save_file_name)
		return h.draw_screen()
	}
	h.lp.Quit(0)
	return nil
}

func (h *Handler) change_filter(delta int) bool {
	if len(h.state.filter_names) < 2 {
		return false
	}
	idx := slices.Index(h.state.filter_names, h.state.current_filter)
	idx += delta + len(h.state.filter_names)
	idx %= len(h.state.filter_names)
	h.set_filter(h.state.filter_names[idx])
	return true
}

func (h *Handler) OnKeyEvent(ev *loop.KeyEvent) (err error) {
	switch h.state.screen {
	case NORMAL:
		switch {
		case h.handle_edit_keys(ev), h.handle_result_list_keys(ev):
			h.draw_screen()
		case ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("ctrl+c"):
			h.lp.Quit(1)
		case ev.MatchesPressOrRepeat("tab"):
			return h.change_to_current_dir_if_possible()
		case ev.MatchesPressOrRepeat("ctrl+f"):
			if h.change_filter(1) {
				return h.draw_screen()
			}
			h.lp.Beep()
		case ev.MatchesPressOrRepeat("alt+f"):
			if h.change_filter(-1) {
				return h.draw_screen()
			}
			h.lp.Beep()
		case ev.MatchesPressOrRepeat("shift+tab"):
			curr := h.state.CurrentDir()
			switch curr {
			case "/":
			case ".":
				if curr, err = os.Getwd(); err == nil && curr != "/" {
					h.change_current_dir(filepath.Dir(curr))
					return h.draw_screen()
				}
			default:
				h.change_current_dir(filepath.Dir(curr))
				return h.draw_screen()
			}
			h.lp.Beep()
		case ev.MatchesPressOrRepeat("shift+enter"):
			if !h.toggle_selection() {
				h.lp.Beep()
			} else {
				if len(h.state.selections) > 0 && !h.state.mode.AllowsMultipleSelection() {
					return h.finish_selection()
				}
				return h.draw_screen()
			}
		case ev.MatchesPressOrRepeat("enter"):
			m := h.current_abspath()
			if h.state.mode.SelectFiles() {
				if m != "" {
					var s os.FileInfo
					if s, err = os.Stat(m); err != nil {
						h.lp.Beep()
						return nil
					}
					if s.IsDir() {
						return h.change_to_current_dir_if_possible()
					}
				}
			}
			if h.add_selection_if_possible() {
				if len(h.state.selections) > 0 {
					return h.finish_selection()
				}
				return h.draw_screen()
			} else {
				if h.state.mode.CanSelectNonExistent() {
					t := h.state.SearchText()
					h.initialize_save_file_name(utils.IfElse(t == "", h.state.suggested_save_file_name, t))
					return h.draw_screen()
				} else {
					h.lp.Beep()
				}
			}
		}
	case SAVE_FILE:
		err = h.save_file_name_handle_key(ev)
	}
	return
}

func (h *Handler) OnText(text string, from_key_event, in_bracketed_paste bool) (err error) {
	switch h.state.screen {
	case NORMAL:
		h.set_query(h.state.SearchText() + text)
		return h.draw_screen()
	case SAVE_FILE:
		if err = h.rl.OnText(text, from_key_event, in_bracketed_paste); err == nil {
			err = h.draw_screen()
		}
	}
	return
}

func (h *Handler) set_state_from_config(_ *Config, opts *Options) (err error) {
	h.state = State{}
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
	case "save-files":
		h.state.mode = SELECT_SAVE_FILES
	default:
		h.state.mode = SELECT_SINGLE_FILE
	}
	h.state.suggested_save_file_name = opts.SuggestedSaveFileName
	if opts.SuggestedSaveFilePath != "" {
		switch h.state.mode {
		case SELECT_SAVE_FILE, SELECT_SAVE_DIR:
			if s, err := os.Stat(opts.SuggestedSaveFilePath); err == nil {
				if (s.IsDir() && h.state.mode != SELECT_SAVE_FILE) || (!s.IsDir() && h.state.mode == SELECT_SAVE_FILE) {
					if h.state.AddSelection(opts.SuggestedSaveFileName) {
						return h.finish_selection()
					}
				}
			}
		}
	}
	h.state.filter_map = nil
	h.state.current_filter = ""
	if len(opts.FileFilter) > 0 {
		has_all_files := false
		fmap := make(map[string][]Filter)
		seen := utils.NewSet[string](len(opts.FileFilter))
		for _, x := range opts.FileFilter {
			f, ferr := NewFilter(x)
			if ferr != nil {
				return ferr
			}
			if f.Match == nil {
				has_all_files = true
			}
			if h.state.current_filter == "" {
				h.state.current_filter = f.Name
			}
			fmap[f.Name] = append(fmap[f.Name], *f)
			if !seen.Has(f.Name) {
				seen.Add(f.Name)
				h.state.filter_names = append(h.state.filter_names, f.Name)
			}
		}
		if !has_all_files {
			af, _ := NewFilter("glob:*:All files")
			fmap[af.Name] = append(fmap[af.Name], *af)
			if !seen.Has(af.Name) {
				h.state.filter_names = append(h.state.filter_names, af.Name)
			}
		}
		h.state.filter_map = make(map[string]Filter)
		for name, filters := range fmap {
			h.state.filter_map[name] = CombinedFilter(filters...)
		}
	}
	return
}

var default_cwd string

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	write_output := func(selections []string, interrupted bool) {
		payload := make(map[string]any)
		if err != nil {
			if opts.WriteOutputTo != "" {
				m := fmt.Sprint(err)
				if opts.OutputFormat == "json" {
					payload["error"] = m
					b, _ := json.MarshalIndent(payload, "", "  ")
					m = string(b)
				}
				os.WriteFile(opts.WriteOutputTo, []byte(m), 0600)
			}
			return
		}
		if interrupted {
			if opts.WriteOutputTo != "" {
				if opts.OutputFormat == "json" {
					payload["interrupted"] = true
					b, _ := json.MarshalIndent(payload, "", "  ")
					os.WriteFile(opts.WriteOutputTo, b, 0600)
				}
			}
			return
		}
		m := strings.Join(selections, "\n")
		fmt.Print(m)
		if opts.WriteOutputTo != "" {
			if opts.OutputFormat == "json" {
				payload["paths"] = selections
				b, _ := json.MarshalIndent(payload, "", "  ")
				m = string(b)
			}
			os.WriteFile(opts.WriteOutputTo, []byte(m), 0600)
		}
	}

	conf, err := load_config(opts)
	if err != nil {
		return 1, err
	}
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	handler := Handler{lp: lp, err_chan: make(chan error, 8), rl: readline.New(lp, readline.RlInit{
		Prompt: "> ", ContinuationPrompt: ". ",
	})}
	if err = handler.set_state_from_config(conf, opts); err != nil {
		return 1, err
	}
	handler.result_manager = NewResultManager(handler.err_chan, &handler.state, lp.WakeupMainThread)
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
	lp.OnInitialize = func() (string, error) {
		if opts.WritePidTo != "" {
			if err := utils.AtomicWriteFile(opts.WritePidTo, bytes.NewReader([]byte(strconv.Itoa(os.Getpid()))), 0600); err != nil {
				return "", err
			}
		}
		if opts.Title != "" {
			lp.SetWindowTitle(opts.Title)
		}
		return handler.OnInitialize()
	}
	lp.OnResize = func(old, new_size loop.ScreenSize) (err error) {
		handler.init_sizes(new_size)
		return handler.draw_screen()
	}
	lp.OnKeyEvent = handler.OnKeyEvent
	lp.OnText = handler.OnText
	lp.OnWakeup = func() (err error) {
		select {
		case err = <-handler.err_chan:
		default:
			err = handler.draw_screen()
		}
		return
	}
	err = lp.Run()
	if err != nil {
		write_output(nil, false)
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		write_output(nil, true)
		return 1, nil
	}
	rc = lp.ExitCode()
	switch rc {
	case 0:
		write_output(handler.state.selections, false)
	default:
		write_output(nil, true)
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
