package utils

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"
)

var _ = fmt.Print

type worker struct {
	cmd        *exec.Cmd
	stdin_pipe io.WriteCloser
}

var worker_started atomic.Bool

var get_worker = sync.OnceValues(func() (*worker, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
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
	if err = cmd.Run(); err != nil {
		return nil, err
	}
	worker_started.Store(true)
	return &ans, nil
})

func WaitForAtexitWorkerToFinish() {
	if worker_started.Load() {
		if w, err := get_worker(); err == nil {
			w.stdin_pipe.Close()
			_ = w.cmd.Wait()
		}
	}
}

func register(prefix, path string) error {
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
