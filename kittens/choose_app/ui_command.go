// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

const command_prompt = "command> "

// The maximum number of command lines shown in the preview
const max_preview_commands = 3

var field_codes = [][2]string{
	{"%f", "a single file, runs the command once per file"},
	{"%F", "all the files"},
	{"%u", "a single URL, runs the command once per URL"},
	{"%U", "all the URLs"},
}

// command_completer completes executables for the first word of the command
// line and files for the rest, as well as field codes and previously used commands
func command_completer(rl func() *readline.Readline) readline.CompleterFunction {
	return func(before_cursor, after_cursor string) *cli.Completions {
		argv, word_start := shlex.SplitForCompletion(before_cursor)
		ans := cli.NewCompletions()
		ans.CurrentWordIdx = word_start
		word := ""
		if len(argv) > 0 {
			word = argv[len(argv)-1]
		}
		if len(argv) <= 1 {
			word, _ = strings.CutPrefix(word, terminal_choice_prefix)
			if !strings.Contains(word, "/") {
				if exes := cli.CompleteExecutablesInPath(word); len(exes) > 0 {
					mg := ans.AddMatchGroup("Executables in PATH")
					for _, x := range utils.Uniq(exes) {
						mg.AddMatch(x)
					}
				}
			} else {
				mg := ans.AddMatchGroup("Executables")
				mg.IsFiles = true
				_ = cli.CompleteFiles(word, func(e *cli.FileEntry) {
					if e.IsDir || unix.Access(e.Abspath, unix.X_OK) == nil {
						mg.AddMatch(e.CompletionCandidate)
					}
				}, "")
			}
		} else if strings.HasPrefix(word, "%") {
			mg := ans.AddMatchGroup("Field codes")
			for _, fc := range field_codes {
				if strings.HasPrefix(fc[0], word) {
					mg.AddMatch(fc[0], fc[1])
				}
			}
		} else {
			mg := ans.AddMatchGroup("Files")
			mg.IsFiles = true
			_ = cli.CompleteFiles(word, func(e *cli.FileEntry) {
				mg.AddMatch(e.CompletionCandidate)
			}, "")
		}
		if r := rl(); r != nil && len(argv) <= 1 {
			for _, group := range r.HistoryCompleter(before_cursor, after_cursor).Groups {
				ans.MergeMatchGroup(group)
			}
		}
		return ans
	}
}

func CommandHistoryPath() string {
	return filepath.Join(utils.CacheDir(), "choose-app", "command-history.json")
}

func (h *Handler) init_command_rl() {
	// the history file is opened immediately, so its directory must exist
	if err := os.MkdirAll(filepath.Dir(CommandHistoryPath()), 0o700); err != nil {
		h.warnings = append(h.warnings, fmt.Sprintf("Could not create the directory for the command history: %s", err))
	}
	h.cmd_rl = readline.New(h.lp, readline.RlInit{
		Prompt: command_prompt, Completer: command_completer(func() *readline.Readline { return h.cmd_rl }),
		HistoryPath: CommandHistoryPath(), DontMarkPrompts: true,
	})
}

// enter_command_mode switches to typing a command line, starting with the specified text
func (h *Handler) enter_command_mode(text string, terminal bool) error {
	if sanitize(text) != text {
		// readline would write control codes to the terminal unsanitized
		text = ""
	}
	if sc := h.saved_command; sc.valid && sc.query == h.query && text == h.query {
		text, terminal = sc.text, sc.terminal
	}
	h.in_command_mode = true
	h.cmd_terminal = terminal
	h.cmd_rl.ResetText()
	h.cmd_rl.SetText(text)
	return h.draw_screen()
}

func (h *Handler) leave_command_mode() error {
	h.in_command_mode = false
	// keep the edited command in case the user comes back to it without
	// changing the search text
	h.saved_command = saved_command{text: h.cmd_rl.AllText(), terminal: h.cmd_terminal, query: h.query, valid: true}
	return h.draw_screen()
}

type saved_command struct {
	text, query     string
	terminal, valid bool
}

// typed_choice returns the choice for the typed command line, or an error if it is invalid
func (h *Handler) typed_choice() (Choice, error) {
	parts, err := shlex.Split(strings.TrimSpace(h.cmd_rl.AllText()))
	if err != nil {
		return Choice{}, err
	}
	c, err := parse_cmdline_choice(parts)
	if err != nil {
		return c, err
	}
	c.Terminal = c.Terminal || h.cmd_terminal
	return c, nil
}

func (h *Handler) accept_typed_command() error {
	c, err := h.typed_choice()
	if err != nil {
		h.lp.Beep()
		return h.draw_screen()
	}
	h.cmd_rl.AddHistoryItem(readline.HistoryItem{Cmd: strings.TrimSpace(h.cmd_rl.AllText()), Timestamp: time.Now()})
	return h.accept(c)
}

func (h *Handler) command_mode_key_event(ev *loop.KeyEvent) error {
	if ac := h.shortcut_tracker.Match(ev, h.settings.KeyboardShortcuts); ac != nil {
		switch ac.Name {
		case "accept", "use_command":
			ev.Handled = true
			return h.accept_typed_command()
		case "quit":
			ev.Handled = true
			return h.leave_command_mode()
		case "toggle":
			switch ac.Args {
			case "remember":
				h.toggle_remember()
			case "terminal":
				h.cmd_terminal = !h.cmd_terminal
			}
			ev.Handled = true
			return h.draw_screen()
		}
	}
	// All other keys, including the arrow keys, edit the command line
	if err := h.cmd_rl.OnKeyEvent(ev); err != nil {
		return err
	}
	return h.draw_screen()
}

