// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
)

var _ = fmt.Print

type ReportFunc = func(done, total uint64) error

type write_counter struct {
	done, total uint64
	report      ReportFunc
}

func (self *write_counter) Write(p []byte) (int, error) {
	n := len(p)
	self.done += uint64(n)
	if self.report != nil {
		err := self.report(self.done, self.total)
		if err != nil {
			return 0, err
		}
	}
	return n, nil
}

func DownloadFile(destpath, url string, progress_callback ReportFunc) error {
	resp, err := http.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	destpath, err = filepath.EvalSymlinks(destpath)
	if err != nil {
		return err
	}
	dest, err := os.CreateTemp(filepath.Dir(destpath), filepath.Base(destpath)+".partial-download.")
	if err != nil {
		return err
	}
	dest_removed := false
	defer func() {
		dest.Close()
		if !dest_removed {
			os.Remove(dest.Name())
		}
	}()
	wc := write_counter{report: progress_callback}
	cl, err := strconv.Atoi(resp.Header.Get("Content-Length"))
	if err == nil {
		wc.total = uint64(cl)
	}
	_, err = io.Copy(dest, io.TeeReader(resp.Body, &wc))
	if err != nil {
		return err
	}
	dest.Close()
	err = os.Rename(dest.Name(), destpath)
	if err != nil {
		return err
	}
	dest_removed = true
	return nil
}
