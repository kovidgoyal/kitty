// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type listed_target struct {
	Target     string          `json:"target"`
	MimeType   string          `json:"mime_type"`
	Default    string          `json:"default,omitempty"`
	Resolution *Resolution     `json:"resolution,omitempty"`
	Warnings   []string        `json:"warnings,omitempty"`
	Apps       []*DesktopEntry `json:"apps"`
}

func list_apps(r *Resolver, targets []Target) (err error) {
	output := make([]listed_target, len(targets))
	for i, t := range targets {
		mt := MimeTypeForTarget(t)
		output[i] = listed_target{Target: t.String(), MimeType: mt, Apps: r.DB.AppsFor(mt)}
		if d := r.DB.DefaultAppFor(mt); d != nil {
			output[i].Default = d.ID
		}
		res, found, warnings := r.Resolve(t)
		if found {
			output[i].Resolution = &res
		}
		output[i].Warnings = warnings
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(output)
}

func forget(store *ChoiceStore, targets []Target) error {
	mimes := make([]string, len(targets))
	for i, t := range targets {
		mimes[i] = MimeTypeForTarget(t)
	}
	forgotten, err := store.Forget(mimes...)
	if err != nil {
		return err
	}
	if len(forgotten) == 0 {
		fmt.Println("No applications were remembered for:", utils.Uniq(mimes))
	} else {
		fmt.Println("Forgot the remembered applications for:", forgotten)
	}
	return nil
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	if opts.ClearCache {
		if err = os.RemoveAll(filepath.Dir(ChoicesPath())); err != nil {
			return 1, fmt.Errorf("failed to clear the cache with error: %w", err)
		}
		if len(args) == 0 {
			return 0, nil
		}
	}
	settings, err := LoadSettings(opts.Config, opts.Override)
	if err != nil {
		return 1, err
	}
	targets := make([]Target, len(args))
	for i, x := range args {
		if targets[i], err = NewTarget(x); err != nil {
			return 1, err
		}
	}
	store, serr := LoadChoiceStore(ChoicesPath())
	if serr != nil {
		fmt.Fprintln(os.Stderr, "Warning:", serr)
	}
	if opts.Forget {
		if len(targets) == 0 {
			return 1, fmt.Errorf("must specify at least one file or URL to forget the remembered application for")
		}
		if err = forget(store, targets); err != nil {
			return 1, err
		}
		return 0, nil
	}
	db := LoadAppDatabase()
	for _, e := range db.Errors {
		fmt.Fprintln(os.Stderr, "Warning:", e)
	}
	resolver := &Resolver{Settings: settings, Store: store, DB: db}
	if opts.List {
		if len(targets) == 0 {
			return 1, fmt.Errorf("must specify at least one file or URL to list applications for")
		}
		if err = list_apps(resolver, targets); err != nil {
			return 1, err
		}
		return 0, nil
	}
	if opts.Open {
		if len(targets) == 0 {
			return 1, fmt.Errorf("must specify at least one file or URL to open")
		}
		err = open_targets(resolver, targets, opts.Ask, func(t []Target) (*Result, error) { return ask(opts, resolver, t) }, default_launchers)
		var oe *open_error
		if errors.As(err, &oe) {
			return oe.exit_code, oe.err
		}
		return utils.IfElse(err == nil, 0, 1), err
	}
	input := NewChooserInput(targets)
	if opts.ContentType != "" {
		input.MimeTypes = utils.Uniq(append([]string{opts.ContentType}, input.MimeTypes...))
	}
	input.DisplayName, input.Preselect = opts.DisplayName, opts.Preselect
	for _, id := range opts.Recommend {
		input.Recommend = append(input.Recommend, ChoiceForDesktopID(id))
	}
	if opts.WritePidTo != "" {
		if err = utils.AtomicWriteFile(opts.WritePidTo, strings.NewReader(strconv.Itoa(os.Getpid())), 0o600); err != nil {
			return 1, fmt.Errorf("failed to write the process id to %s with error: %w", opts.WritePidTo, err)
		}
	}
	result, err := run_chooser(opts, resolver, input)
	if err != nil {
		write_output(opts, nil, err)
		return 1, err
	}
	if result == nil {
		write_output(opts, nil, nil)
		return 1, nil
	}
	output := *result
	if opts.CommandsAsDesktopFiles && output.Choice.DesktopID == "" {
		id, err := WriteCommandDesktopFile(db.dirs, output.Choice)
		if err != nil {
			write_output(opts, nil, err)
			return 1, err
		}
		output.Choice = Choice{DesktopID: id}
	}
	write_output(opts, &output, nil)
	// the original command is recorded, so that it is used as is when opening files
	record_choice(resolver.Store, input.MimeTypes, result)
	return 0, nil
}

// record_choice records the choice even if not remembered, to rank it higher in future
func record_choice(store *ChoiceStore, mimes []string, result *Result) {
	for _, m := range mimes {
		if err := store.RecordChoice(m, result.Choice, result.Remember); err != nil {
			fmt.Fprintln(os.Stderr, "Warning: could not save the chosen application:", err)
		}
	}
}

// ask asks the user to choose an application to open the targets with, in
// this terminal or a kitty panel
func ask(opts *Options, resolver *Resolver, targets []Target) (*Result, error) {
	in_terminal := false
	switch opts.AskIn {
	case "terminal":
		if !can_ask_in_terminal() {
			return nil, fmt.Errorf("cannot ask in the terminal as STDIN or STDOUT is not a terminal")
		}
		in_terminal = true
	case "auto":
		in_terminal = can_ask_in_terminal()
	}
	if !in_terminal {
		// the chooser running in the panel records the choice itself
		return ask_in_panel(opts, resolver.Settings, targets)
	}
	input := NewChooserInput(targets)
	result, err := run_chooser(opts, resolver, input)
	if err == nil && result != nil {
		record_choice(resolver.Store, input.MimeTypes, result)
	}
	return result, err
}

// write_output writes the result, which is nil if the user cancelled
func write_output(opts *Options, result *Result, err error) {
	var text string
	if opts.OutputFormat == "json" {
		payload := map[string]any{}
		switch {
		case err != nil:
			payload["error"] = err.Error()
		case result == nil:
			payload["interrupted"] = true
		default:
			payload["choice"] = result.Choice
			payload["remember"] = result.Remember
			if result.ActivationToken != "" {
				payload["activation_token"] = result.ActivationToken
			}
		}
		b, merr := json.MarshalIndent(payload, "", "  ")
		if merr != nil {
			fmt.Fprintln(os.Stderr, "Failed to serialize output:", merr)
			return
		}
		text = string(b) + "\n"
	} else if err == nil && result != nil {
		text = result.Choice.String() + "\n"
	}
	if text != "" && err == nil {
		os.Stdout.WriteString(text)
	}
	if opts.WriteOutputTo != "" {
		if werr := utils.AtomicWriteFile(opts.WriteOutputTo, strings.NewReader(text), 0o600); werr != nil {
			fmt.Fprintln(os.Stderr, "Failed to write output to", opts.WriteOutputTo, "with error:", werr)
		}
	}
}

func run_chooser(opts *Options, resolver *Resolver, input *ChooserInput) (result *Result, err error) {
	lp, err := loop.New()
	if err != nil {
		return nil, err
	}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)
	lp.ColorSchemeChangeNotifications()
	h := NewHandler(lp, resolver.Settings, resolver.DB, resolver.Store, input)
	defer func() {
		h.icon_display.Cleanup()
		h.cmd_rl.Shutdown() // saves the command history
		for _, w := range h.warnings {
			fmt.Fprintln(os.Stderr, "Warning:", w)
		}
	}()
	lp.OnInitialize = func() (string, error) {
		lp.SetWindowTitle(utils.IfElse(opts.Title != "", opts.Title, "Choose an application"))
		return h.OnInitialize()
	}
	lp.OnFinalize = h.OnFinalize
	lp.OnResize = h.OnResize
	lp.OnKeyEvent = h.OnKeyEvent
	lp.OnText = h.OnText
	lp.OnMouseEvent = h.OnMouseEvent
	lp.OnEscapeCode = h.on_escape_code
	lp.OnWakeup = h.OnWakeup
	lp.OnColorSchemeChange = h.on_color_scheme_change
	if err = lp.Run(); err != nil {
		return nil, err
	}
	if ds := lp.DeathSignalName(); ds != "" {
		lp.KillIfSignalled()
		return nil, nil
	}
	if lp.ExitCode() != 0 {
		return nil, nil
	}
	return h.result, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
