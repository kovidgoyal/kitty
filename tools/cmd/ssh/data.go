// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"archive/tar"
	_ "embed"
	"errors"
	"fmt"
	"io"
	"kitty/tools/utils"
	"path/filepath"
)

var _ = fmt.Print

//go:embed data_generated.bin
var embedded_data string

type Entry struct {
	metadata *tar.Header
	data     []byte
}

type Container map[string]Entry

var Data = (&utils.Once[Container]{Run: func() Container {
	tr := tar.NewReader(utils.ReaderForCompressedEmbeddedData(embedded_data))
	ans := make(Container, 64)
	for {
		hdr, err := tr.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			panic(err)
		}
		data, err := utils.ReadAll(tr, int(hdr.Size))
		if err != nil {
			panic(err)
		}
		ans[hdr.Name] = Entry{hdr, data}
	}
	return ans
}}).Get

func (self Container) files_matching(include_pattern string, exclude_patterns ...string) []string {
	ans := make([]string, 0, len(self))
	for name := range self {
		if matched, err := filepath.Match(include_pattern, name); matched && err == nil {
			excluded := false
			for _, pat := range exclude_patterns {
				if matched, err := filepath.Match(pat, name); matched && err == nil {
					excluded = true
					break
				}
			}
			if !excluded {
				ans = append(ans, name)
			}
		}
	}
	return ans
}
