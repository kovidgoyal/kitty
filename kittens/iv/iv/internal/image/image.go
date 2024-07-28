package image

import (
	"encoding/base64"
	"fmt"
	"image"
	"image/png"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/nfnt/resize"
)

var GlobalImages []string
var GlobalImagePages [][]string

func DiscoverImages(dir string) error {
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && isImage(d.Name()) {
			GlobalImages = append(GlobalImages, path)
		}
		return nil
	})
	if err != nil {
		return fmt.Errorf("error walking directory: %w", err)
	}
	return nil
}

func isImage(fileName string) bool {
	extensions := []string{".jpg", ".jpeg", ".png", ".gif", ".bmp"}
	ext := strings.ToLower(filepath.Ext(fileName))
	for _, e := range extensions {
		if ext == e {
			return true
		}
	}
	return false
}

func ResizeImage(img image.Image, width, height uint) image.Image {
	return resize.Resize(width, height, img, resize.Lanczos3)
}

func ImageToBase64(img image.Image) (string, error) {
	var buf strings.Builder
	err := png.Encode(&buf, img)
	if err != nil {
		return "", err
	}
	encoded := base64.StdEncoding.EncodeToString([]byte(buf.String()))
	return encoded, nil
}

func LoadImage(filePath string) (image.Image, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	img, _, err := image.Decode(file)
	if err != nil {
		return nil, err
	}
	return img, nil
}

func PrintImageToKitty(encoded string, width, height int) {
	fmt.Printf("\x1b_Gf=1,t=%d,%d;x=%s\x1b\\", width, height, encoded)
}

func PaginateImages(xParam, yParam int) {
	for i := 0; i < len(GlobalImages); i += xParam {
		end := i + xParam
		if end > len(GlobalImages) {
			end = len(GlobalImages)
		}

		row := GlobalImages[i:end]
		GlobalImagePages = append(GlobalImagePages, row)

		if len(GlobalImagePages) == yParam {
			break
		}
	}
}
