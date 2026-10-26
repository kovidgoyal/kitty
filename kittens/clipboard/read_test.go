// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"bytes"
	"fmt"
	"image"
	"image/png"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"testing"
)

func TestClipboardReadMultipleOutputs(t *testing.T) {
	var png_data bytes.Buffer
	bounds := image.Rect(0, 0, 2, 3)
	if err := png.Encode(&png_data, image.NewRGBA(bounds)); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name            string
		available_mimes []string
		output_mimes    []string
		aliases         []string
	}{
		{"text", []string{"text/plain"}, []string{"text/plain", "text/plain"}, nil},
		{"images", []string{"image/png"}, []string{"image/png", "image/jpeg"}, nil},
		{"images reversed", []string{"image/png"}, []string{"image/jpeg", "image/png"}, nil},
		{"mixed", []string{"image/png", "text/plain"}, []string{"text/plain", "image/png", "text/plain", "image/jpeg"}, nil},
		{"alias", []string{"text/x-custom"}, []string{"text/plain", "text/x-custom"}, []string{"text/plain=text/x-custom"}},
		{"wildcard", []string{"text/plain"}, []string{"text/*", "text/plain"}, nil},
		{"text fallback", []string{"text/plain"}, []string{"text/html", "text/plain"}, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			requested := make(read_outputs)
			defer requested.cleanup()
			aliases, err := parse_aliases(tc.aliases)
			if err != nil {
				t.Fatal(err)
			}
			var outputs []*Output
			var names []string
			for i, mime_type := range tc.output_mimes {
				name := fmt.Sprintf("output-%d", i)
				names = append(names, name)
				o := &Output{arg: filepath.Join(dir, name), mime_type: mime_type}
				defer o.cleanup()
				if err := o.assign_mime_type(tc.available_mimes, aliases); err != nil {
					t.Fatal(err)
				}
				outputs = append(outputs, o)
				if err := requested.add(o); err != nil {
					t.Fatal(err)
				}
			}
			if len(requested) != len(tc.available_mimes) {
				t.Fatalf("Expected one request per remote MIME type, got %d", len(requested))
			}
			text_data := []byte("first line\nsecond line\n")
			var wg sync.WaitGroup
			for _, mime_type := range tc.available_mimes {
				data := text_data
				if mime_type == "image/png" {
					data = png_data.Bytes()
				}
				for chunk := range slices.Chunk(data, 7) {
					requested.add_data(mime_type, chunk)
				}
				requested.commit(mime_type, &wg)
				// Completed outputs must ignore further data and not be committed twice.
				requested.add_data(mime_type, []byte("ignored"))
				requested.commit(mime_type, &wg)
			}
			wg.Wait()
			for _, o := range outputs {
				if o.err != nil {
					t.Fatal(o.err)
				}
				if !o.started || !o.all_data_received {
					t.Fatalf("Output %s was not completed", o.arg)
				}
				data, err := os.ReadFile(o.arg)
				if err != nil {
					t.Fatal(err)
				}
				switch o.mime_type {
				case "image/jpeg":
					img, format, err := image.Decode(bytes.NewReader(data))
					if err != nil {
						t.Fatal(err)
					}
					if format != "jpeg" || img.Bounds() != bounds {
						t.Fatalf("Incorrect converted image: %s %v", format, img.Bounds())
					}
				case "image/png":
					if !bytes.Equal(data, png_data.Bytes()) {
						t.Fatal("PNG output differs from clipboard data")
					}
				default:
					if !bytes.Equal(data, text_data) {
						t.Fatalf("Incorrect text output: %q", data)
					}
				}
			}
			if actual := list_dir(t, dir); !slices.Equal(actual, names) {
				t.Fatalf("Unexpected output files: %v", actual)
			}
		})
	}
}

