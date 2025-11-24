package choose_files

import (
	"archive/tar"
	"compress/bzip2"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/klauspost/compress/gzip"
	"github.com/klauspost/compress/zip"
	"github.com/klauspost/compress/zstd"
	"github.com/ulikunitz/xz"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func IsSupportedArchiveFile(abspath string) bool {
	name := strings.ToLower(filepath.Base(abspath))
	ext := filepath.Ext(name)
	switch ext {
	case ".zip", ".tgz", ".tbz2", ".tzst", ".txz":
		return true
	case ".gz", ".bz2", ".zst", ".xz":
		name = name[:len(name)-len(ext)]
		ext = filepath.Ext(name)
		return ext == ".tar"
	default:
		return false
	}
}

type archive_preview struct {
	path             string
	metadata         fs.FileInfo
	WakeupMainThread func() bool
	ch               chan *MessagePreview
	mp               *MessagePreview
}

func displayFilename(s string) string {
	if isPrintableUTF8(s) {
		return s
	}
	return fmt.Sprintf("%X", utils.UnsafeStringToBytes(s))
}

func isPrintableUTF8(s string) bool {
	for _, r := range s {
		if r == '\uFFFD' { // replacement char
			return false
		}
	}
	return true
}

func (p *archive_preview) render() {
	name := strings.ToLower(filepath.Base(p.path))
	ext := filepath.Ext(name)
	names := []string{""}
	populate_tar := func(r io.Reader) {
		tr := tar.NewReader(r)
		for len(names) < 500 {
			hdr, err := tr.Next()
			if err != nil {
				break
			}
			names = append(names, displayFilename(hdr.Name))
		}
	}
	switch ext {
	case ".zip":
		r, err := zip.OpenReader(p.path)
		if err == nil || errors.Is(err, zip.ErrInsecurePath) {
			defer r.Close()
			for _, f := range r.File {
				if f.NonUTF8 {
					names = append(names, displayFilename(f.Name))
				} else {
					names = append(names, f.Name)
				}

			}
		}
	case ".gz", ".tgz":
		if f, err := os.Open(p.path); err == nil {
			defer f.Close()
			if gz, err := gzip.NewReader(f); err == nil {
				defer gz.Close()
				populate_tar(gz)
			}
		}
	case ".xz", ".txz":
		if f, err := os.Open(p.path); err == nil {
			defer f.Close()
			if gz, err := xz.NewReader(f); err == nil {
				populate_tar(gz)
			}
		}
	case ".bz2", ".tbz2":
		if f, err := os.Open(p.path); err == nil {
			defer f.Close()
			populate_tar(bzip2.NewReader(f))
		}
	case ".zst", ".tzst":
		if f, err := os.Open(p.path); err == nil {
			defer f.Close()
			if gz, err := zstd.NewReader(f); err == nil {
				defer gz.Close()
				populate_tar(gz)
			}
		}
	}
	mp := *p.mp
	mp.trailers = append(mp.trailers, names...)
	p.ch <- &mp
	p.WakeupMainThread()
}

func (p *archive_preview) IsReady() bool                         { return true }
func (p *archive_preview) Unload()                               {}
func (p *archive_preview) IsValidForColorScheme(light bool) bool { return true }
func (p *archive_preview) String() string                        { return fmt.Sprintf("ArchivePreview{%s}", p.path) }

func (p *archive_preview) Render(h *Handler, x, y, width, height int) {
	if p.ch != nil {
		select {
		case mp := <-p.ch:
			p.mp = mp
			close(p.ch)
			p.ch = nil
		default:
		}
	}
	p.mp.Render(h, x, y, width, height)
}

func NewArchivePeview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool,
) Preview {
	mp := NewFileMetadataPreview(abspath, metadata)
	ans := &archive_preview{
		path: abspath, metadata: metadata, WakeupMainThread: WakeupMainThread, ch: make(chan *MessagePreview, 1), mp: mp,
	}
	go ans.render()
	return ans
}
