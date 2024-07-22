package images

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"image"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"kitty/tools/cli"
	"kitty/tools/utils"
)

var _ = fmt.Print

func convert_and_save_as_rgba_data(input_path, output_path string, perm os.FileMode) (err error) {
	f, err := os.Open(input_path)
	if err != nil {
		return err
	}
	defer f.Close()
	image_data, err := OpenNativeImageFromReader(f)
	if err != nil {
		return err
	}
	if len(image_data.Frames) == 0 {
		return fmt.Errorf("Image at %s has no frames", input_path)
	}
	img := image_data.Frames[0].Img
	var final_img *image.NRGBA
	switch img.(type) {
	case *image.NRGBA:
		final_img = img.(*image.NRGBA)
	default:
		b := img.Bounds()
		final_img = image.NewNRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
		ctx := Context{}
		ctx.PasteCenter(final_img, img, nil)
	}
	b := final_img.Bounds()
	header := make([]byte, 8)
	var width = utils.Abs(b.Dx())
	var height = utils.Abs(b.Dy())
	binary.LittleEndian.PutUint32(header, uint32(width))
	binary.LittleEndian.PutUint32(header[4:], uint32(height))
	readers := []io.Reader{bytes.NewReader(header)}
	stride := 4 * width

	if final_img.Stride == stride {
		readers = append(readers, bytes.NewReader(final_img.Pix))
	} else {
		p := final_img.Pix
		for y := 0; y < b.Dy(); y++ {
			readers = append(readers, bytes.NewReader(p[:min(stride, len(p))]))
			p = p[final_img.Stride:]
		}
	}
	return utils.AtomicUpdateFile(output_path, io.MultiReader(readers...), perm)
}

var now_implementation = time.Now
var chmtime_after_creation = false

func prune_cache(cdir string, max_entries int) error {
	entries, err := os.ReadDir(cdir)
	if err != nil {
		return err
	}
	if len(entries) <= max_entries {
		return nil
	}
	now := now_implementation()
	epoch := time.Unix(0, 0)
	entries = utils.SortWithKey(entries, func(a fs.DirEntry) time.Duration {
		if info, err := a.Info(); err == nil {
			return now.Sub(info.ModTime())
		}
		return now.Sub(epoch)
	})
	for _, x := range entries[max_entries:] {
		if err = os.Remove(filepath.Join(cdir, x.Name())); err != nil {
			return err
		}
	}
	return nil
}

func render_image(src_path, cdir string, max_cache_entries int) (output_path string, err error) {
	src_path, err = filepath.EvalSymlinks(src_path)
	if err != nil {
		return
	}
	lock_file := filepath.Join(cdir, "lock")
	lockf, err := os.OpenFile(lock_file, os.O_CREATE|os.O_RDWR, 0600)
	defer lockf.Close()
	if err != nil {
		return
	}
	if err = utils.LockFileExclusive(lockf); err != nil {
		return "", fmt.Errorf("Failed to lock cache file %s with error: %w", lock_file, err)
	}
	defer func() {
		utils.UnlockFile(lockf)
	}()
	output_path = filepath.Join(cdir, hex.EncodeToString(sha256.New().Sum([]byte(src_path)))) + ".rgba"
	needs_update := true
	input_info, err := os.Stat(src_path)
	if err != nil {
		return
	}
	output_info, err := os.Stat(output_path)
	if err == nil {
		needs_update = input_info.Size() != output_info.Size() || input_info.ModTime().After(output_info.ModTime())
	} else {
		if !errors.Is(err, fs.ErrNotExist) {
			return
		}
	}
	if needs_update {
		if err = convert_and_save_as_rgba_data(src_path, output_path, 0600); err != nil {
			return
		}
		if chmtime_after_creation {
			n := now_implementation()
			if err = os.Chtimes(output_path, n, n); err != nil {
				return
			}
		}
		if err = prune_cache(cdir, max_cache_entries); err != nil {
			return
		}
	} else {
		n := now_implementation()
		if err = os.Chtimes(output_path, n, n); err != nil {
			return
		}
	}
	return
}

func RenderEntryPoint(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "__render_image__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			if len(args) != 1 {
				return 1, fmt.Errorf("Usage: render input_image_path")
			}
			src_path, err := filepath.EvalSymlinks(args[0])
			if err != nil {
				return 1, err
			}
			cdir := utils.CacheDir()
			cdir = filepath.Join(cdir, "rgba")
			if err = os.MkdirAll(cdir, 0755); err != nil {
				return 1, err
			}
			if output_path, err := render_image(src_path, cdir, 32); err != nil {
				return 1, err
			} else {
				fmt.Println(output_path)
			}
			return
		},
	})
}
