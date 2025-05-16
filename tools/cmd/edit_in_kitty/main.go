// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package edit_in_kitty

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
)

var _ = fmt.Print

func encode(x string) string {
	return base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(x))
}

type OnDataCallback = func(data_type string, data []byte) error

func edit_loop(data_to_send string, kill_if_signaled bool, on_data OnDataCallback) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	current_text := strings.Builder{}
	data := strings.Builder{}
	data.Grow(4096)
	started := false
	canceled := false
	update_type := ""

	handle_line := func(line string) error {
		if canceled {
			return nil
		}
		if started {
			if update_type == "" {
				update_type = line
			} else {
				if line == "KITTY_DATA_END" {
					lp.QueueWriteString(update_type + "\r\n")
					if update_type == "DONE" {
						lp.Quit(0)
						return nil
					}
					b, err := base64.StdEncoding.DecodeString(data.String())
					data.Reset()
					data.Grow(4096)
					started = false
					if err == nil {
						err = on_data(update_type, b)
					}
					update_type = ""
					if err != nil {
						return err
					}
				} else {
					data.WriteString(line)
				}
			}
		} else {
			if line == "KITTY_DATA_START" {
				started = true
				update_type = ""
			}
		}
		return nil
	}

	check_for_line := func() error {
		if canceled {
			return nil
		}
		s := current_text.String()
		for {
			idx := strings.Index(s, "\n")
			if idx < 0 {
				break
			}
			err = handle_line(s[:idx])
			if err != nil {
				return err
			}
			s = s[idx+1:]
		}
		current_text.Reset()
		current_text.Grow(4096)
		if s != "" {
			current_text.WriteString(s)
		}
		return nil
	}

	lp.OnInitialize = func() (string, error) {
		pos, chunk_num := 0, 0
		for {
			limit := min(pos+2048, len(data_to_send))
			if limit <= pos {
				break
			}
			lp.QueueWriteString("\x1bP@kitty-edit|" + strconv.Itoa(chunk_num) + ":")
			lp.QueueWriteString(data_to_send[pos:limit])
			lp.QueueWriteString("\x1b\\")
			chunk_num++
			pos = limit
		}
		lp.QueueWriteString("\x1bP@kitty-edit|\x1b\\")
		return "", nil
	}

	lp.OnText = func(text string, from_key_event bool, in_bracketed_paste bool) error {
		if !from_key_event {
			current_text.WriteString(text)
			err = check_for_line()
			if err != nil {
				return err
			}
		}
		return nil
	}

	const abort_msg = "\x1bP@kitty-edit|0:abort_signaled=interrupt\x1b\\\x1bP@kitty-edit|\x1b\\"

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			canceled = true
			lp.QueueWriteString(abort_msg)
			if !started {
				return tui.Canceled
			}
		}
		return nil
	}

	err = lp.Run()
	if err != nil {
		return
	}
	if canceled {
		return tui.Canceled
	}

	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Print(abort_msg)
		if kill_if_signaled {
			lp.KillIfSignalled()
			return
		}
		return &tui.KilledBySignal{Msg: fmt.Sprint("Killed by signal: ", ds), SignalName: ds}
	}
	return
}

func edit_in_kitty(path string, opts *Options) (err error) {
	read_file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("Failed to open %s for reading with error: %w", path, err)
	}
	defer read_file.Close()
	var s unix.Stat_t
	err = unix.Fstat(int(read_file.Fd()), &s)
	if err != nil {
		return fmt.Errorf("Failed to stat %s with error: %w", path, err)
	}
	if s.Size > int64(opts.MaxFileSize)*1024*1024 {
		return fmt.Errorf("File size %s is too large for performant editing", humanize.Bytes(uint64(s.Size)))
	}

	file_data, err := io.ReadAll(read_file)
	if err != nil {
		return fmt.Errorf("Failed to read from %s with error: %w", path, err)
	}
	read_file.Close()
	data := strings.Builder{}
	data.Grow(len(file_data) * 4)

	add := func(key, val string) {
		if data.Len() > 0 {
			data.WriteString(",")
		}
		data.WriteString(key)
		data.WriteString("=")
		data.WriteString(val)
	}
	add_encoded := func(key, val string) { add(key, encode(val)) }

	if unix.Access(path, unix.R_OK|unix.W_OK) != nil {
		return fmt.Errorf("%s is not readable and writeable", path)
	}
	cwd, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("Failed to get the current working directory with error: %w", err)
	}
	add_encoded("cwd", cwd)
	for _, arg := range os.Args[2:] {
		add_encoded("a", arg)
	}
	add("file_inode", fmt.Sprintf("%d:%d:%d", s.Dev, s.Ino, s.Mtim.Nano()))
	add_encoded("file_data", utils.UnsafeBytesToString(file_data))
	fmt.Println("Waiting for editing to be completed, press Esc to abort...")
	write_data := func(data_type string, rdata []byte) (err error) {
		err = utils.AtomicWriteFile(path, bytes.NewReader(rdata), fs.FileMode(s.Mode).Perm())
		if err != nil {
			err = fmt.Errorf("Failed to write data to %s with error: %w", path, err)
		}
		return
	}
	err = edit_loop(data.String(), true, write_data)
	if err != nil {
		if err == tui.Canceled {
			return err
		}
		return fmt.Errorf("Failed to receive edited file back from terminal with error: %w", err)
	}
	return
}

type Options struct {
	MaxFileSize int
}

func EntryPoint(parent *cli.Command) *cli.Command {
	sc := parent.AddSubCommand(&cli.Command{
		Name:             "edit-in-kitty",
		Usage:            "[options] file-to-edit",
		ShortDescription: "Edit a file in a kitty overlay window",
		HelpText: "Edit the specified file in a kitty overlay window. Works over SSH as well.\n\n" +
			"For usage instructions see: https://sw.kovidgoyal.net/kitty/shell-integration/#edit-file",
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			if len(args) == 0 {
				fmt.Fprintln(os.Stderr, "Usage:", cmd.Usage)
				return 1, fmt.Errorf("No file to edit specified.")
			}
			if len(args) != 1 {
				fmt.Fprintln(os.Stderr, "Usage:", cmd.Usage)
				return 1, fmt.Errorf("Only one file to edit must be specified")
			}
			var opts Options
			err = cmd.GetOptionValues(&opts)
			if err != nil {
				return 1, err
			}
			err = edit_in_kitty(args[0], &opts)
			return 0, err
		},
	})
	AddCloneSafeOpts(sc)
	sc.Add(cli.OptionSpec{
		Name:    "--max-file-size",
		Default: "8",
		Type:    "int",
		Help:    "The maximum allowed size (in MB) of files to edit. Since the file data has to be base64 encoded and transmitted over the tty device, overly large files will not perform well.",
	})
	return sc
}