func TestClipboardReadOutputFailure(t *testing.T) {
	dir := t.TempDir()
	failed := &Output{arg: filepath.Join(dir, "missing", "output"), remote_mime_type: "text/plain"}
	succeeded := &Output{arg: filepath.Join(dir, "output"), remote_mime_type: "text/plain"}
	defer failed.cleanup()
	defer succeeded.cleanup()
	requested := make(read_outputs)
	for _, o := range []*Output{failed, succeeded} {
		if err := requested.add(o); err != nil {
			t.Fatal(err)
		}
	}
	requested.add_data("text/plain", []byte("clipboard contents"))
	var wg sync.WaitGroup
	requested.commit("text/plain", &wg)
	wg.Wait()
	if failed.err == nil {
		t.Fatal("Expected an error writing to a missing directory")
	}
	if succeeded.err != nil {
		t.Fatal(succeeded.err)
	}
	if data, err := os.ReadFile(succeeded.arg); err != nil || string(data) != "clipboard contents" {
		t.Fatalf("Other output was not saved after a write failure: %q %v", data, err)
	}
}

func TestClipboardReadDuplicateStreamOutputs(t *testing.T) {
	stream := func(arg, remote_mime_type string) *Output {
		return &Output{arg: arg, arg_is_stream: true, remote_mime_type: remote_mime_type}
	}
	requested := make(read_outputs)
	for _, o := range []*Output{
		stream("/dev/stdout", "text/plain"),
		stream("/dev/stderr", "text/plain"),
		stream("/dev/stdout", "text/html"),
		{arg: filepath.Join(t.TempDir(), "output"), remote_mime_type: "text/plain"},
	} {
		if err := requested.add(o); err != nil {
			t.Fatal(err)
		}
	}
	for _, o := range []*Output{stream("/dev/stdout", "text/plain"), stream("/dev/stderr", "text/plain")} {
		if err := requested.add(o); err == nil {
			t.Fatalf("Duplicate stream output to %s for %s was not rejected", o.arg, o.remote_mime_type)
		}
	}
	if len(requested["text/plain"].outputs) != 3 || len(requested["text/html"].outputs) != 1 {
		t.Fatalf("Rejected outputs were added: %d %d", len(requested["text/plain"].outputs), len(requested["text/html"].outputs))
	}
}

func TestClipboardReadSharedDownload(t *testing.T) {
	dir := t.TempDir()
	requested := make(read_outputs)
	defer requested.cleanup()
	var outputs []*Output
	for _, name := range []string{"a", "b", "c"} {
		o := &Output{arg: filepath.Join(dir, name), remote_mime_type: "text/plain"}
		outputs = append(outputs, o)
		if err := requested.add(o); err != nil {
			t.Fatal(err)
		}
	}
	requested.add_data("text/plain", []byte("clipboard "))
	// All outputs share a single temporary file for the downloaded data
	if actual := list_dir(t, dir); len(actual) != 1 {
		t.Fatalf("Expected a single temporary file, got: %v", actual)
	}
	requested.add_data("text/plain", []byte("contents"))
	var wg sync.WaitGroup
	requested.commit("text/plain", &wg)
	wg.Wait()
	for _, o := range outputs {
		if o.err != nil {
			t.Fatal(o.err)
		}
		if data, err := os.ReadFile(o.arg); err != nil || string(data) != "clipboard contents" {
			t.Fatalf("Incorrect contents for %s: %q %v", o.arg, data, err)
		}
	}
	if actual := list_dir(t, dir); !slices.Equal(actual, []string{"a", "b", "c"}) {
		t.Fatalf("Temporary file not removed: %v", actual)
	}
}

func TestClipboardReadDownloadFailure(t *testing.T) {
	dir := t.TempDir()
	outputs := []*Output{
		{arg: filepath.Join(dir, "missing", "a"), remote_mime_type: "text/plain"},
		{arg: filepath.Join(dir, "missing", "b"), remote_mime_type: "text/plain"},
	}
	requested := make(read_outputs)
	defer requested.cleanup()
	for _, o := range outputs {
		if err := requested.add(o); err != nil {
			t.Fatal(err)
		}
	}
	requested.add_data("text/plain", []byte("clipboard contents"))
	var wg sync.WaitGroup
	requested.commit("text/plain", &wg)
	wg.Wait()
	for _, o := range outputs {
		if o.err == nil {
			t.Fatalf("Expected an error for %s when no temporary file can be created", o.arg)
		}
	}
}

