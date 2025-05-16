// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
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

type render_data struct {
	done, total  uint64
	screen_width int
	spinner      *Spinner
	started_at   time.Time
}

func render_without_total(rd *render_data) string {
	return fmt.Sprint(rd.spinner.Tick(), humanize.Bytes(rd.done), " downloaded so far. Started %s", humanize.Time(rd.started_at))
}

func format_time(d time.Duration) string {
	d = d.Round(time.Second)
	ans := ""
	if d.Hours() > 1 {
		h := d / time.Hour
		d -= h * time.Hour
		ans += fmt.Sprintf("%02d:", h)
	}
	m := d / time.Minute
	d -= m * time.Minute
	s := d / time.Second
	return fmt.Sprintf("%s%02d:%02d", ans, m, s)
}

func render_progress(rd *render_data) string {
	if rd.total == 0 {
		return render_without_total(rd)
	}
	now := time.Now()
	duration := now.Sub(rd.started_at)
	rate := float64(rd.done) / float64(duration)
	frac := float64(rd.done) / float64(rd.total)
	bytes_left := rd.total - rd.done
	time_left := time.Duration(float64(bytes_left) / rate)
	speed := rate * float64(time.Second)
	before := rd.spinner.Tick()
	after := fmt.Sprintf(" %d%% %s/s %s", int(frac*100), strings.ReplaceAll(humanize.Bytes(uint64(speed)), " ", ""), format_time(time_left))
	available_width := rd.screen_width - len("T  100% 1000 MB/s 11:11:11")
	// fmt.Println("\r\n", frac, available_width)
	progress_bar := ""
	if available_width > 10 {
		progress_bar = " " + RenderProgressBar(frac, available_width)
	}
	return before + progress_bar + after
}

func DownloadFileWithProgress(destpath, url string, kill_if_signaled bool) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	dl_data := dl_data{}
	rd := render_data{spinner: NewSpinner("dots"), started_at: time.Now()}

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
		lp.StartAtomicUpdate()
		lp.AllowLineWrapping(false)
		defer func() {
			lp.AllowLineWrapping(true)
			lp.EndAtomicUpdate()
		}()
		lp.QueueWriteString("\r")
		lp.ClearToEndOfLine()
		dl_data.mutex.Lock()
		rd.done, rd.total = dl_data.done, dl_data.total
		dl_data.mutex.Unlock()
		if rd.done+rd.total == 0 {
			lp.QueueWriteString("Waiting for download to start...")
		} else {
			sz, err := lp.ScreenSize()
			w := sz.WidthCells
			if err != nil {
				w = 80
			}
			rd.screen_width = int(w)
			lp.QueueWriteString(render_progress(&rd))
		}
	}

	on_timer_tick := func(timer_id loop.IdType) error {
		return lp.OnWakeup()
	}

	lp.OnInitialize = func() (string, error) {
		if _, err = lp.AddTimer(rd.spinner.interval, true, on_timer_tick); err != nil {
			return "", err
		}
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
