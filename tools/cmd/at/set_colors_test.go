// License: GPLv3 Copyright: 2026, kitty contributors

package at

import (
	"fmt"
	"path/filepath"
	"testing"

	"github.com/kovidgoyal/kitty/tools/utils"
)

func TestSetColorsResetIgnoresArguments(t *testing.T) {
	original_reset := options_set_colors.Reset
	t.Cleanup(func() { options_set_colors.Reset = original_reset })
	missing_file := filepath.Join(t.TempDir(), "missing.conf")
	for _, reset := range []bool{false, true} {
		for _, test := range []struct {
			name, arg string
			invalid   bool
		}{
			{"invalid-color", "foreground=not-a-color", true},
			{"missing-file", missing_file, true},
			{"valid-color", "foreground=red", false},
		} {
			t.Run(fmt.Sprintf("%s/reset=%t", test.name, reset), func(t *testing.T) {
				options_set_colors.Reset = reset
				io_data := rc_io_data{rc: &utils.RemoteControlCmd{}}
				err := create_payload_set_colors(&io_data, nil, []string{test.arg})
				want_error := test.invalid && !reset
				if (err != nil) != want_error {
					t.Fatalf("expected error=%t, got: %v", want_error, err)
				}
				if err != nil {
					return
				}
				payload := io_data.rc.Payload.(set_colors_json_type)
				if payload.Reset != reset {
					t.Fatalf("expected reset=%t, got: %#v", reset, payload)
				}
				if reset {
					if len(payload.Colors) != 0 {
						t.Fatalf("--reset did not ignore color arguments: %#v", payload.Colors)
					}
				} else if payload.Colors["foreground"] != uint32(0xff0000) {
					t.Fatalf("foreground was not parsed: %#v", payload.Colors)
				}
			})
		}
	}
}
