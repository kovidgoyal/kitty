// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"fmt"
	"kitty/tools/utils"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestHintMarking(t *testing.T) {

	opts := &Options{Type: "url"}
	r := func(text string, url ...string) {
		ptext := convert_text(text, 20)
		marks, _, err := find_marks(ptext, opts)
		if err != nil {
			t.Fatalf("%#v failed with error: %s", text, err)
		}
		actual := utils.Map(func(m Mark) string { return m.Text }, marks)
		if diff := cmp.Diff(url, actual); diff != "" {
			t.Fatalf("%#v failed:\n%s", text, diff)
		}
	}

	u := `http://test.me/`
	r(u, u)
}
