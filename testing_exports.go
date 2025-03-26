//go:build testing

package kitty

import (
	_ "embed"
	"fmt"
)

var _ = fmt.Print

//go:embed kitty_tests/GraphemeBreakTest.json
var GraphemeBreakTestData []byte
