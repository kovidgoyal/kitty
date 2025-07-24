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
	"sync"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/ignorefiles"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/text/message"
)

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
	num_matches, num_of_slots, num_before, num_per_column, num_columns, num_shown, preview_width int
	first_idx                                                                                    CollectionIndex
}

type State struct {
	base_dir                            string
	current_dir                         string
	multiselect                         bool
	search_text                         string
	mode                                Mode
	suggested_save_file_name            string
	suggested_save_file_path            string
	window_title                        string
	screen                              Screen
	current_filter                      string
	filter_map                          map[string]Filter
	filter_names                        []string
	show_hidden                         bool
	show_preview                        bool
	respect_ignores                     bool
	sort_by_last_modified               bool
	global_ignores                      ignorefiles.IgnoreFile
	keyboard_shortcuts                  []*config.KeyAction
	display_title                       bool
	pygments_style, dark_pygments_style string
	syntax_aliases                      map[string]string

	selections    []string
	current_idx   CollectionIndex
	last_render   render_state
	mouse_state   tui.MouseState
	redraw_needed bool
}

func (s State) HighlightStyles() (string, string)     { return s.pygments_style, s.dark_pygments_style }
func (s State) SyntaxAliases() map[string]string      { return s.syntax_aliases }
func (s State) DisplayTitle() bool                    { return s.display_title }
func (s State) ShowHidden() bool                      { return s.show_hidden }
func (s State) ShowPreview() bool                     { return s.show_preview }
func (s State) RespectIgnores() bool                  { return s.respect_ignores }
func (s State) SortByLastModified() bool              { return s.sort_by_last_modified }
func (s State) GlobalIgnores() ignorefiles.IgnoreFile { return s.global_ignores }
func (s State) BaseDir() string                       { return utils.IfElse(s.base_dir == "", default_cwd, s.base_dir) }
func (s State) Filter() Filter                        { return s.filter_map[s.current_filter] }
func (s State) Multiselect() bool                     { return s.multiselect }
func (s State) String() string                        { return utils.Repr(s) }
func (s State) SearchText() string                    { return s.search_text }
func (s State) OnlyDirs() bool                        { return s.mode.OnlyDirs() }
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

func (s *State) ToggleSelection(abspath string) (added bool) {
	before := len(s.selections)
	s.selections = slices.DeleteFunc(s.selections, func(x string) bool { return x == abspath })
	if len(s.selections) == before {
		s.selections = append(s.selections, abspath)
		added = true
	}
	return
}

func (s *State) IsSelected(x *ResultItem) bool {
	if len(s.selections) == 0 {
		return false
	}
	q := filepath.Join(s.CurrentDir(), x.text)
	return slices.Contains(s.selections, q)
}

type ScreenSize struct {
	width, height, cell_width, cell_height, width_px, height_px int
}

type Handler struct {
	state            State
	screen_size      ScreenSize
	result_manager   *ResultManager
	lp               *loop.Loop
	rl               *readline.Readline
	err_chan         chan error
	shortcut_tracker config.ShortcutTracker
	msg_printer      *message.Printer
	spinner          *tui.Spinner
	preview_manager  *PreviewManager
}

