// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestClipboardOutputCommitAtomic(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "output")
	old_data := bytes.Repeat([]byte("old contents\n"), 1024)
	new_data := bytes.Repeat([]byte("new contents\n"), 1024)
	if err := os.WriteFile(dest, old_data, 0o600); err != nil {
		t.Fatal(err)
	}

	started, stop := make(chan struct{}), make(chan struct{})
	result := make(chan error, 1)
	go func() {
		data, err := os.ReadFile(dest)
		close(started)
		for {
			if err != nil {
				result <- fmt.Errorf("Concurrent read failed: %w", err)
				return
			}
			if !bytes.Equal(data, old_data) && !bytes.Equal(data, new_data) {
				result <- fmt.Errorf("Concurrent read returned incomplete contents: %q", data)
				return
			}
			select {
			case <-stop:
				result <- nil
				return
			default:
			}
			data, err = os.ReadFile(dest)
		}
	}()
	<-started
	t.Cleanup(func() {
		close(stop)
		if err := <-result; err != nil {
			t.Error(err)
		}
	})

	for i := range 100 {
		data := new_data
		if i%2 != 0 {
			data = old_data
		}
		output := Output{arg: dest}
		output.add_data(data)
		if output.err != nil {
			t.Fatal(output.err)
		}
		temp_name := output.dest.Name()
		output.commit()
		if output.err != nil {
			t.Fatal(output.err)
		}
		actual, err := os.ReadFile(dest)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(actual, data) {
			t.Fatal("Committed file has incorrect contents")
		}
		if _, err := os.Stat(temp_name); !os.IsNotExist(err) {
			t.Fatalf("Temporary file still exists after commit: %v", err)
		}
	}
}

func TestClipboardOutputCommitRenameFailure(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "output")
	old_data := []byte("old contents")
	if err := os.WriteFile(dest, old_data, 0o600); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest}
	defer output.cleanup()
	output.add_data([]byte("new contents"))
	if output.err != nil {
		t.Fatal(output.err)
	}
	// Removing the source forces rename to fail even when running as root.
	if err := os.Remove(output.dest.Name()); err != nil {
		t.Fatal(err)
	}
	output.commit()
	if !errors.Is(output.err, os.ErrNotExist) {
		t.Fatalf("Expected rename to fail with a missing source, got: %v", output.err)
	}
	actual, err := os.ReadFile(dest)
	if err != nil {
		t.Fatalf("Original destination lost after failed rename: %v", err)
	}
	if !bytes.Equal(actual, old_data) {
		t.Fatalf("Original destination changed after failed rename: %q", actual)
	}
}
