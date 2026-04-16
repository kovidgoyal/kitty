package watch

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/sgtdi/fswatcher"
	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// watch_dir starts fswatcher in a background goroutine and pipes events to a custom channel.
func watch_dir(ctx context.Context, path string, debounce time.Duration, eventChan chan<- fswatcher.WatchEvent) error {
	w, err := fswatcher.New(
		fswatcher.WithPath(path),
		fswatcher.WithCooldown(debounce),
	)
	if err != nil {
		return err
	}
	go w.Watch(ctx)
	go func() {
		for event := range w.Events() {
			eventChan <- event
		}
	}()
	return nil
}

type config_file_collection struct {
	mutex         sync.Mutex
	config_paths  []string
	dirs_to_watch []string
}

func (cfc *config_file_collection) get_list_of_config_files() *utils.Set[string] {
	cp := config.ConfigParser{
		AllIncludedFiles: utils.NewSet[string](), LineHandler: func(k, v string) error { return nil }}
	cp.ParseFiles(cfc.config_paths...)
	for _, path := range cfc.config_paths {
		path = filepath.Clean(path)
		cp.AllIncludedFiles.Add(path)
		for _, q := range []string{"dark-theme.auto.conf", "light-theme.auto.conf", "no-preference-theme.auto.conf"} {
			q = filepath.Join(filepath.Dir(path), q)
			cp.AllIncludedFiles.Add(filepath.Clean(q))
		}
	}
	return cp.AllIncludedFiles
}

func (cfc *config_file_collection) EventIsSignificant(ev fswatcher.WatchEvent) bool {
	cfc.mutex.Lock()
	defer cfc.mutex.Unlock()
	conf_files := cfc.get_list_of_config_files()
	q := filepath.Clean(ev.Path)
	return conf_files.Has(q)
}

func watch_for_kitty_config_changes(action func() error, debounce_time time.Duration, config_paths []string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	event_chan := make(chan fswatcher.WatchEvent)
	dirs := utils.NewSet[string](len(config_paths))
	for _, path := range config_paths {
		if parent := filepath.Dir(path); parent != "" && parent != "." && parent != "/" {
			dirs.Add(path)
		}
	}
	if dirs.Len() == 0 {
		return fmt.Errorf("No directories to watch provided")
	}
	cfc := config_file_collection{config_paths: config_paths, dirs_to_watch: dirs.AsSlice()}

	filtered_action := func(ev fswatcher.WatchEvent) error {
		if cfc.EventIsSignificant(ev) {
			return action()
		}
		return nil
	}
	for _, path := range cfc.dirs_to_watch {
		if err := watch_dir(ctx, path, debounce_time, event_chan); err != nil {
			return err
		}
	}
	stdinClosed := make(chan struct{})
	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
		}
		close(stdinClosed)
	}()
	for {
		select {
		case event := <-event_chan:
			if err := filtered_action(event); err != nil {
				fmt.Fprintf(os.Stderr, "failed to signal kitty in event: %s with error: %s\n", event, err)
			}
		case <-stdinClosed:
			return nil
		}
	}
}

func signal_kitty_to_reload_config(kitty_pid int) error {
	return unix.Kill(kitty_pid, unix.SIGUSR1)
}

func EntryPoint(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "__watch_conf__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			if len(args) < 3 {
				return 1, fmt.Errorf("Usage: __watch_conf__ kitty_pid debounce_time_ms config_paths...")
			}
			kitty_pid, err := strconv.Atoi(args[0])
			if err != nil {
				return 1, err
			}
			debounce_time_ms, err := strconv.ParseUint(args[1], 10, 64)
			if err != nil {
				return 1, err
			}
			if err = watch_for_kitty_config_changes(
				func() error { return signal_kitty_to_reload_config(kitty_pid) },
				time.Millisecond*time.Duration(debounce_time_ms), args[2:]); err != nil {
				return 1, err
			}
			return 0, nil
		},
	})
}
