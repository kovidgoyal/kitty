// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"
	"os"

	"golang.org/x/sys/unix"

	"kitty/kittens/ask"
	"kitty/tools/cli/markup"
	"kitty/tools/utils"
)

var _ = fmt.Print

func ask_for_permission(script_path string) (allowed bool, err error) {
	opts := &ask.Options{Type: "yesno", Default: "n"}

	ctx := markup.New(true)
	opts.Message = ctx.Prettify(fmt.Sprintf(
		"Attempting to execute the script: :yellow:`%s`\nExecuting untrusted scripts can be dangerous. Proceed anyway?", script_path))
	response, err := ask.GetChoices(opts)
	return response == "y", err
}

func confirm_and_run_shebang(args []string) (rc int, err error) {
	script_path := args[len(args)-1]
	if unix.Access(script_path, unix.X_OK) != nil {
		allowed, err := ask_for_permission(script_path)
		if err != nil {
			return 1, err
		}
		if !allowed {
			return 1, fmt.Errorf("Execution of %s was denied by user", script_path)
		}
	}
	exe := utils.FindExe(args[0])
	if exe == "" {
		return 1, fmt.Errorf("Failed to find the script interpreter: %s", args[0])
	}
	err = unix.Exec(exe, args, os.Environ())
	if err != nil {
		rc = 1
	}
	return
}
