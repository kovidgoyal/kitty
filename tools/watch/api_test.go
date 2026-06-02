// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package watch

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

// prime_watcher repeatedly writes to path until the watcher delivers an event and
// the action fires, confirming the watcher goroutine is ready.  A single write may
// race the watcher's initialisation so retrying ensures at least one write lands
// while the watcher is active.  After success it waits one full debounce period
// so the cooldown window is clear before returning.
// Returns the current action count after settling.
func prime_watcher(t *testing.T, path string, counter *atomic.Int32, debounce time.Duration) int32 {
	t.Helper()
	before := counter.Load()
	deadline := time.Now().Add(5 * time.Second)
	n := 0
	for time.Now().Before(deadline) {
		write_file(t, path, fmt.Sprintf("# prime %d\n", n))
		n++
		if wait_for_count(counter, before+1, debounce+100*time.Millisecond) > before {
			// Action fired — clear the debounce window before returning.
			time.Sleep(debounce + 20*time.Millisecond)
			return counter.Load()
		}
	}
	t.Fatal("watcher failed to become ready: no action fired within 5 seconds of repeated prime writes")
	return 0
}

func write_file(t *testing.T, path string, data string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestGetParentDirs(t *testing.T) {
	type tc struct {
		name   string
		input  []string
		expect []string
	}
	cases := []tc{
		{
			name:   "nil input",
			input:  nil,
			expect: nil,
		},
		{
			name:   "single file",
			input:  []string{"/a/b/file.conf"},
			expect: []string{"/a/b"},
		},
		{
			name:   "files in same directory",
			input:  []string{"/a/b/file1.conf", "/a/b/file2.conf"},
			expect: []string{"/a/b"},
		},
		{
			name:   "sibling directories",
			input:  []string{"/a/b/file.conf", "/a/c/file.conf"},
			expect: []string{"/a/b", "/a/c"},
		},
		{
			name: "parent and child directory both returned",
			// Unlike get_unique_directories, subdirectories are NOT filtered out.
			input:  []string{"/a/file.conf", "/a/b/file.conf"},
			expect: []string{"/a", "/a/b"},
		},
		{
			name: "deeply nested all returned",
			input: []string{
				"/a/file.conf",
				"/a/b/file.conf",
				"/a/b/c/file.conf",
			},
			expect: []string{"/a", "/a/b", "/a/b/c"},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			result := get_parent_dirs(tc.input)
			sort.Strings(result)
			sort.Strings(tc.expect)
			if tc.expect == nil {
				if len(result) != 0 {
					t.Fatalf("expected empty result, got %v", result)
				}
				return
			}
			if diff := cmp.Diff(tc.expect, result); diff != "" {
				t.Fatalf("get_parent_dirs mismatch (-want +got):\n%s", diff)
			}
		})
	}
}

func TestGetUniqueDirectories(t *testing.T) {
	// Empty input
	if result := get_unique_directories(nil); result != nil {
		t.Fatalf("Expected nil for empty input, got %v", result)
	}

	type tc struct {
		name   string
		input  []string
		expect []string
	}

	cases := []tc{
		{
			name:   "single file",
			input:  []string{"/a/b/file.conf"},
			expect: []string{"/a/b"},
		},
		{
			name:   "files in same directory",
			input:  []string{"/a/b/file1.conf", "/a/b/file2.conf"},
			expect: []string{"/a/b"},
		},
		{
			name:   "sibling directories",
			input:  []string{"/a/b/file.conf", "/a/c/file.conf"},
			expect: []string{"/a/b", "/a/c"},
		},
		{
			name: "subdirectory is excluded",
			// /a/b is a subdirectory of /a, so only /a should be in results
			input:  []string{"/a/file.conf", "/a/b/file.conf"},
			expect: []string{"/a"},
		},
		{
			name: "deeply nested subdirectory is excluded",
			input: []string{
				"/a/file.conf",
				"/a/b/file.conf",
				"/a/b/c/file.conf",
				"/x/y/file.conf",
			},
			expect: []string{"/a", "/x/y"},
		},
		{
			name: "duplicate parent directories deduplicated",
			input: []string{
				"/a/b/file1.conf",
				"/a/b/file2.conf",
				"/a/b/sub/file3.conf",
			},
			expect: []string{"/a/b"},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			result := get_unique_directories(tc.input)
			sort.Strings(result)
			sort.Strings(tc.expect)
			if diff := cmp.Diff(tc.expect, result); diff != "" {
				t.Fatalf("get_unique_directories mismatch (-want +got):\n%s", diff)
			}
		})
	}
}

