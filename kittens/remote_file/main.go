// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package remote_file

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/kittens/choose_files"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// reset_terminal performs a full terminal reset (RIS), exactly mirroring
// kittens/tui/operations.py:reset_terminal()'s escape sequence
// ('\033]\033\\\033c'). Python's remote_file calls this between UI phases
// (after the ask menu, around hostname-mismatch prompts, around the
// overwrite-prompt, and around the $EDITOR invocation) to clear whatever was
// drawn by the previous phase/loop before drawing the next; we mirror those
// call sites exactly so the two implementations look the same on screen.
func reset_terminal() {
	fmt.Print("\x1b]\x1b\\\x1bc")
}

// get_key_press shows `draw` and waits for one of the runes in allowed.
// Returns deflt on Esc/Ctrl+C. Mirrors kittens/tui/utils.py:get_key_press.
func get_key_press(draw func(lp *loop.Loop, ctx *markup.Context), allowed, deflt string) (ans string, err error) {
	lp, err := loop.NewForSimpleInteraction()
	if err != nil {
		return "", err
	}
	ctx := markup.New(true)
	ans = deflt
	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		draw(lp, ctx)
		return "", nil
	}
	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error {
		text = strings.ToLower(text)
		if allowed != "" && strings.Contains(allowed, text) {
			ans = text
			lp.Quit(0)
		}
		return nil
	}
	lp.OnKeyEvent = func(e *loop.KeyEvent) error {
		if e.MatchesPressOrRepeat("esc") || e.MatchesPressOrRepeat("ctrl+c") {
			e.Handled = true
			lp.Quit(1)
		}
		return nil
	}
	err = lp.Run()
	lp.KillIfSignalled()
	return ans, err
}

// wait_for_any_key blocks until the user presses any single key. Unlike
// get_key_press it does not filter by an allowed set, matching Python's
// show_error which breaks on the first byte read regardless of its value.
func wait_for_any_key() error {
	lp, err := loop.NewForSimpleInteraction()
	if err != nil {
		return err
	}
	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		return "", nil
	}
	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error {
		lp.Quit(0)
		return nil
	}
	lp.OnKeyEvent = func(e *loop.KeyEvent) error {
		e.Handled = true
		lp.Quit(0)
		return nil
	}
	err = lp.Run()
	lp.KillIfSignalled()
	return err
}

func show_error(msg string) {
	ctx := markup.New(true)
	fmt.Fprintln(os.Stderr, ctx.Err(msg))
	fmt.Println()
	fmt.Println("Press any key to quit")
	_ = wait_for_any_key()
}

func ask_action(opts *Options) (string, error) {
	draw := func(lp *loop.Loop, ctx *markup.Context) {
		hostname := opts.Hostname
		if hostname == "" {
			hostname = "unknown"
		}
		lp.Println("What would you like to do with the remote file on " + ctx.Magenta(hostname) + ":")
		lp.Println(ctx.Yellow(opts.Path))
		lp.Println()
		lp.Println(ctx.Green("E") + "dit the file")
		lp.Println(lp.SprintStyled("dim", "The file will be downloaded and opened in an editor. Any changes you save will be automatically sent back to the remote machine"))
		lp.Println()
		lp.Println(ctx.Green("O") + "pen the file")
		lp.Println(lp.SprintStyled("dim", "The file will be downloaded and opened by the default open program"))
		lp.Println()
		lp.Println(ctx.Green("S") + "ave the file")
		lp.Println(lp.SprintStyled("dim", "The file will be downloaded to a destination you select"))
		lp.Println()
		lp.Println(ctx.Green("C") + "ancel")
	}
	response, err := get_key_press(draw, "ceos", "c")
	if err != nil {
		return "cancel", err
	}
	return map[string]string{"e": "edit", "o": "open", "s": "save"}[response], nil
}

