// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
)

var _ = fmt.Print

func DetectSupport(timeout time.Duration) (memory, files, direct bool, err error) {
	temp_files_to_delete := make([]string, 0, 8)
	shm_files_to_delete := make([]shm.MMap, 0, 8)
	var direct_query_id, file_query_id, memory_query_id uint32
	lp, e := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking, loop.NoInBandResizeNotifications)
	if e != nil {
		err = e
		return
	}
	print_error := func(format string, args ...any) {
		lp.Println(fmt.Sprintf(format, args...))
	}

	defer func() {
		if len(temp_files_to_delete) > 0 && transfer_by_file != supported {
			for _, name := range temp_files_to_delete {
				os.Remove(name)
			}
		}
		if len(shm_files_to_delete) > 0 && transfer_by_memory != supported {
			for _, name := range shm_files_to_delete {
				_ = name.Unlink()
			}
		}
	}()

	lp.OnInitialize = func() (string, error) {
		var iid uint32
		_, _ = lp.AddTimer(timeout, false, func(loop.IdType) error {
			return fmt.Errorf("Timed out waiting for a response from the terminal: %w", os.ErrDeadlineExceeded)
		})

		g := func(t graphics.GRT_t, payload string) uint32 {
			iid += 1
			g1 := &graphics.GraphicsCommand{}
			g1.SetTransmission(t).SetAction(graphics.GRT_action_query).SetImageId(iid).SetDataWidth(1).SetDataHeight(1).SetFormat(
				graphics.GRT_format_rgb).SetDataSize(uint64(len(payload)))
			_ = g1.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(payload))
			return iid
		}

		direct_query_id = g(graphics.GRT_transmission_direct, "123")
		tf, err := images.CreateTempInRAM()
		if err == nil {
			file_query_id = g(graphics.GRT_transmission_tempfile, tf.Name())
			temp_files_to_delete = append(temp_files_to_delete, tf.Name())
			if _, err = tf.Write([]byte{1, 2, 3}); err != nil {
				print_error("Failed to write to temporary file for data transfer, file based transfer is disabled. Error: %v", err)
			}
			tf.Close()
		} else {
			print_error("Failed to create temporary file for data transfer, file based transfer is disabled. Error: %v", err)
		}
		sf, err := shm.CreateTemp("icat-", 3)
		if err == nil {
			memory_query_id = g(graphics.GRT_transmission_sharedmem, sf.Name())
			shm_files_to_delete = append(shm_files_to_delete, sf)
			copy(sf.Slice(), []byte{1, 2, 3})
			sf.Close()
		} else {
			var ens *shm.ErrNotSupported
			if !errors.As(err, &ens) {
				print_error("Failed to create SHM for data transfer, memory based transfer is disabled. Error: %v", err)
			}
		}
		lp.QueueWriteString("\x1b[c")

		return "", nil
	}

	lp.OnEscapeCode = func(etype loop.EscapeCodeType, payload []byte) (err error) {
		switch etype {
		case loop.CSI:
			if len(payload) > 3 && payload[0] == '?' && payload[len(payload)-1] == 'c' {
				lp.Quit(0)
				return nil
			}
		case loop.APC:
			g := graphics.GraphicsCommandFromAPC(payload)
			if g != nil {
				if g.ResponseMessage() == "OK" {
					switch g.ImageId() {
					case direct_query_id:
						direct = true
					case file_query_id:
						files = true
					case memory_query_id:
						memory = true
					}
				}
				return
			}
		}
		return
	}

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") {
			event.Handled = true
			print_error("Waiting for response from terminal, aborting now could lead to corruption")
		}
		if event.MatchesPressOrRepeat("ctrl+z") {
			event.Handled = true
		}
		return nil
	}

	err = lp.Run()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}

	return
}