// command_preview returns lines describing how the typed command will be run
func (h *Handler) command_preview() (lines []string) {
	if strings.TrimSpace(h.cmd_rl.AllText()) == "" {
		return []string{h.styled(dim_style, "Type the program to run and its arguments, press tab to complete")}
	}
	c, err := h.typed_choice()
	var cmds [][]string
	if err == nil {
		var e *DesktopEntry
		if e, err = c.Entry(h.db); err == nil {
			cmds, err = e.Commands(h.preview_targets()...)
		}
	}
	if err != nil {
		return []string{h.styled("fg=red", "Invalid command: "+sanitize(err.Error()))}
	}
	if !program_exists(c.Cmdline[0]) {
		lines = append(lines, h.styled("fg=yellow", "Warning: "+sanitize(c.Cmdline[0])+" was not found"))
	}
	where := utils.IfElse(c.Terminal, " in a terminal", "")
	switch len(cmds) {
	case 1:
		lines = append(lines, "Will run"+where+":")
	default:
		lines = append(lines, fmt.Sprintf("Will run %d times%s:", len(cmds), where))
	}
	for i, cmd := range cmds {
		if i >= max_preview_commands {
			lines = append(lines, h.styled(dim_style, fmt.Sprintf("  … and %d more", len(cmds)-i)))
			break
		}
		lines = append(lines, "  "+h.styled("fg=green", sanitize(join_cmdline(cmd))))
	}
	return
}

func (h *Handler) draw_command_screen() {
	lp := h.lp
	h.draw_header()
	lp.MoveCursorTo(1, header_height+2)
	lp.AllowLineWrapping(true)
	lp.Println(" Type the command to open with. " + h.styled(accent_style, "%f") + " is replaced by a single file, " +
		h.styled(accent_style, "%F") + " by all the files and " + h.styled(accent_style, "%u") + ", " + h.styled(accent_style, "%U") +
		" by URLs. Without them, the file is added at the end.")
	lp.Println()
	h.cmd_rl.RedrawNonAtomic()
	lp.AllowLineWrapping(false)

	lp.SaveCursorPosition()
	defer lp.RestoreCursorPosition()
	width := int(h.screen_size.WidthCells) - 2
	preview := h.command_preview()
	controls_y := int(h.screen_size.HeightCells) - 2
	y := controls_y - len(preview) - 1
	for _, line := range preview {
		lp.MoveCursorTo(2, y)
		lp.QueueWriteString(wcswidth.TruncateToVisualLength(line, width))
		y++
	}
	// The toggles
	x := 1
	add_toggle := func(id string, on bool, label, action string, toggle func()) {
		text := utils.IfElse(on, "󰄲 ", "󰄱 ") + label
		if sc := h.shortcut_for(action); sc != "" {
			text += " (" + sc + ")"
		}
		w := wcswidth.Stringwidth(text)
		lp.MoveCursorTo(x+1, controls_y)
		lp.QueueWriteString(utils.IfElse(on, h.styled(accent_style, text), text))
		h.mouse_state.AddCellRegion(id, x, controls_y-1, x+w-1, controls_y-1, func(string) error {
			toggle()
			return h.draw_screen()
		})
		x += w + 3
	}
	add_toggle("toggle-terminal", h.cmd_terminal, "run in terminal", "toggle terminal", func() { h.cmd_terminal = !h.cmd_terminal })
	add_toggle("toggle-remember-cmd", h.remember, "remember", "toggle remember", h.toggle_remember)
	hints := []string{}
	if sc := h.shortcut_for("accept"); sc != "" {
		hints = append(hints, h.styled(accent_style, sc)+" open")
	}
	hints = append(hints, h.styled(accent_style, "tab")+" complete", h.styled(accent_style, "up/down")+" history")
	if sc := h.shortcut_for("quit"); sc != "" {
		hints = append(hints, h.styled(accent_style, sc)+" back to applications")
	}
	lp.MoveCursorTo(2, controls_y+1)
	lp.QueueWriteString(wcswidth.TruncateToVisualLength(strings.Join(hints, "  "), width))
}

// program_exists returns true if the program is an executable file, looking
// it up in PATH if it is not a path
func program_exists(program string) bool {
	program = utils.Expanduser(program)
	if strings.Contains(program, "/") {
		s, err := os.Stat(program)
		return err == nil && !s.IsDir() && unix.Access(program, unix.X_OK) == nil
	}
	return utils.Which(program) != ""
}

// preview_targets returns the targets to show in the preview of the command.
// When choosing without any files, such as for the AppChooser portal, the
// display name is used instead.
func (h *Handler) preview_targets() []Target {
	if len(h.targets) > 0 {
		return h.targets
	}
	name := h.input.DisplayName
	if name == "" {
		name = "FILE"
	}
	if strings.Contains(name, "://") {
		return []Target{{URL: name}}
	}
	return []Target{{Path: name}}
}
