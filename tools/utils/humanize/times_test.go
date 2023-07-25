// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package humanize

import (
	"fmt"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestShortDuration(t *testing.T) {
	q := func(i float64, e string) {
		d := time.Duration(i * float64(time.Second))
		if diff := cmp.Diff(e, ShortDuration(d)); diff != "" {
			t.Fatalf("Failed for %f (%s): %s", i, d, diff)
		}
	}
	q(0.1, "  <1 sec")
	q(1, `00:00:01`)
	q(1.1234567, `00:00:01`)
	q(60.1234567, `00:01:00`)
	q(61.1234567, `00:01:01`)
	q(3600, `01:00:00`)
	q(3601.1234567, `01:00:01`)
	day := 24. * 3600.
	q(day, "24:00:00")
	q(day+1, "  >1 day")
	q(day*2, " >2 days")
	q(day*23, ">23 days")
	q(day*999, "       ∞")
}
