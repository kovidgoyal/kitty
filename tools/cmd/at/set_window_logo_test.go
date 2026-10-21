// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"image"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/utils"
)

// Truncate a JPEG immediately after its SOS segment header so that the
// header (and thus image.DecodeConfig) is valid but there is no image data.
func truncate_jpeg_before_scan_data(t *testing.T, data []byte) []byte {
	idx := bytes.Index(data, []byte{0xff, 0xda})
	if idx < 0 || idx+4 > len(data) {
		t.Fatal("Could not find SOS marker in JPEG data")
	}
	end := idx + 2 + int(binary.BigEndian.Uint16(data[idx+2:]))
	if end > len(data) {
		t.Fatal("Invalid SOS segment length in JPEG data")
	}
	return data[:end]
}

func TestReadRemoteImage(t *testing.T) {
	type payload struct{ Data string }
	src := image.NewRGBA(image.Rect(0, 0, 4, 4))
	var jpeg_data, png_data bytes.Buffer
	if err := jpeg.Encode(&jpeg_data, src, nil); err != nil {
		t.Fatal(err)
	}
	if err := png.Encode(&png_data, src); err != nil {
		t.Fatal(err)
	}
	truncated := truncate_jpeg_before_scan_data(t, jpeg_data.Bytes())
	if _, _, err := image.DecodeConfig(bytes.NewReader(truncated)); err != nil {
		t.Fatalf("Truncated JPEG does not have a valid header: %s", err)
	}
	tdir := t.TempDir()

	for _, tc := range []struct {
		name         string
		data         []byte
		expected_err string
	}{
		{"truncated_jpeg", truncated, "failed to decode"},
		{"not_an_image", []byte("not an image"), "not a supported image format"},
		{"jpeg", jpeg_data.Bytes(), ""},
		{"png", png_data.Bytes(), ""},
	} {
		path := filepath.Join(tdir, tc.name)
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
				io_data := rc_io_data{rc: &utils.RemoteControlCmd{Stream: true, Payload: payload{}}}
				next, err := reader.read(&io_data, path)
				if tc.expected_err != "" {
					if err == nil || next != nil {
						t.Fatalf("Expected an error and no image stream, got error: %v", err)
					}
					if !strings.Contains(err.Error(), tc.expected_err) || !strings.Contains(err.Error(), path) {
						t.Fatalf("Error message %q does not contain %q and the path", err, tc.expected_err)
					}
					return
				}
				if err != nil {
					t.Fatal(err)
				}
				var received []byte
				for done := false; !done; {
					if done, err = next(&io_data); err != nil {
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
				if tc.name == "png" && !bytes.Equal(received, tc.data) {
					t.Fatal("PNG data was not sent unmodified")
				}
			})
		}
	}
}
