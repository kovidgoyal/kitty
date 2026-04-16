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

func write_file(t *testing.T, path string, data string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
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
	tdir := t.TempDir()
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

func TestWatchForConfigChanges(t *testing.T) {
	tdir := t.TempDir()
	subdir := filepath.Join(tdir, "sub")
	if err := os.Mkdir(subdir, 0o700); err != nil {
		t.Fatal(err)
	}

	main_conf := filepath.Join(tdir, "kitty.conf")
	included_conf := filepath.Join(subdir, "included.conf")
	dark_theme := filepath.Join(tdir, "dark-theme.auto.conf")
	unrelated := filepath.Join(tdir, "unrelated.txt")

	write_file(t, main_conf, "include sub/included.conf\n")
	write_file(t, included_conf, "background black\n")
	write_file(t, dark_theme, "background #000000\n")
	write_file(t, unrelated, "this file should not trigger action\n")

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

	// Give the watcher time to start
	time.Sleep(200 * time.Millisecond)

	t.Run("main config change triggers action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, main_conf, "include sub/included.conf\nfont_size 13\n")
		count := wait_for_count(&action_count, before+1, 2*time.Second)
		if count <= before {
			t.Fatalf("Expected action to be called after main config change, count=%d", count)
		}
	})

	t.Run("included file change triggers action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, included_conf, "background white\n")
		count := wait_for_count(&action_count, before+1, 2*time.Second)
		if count <= before {
			t.Fatalf("Expected action to be called after included file change, count=%d", count)
		}
	})

	t.Run("auto color scheme file change triggers action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, dark_theme, "background #111111\n")
		count := wait_for_count(&action_count, before+1, 2*time.Second)
		if count <= before {
			t.Fatalf("Expected action to be called after dark-theme.auto.conf change, count=%d", count)
		}
	})

	t.Run("unrelated file change does not trigger action", func(t *testing.T) {
		before := action_count.Load()
		write_file(t, unrelated, "still unrelated\n")
		// Wait debounce + a bit more to ensure no spurious call
		time.Sleep(debounce + 200*time.Millisecond)
		after := action_count.Load()
		if after != before {
			t.Fatalf("Expected action NOT to be called for unrelated file, count went from %d to %d", before, after)
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

	// Give the watcher time to start
	time.Sleep(200 * time.Millisecond)

	// Write to the file several times rapidly within the debounce window.
	// The fswatcher debouncer drops events that occur within the cooldown period
	// after the first event, so only the first write should produce an action call.
	for i := 0; i < 5; i++ {
		write_file(t, main_conf, fmt.Sprintf("font_size %d\n", 12+i))
		time.Sleep(20 * time.Millisecond)
	}

	// Wait for up to one full debounce period for the first action to fire
	count_after_burst := wait_for_count(&action_count, 1, debounce+500*time.Millisecond)

	// Debouncing should have collapsed the burst into at most 2 calls.
	// The fswatcher debouncer uses leading-edge logic: the first event fires
	// immediately and subsequent events within the cooldown window are dropped.
	// A trailing event may fire at the end of the cooldown window, giving at most 2.
	if count_after_burst == 0 {
		t.Fatalf("Expected at least one action call after burst of writes, got 0")
	}
	if count_after_burst > 2 {
		t.Fatalf("Expected debouncing to collapse burst: want ≤2 calls, got %d", count_after_burst)
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