func (h *Handler) draw_screen() (err error) {
	h.state.redraw_needed = false
	h.lp.StartAtomicUpdate()
	defer func() {
		h.state.mouse_state.UpdateHoveredIds()
		h.state.mouse_state.ApplyHoverStyles(h.lp)
		h.lp.EndAtomicUpdate()
	}()
	h.lp.ClearScreen()
	h.state.mouse_state.ClearCellRegions()
	switch h.state.screen {
	case NORMAL:
		matches, is_complete := h.get_results()
		h.lp.SetWindowTitle(h.state.WindowTitle())
		defer func() { // so that the cursor ends up in the right place
			h.lp.MoveCursorTo(1, 1)
			if h.state.DisplayTitle() {
				h.lp.Println(h.state.WindowTitle())
				h.draw_search_bar(1)
			} else {
				h.draw_search_bar(0)
			}
		}()
		y := SEARCH_BAR_HEIGHT + utils.IfElse(h.state.DisplayTitle(), 1, 0)
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
	ans.KeyboardShortcuts = config.ResolveShortcuts(ans.KeyboardShortcuts)
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
	if h.state.suggested_save_file_path != "" {
		switch h.state.mode {
		case SELECT_SAVE_FILE, SELECT_SAVE_DIR:
			if s, err := os.Stat(h.state.suggested_save_file_path); err == nil {
				if (s.IsDir() && h.state.mode != SELECT_SAVE_FILE) || (!s.IsDir() && h.state.mode == SELECT_SAVE_FILE) {
					h.state.SetCurrentDir(filepath.Dir(h.state.suggested_save_file_path))
					h.state.SetSearchText(filepath.Base(h.state.suggested_save_file_name))
				}
			}
		}
	}
	h.result_manager.set_root_dir()
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

func (s *State) CanSelect(r *ResultItem) bool {
	return utils.IfElse(s.OnlyDirs(), r.ftype.IsDir(), !r.ftype.IsDir())
}

func (h *Handler) toggle_selection_at(idx CollectionIndex) bool {
	matches, _ := h.get_results()
	if r := matches.At(idx); r != nil && h.state.CanSelect(r) {
		m := filepath.Join(h.state.CurrentDir(), r.text)
		if added := h.state.ToggleSelection(m); added {
			h.result_manager.last_click_anchor = &idx
		} else {
			h.result_manager.last_click_anchor = nil
			if len(h.state.selections) > 0 {
				x := utils.NewSetWithItems(h.state.selections...)
				cdir := h.state.CurrentDir()
				h.result_manager.last_click_anchor = matches.Closest(idx, func(q *ResultItem) bool { return x.Has(filepath.Join(cdir, q.text)) })
			}
		}
		return true
	}
	return false
}

func (h *Handler) toggle_selection() bool {
	return h.toggle_selection_at(h.state.CurrentIndex())
}

func (h *Handler) change_current_dir(dir string) {
	if dir != h.state.CurrentDir() {
		h.state.SetCurrentDir(dir)
		h.result_manager.set_root_dir()
		h.state.last_render = render_state{}
	}
}

func (h *Handler) set_query(q string) {
	if q != h.state.SearchText() {
		h.state.SetSearchText(q)
		h.result_manager.set_query()
		h.state.last_render = render_state{}
	}
}

func (h *Handler) set_filter(filter_name string) {
	if filter_name != h.state.current_filter {
		h.state.current_filter = filter_name
		h.result_manager.set_filter()
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
	if h.state.mode.CanSelectNonExistent() && len(h.state.selections) == 0 {
		return h.switch_to_save_file_name_mode()
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

func (h *Handler) switch_to_save_file_name_mode() error {
	name := h.state.suggested_save_file_name
	if h.state.SearchText() != "" {
		name = h.state.SearchText()
	}
	h.initialize_save_file_name(name)
	return h.draw_screen()
}

func (h *Handler) accept_idx(idx CollectionIndex) (accepted bool, err error) {
	matches, _ := h.get_results()
	if r := matches.At(idx); r != nil {
		m := filepath.Join(h.state.CurrentDir(), r.text)

		if h.state.mode.SelectFiles() {
			var s os.FileInfo
			if s, err = os.Stat(m); err != nil {
				return false, nil
			}
			if s.IsDir() {
				if h.state.mode.CanSelectNonExistent() {
					return true, h.switch_to_save_file_name_mode()
				}
				return false, nil
			}
		}

		h.state.AddSelection(m)
		h.result_manager.last_click_anchor = &idx
		if len(h.state.selections) > 0 {
			return true, h.finish_selection()
		}
		return true, h.draw_screen()
	}
	return
}

func (h *Handler) dispatch_action(name, args string) (err error) {
	switch name {
	case "quit":
		h.lp.Quit(1)
	case "next":
		if n, nerr := strconv.Atoi(args); nerr == nil {
			h.next_result(n)
		} else {
			switch args {
			case "":
				h.next_result(1)
			case "left":
				h.move_sideways(true)
			case "right":
				h.move_sideways(false)
			case "first":
				h.state.SetCurrentIndex(CollectionIndex{})
				h.state.last_render.num_before = 0
			case "last":
				matches, _ := h.get_results()
				h.state.SetCurrentIndex(matches.IncrementIndexWithWrapAround(CollectionIndex{}, -1))
				h.state.last_render.num_before = 0
			case "first_on_screen":
				h.state.SetCurrentIndex(h.state.last_render.first_idx)
				h.state.last_render.num_before = 0
			case "last_on_screen":
				matches, _ := h.get_results()
				h.state.SetCurrentIndex(matches.IncrementIndexWithWrapAround(h.state.last_render.first_idx, h.state.last_render.num_shown-1))
				h.state.last_render.num_before = h.state.last_render.num_shown - 1
			}
		}
		return h.draw_screen()
	case "next_filter":
		if n, nerr := strconv.Atoi(args); nerr == nil {
			h.change_filter(n)
			return h.draw_screen()
		}
		h.lp.Beep()
	case "select":
		if !h.toggle_selection() {
			h.lp.Beep()
		} else {
			return h.draw_screen()
		}
	case "accept":
		accepted, aerr := h.accept_idx(h.state.CurrentIndex())
		if aerr != nil {
			return aerr
		}
		if !accepted {
			h.lp.Beep()
		}
	case "typename":
		if !h.state.mode.CanSelectNonExistent() {
			if h.state.mode.OnlyDirs() {
				h.state.AddSelection(h.state.CurrentDir())
				return h.finish_selection()
			}
			h.lp.Beep()
		} else {
			return h.switch_to_save_file_name_mode()
		}
	case "toggle":
		switch args {
		case "preview":
			h.state.show_preview = !h.state.show_preview
			return h.draw_screen()
		case "dotfiles":
			h.state.show_hidden = !h.state.show_hidden
			h.result_manager.set_show_hidden()
			return h.draw_screen()
		case "ignorefiles":
			h.state.respect_ignores = !h.state.respect_ignores
			h.result_manager.set_respect_ignores()
			return h.draw_screen()
		case "sort_by_dates":
			h.state.sort_by_last_modified = !h.state.sort_by_last_modified
			h.result_manager.set_sort_by_last_modified()
			return h.draw_screen()
		default:
			h.lp.Beep()
		}
	case "cd":
		switch args {
		case ".":
			return h.change_to_current_dir_if_possible()
		case "..":
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
		default:
			args = utils.Expanduser(args)
			if st, serr := os.Stat(args); serr != nil || !st.IsDir() {
				h.lp.Beep()
				return
			}
			if absp, err := filepath.Abs(args); err == nil {
				h.change_current_dir(absp)
				return h.draw_screen()
			} else {
				h.lp.Beep()
				return nil
			}
		}
	}
	return
}

func (h *Handler) OnKeyEvent(ev *loop.KeyEvent) (err error) {
	switch h.state.screen {
	case NORMAL:
		if h.handle_edit_keys(ev) {
			ev.Handled = true
			h.draw_screen()
		}
		ac := h.shortcut_tracker.Match(ev, h.state.keyboard_shortcuts)
		if ac != nil {
			ev.Handled = true
			return h.dispatch_action(ac.Name, ac.Args)
		}
	case SAVE_FILE:
		err = h.save_file_name_handle_key(ev)
	}
	return
}

func (h *Handler) OnMouseEvent(event *loop.MouseEvent) (err error) {
	h.state.redraw_needed = h.state.mouse_state.UpdateState(event)
	if err = h.state.mouse_state.DispatchEventToHoveredRegions(event); err != nil {
		return
	}
	if h.state.redraw_needed {
		err = h.draw_screen()
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

type CachedValues struct {
	Show_hidden           bool `json:"show_hidden"`
	Hide_preview          bool `json:"hide_preview"`
	Respect_ignores       bool `json:"respect_ignores"`
	Sort_by_last_modified bool `json:"sort_by_last_modified"`
}

const cache_filename = "choose-files.json"

var cached_values = sync.OnceValue(func() *CachedValues {
	ans := CachedValues{Respect_ignores: true}
	fname := filepath.Join(utils.CacheDir(), cache_filename)
	if data, err := os.ReadFile(fname); err == nil {
		_ = json.Unmarshal(data, &ans)
	}
	return &ans
})

func (s State) save_cached_values() {
	c := CachedValues{Show_hidden: s.show_hidden, Respect_ignores: s.respect_ignores, Sort_by_last_modified: s.sort_by_last_modified, Hide_preview: !s.show_preview}
	fname := filepath.Join(utils.CacheDir(), cache_filename)
	if data, err := json.Marshal(c); err == nil {
		_ = os.WriteFile(fname, data, 0600)
	}
}

func (h *Handler) set_state_from_config(conf *Config, opts *Options) (err error) {
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
	h.state.suggested_save_file_path = opts.SuggestedSaveFilePath
	h.state.filter_map = nil
	h.state.current_filter = ""
	if len(opts.FileFilter) > 0 {
		opts.FileFilter = utils.Uniq(opts.FileFilter)
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
	h.state.sort_by_last_modified = false
	h.state.respect_ignores = true
	h.state.show_hidden = false
	h.state.show_preview = true

	switch conf.Show_hidden {
	case Show_hidden_true, Show_hidden_y, Show_hidden_yes:
		h.state.show_hidden = true
	case Show_hidden_false, Show_hidden_n, Show_hidden_no:
		h.state.show_hidden = false
	case Show_hidden_last:
		h.state.show_hidden = cached_values().Show_hidden
	}
	switch conf.Respect_ignores {
	case Respect_ignores_true, Respect_ignores_y, Respect_ignores_yes:
		h.state.respect_ignores = true
	case Respect_ignores_false, Respect_ignores_n, Respect_ignores_no:
		h.state.respect_ignores = false
	case Respect_ignores_last:
		h.state.respect_ignores = cached_values().Respect_ignores
	}
	switch conf.Sort_by_last_modified {
	case Sort_by_last_modified_true, Sort_by_last_modified_y, Sort_by_last_modified_yes:
		h.state.sort_by_last_modified = true
	case Sort_by_last_modified_false, Sort_by_last_modified_n, Sort_by_last_modified_no:
		h.state.sort_by_last_modified = false
	case Sort_by_last_modified_last:
		h.state.sort_by_last_modified = cached_values().Sort_by_last_modified
	}
	switch conf.Show_preview {
	case Show_preview_true, Show_preview_y, Show_preview_yes:
		h.state.show_preview = true
	case Show_preview_false, Show_preview_n, Show_preview_no:
		h.state.show_preview = false
	case Show_preview_last:
		h.state.show_preview = !cached_values().Hide_preview
	}

	h.state.global_ignores = ignorefiles.NewGitignore()
	if err = h.state.global_ignores.LoadLines(conf.Ignore...); err != nil {
		return err
	}
	h.state.keyboard_shortcuts = conf.KeyboardShortcuts
	h.state.display_title = opts.DisplayTitle
	h.state.pygments_style = conf.Pygments_style
	h.state.dark_pygments_style = conf.Dark_pygments_style
	h.state.syntax_aliases = conf.Syntax_aliases
	return
}

var default_cwd string
var use_light_colors bool

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	write_output := func(selections []string, interrupted bool, current_filter string) {
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
				if current_filter != "" {
					payload["current_filter"] = current_filter
				}
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
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)
	lp.ColorSchemeChangeNotifications()
	handler := Handler{lp: lp, err_chan: make(chan error, 8), msg_printer: message.NewPrinter(utils.LanguageTag()), spinner: tui.NewSpinner("dots")}
	handler.rl = readline.New(lp, readline.RlInit{
		Prompt: "> ", ContinuationPrompt: ". ", Completer: handler.complete_save_prompt,
	})
	if err = handler.set_state_from_config(conf, opts); err != nil {
		return 1, err
	}
	handler.result_manager = NewResultManager(handler.err_chan, &handler.state, lp.WakeupMainThread)
	handler.preview_manager = NewPreviewManager(handler.err_chan, &handler.state, lp.WakeupMainThread)
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
		lp.RequestCurrentColorScheme()
		return handler.OnInitialize()
	}
	lp.OnResize = func(old, new_size loop.ScreenSize) (err error) {
		handler.init_sizes(new_size)
		return handler.draw_screen()
	}
	lp.OnColorSchemeChange = func(p loop.ColorPreference) (err error) {
		new_val := p == loop.LIGHT_COLOR_PREFERENCE
		if new_val != use_light_colors {
			use_light_colors = new_val
			handler.preview_manager.invalidate_color_scheme_based_cached_items()
			return handler.draw_screen()
		}
		return
	}
	lp.OnKeyEvent = handler.OnKeyEvent
	lp.OnText = handler.OnText
	lp.OnMouseEvent = handler.OnMouseEvent
	lp.OnWakeup = func() (err error) {
		select {
		case err = <-handler.err_chan:
		default:
			err = handler.draw_screen()
		}
		return
	}
	err = lp.Run()
	handler.state.save_cached_values()
	if err != nil {
		write_output(nil, false, "")
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		write_output(nil, true, "")
		return 1, nil
	}
	rc = lp.ExitCode()
	switch rc {
	case 0:
		write_output(handler.state.selections, false, handler.state.current_filter)
	default:
		write_output(nil, true, "")
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
