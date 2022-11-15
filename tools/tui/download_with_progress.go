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
	return fmt.Sprint(1111111, done, total)
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
		dl_data.done = done
		dl_data.total = total
		canceled := dl_data.canceled_by_user
		dl_data.mutex.Unlock()
		if canceled {
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
		dl_data.download_finished = true
		if err != Canceled && err != nil {
			dl_data.error_from_download = err
		}
		dl_data.mutex.Unlock()
		lp.WakeupMainThread()
	}

	redraw := func() {
		lp.QueueWriteString("\r")
		lp.ClearToEndOfLine()
		dl_data.mutex.Lock()
		done, total := dl_data.done, dl_data.total
		dl_data.mutex.Unlock()
		if done+total == 0 {
			lp.QueueWriteString("Waiting for download to start...")
		} else {
			sz, err := lp.ScreenSize()
			w := sz.WidthCells
			if err != nil {
				w = 80
			}
			lp.QueueWriteString(render_progress(done, total, w))
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
		dl_data.mutex.Lock()
		err := dl_data.error_from_download
		finished := dl_data.download_finished
		dl_data.mutex.Unlock()
		if err != nil {
			return dl_data.error_from_download
		}
		if finished {
			lp.Quit(0)
			return nil
		}
		redraw()
		return nil
	}
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			dl_data.mutex.Lock()
			dl_data.canceled_by_user = true
			dl_data.mutex.Unlock()
			return Canceled
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
