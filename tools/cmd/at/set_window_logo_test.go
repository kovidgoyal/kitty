// License: GPLv3 Copyright: 2026, kitty contributors

package at

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"testing"

	"github.com/kovidgoyal/kitty/tools/utils"
)

func TestReadRemoteImage(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 4, 4))
	var jpeg_data, png_data bytes.Buffer
	if err := jpeg.Encode(&jpeg_data, src, nil); err != nil {
		t.Fatal(err)
	}
	if err := png.Encode(&png_data, src); err != nil {
		t.Fatal(err)
	}
	// Keep a readable JPEG header but truncate the image data so decoding fails.
	var truncated []byte
	for n := 1; n < jpeg_data.Len(); n++ {
		data := jpeg_data.Bytes()[:n]
		if _, _, err := image.DecodeConfig(bytes.NewReader(data)); err == nil {
			if _, _, err := image.Decode(bytes.NewReader(data)); err != nil {
				truncated = data
				break
			}
		}
	}
	if truncated == nil {
		t.Fatal("Could not construct a JPEG with a valid header and truncated image data")
	}
	for _, tc := range []struct {
		name    string
		data    []byte
		invalid bool
	}{
		{"truncated_jpeg", truncated, true},
		{"jpeg", jpeg_data.Bytes(), false},
		{"png", png_data.Bytes(), false},
	} {
		path := filepath.Join(t.TempDir(), tc.name)
		if err := os.WriteFile(path, tc.data, 0o600); err != nil {
			t.Fatal(err)
		}
		for _, reader := range []struct {
			name string
			read func(*rc_io_data, string) (func(*rc_io_data) (bool, error), error)
		}{
			{"window_logo", read_window_logo},
			{"background_image", read_background_image},
		} {
			t.Run(reader.name+"/"+tc.name, func(t *testing.T) {
				type payload struct{ Data string }
				io_data := rc_io_data{rc: &utils.RemoteControlCmd{Stream: true, Payload: payload{}}}
				next, err := reader.read(&io_data, path)
				if tc.invalid {
					if err == nil || next != nil {
						t.Fatalf("Expected a decoding error and no image stream, got %v", err)
					}
					return
				}
				if err != nil {
					t.Fatal(err)
				}
				var received []byte
				for done := false; !done; {
					done, err = next(&io_data)
					if err != nil {
						t.Fatal(err)
					}
					chunk, err := base64.StdEncoding.DecodeString(io_data.rc.Payload.(payload).Data)
					if err != nil {
						t.Fatal(err)
					}
					received = append(received, chunk...)
				}
				img, format, err := image.Decode(bytes.NewReader(received))
				if err != nil {
					t.Fatal(err)
				}
				if format != "png" || img.Bounds() != src.Bounds() {
					t.Fatalf("Incorrect image stream: format=%s, bounds=%v", format, img.Bounds())
				}
			})
		}
	}
}
