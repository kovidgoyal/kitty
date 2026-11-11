package choose_files

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print
var calibre_needs_cleanup atomic.Bool
var calibre_server_load_finished atomic.Bool

type calibre_server_process struct {
	proc            *exec.Cmd
	stdout          io.ReadCloser
	stdin           io.WriteCloser
	file_extensions *utils.Set[string]
	reader_done     chan struct{}
	lock            sync.Mutex
	request_id      uint64
	pending         map[uint64]chan calibre_result
	read_err        error
}

type calibre_request struct {
	ID    uint64 `json:"id"`
	Path  string `json:"path"`
	Cover string `json:"cover,omitempty"`
}

type calibre_reply struct {
	ID       uint64          `json:"id"`
	Response json.RawMessage `json:"response"`
}

type calibre_result struct {
	data json.RawMessage
	err  error
}

type CalibreMetadata struct {
	Title        string    `json:"title"`
	Authors      []string  `json:"authors"`
	Series       string    `json:"series"`
	Series_index float64   `json:"series_index"`
	Tags         []string  `json:"tags"`
	Rating       float64   `json:"rating"`
	Published    time.Time `json:"pubdate"`
	Timestamp    time.Time `json:"timestamp"`
}

type CalibreResponse struct {
	Path      string          `json:"path"`
	Filetypes []string        `json:"filetypes"`
	Cover     string          `json:"cover"`
	Error     string          `json:"error"`
	Metadata  CalibreMetadata `json:"metadata"`
}

// The path can be reused, and calibre only echoes the cover path if it writes
// a cover. Attach a request ID to every response in the forked worker.
const calibre_server_program = `
def serve():
    # calibre-debug runs -c with exec() inside a function. Keep imports local.
    import io
    import json
    import sys
    from contextlib import nullcontext
    from calibre.ebooks.metadata import cli

    read_metadata = cli.one

    def reply_with_id(line, lock):
        request = json.loads(line)
        request_id = request['id']
        stdout = sys.__stdout__
        # Always reply, otherwise the request blocks until it times out.
        try:
            with io.StringIO() as output:
                try:
                    sys.__stdout__ = output
                    read_metadata(line, nullcontext())
                finally:
                    sys.__stdout__ = stdout
                # The response is the last line, ignore any stray output before it.
                lines = output.getvalue().splitlines()
            response = json.loads(lines[-1]) if lines else None
            if not isinstance(response, dict):
                raise ValueError('no metadata response from calibre')
        except Exception as e:
            response = {'path': request['path'], 'error': f'reading metadata failed: {e}'}
        with lock:
            print(json.dumps({'id': request_id, 'response': response}), file=stdout, flush=True)

    cli.one = reply_with_id
    cli.simple_metadata_server()

serve()
`

func new_calibre_server_process(proc *exec.Cmd, stdin io.WriteCloser, stdout io.ReadCloser) *calibre_server_process {
	s := &calibre_server_process{
		proc: proc, stdin: stdin, stdout: stdout, reader_done: make(chan struct{}),
		pending: make(map[uint64]chan calibre_result),
	}
	go s.read_replies()
	return s
}

func (s *calibre_server_process) read_replies() {
	defer close(s.reader_done)
	reader := bufio.NewReader(s.stdout)
	for {
		line, err := reader.ReadBytes('\n')
		if err != nil {
			s.lock.Lock()
			s.read_err = fmt.Errorf("error reading from calibre metadata server: %w", err)
			for _, ch := range s.pending {
				ch <- calibre_result{err: s.read_err}
			}
			clear(s.pending)
			s.lock.Unlock()
			return
		}
		var reply calibre_reply
		if err := json.Unmarshal(line, &reply); err != nil {
			continue
		}
		s.lock.Lock()
		if ch := s.pending[reply.ID]; ch != nil {
			delete(s.pending, reply.ID)
			ch <- calibre_result{data: reply.Response}
		}
		s.lock.Unlock()
	}
}

