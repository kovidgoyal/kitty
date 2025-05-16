// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/kittens/ask"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type ConfirmPolicy uint8

const (
	ConfirmAlways = iota
	ConfirmNever
	ConfirmIfNeeded
)

func ask_for_permission(script_path string) (response string, err error) {
	opts := &ask.Options{Type: "choices", Default: "n", Choices: []string{"y;green:Yes", "n;red:No", "v;yellow:View", "e;magenta:Edit"}}

	ctx := markup.New(true)
	opts.Message = ctx.Prettify(fmt.Sprintf(
		"Attempting to execute the script: :yellow:`%s`\nExecuting untrusted scripts can be dangerous. Proceed anyway?", script_path))
	response, err = ask.GetChoices(opts)
	return response, err
}

func ask_if_exe_allowed(exe_path string) (ok bool, err error) {
	opts := &ask.Options{Type: "yesno", Default: "n"}
	ctx := markup.New(true)
	opts.Message = ctx.Prettify(fmt.Sprintf(
		"Attempting to execute the program: :yellow:`%s`\nExecuting untrusted programs can be dangerous. Proceed anyway?", exe_path))
	response, err := ask.GetChoices(opts)
	return response == "y", err
}

func permission_denied(script_path string) error {
	return fmt.Errorf("Execution of %s was denied by user", script_path)
}

func confirm_and_run_exe(args []string) (rc int, err error) {
	exe := args[len(args)-1]
	ok, err := ask_if_exe_allowed(exe)
	if err != nil {
		return 1, err
	}
	if ok {
		exe = utils.FindExe(args[0])
		if exe == "" {
			return 1, fmt.Errorf("Failed to find the script interpreter: %s", args[0])
		}
		if err = unix.Exec(exe, []string{exe}, os.Environ()); err != nil {
			rc = 1
		}
	} else {
		return 1, permission_denied(exe)
	}
	return
}

func confirm_and_run_shebang(args []string, confirm_policy ConfirmPolicy) (rc int, err error) {
	script_path := args[len(args)-1]
	do_confirm := true
	switch confirm_policy {
	case ConfirmNever:
		do_confirm = false
	case ConfirmAlways:
		do_confirm = true
	case ConfirmIfNeeded:
		do_confirm = unix.Access(script_path, unix.X_OK) != nil
	}
	if do_confirm {
		response, err := ask_for_permission(script_path)
		if err != nil {
			return 1, err
		}
		switch response {
		default:
			return 1, permission_denied(script_path)
		case "v":
			raw, err := os.ReadFile(script_path)
			if err != nil {
				return 1, err
			}
			cli.ShowHelpInPager(utils.UnsafeBytesToString(raw))
			// The pager might have exited automatically if there is less than
			// one screen of text, so confirm manually, here, where output from
			// pager will still be visible.
			fmt.Print("Execute the script? (y/n): ")
			q, err := tty.ReadSingleByteFromTerminal()
			if err != nil {
				return 1, err
			}
			if q != 'y' && q != 'Y' {
				fmt.Println()
				return 1, permission_denied(script_path)
			}
			fmt.Print("\x1b[H\x1b[2J") // clear screen
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
			return confirm_and_run_shebang(args, ConfirmIfNeeded)
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

func run_shebang(args []string) (rc int, err error) {
	if len(args) < 3 {
		return 1, fmt.Errorf("Usage: kitten __shebang__ confirm-exe path_to_script cmd...")
	}
	var confirm_policy ConfirmPolicy
	switch args[0] {
	case "confirm-always":
		confirm_policy = ConfirmAlways
	case "confirm-never":
		confirm_policy = ConfirmNever
	case "confirm-if-needed":
		confirm_policy = ConfirmIfNeeded
	default:
		return 1, fmt.Errorf("Unknown confirmation policy: %s", args[1])
	}
	script_path := args[1]
	cmd := args[2:]
	if len(cmd) == 1 && cmd[0] == "__ext__" {
		ext := filepath.Ext(script_path)
		if ext == "" || ext == "." {
			return 1, fmt.Errorf("%s has no file extension so cannot be used in __ext__ mode", script_path)
		}
		cmd = []string{ext[1:]}
	}
	f, err := os.Open(script_path)
	if err != nil {
		return 1, err
	}
	scanner := bufio.NewScanner(f)
	first_line := ""
	if scanner.Scan() {
		first_line = scanner.Text()
	} else if err = scanner.Err(); err != nil {
		f.Close()
		return 1, fmt.Errorf("Failed to read from %s with error: %w", script_path, err)
	}
	f.Close()
	if strings.HasPrefix(first_line, "#!") {
		first_line = strings.TrimSpace(first_line[2:])
		switch runtime.GOOS {
		case "darwin":
			cmd = strings.Split(first_line, " ")
		default:
			cmd = strings.SplitN(first_line, " ", 2)
		}
	}
	cmd = append(cmd, script_path)
	return confirm_and_run_shebang(cmd, confirm_policy)
}
