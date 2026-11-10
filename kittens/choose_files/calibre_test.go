package choose_files

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"
)

func TestCalibreResponseRouting(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		requests, stdin := io.Pipe()
		stdout, replies := io.Pipe()
		server := new_calibre_server_process(nil, stdin, stdout)
		defer func() {
			stdin.Close()
			stdout.Close()
			<-server.reader_done
		}()
		decoder := json.NewDecoder(requests)
		start_request := func(path string, timeout time.Duration) (calibre_request, chan calibre_result) {
			t.Helper()
			done := make(chan calibre_result, 1)
			go func() {
				data, err := server.request(path, "", timeout)
				done <- calibre_result{data: data, err: err}
			}()
			var request calibre_request
			if err := decoder.Decode(&request); err != nil {
				t.Fatal(err)
			}
			return request, done
		}
		make_reply := func(request calibre_request, title string) calibre_reply {
			t.Helper()
			data, err := json.Marshal(CalibreResponse{Path: request.Path, Metadata: CalibreMetadata{Title: title}})
			if err != nil {
				t.Fatal(err)
			}
			return calibre_reply{ID: request.ID, Response: data}
		}
		send := func(responses ...calibre_reply) {
			t.Helper()
			var data bytes.Buffer
			encoder := json.NewEncoder(&data)
			for _, response := range responses {
				if err := encoder.Encode(response); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := replies.Write(data.Bytes()); err != nil {
				t.Fatal(err)
			}
		}
		check := func(done chan calibre_result, path, title string) {
			t.Helper()
			result := <-done
			if result.err != nil {
				t.Fatal(result.err)
			}
			response, err := unmarshal_calibre_response(result.data, path)
			if err != nil {
				t.Fatal(err)
			}
			if response.Metadata.Title != title {
				t.Fatalf("metadata for %q: got %q, want %q", path, response.Metadata.Title, title)
			}
		}

		a, a_done := start_request("a.epub", time.Second)
		b, b_done := start_request("b.epub", time.Second)
		send(make_reply(b, "Book B"))
		check(b_done, b.Path, "Book B")
		send(make_reply(a, "Book A"))
		check(a_done, a.Path, "Book A")

		expired, expired_done := start_request(a.Path, time.Second)
		if err := (<-expired_done).err; !errors.Is(err, os.ErrDeadlineExceeded) {
			t.Fatalf("expected timeout, got %v", err)
		}
		retry, retry_done := start_request(a.Path, time.Second)
		next, next_done := start_request(b.Path, time.Second)
		// The stale and live replies arrive in one read, with no cover paths
		// to distinguish the two requests for the same book.
		send(make_reply(expired, "Expired"), make_reply(next, "Book B"), make_reply(retry, "Retried"))
		check(retry_done, retry.Path, "Retried")
		check(next_done, next.Path, "Book B")

		_, pending := start_request(a.Path, time.Second)
		replies.Close()
		if err := (<-pending).err; !errors.Is(err, io.EOF) {
			t.Fatalf("expected read error, got %v", err)
		}
	})
}

func TestCalibreCachedMetadataPath(t *testing.T) {
	path := filepath.Join(t.TempDir(), CALIBRE_METADATA_KEY)
	if err := os.WriteFile(path, []byte(`{"path":"/book.epub","metadata":{"title":"Book"}}`), 0600); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{CALIBRE_METADATA_KEY: path}
	if _, err := (calibre_renderer{path: "/other.epub"}).Unmarshall(files); err == nil {
		t.Fatal("accepted metadata for another book")
	}
	result, err := (calibre_renderer{path: "/book.epub"}).Unmarshall(files)
	if err != nil {
		t.Fatal(err)
	}
	if title := result.(*CalibreResponse).Metadata.Title; title != "Book" {
		t.Fatalf("expected cached title %q, got %q", "Book", title)
	}
}

func TestCalibreCachedMetadataSymlink(t *testing.T) {
	tdir := t.TempDir()
	book := filepath.Join(tdir, "book.epub")
	link := filepath.Join(tdir, "link.epub")
	other := filepath.Join(tdir, "other.epub")
	for _, p := range []string{book, other} {
		if err := os.WriteFile(p, []byte("x"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(book, link); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(CalibreResponse{Path: link, Metadata: CalibreMetadata{Title: "Book"}})
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(tdir, CALIBRE_METADATA_KEY)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{CALIBRE_METADATA_KEY: path}
	// The disk cache shares one entry between a symlink and its target
	if _, err := (calibre_renderer{path: book}).Unmarshall(files); err != nil {
		t.Fatalf("rejected metadata cached via a symlink: %v", err)
	}
	if _, err := (calibre_renderer{path: other}).Unmarshall(files); err == nil {
		t.Fatal("accepted metadata for another book")
	}
}
