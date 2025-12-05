package choose_files

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

const CMD_METADATA_KEY = "cmd-metadata.json"

type cmd_renderer struct {
	cmdline []string
}

func (c cmd_renderer) String() string {
	return c.cmdline[0]
}

type CmdResult struct {
	Lines      []string `json:"lines"`
	Image      string   `json:"image"`
	TitleExtra string   `json:"title_extra"`
}

func (c cmd_renderer) Render(path string) (m map[string][]byte, mi metadata, img *images.ImageData, err error) {
	cmdline := append(c.cmdline, path)
	cmd := exec.Command(cmdline[0], cmdline[1:]...)
	cmd.Stdin = nil
	cmd.SysProcAttr = &unix.SysProcAttr{Setsid: true}
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err = cmd.Run(); err != nil {
		err = fmt.Errorf("failed to run %v to read metadata from %s with error: %w and stderr: %s", c.cmdline, path, err, stderr.String())
		return
	}
	var md CmdResult
	if err = json.Unmarshal(stdout.Bytes(), &md); err != nil {
		err = fmt.Errorf("could not decode JSON response from %v for %s: %w", c.cmdline, path, err)
	}
	if md.Image != "" {
		var ip ImagePreviewRenderer
		if m, mi, img, err = ip.Render(md.Image); err != nil {
			return
		}
	}
	mi.custom = &md
	return
}

func (c cmd_renderer) Unmarshall(m map[string]string) (any, error) {
	data, err := os.ReadFile(m[CMD_METADATA_KEY])
	if err != nil {
		return nil, err
	}
	var ans CmdResult
	if err = json.Unmarshal(data, &ans); err != nil {
		return nil, err
	}
	return &ans, nil
}

func (c cmd_renderer) ShowMetadata(h *Handler, s ShowData) (offset int) {
	w := func(text string, center bool) {
		if s.height > offset {
			offset += h.render_wrapped_text_in_region(text, s.x, s.y+offset, s.width, s.height-offset, center)
		}
	}
	ext := filepath.Ext(s.abspath)
	r := s.custom_metadata.custom.(*CmdResult)
	text := fmt.Sprintf("%s: %s%s", ext, humanize.Bytes(uint64(s.metadata.Size())), r.TitleExtra)
	icon := icons.IconForPath(s.abspath)
	w(icon+"  "+text, true)
	for _, line := range r.Lines {
		w(line, false)
	}
	h.lp.QueueWriteString("\x1b[m") // reset SGR attributes
	return
}

func NewCmdPreview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool, p previewer,
) Preview {
	c := cmd_renderer{p.cmdline}
	if ans, err := NewImagePreview(abspath, metadata, opts, WakeupMainThread, c); err == nil {
		return ans
	} else {
		return NewErrorPreview(err)
	}
}
