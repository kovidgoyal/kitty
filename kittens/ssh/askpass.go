// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
)

var _ = fmt.Print

func fatal(err error) int {
	cli.ShowError(err)
	return 1
}

func trigger_ask(name string) int {
	term, err := tty.OpenControllingTerm()
	if err != nil {
		return fatal(err)
	}
	defer term.Close()
	_, err = term.WriteString("\x1bP@kitty-ask|" + name + "\x1b\\")
	if err != nil {
		return fatal(err)
	}
	return 0
}

func RunSSHAskpass() int {
	msg := os.Args[len(os.Args)-1]
	prompt := os.Getenv("SSH_ASKPASS_PROMPT")
	is_confirm := prompt == "confirm"
	q_type := "get_line"
	if is_confirm {
		q_type = "confirm"
	}
	is_fingerprint_check := strings.Contains(msg, "(yes/no/[fingerprint])")
	q := map[string]any{
		"message":     msg,
		"type":        q_type,
		"is_password": !is_fingerprint_check,
	}
	data, err := json.Marshal(q)
	if err != nil {
		return fatal(err)
	}
	data_shm, err := shm.CreateTemp("askpass-*", uint64(len(data)+32))
	if err != nil {
		return fatal(fmt.Errorf("Failed to create SHM file with error: %w", err))
	}
	defer data_shm.Close()
	defer func() { _ = data_shm.Unlink() }()

	data_shm.Slice()[0] = 0
	if err = shm.WriteWithSize(data_shm, data, 1); err != nil {
		return fatal(fmt.Errorf("Failed to write to SHM file with error: %w", err))
	}
	if err = data_shm.Flush(); err != nil {
		return fatal(fmt.Errorf("Failed to flush SHM file with error: %w", err))
	}
	trigger_ask(data_shm.Name())
	for {
		time.Sleep(50 * time.Millisecond)
		if data_shm.Slice()[0] == 1 {
			break
		}
	}
	data, err = shm.ReadWithSize(data_shm, 1)
	if err != nil {
		return fatal(fmt.Errorf("Failed to read from SHM file with error: %w", err))
	}
	response := ""
	if is_confirm {
		var ok bool
		err = json.Unmarshal(data, &ok)
		if err != nil {
			return fatal(fmt.Errorf("Failed to parse response data: %#v with error: %w", string(data), err))
		}
		response = "no"
		if ok {
			response = "yes"
		}
	} else {
		err = json.Unmarshal(data, &response)
		if err != nil {
			return fatal(fmt.Errorf("Failed to parse response data: %#v with error: %w", string(data), err))
		}
		if is_fingerprint_check {
			response = strings.ToLower(response)
			switch response {
			case "y":
				response = "yes"
			case "n":
				response = "no"
			}
		}
	}
	if response != "" {
		fmt.Println(response)
	}
	return 0
}