func (s *calibre_server_process) request(path, cover string, timeout time.Duration) (json.RawMessage, error) {
	s.lock.Lock()
	if err := s.read_err; err != nil {
		s.lock.Unlock()
		return nil, err
	}
	s.request_id++
	id := s.request_id
	ch := make(chan calibre_result, 1)
	s.pending[id] = ch
	s.lock.Unlock()
	defer func() {
		s.lock.Lock()
		delete(s.pending, id)
		s.lock.Unlock()
	}()

	payload, err := json.Marshal(calibre_request{ID: id, Path: path, Cover: cover})
	if err != nil {
		return nil, err
	}
	if _, err := s.stdin.Write(append(payload, '\n')); err != nil {
		return nil, fmt.Errorf("error writing to calibre metadata server: %w", err)
	}
	select {
	case reply := <-ch:
		return reply.data, reply.err
	case <-time.After(timeout):
		return nil, os.ErrDeadlineExceeded
	}
}

func (s *calibre_server_process) close() {
	s.stdin.Close()
	s.stdout.Close()
	// The request workers share the server's process group and can outlive it.
	unix.Kill(-s.proc.Process.Pid, unix.SIGKILL)
	<-s.reader_done
	s.proc.Wait()
}

var calibre_server = sync.OnceValues(func() (_ *calibre_server_process, err error) {
	defer func() { calibre_server_load_finished.Store(true) }()
	cmd := exec.Command("calibre-debug", "-c", calibre_server_program)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		stdout.Close()
		return nil, err
	}
	cmd.SysProcAttr = &unix.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("calibre-debug executable not found in PATH, you must install the calibre program to preview these file types: %w", err)
	}
	server := new_calibre_server_process(cmd, stdin, stdout)
	calibre_needs_cleanup.Store(true)
	defer func() {
		if err != nil {
			server.close()
		}
	}()
	data, err := server.request("", "", 2*time.Second)
	if err != nil {
		if errors.Is(err, os.ErrDeadlineExceeded) {
			return nil, fmt.Errorf("timed out waiting for response from calibre metadata server, make sure you are using calibre version >= 8.16")
		}
		return nil, err
	}
	r, err := unmarshal_calibre_response(data, "")
	if err != nil {
		return nil, fmt.Errorf("unexpected response from calibre metadata server: %w", err)
	}
	server.file_extensions = utils.NewSet[string](len(r.Filetypes))
	for _, ft := range r.Filetypes {
		server.file_extensions.Add("." + ft)
	}
	return server, nil
})

func calibre_cleanup() {
	if !calibre_needs_cleanup.Swap(false) {
		return
	}
	if calibre, err := calibre_server(); err == nil {
		calibre.close()
	}
}

func IsSupportedByCalibre(path string) bool {
	ext := strings.ToLower(filepath.Ext(filepath.Base(path)))
	if len(ext) > 1 {
		if calibre_server_load_finished.Load() {
			if calibre, err := calibre_server(); err == nil {
				return calibre.file_extensions.Has(ext)
			}
		} else {
			// we dont want to delay the render loop waiting for data from
			// calibre-server as it causes flicker because the atomic update
			// timeout expires, so use a default set of extensions.
			go func() { _, _ = calibre_server() }()
			return slices.Contains([]string{"cb7", "azw3", "kepub", "zip", "htmlz", "rar", "lrf", "cbr", "tpz", "azw1", "mobi", "lit", "pdf", "updb", "pml", "pobi", "fbz", "azw", "fb2", "cbc", "rtf", "snb", "opf", "txt", "epub", "oebzip", "txtz", "imp", "docx", "odt", "pdb", "rb", "prc", "html", "chm", "pmlz", "cbz", "lrx", "azw4"}, ext[1:])
		}
	}
	return false
}

const CALIBRE_METADATA_KEY = "calibre-metadata.json"

type calibre_renderer struct {
	path string
}

func unmarshal_calibre_response(data []byte, path string) (*CalibreResponse, error) {
	return unmarshal_calibre_response_for(data, path, func(p string) bool { return p == path })
}

