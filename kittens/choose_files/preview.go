package choose_files

import (
	"fmt"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/highlight"
	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type Preview interface {
	Render(h *Handler, x, y, width, height int)
	IsValidForColorScheme(light bool) bool
}

type PreviewManager struct {
	report_errors    chan error
	settings         Settings
	WakeupMainThread func() bool
	cache            map[string]Preview
	lock             sync.Mutex
	highlighter      highlight.Highlighter
}

func NewPreviewManager(err_chan chan error, settings Settings, WakeupMainThread func() bool) (ans *PreviewManager) {
	defer func() { sanitize = ans.highlighter.Sanitize }()
	return &PreviewManager{
		report_errors: err_chan, settings: settings, WakeupMainThread: WakeupMainThread,
		cache: make(map[string]Preview), highlighter: highlight.NewHighlighter(nil),
	}
}

func (pm *PreviewManager) cached_preview(path string) Preview {
	pm.lock.Lock()
	defer pm.lock.Unlock()
	return pm.cache[path]
}

func (pm *PreviewManager) set_cached_preview(path string, val Preview) {
	pm.lock.Lock()
	defer pm.lock.Unlock()
	pm.cache[path] = val
}

func (h *Handler) render_wrapped_text_in_region(text string, x, y, width, height int, centered bool) int {
	lines := style.WrapTextAsLines(text, width, style.WrapOptions{})
	for i, line := range lines {
		extra := 0
		if centered {
			extra = max(0, width-wcswidth.Stringwidth(line)) / 2
		}
		h.lp.MoveCursorTo(x+extra, y+i)
		h.lp.QueueWriteString(line)
		if i >= height {
			break
		}
	}
	return len(lines)
}

type MessagePreview struct {
	title    string
	msg      string
	trailers []string
}

func (p MessagePreview) IsValidForColorScheme(bool) bool { return true }

func (p MessagePreview) Render(h *Handler, x, y, width, height int) {
	offset := 0
	if p.title != "" {
		offset += h.render_wrapped_text_in_region(p.title, x, y, width, height, true)
	}
	offset += h.render_wrapped_text_in_region(p.msg, x, y+offset, width, height-offset, false)
	limit := height - offset
	if limit > 1 {
		for i, line := range p.trailers {
			text := wcswidth.TruncateToVisualLength(line, width-1)
			if len(text) < len(line) {
				text += "…"
			}
			h.lp.MoveCursorTo(x, y+offset+i-1)
			if i >= limit {
				h.lp.QueueWriteString("…")
				break
			}
			h.lp.QueueWriteString(text)
		}
	}
}

func NewErrorPreview(err error) Preview {
	sctx := style.Context{AllowEscapeCodes: true}
	text := fmt.Sprintf("%s: %s", sctx.SprintFunc("fg=red")("Error"), err)
	return &MessagePreview{msg: text}
}

var sanitize func(string) string

func write_file_metadata(abspath string, metadata fs.FileInfo, entries []fs.DirEntry) (header string, trailers []string) {
	buf := strings.Builder{}
	buf.Grow(4096)
	add := func(key, val string) { fmt.Fprintf(&buf, "%s: %s\n", key, val) }
	ftype := metadata.Mode().Type()
	const file_icon = " "
	switch ftype {
	case 0:
		add("Size", humanize.Bytes(uint64(metadata.Size())))
	case fs.ModeSymlink:
		if tgt, err := os.Readlink(abspath); err == nil {
			add("Target", sanitize(tgt))
		} else {
			add("Target", err.Error())
		}
	case fs.ModeDir:
		num_files, num_dirs := 0, 0
		for _, e := range entries {
			if e.IsDir() {
				num_dirs++
			} else {
				num_files++
			}
		}
		add("Children", fmt.Sprintf("%d %s  %d %s", num_dirs, icons.IconForFileWithMode("dir", fs.ModeDir, false), num_files, file_icon))
	}
	add("Modified", humanize.Time(metadata.ModTime()))
	add("Mode", metadata.Mode().String())
	if len(entries) > 0 {
		type entry struct {
			lname string
			ftype fs.FileMode
		}
		type_map := make(map[string]entry, len(entries))
		for _, e := range entries {
			type_map[e.Name()] = entry{strings.ToLower(e.Name()), e.Type()}
		}
		names := utils.Map(func(e fs.DirEntry) string { return e.Name() }, entries)
		slices.SortFunc(names, func(a, b string) int { return strings.Compare(type_map[a].lname, type_map[b].lname) })
		fmt.Fprintln(&buf, "Contents:")
		for _, n := range names {
			trailers = append(trailers, icons.IconForFileWithMode(n, type_map[n].ftype, false)+"  "+sanitize(n))
		}
	}
	return buf.String(), trailers
}

func NewDirectoryPreview(abspath string, metadata fs.FileInfo) Preview {
	entries, err := os.ReadDir(abspath)
	if err != nil {
		return NewErrorPreview(fmt.Errorf("failed to read the directory %s with error: %w", abspath, err))
	}
	title := icons.IconForFileWithMode("dir", fs.ModeDir, false) + "  Directory\n"
	header, extra := write_file_metadata(abspath, metadata, entries)
	return &MessagePreview{title: title, msg: header, trailers: extra}
}

func NewFileMetadataPreview(abspath string, metadata fs.FileInfo) Preview {
	title := icons.IconForFileWithMode(filepath.Base(abspath), metadata.Mode().Type(), false) + "  File"
	h, t := write_file_metadata(abspath, metadata, nil)
	return &MessagePreview{title: title, msg: h, trailers: t}
}

type highlighed_data struct {
	text  string
	light bool
	err   error
}

type TextFilePreview struct {
	plain_text, highlighted_text string
	highlighted_chan             chan highlighed_data
	light                        bool
	path                         string
}

func (p TextFilePreview) IsValidForColorScheme(light bool) bool { return p.light == light }

func (p *TextFilePreview) Render(h *Handler, x, y, width, height int) {
	if p.highlighted_chan != nil {
		select {
		case hd := <-p.highlighted_chan:
			p.highlighted_chan = nil
			if hd.err == nil {
				p.highlighted_text = hd.text
			}
		default:
		}
	}
	text := p.highlighted_text
	if text == "" {
		text = p.plain_text
	}
	s := utils.NewLineScanner(text)
	buf := strings.Builder{}
	buf.Grow(1024 * height)
	for num := 0; s.Scan() && num < height; num++ {
		line := s.Text()
		truncated := wcswidth.TruncateToVisualLength(line, width)
		buf.WriteString(fmt.Sprintf(loop.MoveCursorToTemplate, y+num, x))
		buf.WriteString(truncated)
		if len(truncated) < len(line) {
			wcswidth.KeepOnlyCSI(line[len(truncated):], &buf)
		}
	}
	buf.WriteString("\x1b[m") // reset any highlight styles
	h.lp.QueueWriteString(buf.String())
}

func NewTextFilePreview(abspath string, metadata fs.FileInfo, highlighted_chan chan highlighed_data, sanitize func(string) string) Preview {
	data, err := os.ReadFile(abspath)
	if err != nil {
		return NewFileMetadataPreview(abspath, metadata)
	}
	text := utils.UnsafeBytesToString(data)
	if !utf8.ValidString(text) {
		text = "Error: not valid utf-8 text"
	}
	return &TextFilePreview{path: abspath, plain_text: sanitize(text), highlighted_chan: highlighted_chan, light: use_light_colors}
}

type style_resolver struct {
	light                   bool
	light_style, dark_style string
	syntax_aliases          map[string]string
}

func (s style_resolver) StyleName() string {
	return utils.IfElse(s.light, s.light_style, s.dark_style)
}
func (s style_resolver) UseLightColors() bool             { return s.light }
func (s style_resolver) SyntaxAliases() map[string]string { return s.syntax_aliases }
func (s style_resolver) TextForPath(path string) (string, error) {
	ans, err := os.ReadFile(path)
	if err == nil {
		return utils.UnsafeBytesToString(ans), nil
	}
	return "", err
}

func (pm *PreviewManager) highlight_file_async(path string, output chan highlighed_data) {
	s := style_resolver{light: use_light_colors, syntax_aliases: pm.settings.SyntaxAliases()}
	s.light_style, s.dark_style = pm.settings.HighlightStyles()
	go func() {
		highlighted, err := pm.highlighter.HighlightFile(path, &s)
		if err != nil {
			debugprintln(fmt.Sprintf("Failed to highlight: %s with error: %s", path, err))
		}
		output <- highlighed_data{text: highlighted, err: err, light: s.light}
		close(output)
		pm.WakeupMainThread()
	}()
}

func (pm *PreviewManager) invalidate_color_scheme_based_cached_items() {
	pm.lock.Lock()
	defer pm.lock.Unlock()
	maps.DeleteFunc(pm.cache, func(key string, p Preview) bool { return !p.IsValidForColorScheme(use_light_colors) })
}

func (pm *PreviewManager) preview_for(abspath string, ftype fs.FileMode) (ans Preview) {
	if ans = pm.cached_preview(abspath); ans != nil {
		return ans
	}
	defer func() { pm.set_cached_preview(abspath, ans) }()
	s, err := os.Lstat(abspath)
	if err != nil {
		return NewErrorPreview(err)
	}
	if s.IsDir() {
		return NewDirectoryPreview(abspath, s)
	}
	if ftype&fs.ModeSymlink != 0 && ftype&SymlinkToDir != 0 {
		s, err = os.Stat(abspath)
		if err != nil {
			return NewErrorPreview(err)
		}
		return NewDirectoryPreview(abspath, s)
	}
	mt := utils.GuessMimeType(filepath.Base(abspath))
	const MAX_TEXT_FILE_SIZE = 16 * 1024 * 1024
	if s.Size() <= MAX_TEXT_FILE_SIZE && (utils.KnownTextualMimes[mt] || strings.HasPrefix(mt, "text/")) {
		ch := make(chan highlighed_data, 2)
		pm.highlight_file_async(abspath, ch)
		return NewTextFilePreview(abspath, s, ch, pm.highlighter.Sanitize)
	}
	return NewFileMetadataPreview(abspath, s)
}

func (h *Handler) draw_preview_content(x, y, width, height int) {
	matches, _ := h.get_results()
	r := matches.At(h.state.CurrentIndex())
	if r == nil {
		h.render_wrapped_text_in_region("No preview available", x, y, width, height, false)
		return
	}
	abspath := filepath.Join(h.state.CurrentDir(), r.text)
	if p := h.preview_manager.preview_for(abspath, r.ftype); p == nil {
		h.render_wrapped_text_in_region("No preview available", x, y, width, height, false)
	} else {
		p.Render(h, x, y, width, height)
	}
}
