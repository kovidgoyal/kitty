// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"
	"os"
	"os/exec"

	"golang.org/x/sys/unix"

	"kitty/kittens/ask"
	"kitty/tools/cli"
	"kitty/tools/cli/markup"
	"kitty/tools/utils"
)

var _ = fmt.Print

func ask_for_permission(script_path string) (response string, err error) {
	opts := &ask.Options{Type: "choices", Default: "n", Choices: []string{"y;green:Yes", "n;red:No", "v;yellow:View", "e;magenta:Edit"}}

	ctx := markup.New(true)
	opts.Message = ctx.Prettify(fmt.Sprintf(
		"Attempting to execute the script: :yellow:`%s`\nExecuting untrusted scripts can be dangerous. Proceed anyway?", script_path))
	response, err = ask.GetChoices(opts)
	return response, err
}

func confirm_and_run_shebang(args []string) (rc int, err error) {
	script_path := args[len(args)-1]
	if unix.Access(script_path, unix.X_OK) != nil {
		response, err := ask_for_permission(script_path)
		if err != nil {
			return 1, err
		}
		switch response {
		default:
			return 1, fmt.Errorf("Execution of %s was denied by user", script_path)
		case "v":
			raw, err := os.ReadFile(script_path)
			if err != nil {
				return 1, err
			}
			cli.ShowHelpInPager(utils.UnsafeBytesToString(raw))
			return confirm_and_run_shebang(args)
		case "e":
			exe, err := os.Executable()
			if err != nil {
				return 1, err
			}
			editor := exec.Command(exe, "edit-in-kitty", script_path)
			editor.Stdin = os.Stdin
			editor.Stdout = os.Stdout
			editor.Stderr = os.Stderr
			editor.Run()
			return confirm_and_run_shebang(args)
		case "y":
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
