package utils

import (
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
)

var _ = fmt.Print

type worker struct {
	cmd        *exec.Cmd
	stdin_pipe io.WriteCloser
}

var worker_started atomic.Bool

// IsTesting returns true if the code is being run by "go test".
func IsTesting() bool {
	return flag.Lookup("test.v") != nil
}

var get_worker = sync.OnceValues(func() (*worker, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	if IsTesting() {
		if exe, err = filepath.Abs("../../kitty/launcher/kitten"); err != nil {
			return nil, err
		}
	}
	cmd := exec.Command(exe, "__atexit__")
	cmd.Stdout = nil
	cmd.Stderr = os.Stderr
	ans := worker{cmd: cmd}
	si, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	ans.stdin_pipe = si
	if err = cmd.Start(); err != nil {
		return nil, err
	}
	worker_started.Store(true)
	return &ans, nil
})

func WaitForAtexitWorkerToFinish() error {
	if worker_started.Load() {
		if w, err := get_worker(); err == nil {
			w.stdin_pipe.Close()
			return w.cmd.Wait()
		} else {
			return err
		}
	}
	return nil
}

func register(prefix, path string) error {
	// no atexit cleanup is done as we dont have a good place to run
	// WaitForAtexitWorkerToFinish() and anyway we may want to run tests in
	// parallel, etc.
	if IsTesting() {
		return nil
	}
	path, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	if w, err := get_worker(); err == nil {
		_, err = fmt.Fprintln(w.stdin_pipe, prefix+" "+path)
		return err
	} else {
		return err
	}

}

func AtExitUnlink(path string) error {
	return register("unlink", path)
}

func AtExitShmUnlink(path string) error {
	return register("shm_unlink", path)
}

func AtExitRmtree(path string) error {
	return register("rmtree", path)
}
