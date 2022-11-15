// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"os"
	"sync"
)

var _ = fmt.Print

type dl_data struct {
	mutex               sync.Mutex
	canceled_by_user    bool
	error_from_download error
	done, total         uint64
	download_started    bool
	download_finished   bool
	temp_file_path      string
}

func render_progress(done, total uint64, screen_width uint) string {
	return fmt.Sprintln(1111111, done, total)
}

func DownloadFileWithProgress(destpath, url string, kill_if_signaled bool) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	dl_data := dl_data{}

	register_temp_file_path := func(path string) {
		dl_data.mutex.Lock()
		dl_data.temp_file_path = path
		dl_data.mutex.Unlock()
	}

	report_progress := func(done, total uint64) error {
		dl_data.mutex.Lock()
		defer dl_data.mutex.Unlock()
		dl_data.done = done
		dl_data.total = total
		if dl_data.canceled_by_user {
			return Canceled
		}
		lp.WakeupMainThread()
		return nil
	}

	do_download := func() {
		dl_data.mutex.Lock()
		dl_data.download_started = true
		dl_data.mutex.Unlock()
		err := utils.DownloadToFile(destpath, url, report_progress, register_temp_file_path)
		dl_data.mutex.Lock()
		defer dl_data.mutex.Unlock()
		dl_data.download_finished = true
		if err != Canceled && err != nil {
			dl_data.error_from_download = err
			lp.WakeupMainThread()
		}
	}

	redraw := func() {
		lp.QueueWriteString("\r")
		lp.ClearToEndOfLine()
		dl_data.mutex.Lock()
		defer dl_data.mutex.Unlock()
		if dl_data.done+dl_data.total == 0 {
			lp.QueueWriteString("Waiting for download to start...")
		} else {
			sz, err := lp.ScreenSize()
			w := sz.WidthCells
			if err != nil {
				w = 80
			}
			lp.QueueWriteString(render_progress(dl_data.done, dl_data.total, w))
		}
	}

	lp.OnInitialize = func() (string, error) {
		go do_download()
		lp.QueueWriteString("Downloading: " + url + "\r\n")
		return "\r\n", nil
	}

	lp.OnResumeFromStop = func() error {
		redraw()
		return nil
	}
	lp.OnResize = func(old_size, new_size loop.ScreenSize) error {
		redraw()
		return nil
	}
	lp.OnWakeup = func() error {
		lp.DebugPrintln("11111111111111")
		dl_data.mutex.Lock()
		defer dl_data.mutex.Unlock()
		if dl_data.error_from_download != nil {
			return dl_data.error_from_download
		}
		redraw()
		return nil
	}
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			dl_data.mutex.Lock()
			defer dl_data.mutex.Unlock()
			dl_data.canceled_by_user = true
			lp.Quit(1)
		}
		return nil
	}

	err = lp.Run()
	dl_data.mutex.Lock()
	if dl_data.temp_file_path != "" && !dl_data.download_finished {
		os.Remove(dl_data.temp_file_path)
	}
	dl_data.mutex.Unlock()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		if kill_if_signaled {
			lp.KillIfSignalled()
			return
		}
		return &KilledBySignal{Msg: fmt.Sprint("Killed by signal: ", ds), SignalName: ds}
	}

	return
}
