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

// get_parent_dirs returns a deduplicated list of the immediate parent directory for each path.
// Unlike get_unique_directories it does not filter out subdirectories, so every unique
// parent is returned even when some are descendants of others.  This is the correct
// set of directories to pass to a non-recursive (top-level) file-system watcher.
func get_parent_dirs(paths []string) []string {
	dirSet := utils.NewSet[string](len(paths))
	for _, p := range paths {
		dirSet.Add(filepath.Dir(p))
	}
	return dirSet.AsSlice()
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

func safe_eval_symlinks(path string) string {
	if q, err := filepath.EvalSymlinks(path); err == nil {
		path = q
	}
	return path
}

func get_set_of_config_files(config_paths []string) *utils.Set[string] {
	cp := config.ConfigParser{
		AllIncludedFiles: utils.NewSet[string](), LineHandler: func(k, v string) error { return nil }}
	config_paths = utils.Filter(config_paths, func(path string) bool {
		_, err := os.Stat(path)
		return err == nil
	})
	cp.ParseFiles(config_paths...)
	// Resolve symlinks in all paths collected by the parser (important on macOS
	// where /tmp -> /private/tmp causes mismatches with FSEvents-reported paths).
	result := utils.NewSet[string](cp.AllIncludedFiles.Len() + len(config_paths)*4)
	for _, p := range cp.AllIncludedFiles.AsSlice() {
		result.Add(safe_eval_symlinks(resolve_path(p)))
	}
	for _, path := range config_paths {
		path = resolve_path(path)
		dir := filepath.Dir(path)
		result.Add(safe_eval_symlinks(path))
		for _, q := range []string{"dark-theme.auto.conf", "light-theme.auto.conf", "no-preference-theme.auto.conf"} {
			result.Add(safe_eval_symlinks(resolve_path(filepath.Join(dir, q))))
		}
	}
	return result
}

// watch_for_config_changes watches the parent directories of every conf file (main configs,
// includes, and auto color-scheme files) and calls action whenever one of those files changes.
// Watching is non-recursive (top-level only): only the immediate parent directories are added.
// When a conf file change is detected the full set of conf files is re-scanned so that newly
// added or removed include directives are reflected in the watched-directory set.
// It runs until ctx is cancelled.
func watch_for_config_changes(ctx context.Context, action func() error, debounce_time time.Duration, config_paths []string) error {
	event_chan := make(chan fswatcher.WatchEvent)

	all_paths := get_set_of_config_files(config_paths)

	// desired_dirs is the full set of parent directories we want to watch
	// (one per conf file, including files that may not yet exist).
	desired_dirs := utils.NewSet[string]()
	for _, p := range all_paths.AsSlice() {
		desired_dirs.Add(filepath.Dir(p))
	}
	if desired_dirs.Len() == 0 {
		return fmt.Errorf("No directories to watch provided")
	}

	// Create the watcher with top-level (non-recursive) depth.
	opts := []fswatcher.WatcherOpt{fswatcher.WithCooldown(debounce_time)}
	watched_dirs := utils.NewSet[string]()
	for _, dir := range desired_dirs.AsSlice() {
		if unix.Access(dir, unix.R_OK|unix.X_OK) == nil {
			opts = append(opts, fswatcher.WithPath(dir, fswatcher.WithDepth(fswatcher.WatchTopLevel)))
			watched_dirs.Add(dir)
		}
	}
	if watched_dirs.Len() == 0 {
		return fmt.Errorf("No directories to watch provided")
	}

	w, err := fswatcher.New(opts...)
	if err != nil {
		return err
	}
	go w.Watch(ctx)
	go func() {
		for event := range w.Events() {
			event_chan <- event
		}
	}()

	// sync_watched_dirs reconciles watched_dirs with desired_dirs: any desired directory
	// that now exists is added to the watcher, and any watched directory that is no longer
	// desired is dropped.
	sync_watched_dirs := func() {
		desired_dirs.ForEach(func(d string) {
			if !watched_dirs.Has(d) && unix.Access(d, unix.R_OK|unix.X_OK) == nil {
				if err := w.AddPath(d, fswatcher.WithDepth(fswatcher.WatchTopLevel)); err == nil {
					watched_dirs.Add(d)
				}
			}
		})
		watched_dirs.ForEach(func(d string) {
			if !desired_dirs.Has(d) {
				_ = w.DropPath(d)
				watched_dirs.Discard(d)
			}
		})
	}

	for {
		select {
		case event := <-event_chan:
			// On every event try to activate any desired directories that may have been
			// created since the last check (e.g. a new include directory was mkdir'd).
			sync_watched_dirs()

			new_all_paths := get_set_of_config_files(config_paths)
			if new_all_paths.Has(resolve_path(event.Path)) {
				// A conf file changed: rebuild desired_dirs from the new include set and
				// sync the watcher so new include directories are watched and stale ones dropped.
				new_desired := utils.NewSet[string]()
				for _, p := range new_all_paths.AsSlice() {
					new_desired.Add(filepath.Dir(p))
				}
				desired_dirs = new_desired
				sync_watched_dirs()

				if err := action(); err != nil {
					fmt.Fprintf(os.Stderr, "failed to signal kitty in event: %s with error: %s\n", event, err)
				}
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
		_ = scanner.Err()
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
			debounce_time_ms, err := strconv.Atoi(args[1])
			if err != nil {
				return 1, err
			}
			if debounce_time_ms < 0 {
				return 0, fmt.Errorf("debounce_time must be >= 0")
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
