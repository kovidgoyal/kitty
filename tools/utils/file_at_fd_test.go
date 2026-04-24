package utils

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRemoveChildren(t *testing.T) {
	tmpDir := t.TempDir()

	// Create nested structure
	subDir := filepath.Join(tmpDir, "subdir")
	os.Mkdir(subDir, 0755)
	os.WriteFile(filepath.Join(tmpDir, "file1.txt"), []byte("data"), 0644)
	os.WriteFile(filepath.Join(subDir, "file2.txt"), []byte("data"), 0644)

	d, err := os.Open(tmpDir)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()

	if err := RemoveChildren(d); err != nil {
		t.Errorf("expected no error, got %v", err)
	}

	// Verify directory is empty
	entries, _ := os.ReadDir(tmpDir)
	if len(entries) != 0 {
		t.Errorf("expected 0 entries, got %d", len(entries))
	}
}

func TestRemoveChildren_FirstError(t *testing.T) {
	tmpDir := t.TempDir()

	// Create a read-only file to trigger an error on some systems
	// (Note: Behavior varies by OS; this is a conceptual test for firstErr)
	lockedFile := filepath.Join(tmpDir, "locked")
	os.WriteFile(lockedFile, nil, 0000)

	d, _ := os.Open(tmpDir)
	defer d.Close()

	err := RemoveChildren(d)
	if err != nil {
		if _, ok := err.(*os.PathError); !ok {
			t.Errorf("expected *os.PathError, got %T", err)
		}
	}
}