func TestGetSetOfConfigFiles(t *testing.T) {
	tdir := resolve_path(t.TempDir())
	subdir := filepath.Join(tdir, "sub")
	if err := os.Mkdir(subdir, 0o700); err != nil {
		t.Fatal(err)
	}

	main_conf := filepath.Join(tdir, "kitty.conf")
	included_conf := filepath.Join(subdir, "included.conf")

	// Main config that includes another file
	write_file(t, main_conf, "include sub/included.conf\nfont_size 12\n")
	write_file(t, included_conf, "background black\n")

	result := get_set_of_config_files([]string{main_conf})

	// Must contain the main config file
	if !result.Has(main_conf) {
		t.Errorf("Expected set to contain main config %q", main_conf)
	}
	// Must contain the included file
	if !result.Has(included_conf) {
		t.Errorf("Expected set to contain included config %q", included_conf)
	}
	// Must contain auto color scheme files (even if they don't exist)
	for _, name := range []string{"dark-theme.auto.conf", "light-theme.auto.conf", "no-preference-theme.auto.conf"} {
		expected := filepath.Join(tdir, name)
		if !result.Has(expected) {
			t.Errorf("Expected set to contain auto color scheme file %q", expected)
		}
	}
}

// wait_for_count waits until counter reaches at least target or timeout fires.
// Returns the count observed.
func wait_for_count(counter *atomic.Int32, target int32, timeout time.Duration) int32 {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if counter.Load() >= target {
			return counter.Load()
		}
		time.Sleep(10 * time.Millisecond)
	}
	return counter.Load()
}

// TestWatchForConfigChanges consolidates all watcher integration tests into a single
// function that starts the watcher once and confirms readiness via prime_watcher
// instead of a blind time.Sleep.  Include-watching scenarios (file changes, include
// added/removed from main config, include added to an already-included file) run as
// sequential subtests.
func TestWatchForConfigChanges(t *testing.T) {
	tdir := resolve_path(t.TempDir())
	subdir := filepath.Join(tdir, "sub")
	extradir := filepath.Join(tdir, "extra")
	extra2dir := filepath.Join(tdir, "extra2")
	for _, d := range []string{subdir, extradir, extra2dir} {
		if err := os.Mkdir(d, 0o700); err != nil {
			t.Fatal(err)
		}
	}

	main_conf := filepath.Join(tdir, "kitty.conf")
	included_conf := filepath.Join(subdir, "included.conf")
	dark_theme := filepath.Join(tdir, "dark-theme.auto.conf")
	unrelated := filepath.Join(tdir, "unrelated.txt")
	extra_conf := filepath.Join(extradir, "custom.conf")
	extra2_conf := filepath.Join(extra2dir, "another.conf")

	write_file(t, main_conf, "include sub/included.conf\n")
	write_file(t, included_conf, "background black\n")
	write_file(t, dark_theme, "background #000000\n")
	write_file(t, unrelated, "this file should not trigger action\n")
	write_file(t, extra_conf, "background black\n")
	write_file(t, extra2_conf, "background black\n")

	var action_count atomic.Int32
	action := func() error {
		action_count.Add(1)
		return nil
	}

	const debounce = 50 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan error, 1)
	go func() {
		done <- watch_for_config_changes(ctx, action, debounce, []string{main_conf})
	}()

	// Confirm the watcher is ready by writing to the dark-theme auto conf (an
	// always-watched file that does not affect the include graph) and waiting for
	// an action to fire.  This replaces the blind time.Sleep used previously.
	prime_watcher(t, dark_theme, &action_count, debounce)

	t.Run("main config change triggers action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, main_conf, "include sub/included.conf\nfont_size 13\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action to be called after main config change, count=%d", action_count.Load())
		}
	})
	time.Sleep(debounce + 20*time.Millisecond)

	t.Run("included file change triggers action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, included_conf, "background white\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action to be called after included file change, count=%d", action_count.Load())
		}
	})
	time.Sleep(debounce + 20*time.Millisecond)

	t.Run("auto color scheme file change triggers action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, dark_theme, "background #111111\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action to be called after dark-theme.auto.conf change, count=%d", action_count.Load())
		}
	})
	time.Sleep(debounce + 20*time.Millisecond)

	t.Run("unrelated file change does not trigger action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, unrelated, "still unrelated\n")
		time.Sleep(debounce + 200*time.Millisecond)
		if after := action_count.Load(); after != before {
			t.Fatalf("Expected action NOT to be called for unrelated file, count went from %d to %d", before, after)
		}
	})

	// include added to main config: extradir must become watched.
	// sync_watched_dirs() runs before action() in the event loop, so by the time
	// wait_for_count returns the new directory is already registered.
	t.Run("include added to main config is watched", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, main_conf, "include sub/included.conf\ninclude extra/custom.conf\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action after kitty.conf gained include directive")
		}
		// Let the debounce window clear before writing to the newly watched file.
		time.Sleep(debounce + 20*time.Millisecond)
		before = action_count.Load()
		write_file(t, extra_conf, "background white\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action after modifying newly included file")
		}
	})
	time.Sleep(debounce + 20*time.Millisecond)

	// include added to an already-included file: extra2dir must become watched.
	t.Run("include added to already-included file adds its parent dir", func(t *testing.T) {
		// Add an include to sub/included.conf that points into extra2dir, which is
		// not currently watched.  The watcher re-scans the full include graph on
		// every conf-file change, so extra2dir must be added to the watch set.
		before := action_count.Load()
		write_file(t, included_conf, "include ../extra2/another.conf\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action after sub/included.conf gained include directive")
		}
		time.Sleep(debounce + 20*time.Millisecond)
		// extra2dir is now watched; a change to extra2/another.conf must fire.
		before = action_count.Load()
		write_file(t, extra2_conf, "background blue\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action after modifying file included from an already-included conf file")
		}
	})
	time.Sleep(debounce + 20*time.Millisecond)

	// include removed from main config: extradir must be dropped from the watch set.
	t.Run("include removed from main config is no longer watched", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, main_conf, "include sub/included.conf\n")
		if wait_for_count(&action_count, before+1, 2*time.Second) <= before {
			t.Fatalf("Expected action after kitty.conf lost include directive")
		}
		time.Sleep(debounce + 20*time.Millisecond)
		before = action_count.Load()
		write_file(t, extra_conf, "background green\n")
		time.Sleep(debounce + 200*time.Millisecond)
		if after := action_count.Load(); after != before {
			t.Fatalf("Expected NO action after modifying removed-include file, count went from %d to %d", before, after)
		}
	})

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("watch_for_config_changes returned error: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("watch_for_config_changes did not exit after context cancel")
	}
}