func TestClipboardReadDuplicateOutputFiles(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	if err := os.Symlink("target", "link"); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir("sub", 0o755); err != nil {
		t.Fatal(err)
	}
	outputs := func(args ...string) (ans []*Output) {
		for _, arg := range args {
			ans = append(ans, &Output{arg: arg, arg_is_stream: arg == "/dev/stdout" || arg == "/dev/stderr"})
		}
		return
	}
	for _, args := range [][]string{
		{"a", "b", "sub/a", "/dev/stdout", "/dev/stdout", "/dev/stderr"},
		{"link", "sub/target"},
	} {
		if err := check_for_duplicate_output_files(outputs(args...)); err != nil {
			t.Fatalf("Unexpected error for %v: %s", args, err)
		}
	}
	for _, args := range [][]string{
		{"a", "a"},
		{"a", "./a"},
		{"a", filepath.Join(dir, "a")},
		{"sub/../a", "a"},
		{"link", "target"},
		{"target", filepath.Join(dir, "link")},
	} {
		if err := check_for_duplicate_output_files(outputs(args...)); err == nil {
			t.Fatalf("Duplicate output files not rejected: %v", args)
		}
	}
}

func TestClipboardOutputCommitAtomic(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "output")
	old_data := bytes.Repeat([]byte("old contents\n"), 1024)
	new_data := bytes.Repeat([]byte("new contents\n"), 1024)
	if err := os.WriteFile(dest, old_data, 0o640); err != nil {
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
		if st, err := os.Stat(dest); err != nil {
			t.Fatal(err)
		} else if st.Mode().Perm() != 0o640 {
			t.Fatalf("Committed file has incorrect permissions: %o", st.Mode().Perm())
		}
		if _, err := os.Stat(temp_name); !os.IsNotExist(err) {
			t.Fatalf("Temporary file still exists after commit: %v", err)
		}
	}
}

func list_dir(t *testing.T, dir string) (ans []string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		ans = append(ans, e.Name())
	}
	return
}

func TestClipboardOutputCommitFailure(t *testing.T) {
	dir := t.TempDir()
	// Renaming a file over a non-empty directory fails even when running as root
	dest := filepath.Join(dir, "output")
	if err := os.MkdirAll(filepath.Join(dest, "child"), 0o755); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest}
	defer output.cleanup()
	output.add_data([]byte("new contents"))
	if output.err != nil {
		t.Fatal(output.err)
	}
	output.commit()
	if output.err == nil {
		t.Fatal("Expected commit to fail when destination is a non-empty directory")
	}
	if st, err := os.Stat(filepath.Join(dest, "child")); err != nil || !st.IsDir() {
		t.Fatalf("Original destination changed after failed commit: %v", err)
	}
	if names := list_dir(t, dir); !slices.Equal(names, []string{"output"}) {
		t.Fatalf("Stray files left behind after failed commit: %v", names)
	}
}

func TestClipboardOutputCommitNewFile(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "output")
	output := Output{arg: dest}
	output.add_data([]byte("new contents"))
	output.commit()
	if output.err != nil {
		t.Fatal(output.err)
	}
	if actual, err := os.ReadFile(dest); err != nil || string(actual) != "new contents" {
		t.Fatalf("Incorrect contents in new file: %q %v", actual, err)
	}
	if names := list_dir(t, dir); !slices.Equal(names, []string{"output"}) {
		t.Fatalf("Stray files left behind after commit: %v", names)
	}
}

