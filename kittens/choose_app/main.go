// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
)

var _ = fmt.Print

type listed_target struct {
	Target   string          `json:"target"`
	MimeType string          `json:"mime_type"`
	Default  string          `json:"default,omitempty"`
	Apps     []*DesktopEntry `json:"apps"`
}

func list_apps(db *AppDatabase, targets []Target) (err error) {
	output := make([]listed_target, len(targets))
	for i, t := range targets {
		mt := MimeTypeForTarget(t)
		output[i] = listed_target{Target: t.String(), MimeType: mt, Apps: db.AppsFor(mt)}
		if d := db.DefaultAppFor(mt); d != nil {
			output[i].Default = d.ID
		}
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(output)
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	targets := make([]Target, len(args))
	for i, x := range args {
		if targets[i], err = NewTarget(x); err != nil {
			return 1, err
		}
	}
	db := LoadAppDatabase()
	for _, e := range db.Errors {
		fmt.Fprintln(os.Stderr, "Warning:", e)
	}
	if opts.List {
		if len(targets) == 0 {
			return 1, fmt.Errorf("must specify at least one file or URL to list applications for")
		}
		if err = list_apps(db, targets); err != nil {
			return 1, err
		}
		return 0, nil
	}
	return 1, fmt.Errorf("the interactive chooser is not implemented yet, use --list")
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
