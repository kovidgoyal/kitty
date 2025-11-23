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

func ReadLineWithTimeout(r io.Reader, timeout time.Duration) (string, error) {
	type result struct {
		line string
		err  error
	}
	ch := make(chan result, 1)

	go func() {
		br := bufio.NewReader(r)
		line, err := br.ReadString('\n')
		ch <- result{strings.TrimRight(line, "\n"), err}
	}()

	select {
	case res := <-ch:
		return res.line, res.err
	case <-time.After(timeout):
		return "", os.ErrDeadlineExceeded
	}
}

var calibre_server = sync.OnceValues(func() (ans *calibre_server_process, err error) {
	defer func() { calibre_server_load_finished.Store(true) }()
	ans = &calibre_server_process{}
	ans.proc = exec.Command("calibre-debug", "-c", "from calibre.ebooks.metadata.cli import *; simple_metadata_server()")
	ans.proc.Stderr = nil
	if ans.stdout, err = ans.proc.StdoutPipe(); err != nil {
		return nil, err
	}
	if ans.stdin, err = ans.proc.StdinPipe(); err != nil {
		ans.stdout.Close()
		return nil, err
	}
	ans.proc.SysProcAttr = &unix.SysProcAttr{Setsid: true}
	if err = ans.proc.Start(); err != nil {
		err = fmt.Errorf("calibre-debug executable not found in PATH, you must install the calibre program to preview these file types: %w", err)
		return
	}
	calibre_needs_cleanup.Store(true)
	payload, _ := json.Marshal(map[string]string{"path": ""})
	if _, err = ans.stdin.Write(append(payload, '\n')); err != nil {
		err = fmt.Errorf("error writing to calibre metadata server: %w", err)
		return
	}
	line, err := ReadLineWithTimeout(ans.stdout, 2*time.Second)
	if err != nil {
		if errors.Is(err, os.ErrDeadlineExceeded) {
			err = fmt.Errorf("timed out waiting for response from calibre metadata server, make sure you are using calibre version >= 8.16")
		} else {
			err = fmt.Errorf("error reading from calibre metadata server: %w", err)
		}
		return
	}
	var r CalibreResponse
	if err = json.Unmarshal([]byte(line), &r); err != nil {
		err = fmt.Errorf("unexpected response from calibre metadata server: %#v", line)
		return
	}
	ans.file_extensions = utils.NewSet[string](len(r.Filetypes))
	for _, ft := range r.Filetypes {
		ans.file_extensions.Add("." + ft)
	}
	return
})

func calibre_cleanup() {
	if !calibre_needs_cleanup.Load() {
		return
	}
	calibre_needs_cleanup.Store(false)
	calibre, _ := calibre_server()
	if calibre.stdin != nil {
		calibre.stdin.Close()
	}
	if calibre.stdout != nil {
		calibre.stdout.Close()
	}
	if calibre.proc != nil {
		calibre.proc.Wait()
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

type calibre_renderer int

func (c calibre_renderer) Unmarshall(m map[string]string) (any, error) {
	data, err := os.ReadFile(m[CALIBRE_METADATA_KEY])
	if err != nil {
		return nil, err
	}
	var ans CalibreResponse
	if err = json.Unmarshal(data, &ans); err != nil {
		return nil, err
	}
	return &ans, nil
}

func (c calibre_renderer) Render(path string) (m map[string][]byte, mi metadata, img *images.ImageData, err error) {
	cpath, err := os.CreateTemp("", "")
	if err != nil {
		return
	}
	defer func() {
		cpath.Close()
		os.Remove(cpath.Name())
	}()
	calibre, err := calibre_server()
	if err != nil {
		return
	}
	payload, err := json.Marshal(map[string]string{"path": path, "cover": cpath.Name()})
	if err != nil {
		return
	}
	calibre.stdin.Write(append(payload, '\n'))
	line, err := ReadLineWithTimeout(calibre.stdout, 30*time.Second)
	if err != nil {
		return
	}
	lb := []byte(line)
	var reply CalibreResponse
	if err = json.Unmarshal(lb, &reply); err != nil {
		return
	}
	if reply.Cover == cpath.Name() {
		var ip ImagePreviewRenderer
		if m, mi, img, err = ip.Render(cpath.Name()); err != nil {
			return
		}
	} else {
		m = make(map[string][]byte)
	}
	mi.custom = &reply
	m[CALIBRE_METADATA_KEY] = lb
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
		w("Tags: "+strings.Join(r.Metadata.Authors, ", "), false)
	}
	return
}

func (c calibre_renderer) String() string {
	return "Calibre"
}

func NewCalibrePreview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool,
) Preview {
	c := calibre_renderer(0)
	if ans, err := NewImagePreview(abspath, metadata, opts, WakeupMainThread, c); err == nil {
		return ans
	} else {
		return NewErrorPreview(err)
	}
}
