// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/kovidgoyal/kitty/tools/cli"
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
	return 1, fmt.Errorf("the interactive chooser is not implemented yet, use --list")
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
