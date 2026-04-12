//go:build !darwin

package machine_id

import (
	"fmt"
	"os"
	"strings"
	"unicode"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func read_machine_id() (string, error) {
	if data, err := os.ReadFile("/etc/machine-id"); err == nil {
		ans := utils.UnsafeBytesToString(data)
		return strings.TrimRightFunc(ans, unicode.IsSpace), nil
	} else {
		return "", err
	}
}
