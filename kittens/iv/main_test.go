package main

import (
	"encoding/base64"
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Testing for xyToIndex function
func TestXyToIndex(t *testing.T) {
	x, y, x_param := 1, 2, 3
	expected := 7
	if result := xyToIndex(x, y, x_param); result != expected {
		t.Errorf("xyToIndex(%d, %d, %d) = %d; want %d", x, y, x_param, result, expected)
	}
}

// Testing for indexToXY function
func TestIndexToXY(t *testing.T) {
	index, x_param := 7, 3
	expectedX, expectedY := 1, 2
	x, y := indexToXY(index, x_param)
	if x != expectedX || y != expectedY {
		t.Errorf("indexToXY(%d, %d) = (%d, %d); want (%d, %d)", index, x_param, x, y, expectedX, expectedY)
	}
}

// Testing for loadConfig function
func TestLoadConfig(t *testing.T) {
	configData := `
grid_param:
  x_param: 3
  y_param: 2
`
	tmpFile, err := os.CreateTemp("", "config*.yaml")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.Write([]byte(configData)); err != nil {
		t.Fatalf("Failed to write to temp file: %v", err)
	}
	if err := tmpFile.Close(); err != nil {
		t.Fatalf("Failed to close temp file: %v", err)
	}

	err = loadConfig(tmpFile.Name())
	if err != nil {
		t.Errorf("loadConfig() returned error: %v", err)
	}
	if globalConfig.GridParam.XParam != 3 || globalConfig.GridParam.YParam != 2 {
		t.Errorf("loadConfig() loaded unexpected values: %+v", globalConfig.GridParam)
	}
}

// Testing for isImage function
func TestIsImage(t *testing.T) {
	validImages := []string{"image.jpg", "photo.png", "pic.gif"}
	invalidImages := []string{"document.txt", "music.mp3", "video.mp4"}

	for _, fileName := range validImages {
		if !isImage(fileName) {
			t.Errorf("isImage(%q) = false; want true", fileName)
		}
	}

	for _, fileName := range invalidImages {
		if isImage(fileName) {
			t.Errorf("isImage(%q) = true; want false", fileName)
		}
	}
}

// Testing for discoverImages function
func TestDiscoverImages(t *testing.T) {
	testDir := t.TempDir()
	imgFile := filepath.Join(testDir, "image.jpg")
	os.WriteFile(imgFile, []byte{}, 0644)

	err := discoverImages(testDir)
	if err != nil {
		t.Errorf("discoverImages() returned error: %v", err)
	}
	if len(globalImages) != 1 || globalImages[0] != imgFile {
		t.Errorf("discoverImages() = %v; want [%v]", globalImages, imgFile)
	}
}

// Testing for resizeImage function
func TestResizeImage(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 100, 100))
	width, height := uint(50), uint(50)
	resized := resizeImage(img, width, height)
	if resized.Bounds().Dx() != int(width) || resized.Bounds().Dy() != int(height) {
		t.Errorf("resizeImage() = %v; want width %d and height %d", resized.Bounds(), width, height)
	}
}

// Testing for imageToBase64 function
func TestImageToBase64(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 1, 1))
	img.Set(0, 0, color.RGBA{255, 0, 0, 255})

	base64Str, err := imageToBase64(img)
	if err != nil {
		t.Errorf("imageToBase64() returned error: %v", err)
	}

	decoded, err := base64.StdEncoding.DecodeString(base64Str)
	if err != nil {
		t.Errorf("Failed to decode base64 string: %v", err)
	}

	decodedImg, err := png.Decode(strings.NewReader(string(decoded)))
	if err != nil {
		t.Errorf("Failed to decode image from base64 string: %v", err)
	}

	if decodedImg.Bounds() != img.Bounds() {
		t.Errorf("Decoded image bounds = %v; want %v", decodedImg.Bounds(), img.Bounds())
	}
}

// Testing for loadImage function
func TestLoadImage(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 1, 1))
	tmpFile, err := os.CreateTemp("", "image*.png")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	defer os.Remove(tmpFile.Name())

	if err := png.Encode(tmpFile, img); err != nil {
		t.Fatalf("Failed to encode image to temp file: %v", err)
	}
	if err := tmpFile.Close(); err != nil {
		t.Fatalf("Failed to close temp file: %v", err)
	}

	loadedImg, err := loadImage(tmpFile.Name())
	if err != nil {
		t.Errorf("loadImage() returned error: %v", err)
	}
	if loadedImg.Bounds() != img.Bounds() {
		t.Errorf("loadImage() = %v; want %v", loadedImg.Bounds(), img.Bounds())
	}
}

// Testing for getWindowSize function
func TestGetWindowSize(t *testing.T) {
	var window windowParameters
	err := getWindowSize(window)
	if err != nil {
		t.Errorf("getWindowSize() returned error: %v", err)
	}
}

// Testing for printImageToKitty function
func TestPrintImageToKitty(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 1, 1))
	img.Set(0, 0, color.RGBA{255, 0, 0, 255})

	base64Str, err := imageToBase64(img)
	if err != nil {
		t.Fatalf("Failed to convert image to base64: %v", err)
	}

	printImageToKitty(base64Str, 1, 1)
}

// Testing for pageCoordinater function
func TestPageCoordinater(t *testing.T) {
	globalConfig.GridParam.XParam = 2
	globalConfig.GridParam.YParam = 2
	globalWindowParameters.Row = 20
	globalWindowParameters.Col = 20
	globalImages = []string{"img1", "img2", "img3", "img4"}

	pageCoordinater()

	expectedCoordinates := map[string][2]int{
		"img1": {0, 0},
		"img2": {1, 0},
		"img3": {0, 1},
		"img4": {1, 1},
	}

	for img, coord := range expectedCoordinates {
		if globalImageCoordinates[img] != coord {
			t.Errorf("Coordinates for %s = %v; want %v", img, globalImageCoordinates[img], coord)
		}
	}
}

// Testing for paginateImages function
func TestPaginateImages(t *testing.T) {
	globalConfig.GridParam.XParam = 2
	globalConfig.GridParam.YParam = 2
	globalImages = []string{"img1", "img2", "img3", "img4", "img5"}

	paginateImages()

	expectedPages := [][]string{
		{"img1", "img2"},
		{"img3", "img4"},
	}

	if len(globalImagePages) != len(expectedPages) {
		t.Errorf("Number of pages = %d; want %d", len(globalImagePages), len(expectedPages))
	}

	for i, page := range expectedPages {
		for j, img := range page {
			if globalImagePages[i][j] != img {
				t.Errorf("Page %d, Image %d = %s; want %s", i, j, globalImagePages[i][j], img)
			}
		}
	}
}
