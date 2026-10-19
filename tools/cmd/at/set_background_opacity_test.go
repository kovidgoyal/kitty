// License: GPLv3 Copyright: 2026, kitty contributors

package at

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/utils"
)

func TestSetBackgroundOpacityRejectsInvalidNumber(t *testing.T) {
	io_data := rc_io_data{rc: &utils.RemoteControlCmd{}}
	if err := create_payload_set_background_opacity(&io_data, nil, []string{"oops"}); err == nil {
		t.Fatalf("set-background-opacity accepted an invalid number: %#v", io_data.rc.Payload)
	}
}