// check_hostname_matches prompts the user when the remote hostname does not
// match the hyperlink hostname; mirrors main.py ControlMaster.check_hostname_matches.
func check_hostname_matches(master *ControlMaster, cli_hostname string) (bool, error) {
	if master.conn.IsSSHKitten {
		return true, nil
	}
	q := master.remote_hostname()
	if q == "" || hostname_matches(cli_hostname, q) {
		return true, nil
	}
	reset_terminal()
	draw := func(lp *loop.Loop, ctx *markup.Context) {
		lp.Println("The remote hostname " + ctx.Green(q) + " does not match the")
		lp.Println("hostname in the hyperlink " + ctx.Err(cli_hostname))
		lp.Println("This indicates that kitty has not connected to the correct remote machine.")
		lp.Println("This can happen, for example, when using nested SSH sessions.")
		lp.Printf("The hostname kitty used to connect was: %s", ctx.Yellow(master.conn.Hostname))
		if master.conn.Port > 0 {
			lp.Printf(" with port: %d", master.conn.Port)
		}
		lp.Println()
		lp.Println()
		lp.Println("Do you want to continue anyway?")
		lp.Println(ctx.Green("Y") + "es\t" + ctx.Err("N") + "o")
	}
	response, err := get_key_press(draw, "yn", "n")
	reset_terminal()
	return response == "y", err
}

// get_save_path reads a single line of input for the destination path,
// with filename tab-completion, mirroring kittens/tui/path_completer.py's
// PathCompleter/get_path. aborted is true on Ctrl+C/EOF, matching Python's
// catch of KeyboardInterrupt/EOFError in save_as.
func get_save_path(prompt string) (result string, aborted bool, err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return "", false, err
	}
	rl := readline.New(lp, readline.RlInit{Prompt: prompt, Completer: choose_files.FilePromptCompleter(nil)})
	lp.OnInitialize = func() (string, error) { rl.Start(); return "", nil }
	lp.OnFinalize = func() string { rl.End(); return "" }
	lp.OnResumeFromStop = func() error { rl.Start(); return nil }
	lp.OnResize = rl.OnResize
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") {
			aborted = true
			lp.Quit(0)
			return nil
		}
		kerr := rl.OnKeyEvent(event)
		if kerr != nil {
			if kerr == io.EOF {
				aborted = true
				lp.Quit(0)
				return nil
			}
			if kerr == readline.ErrAcceptInput {
				result = rl.AllText()
				lp.Quit(0)
				return nil
			}
			return kerr
		}
		if event.Handled {
			rl.Redraw()
		}
		return nil
	}
	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error {
		terr := rl.OnText(text, from_key_event, in_bracketed_paste)
		if terr == nil {
			rl.Redraw()
		}
		return terr
	}
	err = lp.Run()
	rl.Shutdown()
	if err != nil {
		return "", false, err
	}
	if ds := lp.DeathSignalName(); ds != "" {
		return "", false, fmt.Errorf("killed by signal: %s", ds)
	}
	return result, aborted, nil
}

func master_show_error(m *ControlMaster, msg string) {
	if m.LastErrorLog != "" {
		fmt.Fprintln(os.Stderr, m.LastErrorLog)
		m.LastErrorLog = ""
	}
	show_error(msg)
}

