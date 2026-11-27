// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/zeebo/xxh3"
)

var _ = fmt.Print

// ErrNoRasterizer is returned when an icon needs to be converted to PNG but
// no program capable of doing so is installed
var ErrNoRasterizer = errors.New("neither rsvg-convert nor ImageMagick is installed, cannot render SVG and XPM icons")

const icon_render_timeout = 10 * time.Second

// Rendered icons that have not been used for this long are deleted
const icon_cache_max_age = 90 * 24 * time.Hour

// IconRenderer converts icons to PNG files suitable for display with the kitty
// graphics protocol, caching the results on disk.
type IconRenderer struct {
	cache_dir string
	// The external programs used for rendering, empty if not available
	rsvg_convert, magick string
	prune_once           sync.Once
}

func IconCacheDir() string {
	return filepath.Join(utils.CacheDir(), "choose-app", "icons")
}

func NewIconRenderer(cache_dir string) *IconRenderer {
	ans := &IconRenderer{cache_dir: cache_dir, rsvg_convert: utils.FindExe("rsvg-convert")}
	if ans.magick = utils.FindExe("magick"); ans.magick == "" {
		// ImageMagick 6
		ans.magick = utils.FindExe("convert")
	}
	return ans
}

func (r *IconRenderer) cache_key(src string, st fs.FileInfo, px int) string {
	key := strings.Join([]string{src, strconv.FormatInt(st.ModTime().UnixNano(), 10), strconv.FormatInt(st.Size(), 10), strconv.Itoa(px)}, "\x00")
	return fmt.Sprintf("%016x", xxh3.HashString(key))
}

// prune deletes rendered icons that have not been used for a long time
func (r *IconRenderer) prune() {
	entries, err := os.ReadDir(r.cache_dir)
	if err != nil {
		return
	}
	cutoff := time.Now().Add(-icon_cache_max_age)
	for _, e := range entries {
		if info, err := e.Info(); err == nil && info.Mode().IsRegular() && info.ModTime().Before(cutoff) {
			_ = os.Remove(filepath.Join(r.cache_dir, e.Name()))
		}
	}
}

// mark_used updates the modification time of cached files so they are not
// pruned, doing so only rarely to avoid unnecessary writes
func mark_used(path string, st fs.FileInfo) {
	if now := time.Now(); now.Sub(st.ModTime()) > 7*24*time.Hour {
		_ = os.Chtimes(path, now, now)
	}
}

func (r *IconRenderer) run(ctx context.Context, output_path string, cmd *exec.Cmd) (err error) {
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if cmd.Stdout == nil {
		cmd.Stdout = &stderr
	}
	if err = cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return fmt.Errorf("%s timed out", cmd.Path)
		}
		return fmt.Errorf("%s failed with error: %w and output: %s", cmd.Path, err, strings.TrimSpace(stderr.String()))
	}
	if s, serr := os.Stat(output_path); serr != nil || s.Size() == 0 {
		return fmt.Errorf("%s produced no output", cmd.Path)
	}
	return nil
}

func (r *IconRenderer) render(src, output_path string, px int) (err error) {
	ext := strings.ToLower(filepath.Ext(src))
	size := strconv.Itoa(px)
	ctx, cancel := context.WithTimeout(context.Background(), icon_render_timeout)
	defer cancel()
	var errs []error
	if r.rsvg_convert != "" && (ext == ".svg" || ext == ".svgz") {
		f, ferr := os.Create(output_path)
		if ferr != nil {
			return ferr
		}
		cmd := exec.CommandContext(ctx, r.rsvg_convert, "--width", size, "--height", size, "--keep-aspect-ratio", "--format", "png", src)
		cmd.Stdout = f
		err = r.run(ctx, output_path, cmd)
		if cerr := f.Close(); err == nil {
			err = cerr
		}
		if err == nil {
			return nil
		}
		errs = append(errs, err)
	}
	if r.magick != "" {
		density := strconv.Itoa(max(96, px*4))
		cmd := exec.CommandContext(ctx, r.magick, "-background", "none", "-density", density, src, "-resize", size+"x"+size, "png32:"+output_path)
		if err = r.run(ctx, output_path, cmd); err == nil {
			return nil
		}
		errs = append(errs, err)
	}
	if len(errs) == 0 {
		return ErrNoRasterizer
	}
	return errors.Join(errs...)
}

// Render returns the path to a PNG file for the icon at src rendered at the
// specified size in pixels. PNG icons are returned as is, since the terminal
// scales them. Other formats are converted and cached. Failures are cached as
// well, so that broken icons are not repeatedly converted.
func (r *IconRenderer) Render(src string, px int) (string, error) {
	if strings.EqualFold(filepath.Ext(src), ".png") {
		return src, nil
	}
	if r.rsvg_convert == "" && r.magick == "" {
		return "", ErrNoRasterizer
	}
	st, err := os.Stat(src)
	if err != nil {
		return "", err
	}
	if err = os.MkdirAll(r.cache_dir, 0o755); err != nil {
		return "", fmt.Errorf("failed to create the icon cache directory with error: %w", err)
	}
	r.prune_once.Do(func() { go r.prune() })
	key := r.cache_key(src, st, px)
	output_path := filepath.Join(r.cache_dir, key+".png")
	failure_path := filepath.Join(r.cache_dir, key+".failed")
	if s, err := os.Stat(output_path); err == nil {
		mark_used(output_path, s)
		return output_path, nil
	}
	if s, err := os.Stat(failure_path); err == nil {
		mark_used(failure_path, s)
		msg, _ := os.ReadFile(failure_path)
		return "", fmt.Errorf("rendering of %s failed previously with error: %s", src, msg)
	}
	tf, err := os.CreateTemp(r.cache_dir, key+"-*.png.tmp")
	if err != nil {
		return "", err
	}
	tpath := tf.Name()
	tf.Close()
	defer func() { _ = os.Remove(tpath) }()
	if err = r.render(src, tpath, px); err != nil {
		if !errors.Is(err, ErrNoRasterizer) {
			_ = utils.AtomicWriteFile(failure_path, strings.NewReader(err.Error()), 0o644)
		}
		return "", err
	}
	if err = os.Rename(tpath, output_path); err != nil {
		return "", err
	}
	return output_path, nil
}
