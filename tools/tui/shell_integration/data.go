// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shell_integration

import (
	"archive/tar"
	_ "embed"
	"errors"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"io"
	"regexp"
	"strings"
	"sync"
)

var _ = fmt.Print

//go:embed data_generated.bin
var embedded_data string

type Entry struct {
	Metadata *tar.Header
	Data     []byte
}

type Container map[string]Entry

var Data = sync.OnceValue(func() Container {
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
})

func (self Container) FilesMatching(prefix string, exclude_patterns ...string) []string {
	ans := make([]string, 0, len(self))
	patterns := make([]*regexp.Regexp, len(exclude_patterns))
	for i, exp := range exclude_patterns {
		patterns[i] = regexp.MustCompile(exp)
	}
	for name := range self {
		if strings.HasPrefix(name, prefix) {
			excluded := false
			for _, pat := range patterns {
				if matched := pat.FindString(name); matched != "" {
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