func unmarshal_calibre_response_for(data []byte, path string, is_for_path func(string) bool) (*CalibreResponse, error) {
	var ans CalibreResponse
	if err := json.Unmarshal(data, &ans); err != nil {
		return nil, err
	}
	if !is_for_path(ans.Path) {
		return nil, fmt.Errorf("calibre metadata is for %q, expected %q", ans.Path, path)
	}
	if ans.Error != "" {
		return nil, errors.New(ans.Error)
	}
	return &ans, nil
}

// resolve_path resolves a path the same way the disk cache does when
// computing its key, so that paths sharing a cache entry compare equal.
func resolve_path(path string) (string, error) {
	path, err := filepath.EvalSymlinks(path)
	if err != nil {
		return "", err
	}
	return filepath.Abs(path)
}

// The book metadata depends only on the file contents, and Unmarshall already
// checks that cached metadata belongs to the selected book.
func (c calibre_renderer) CacheKeyExtra(string) string { return "" }

func (c calibre_renderer) Unmarshall(m map[string]string) (any, error) {
	data, err := os.ReadFile(m[CALIBRE_METADATA_KEY])
	if err != nil {
		return nil, err
	}
	// The disk cache key resolves symlinks, so the cached metadata may
	// have been generated for a different path to the same file.
	ans, err := unmarshal_calibre_response_for(data, c.path, func(cached_path string) bool {
		if cached_path == c.path {
			return true
		}
		a, err := resolve_path(cached_path)
		if err != nil {
			return false
		}
		b, err := resolve_path(c.path)
		return err == nil && a == b
	})
	if err != nil {
		return nil, err
	}
	return ans, nil
}

func (c calibre_renderer) Render(path string) (m map[string][]byte, mi metadata, img *images.ImageData, err error) {
	calibre, err := calibre_server()
	if err != nil {
		return
	}
	cover_dir, err := os.MkdirTemp("", "kitty-calibre-")
	if err != nil {
		return
	}
	// A worker finishing after the request times out cannot recreate this directory.
	defer os.RemoveAll(cover_dir)
	cover_path := filepath.Join(cover_dir, "cover")
	data, err := calibre.request(path, cover_path, 30*time.Second)
	if err != nil {
		return
	}
	reply, err := unmarshal_calibre_response(data, path)
	if err != nil {
		return
	}
	if reply.Cover == cover_path {
		var ip ImagePreviewRenderer
		if m, mi, img, err = ip.Render(cover_path); err != nil {
			return
		}
	} else {
		m = make(map[string][]byte)
	}
	mi.custom = reply
	m[CALIBRE_METADATA_KEY] = data
	return
}

func (c calibre_renderer) ShowMetadata(h *Handler, s ShowData) (offset int) {
	w := func(text string, center bool) {
		if s.height > offset {
			offset += h.render_wrapped_text_in_region(text, s.x, s.y+offset, s.width, s.height-offset, center)
		}
	}
	ext := filepath.Ext(s.abspath)
	text := fmt.Sprintf("%s: %s", ext, humanize.Bytes(uint64(s.metadata.Size())))
	icon := icons.IconForPath(s.abspath)
	w(icon+"  "+text, true)
	r := s.custom_metadata.custom.(*CalibreResponse)
	w("Title: "+r.Metadata.Title, false)
	w("Authors: "+strings.Join(r.Metadata.Authors, " & "), false)
	if r.Metadata.Series != "" {
		w(fmt.Sprintf("Series: Book %g of %s", r.Metadata.Series_index, r.Metadata.Series), false)
	}
	if len(r.Metadata.Tags) > 0 {
		w("Tags: "+strings.Join(r.Metadata.Tags, ", "), false)
	}
	return
}

func (c calibre_renderer) String() string {
	return "Calibre"
}

func NewCalibrePreview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool,
) Preview {
	c := calibre_renderer{path: abspath}
	if ans, err := NewImagePreview(abspath, metadata, opts, WakeupMainThread, c); err == nil {
		return ans
	} else {
		return NewErrorPreview(err)
	}
}
