// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

var _ = fmt.Print

// Exit codes, the same as used by xdg-open
const (
	exit_missing_file = 2
	exit_no_app       = 3
	exit_launch_error = 4
)

// open_error is an error with the exit code to use for it
type open_error struct {
	err       error
	exit_code int
}

func (e *open_error) Error() string { return e.err.Error() }
func (e *open_error) Unwrap() error { return e.err }

// launch_func runs a command in the background, in the specified working directory
type launch_func func(argv []string, cwd string) error

// ask_func asks the user to choose an application for the targets,
// returning nil if the user cancels
type ask_func func(targets []Target) (*Result, error)

// launch_detached runs the command in a new session, with its standard
// input and output connected to /dev/null, without waiting for it.
func launch_detached(argv []string, cwd string) error {
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Dir = cwd
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	// nil means /dev/null for os/exec
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

// terminal_command returns the command line used to run argv in a terminal
func (s *Settings) terminal_command(argv []string) ([]string, error) {
	if s.Terminal == "" || s.Terminal == "kitty" {
		return append([]string{utils.KittyExe(), "--"}, argv...), nil
	}
	prefix, err := shlex.Split(s.Terminal)
	if err != nil {
		return nil, fmt.Errorf("the terminal setting %#v is invalid: %w", s.Terminal, err)
	}
	if len(prefix) == 0 {
		return nil, fmt.Errorf("the terminal setting is empty")
	}
	return append(prefix, argv...), nil
}

// launch opens the targets with the chosen application
func launch(settings *Settings, db *AppDatabase, choice Choice, targets []Target, run launch_func) error {
	e, err := choice.Entry(db)
	if err != nil {
		return err
	}
	cmds, err := e.Commands(targets...)
	if err != nil {
		return err
	}
	cwd := e.WorkingDir
	if cwd == "" {
		if cwd, err = os.Getwd(); err != nil {
			cwd = utils.Expanduser("~")
		}
	}
	var errs []error
	for _, cmd := range cmds {
		if e.Terminal {
			if cmd, err = settings.terminal_command(cmd); err != nil {
				return err
			}
		}
		if err = run(cmd, cwd); err != nil {
			errs = append(errs, fmt.Errorf("failed to run %s with error: %w", join_cmdline(cmd), err))
		}
	}
	return errors.Join(errs...)
}

type target_group struct {
	choice  Choice
	targets []Target
}

// group_targets groups targets by key, preserving the order in which keys
// are first seen
func group_targets[K comparable](targets []Target, key func(Target) K) (keys []K, groups map[K][]Target) {
	groups = map[K][]Target{}
	for _, t := range targets {
		k := key(t)
		if _, found := groups[k]; !found {
			keys = append(keys, k)
		}
		groups[k] = append(groups[k], t)
	}
	return
}

// open_targets opens the targets with the applications configured or
// remembered for them, asking the user to choose for the rest, once per
// MIME type. If always_ask is true, the user is asked for all targets.
// Returns an open_error for failures.
func open_targets(r *Resolver, targets []Target, always_ask bool, ask ask_func, run launch_func) error {
	var missing []string
	for _, t := range targets {
		if t.Path != "" {
			if _, err := os.Stat(t.Path); err != nil {
				missing = append(missing, t.Path)
			}
		}
	}
	if len(missing) > 0 {
		return &open_error{fmt.Errorf("the following files do not exist: %s", missing), exit_missing_file}
	}
	var groups []target_group
	var unresolved []Target
	for _, t := range targets {
		if !always_ask {
			res, found, warnings := r.Resolve(t)
			for _, w := range warnings {
				fmt.Fprintln(os.Stderr, "Warning:", w)
			}
			if found {
				idx := -1
				for i, g := range groups {
					if g.choice.Equal(res.Choice) {
						idx = i
						break
					}
				}
				if idx < 0 {
					groups = append(groups, target_group{choice: res.Choice})
					idx = len(groups) - 1
				}
				groups[idx].targets = append(groups[idx].targets, t)
				continue
			}
		}
		unresolved = append(unresolved, t)
	}
	var errs []error
	exit_code := 0
	fail := func(err error, code int) {
		errs = append(errs, err)
		exit_code = max(exit_code, code)
	}
	for _, g := range groups {
		if err := launch(r.Settings, r.DB, g.choice, g.targets, run); err != nil {
			fail(err, exit_launch_error)
		}
	}
	mimes, by_mime := group_targets(unresolved, MimeTypeForTarget)
	for _, m := range mimes {
		result, err := ask(by_mime[m])
		if err != nil {
			fail(fmt.Errorf("failed to ask for an application to open %s with error: %w", m, err), exit_no_app)
			continue
		}
		if result == nil {
			fail(fmt.Errorf("no application chosen to open: %s", m), exit_no_app)
			continue
		}
		if err := launch(r.Settings, r.DB, result.Choice, by_mime[m], run); err != nil {
			fail(err, exit_launch_error)
		}
	}
	if len(errs) > 0 {
		return &open_error{errors.Join(errs...), exit_code}
	}
	return nil
}

// can_ask_in_terminal returns true if the chooser can be run in the
// terminal this process is connected to
func can_ask_in_terminal() bool {
	return tty.IsTerminal(os.Stdin.Fd()) && tty.IsTerminal(os.Stdout.Fd()) && os.Getenv("TERM") != "dumb"
}

// ask_in_panel runs the chooser in a kitty overlay panel and returns its result
func ask_in_panel(opts *Options, settings *Settings, targets []Target) (*Result, error) {
	tdir, err := os.MkdirTemp("", "kitty-choose-app-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tdir)
	output_path := filepath.Join(tdir, "output.json")
	exe, err := os.Executable()
	if err != nil {
		exe = utils.Which("kitten")
		if exe == "" {
			return nil, fmt.Errorf("could not find the kitten executable: %w", err)
		}
	}
	size_args, err := tui.CenteredPanelArgs(settings.Panel_size)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Warning: ignoring panel_size:", err)
	}
	args := []string{"+kitten", "panel", "--layer=overlay", "--focus-policy=exclusive", "--grab-keyboard"}
	args = append(args, size_args...)
	args = append(args,
		"-o", "background_opacity=0.85", exe, "choose-app", "--output-format=json", "--write-output-to", output_path,
		"--title", utils.IfElse(opts.Title != "", opts.Title, "Open with"),
	)
	for _, x := range opts.Config {
		args = append(args, "--config", x)
	}
	for _, x := range opts.Override {
		args = append(args, "--override", x)
	}
	args = append(args, "--")
	for _, t := range targets {
		args = append(args, t.as_path())
	}
	cmd := exec.Command(utils.KittyExe(), args...)
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	if err = cmd.Run(); err != nil {
		return nil, fmt.Errorf("running the chooser in a kitty panel failed with error: %w. Note that this requires the compositor to support panels, see https://sw.kovidgoyal.net/kitty/kittens/panel/#compatibility-with-various-platforms", err)
	}
	raw, err := os.ReadFile(output_path)
	if err != nil {
		return nil, fmt.Errorf("the chooser in the kitty panel did not produce any output: %w", err)
	}
	var output struct {
		Choice      *Choice `json:"choice"`
		Remember    bool    `json:"remember"`
		Interrupted bool    `json:"interrupted"`
		Error       string  `json:"error"`
	}
	if err = json.Unmarshal(raw, &output); err != nil {
		return nil, fmt.Errorf("the chooser in the kitty panel produced invalid output: %w", err)
	}
	switch {
	case output.Error != "":
		return nil, errors.New(output.Error)
	case output.Interrupted || output.Choice == nil:
		return nil, nil
	}
	return &Result{Choice: *output.Choice, Remember: output.Remember}, nil
}