func TestWatchForConfigChangesDebounce(t *testing.T) {
	tdir := t.TempDir()
	main_conf := filepath.Join(tdir, "kitty.conf")
	write_file(t, main_conf, "font_size 12\n")

	var action_count atomic.Int32
	action := func() error {
		action_count.Add(1)
		return nil
	}

	const debounce = 300 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan error, 1)
	go func() {
		done <- watch_for_config_changes(ctx, action, debounce, []string{main_conf})
	}()

	// Confirm the watcher is ready before sending the burst.
	prime_watcher(t, main_conf, &action_count, debounce)

	// Write to the file several times rapidly within the debounce window.
	// The fswatcher debouncer drops events that occur within the cooldown period
	// after the first event, so only the first write should produce an action call.
	before_burst := action_count.Load()
	for i := range 5 {
		write_file(t, main_conf, fmt.Sprintf("font_size %d\n", 12+i))
		time.Sleep(20 * time.Millisecond)
	}

	// Wait for up to one full debounce period for the first action to fire.
	count_after_burst := wait_for_count(&action_count, before_burst+1, debounce+500*time.Millisecond)
	action_calls_in_burst := count_after_burst - before_burst

	// Debouncing should have collapsed the burst into at most 2 calls.
	// The fswatcher debouncer uses leading-edge logic: the first event fires
	// immediately and subsequent events within the cooldown window are dropped.
	// A trailing event may fire at the end of the cooldown window, giving at most 2.
	if action_calls_in_burst == 0 {
		t.Fatalf("Expected at least one action call after burst of writes, got 0")
	}
	if action_calls_in_burst > 2 {
		t.Fatalf("Expected debouncing to collapse burst: want ≤2 calls, got %d", action_calls_in_burst)
	}

	// After waiting well past the debounce window, a new write should trigger exactly one more call.
	time.Sleep(debounce + 100*time.Millisecond)
	before_new := action_count.Load()
	write_file(t, main_conf, "font_size 20\n")
	count_new := wait_for_count(&action_count, before_new+1, 2*time.Second)
	if count_new <= before_new {
		t.Fatalf("Expected action after post-debounce write, count went from %d to %d", before_new, count_new)
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("watch_for_config_changes returned error: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("watch_for_config_changes did not exit after context cancel")
	}
}
