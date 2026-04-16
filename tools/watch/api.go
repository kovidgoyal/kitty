package watch

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/sgtdi/fswatcher"
	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// watch_dir starts fswatcher in a background goroutine and pipes events to a custom channel.
func watch_dirs(ctx context.Context, paths []string, debounce time.Duration, eventChan chan<- fswatcher.WatchEvent) error {
	opts := []fswatcher.WatcherOpt{
		fswatcher.WithCooldown(debounce),
	}
	for _, path := range paths {
		if unix.Access(path, unix.R_OK|unix.X_OK) == nil {
			opts = append(opts, fswatcher.WithPath(path))
		}
	}
	w, err := fswatcher.New(opts...)
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

// returns the closest unique parent directories for a list of paths.
// It excludes any directory that is a subdirectory of another directory already in the result set.
func get_unique_directories(paths []string) []string {
	if len(paths) == 0 {
		return nil
	}

	// 1. Extract parent directories and remove duplicates
	dirMap := utils.NewSet[string](len(paths))
	for _, p := range paths {
		dirMap.Add(filepath.Dir(p))
	}

	// 2. Convert map to a sorted slice
	// Sorting ensures that shorter paths (potential parents) come before longer ones (potential children)
	uniqueDirs := dirMap.AsSlice()
	sort.Strings(uniqueDirs)

	// 3. Filter out subdirectories
	var result []string
	for _, current := range uniqueDirs {
		isSubDir := false
		for _, parent := range result {
			// Check if 'current' is a subdirectory of 'parent'
			// Strings.HasPrefix is safe here because paths are sorted and Cleaned by filepath.Dir
			if current == parent || strings.HasPrefix(current, parent+string(filepath.Separator)) {
				isSubDir = true
				break
			}
		}
		if !isSubDir {
			result = append(result, current)
		}
	}
	return result
}

// resolve_path resolves symlinks in the directory component of path so the result
// matches what the OS-level file-system watcher (FSEvents on macOS, inotify on Linux)
// reports. This is important on macOS where /tmp is a symlink to /private/tmp.
// If the directory cannot be resolved (e.g. it doesn't exist yet) the path is
// returned cleaned but unresolved.
func resolve_path(path string) string {
	dir := filepath.Dir(path)
	if resolved, err := filepath.EvalSymlinks(dir); err == nil {
		return filepath.Join(resolved, filepath.Base(path))
	}
	return filepath.Clean(path)
}

func get_set_of_config_files(config_paths []string) *utils.Set[string] {
	cp := config.ConfigParser{
		AllIncludedFiles: utils.NewSet[string](), LineHandler: func(k, v string) error { return nil }}
	cp.ParseFiles(config_paths...)
	// Resolve symlinks in all paths collected by the parser (important on macOS
	// where /tmp -> /private/tmp causes mismatches with FSEvents-reported paths).
	result := utils.NewSet[string](cp.AllIncludedFiles.Len() + len(config_paths)*4)
	for _, p := range cp.AllIncludedFiles.AsSlice() {
		result.Add(resolve_path(p))
	}
	for _, path := range config_paths {
		path = resolve_path(path)
		result.Add(path)
		dir := filepath.Dir(path)
		for _, q := range []string{"dark-theme.auto.conf", "light-theme.auto.conf", "no-preference-theme.auto.conf"} {
			result.Add(resolve_path(filepath.Join(dir, q)))
		}
	}
	return result
}

// watch_for_config_changes watches the directories derived from config_paths and calls action
// whenever a watched config file (including includes and auto color scheme files) changes.
// It runs until ctx is cancelled.
func watch_for_config_changes(ctx context.Context, action func() error, debounce_time time.Duration, config_paths []string) error {
	event_chan := make(chan fswatcher.WatchEvent)
	all_paths := get_set_of_config_files(config_paths)
	dirs_to_watch := get_unique_directories(all_paths.AsSlice())
	if len(dirs_to_watch) == 0 {
		return fmt.Errorf("No directories to watch provided")
	}

	filtered_action := func(ev fswatcher.WatchEvent) error {
		all_paths := get_set_of_config_files(config_paths)
		if all_paths.Has(resolve_path(ev.Path)) {
			return action()
		}
		return nil
	}

	if err := watch_dirs(ctx, dirs_to_watch, debounce_time, event_chan); err != nil {
		return err
	}
	for {
		select {
		case event := <-event_chan:
			if err := filtered_action(event); err != nil {
				fmt.Fprintf(os.Stderr, "failed to signal kitty in event: %s with error: %s\n", event, err)
			}
		case <-ctx.Done():
			return nil
		}
	}
}

func watch_for_kitty_config_changes(action func() error, debounce_time time.Duration, config_paths []string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
		}
		cancel()
	}()
	return watch_for_config_changes(ctx, action, debounce_time, config_paths)
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
			config_paths := utils.Map(resolve_path, args[2:])
			if err = watch_for_kitty_config_changes(
				func() error { return signal_kitty_to_reload_config(kitty_pid) },
				time.Millisecond*time.Duration(debounce_time_ms), config_paths); err != nil {
				return 1, err
			}
			return 0, nil
		},
	})
}
