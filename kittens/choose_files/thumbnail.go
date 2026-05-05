package choose_files

import (
	"image"
	"os"
	"strings"

	"github.com/kovidgoyal/imaging/magick"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"golang.org/x/sys/unix"
)

// ThumbnailForPath tries to generate a thumbnail image for the file at path.
// It uses the preview machinery from the choose-files kitten to handle video
// and e-book files. Returns nil if no thumbnail can be generated.
func ThumbnailForPath(path string) image.Image {
	mt := utils.GuessMimeType(path)
	if strings.HasPrefix(mt, "video/") {
		if img := thumbnail_via_ffmpeg(path); img != nil {
			return img
		}
	}
	if IsSupportedByCalibre(path) {
		if img := thumbnail_via_calibre(path); img != nil {
			return img
		}
	}
	return nil
}

func thumbnail_via_ffmpeg(path string) image.Image {
	tempfile, err := os.CreateTemp(magick.TempDirInRAMIfPossible(), "kitty-drag-thumbnail-*.webp")
	if err != nil {
		return nil
	}
	defer func() {
		_ = os.Remove(tempfile.Name())
		tempfile.Close()
	}()
	cmd := ffmpeg_thumbnail_cmd(path, tempfile.Name())
	cmd.Stdin = nil
	cmd.SysProcAttr = &unix.SysProcAttr{Setsid: true}
	if err := cmd.Run(); err != nil {
		return nil
	}
	img, err := images.OpenImageFromPath(tempfile.Name())
	if err != nil || len(img.Frames) == 0 {
		return nil
	}
	return img.Frames[0].Img
}

func thumbnail_via_calibre(path string) image.Image {
	c := calibre_renderer(0) // calibre_renderer is a zero-value int type used only for method dispatch
	_, _, img, err := c.Render(path)
	if err != nil || img == nil || len(img.Frames) == 0 {
		return nil
	}
	return img.Frames[0].Img
}