// save_as mirrors main.py:save_as. hostname is the CLI --hostname value used
// by check_hostname_matches.
func save_as(conn *SSHConnectionData, remote_path, hostname string) error {
	ddir := utils.CacheDir()
	if err := os.MkdirAll(ddir, 0o755); err != nil {
		return err
	}
	last_used_store := filepath.Join(ddir, "remote-file-last-used.txt")
	last_used_path := os.TempDir()
	if b, err := os.ReadFile(last_used_store); err == nil {
		last_used_path = string(b)
	}
	last_used_file := filepath.Join(last_used_path, filepath.Base(remote_path))
	ctx := markup.New(true)
	fmt.Println("Where do you want to save the file? Leaving it blank will save it as:", ctx.Yellow(last_used_file))
	cwd, _ := os.Getwd()
	fmt.Println("Relative paths will be resolved from:", ctx.Bold(cwd))
	fmt.Println()

	dest, aborted, err := get_save_path("> ")
	if err != nil {
		return err
	}
	if aborted {
		return nil
	}
	if dest != "" {
		dest = utils.Expanduser(os.ExpandEnv(dest))
		if st, err := os.Stat(dest); err == nil && st.IsDir() {
			dest = filepath.Join(dest, filepath.Base(remote_path))
		}
		if abs, err := filepath.Abs(dest); err == nil {
			_ = os.WriteFile(last_used_store, []byte(filepath.Dir(abs)), 0o644)
			dest = abs
		}
	} else {
		dest = last_used_file
	}
	if _, err := os.Stat(dest); err == nil {
		reset_terminal()
		draw := func(lp *loop.Loop, mctx *markup.Context) {
			lp.Println("The file " + mctx.Yellow(dest) + " already exists. What would you like to do?")
			lp.Println(mctx.Green("O") + "verwrite  " + mctx.Green("A") + "bort  Auto " + mctx.Green("R") + "ename " + mctx.Green("N") + "ew name")
		}
		response, err := get_key_press(draw, "anor", "a")
		if err != nil {
			return err
		}
		switch response {
		case "a":
			return nil
		case "n":
			reset_terminal()
			return save_as(conn, remote_path, hostname)
		case "r":
			dest = auto_rename_dest(dest, func(p string) bool { _, err := os.Stat(p); return err == nil })
		}
	}
	if d := filepath.Dir(dest); d != "" {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	master := new_control_master(conn, remote_path, dest)
	if err := master.Start(); err != nil {
		return err
	}
	defer master.Close()
	ok, err := check_hostname_matches(master, hostname)
	if err != nil {
		return err
	}
	if !ok {
		return nil
	}
	if err := master.Download(); err != nil {
		master_show_error(master, "Failed to copy file from remote machine")
	}
	return nil
}

// handle_action returns the path to open locally (for the "open" action) or "".
func handle_action(action string, opts *Options) (result string, err error) {
	conn, err := parse_conn_data(opts.SshConnectionData)
	if err != nil {
		return "", err
	}
	remote_path := opts.Path
	switch action {
	case "open":
		fmt.Println("Opening", opts.Path, "from", opts.Hostname)
		tdir, err := os.MkdirTemp("", "kitty-remote-file")
		if err != nil {
			return "", err
		}
		dest := filepath.Join(tdir, filepath.Base(remote_path))
		master := new_control_master(conn, remote_path, dest)
		if err := master.Start(); err != nil {
			return "", err
		}
		defer master.Close()
		ok, err := check_hostname_matches(master, opts.Hostname)
		if err != nil {
			return "", err
		}
		if !ok {
			return "", nil
		}
		if err := master.Download(); err != nil {
			master_show_error(master, "Failed to copy file from remote machine")
			return "", nil
		}
		return dest, nil
	case "edit":
		fmt.Println("Editing", opts.Path, "from", opts.Hostname)
		master := new_control_master(conn, remote_path, "")
		if err := master.Start(); err != nil {
			return "", err
		}
		defer master.Close()
		ok, err := check_hostname_matches(master, opts.Hostname)
		if err != nil {
			return "", err
		}
		if !ok {
			return "", nil
		}
		if err := master.Download(); err != nil {
			master_show_error(master, "Failed to download "+remote_path)
			return "", nil
		}
		if err := edit_loop(master, get_editor()); err != nil {
			master_show_error(master, err.Error())
		}
	case "save":
		fmt.Println("Saving", opts.Path, "from", opts.Hostname)
		if err := save_as(conn, remote_path, opts.Hostname); err != nil {
			return "", err
		}
	}
	return "", nil
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	action := opts.Mode
	if action == "ask" {
		action, err = ask_action(opts)
		reset_terminal()
		if err != nil {
			return 1, err
		}
	}
	if action == "" || action == "cancel" {
		return 0, nil
	}
	result, err := handle_action(action, opts)
	if err != nil {
		reset_terminal()
		show_error(err.Error())
		return 1, nil
	}
	if result != "" {
		serialized, err := tui.KittenOutputSerializer()(result)
		if err != nil {
			return 1, err
		}
		os.Stdout.WriteString(serialized)
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