func TestClipboardOutputCommitSymlink(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "target")
	dest := filepath.Join(dir, "link")
	if err := os.WriteFile(target, []byte("old contents"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, dest); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest}
	output.add_data([]byte("new contents"))
	output.commit()
	if output.err != nil {
		t.Fatal(output.err)
	}
	if st, err := os.Lstat(dest); err != nil || st.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("Symlink at destination was replaced: %v", err)
	}
	if actual, err := os.ReadFile(target); err != nil || string(actual) != "new contents" {
		t.Fatalf("Symlink target not updated: %q %v", actual, err)
	}
}

func TestClipboardOutputCommitDanglingSymlink(t *testing.T) {
	for _, link_type := range []string{"absolute", "relative"} {
		for _, data_type := range []string{"text", "image"} {
			t.Run(link_type+"/"+data_type, func(t *testing.T) {
				dir := t.TempDir()
				target := filepath.Join(dir, "target")
				dest := filepath.Join(dir, "link")
				link := target
				if link_type == "relative" {
					link = "target"
				}
				if err := os.Symlink(link, dest); err != nil {
					t.Fatal(err)
				}
				data := []byte("new contents")
				output := Output{arg: dest}
				defer output.cleanup()
				if data_type == "image" {
					var buf bytes.Buffer
					if err := png.Encode(&buf, image.NewRGBA(image.Rect(0, 0, 2, 3))); err != nil {
						t.Fatal(err)
					}
					data = buf.Bytes()
					output.image_needs_conversion = true
					output.mime_type = "image/jpeg"
				}
				output.add_data(data)
				output.commit()
				if output.err != nil {
					t.Fatal(output.err)
				}
				if actual, err := os.Readlink(dest); err != nil || actual != link {
					t.Errorf("Symlink at destination changed: %q %v", actual, err)
				}
				actual, err := os.ReadFile(target)
				if err != nil {
					t.Fatalf("Symlink target not created: %v", err)
				}
				if data_type == "image" {
					img, format, err := image.Decode(bytes.NewReader(actual))
					if err != nil {
						t.Fatal(err)
					}
					if format != "jpeg" || img.Bounds() != image.Rect(0, 0, 2, 3) {
						t.Fatalf("Incorrect converted image: %s %v", format, img.Bounds())
					}
				} else if !bytes.Equal(actual, data) {
					t.Fatalf("Incorrect contents in symlink target: %q", actual)
				}
				if names := list_dir(t, dir); !slices.Equal(names, []string{"link", "target"}) {
					t.Fatalf("Stray files left behind after commit: %v", names)
				}
			})
		}
	}
}

func TestClipboardOutputImageEncodeFailure(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "output")
	old_data := []byte("old contents")
	if err := os.WriteFile(dest, old_data, 0o600); err != nil {
		t.Fatal(err)
	}
	var png_data bytes.Buffer
	if err := png.Encode(&png_data, image.NewRGBA(image.Rect(0, 0, 1, 1))); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest, image_needs_conversion: true, mime_type: "image/x-unsupported"}
	defer output.cleanup()
	output.add_data(png_data.Bytes())
	if output.err != nil {
		t.Fatal(output.err)
	}
	output.commit()
	if output.err == nil {
		t.Fatal("Expected commit to fail with an unsupported image type")
	}
	if actual, err := os.ReadFile(dest); err != nil || !bytes.Equal(actual, old_data) {
		t.Fatalf("Original destination changed after failed image encode: %q %v", actual, err)
	}
}

func TestClipboardOutputMimeList(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "formats.txt")
	output := Output{arg: dest, mime_type: ".", remote_mime_type: "."}
	defer output.cleanup()
	output.write_mime_list([]string{"text/plain", "image/png"})
	if output.err != nil {
		t.Fatal(output.err)
	}
	if !output.started || !output.all_data_received {
		t.Fatal("MIME list output not marked as complete")
	}
	if actual, err := os.ReadFile(dest); err != nil || string(actual) != "text/plain\nimage/png" {
		t.Fatalf("Incorrect MIME list saved: %q %v", actual, err)
	}
	if names := list_dir(t, dir); !slices.Equal(names, []string{"formats.txt"}) {
		t.Fatalf("Stray files left behind after saving MIME list: %v", names)
	}
}
