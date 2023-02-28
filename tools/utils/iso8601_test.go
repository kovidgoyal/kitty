// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestISO8601(t *testing.T) {
	now := time.Now()

	tt := func(raw string, expected time.Time) {
		actual, err := ISO8601Parse(raw)
		if err != nil {
			t.Fatalf("Parsing: %#v failed with error: %s", raw, err)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Parsing: %#v failed:\n%s", raw, diff)
		}
	}

	tt(ISO8601Format(now), now)
	tt("2023-02-08T07:24:09.551975+00:00", time.Date(2023, 2, 8, 7, 24, 9, 551975000, time.UTC))
	tt("2023-02-08T07:24:09.551975Z", time.Date(2023, 2, 8, 7, 24, 9, 551975000, time.UTC))
	tt("2023", time.Date(2023, 1, 1, 0, 0, 0, 0, time.UTC))
	tt("2023-11-13", time.Date(2023, 11, 13, 0, 0, 0, 0, time.UTC))
	tt("2023-11-13 07:23", time.Date(2023, 11, 13, 7, 23, 0, 0, time.UTC))
	tt("2023-11-13 07:23:01", time.Date(2023, 11, 13, 7, 23, 1, 0, time.UTC))
	tt("2023-11-13 07:23:01.", time.Date(2023, 11, 13, 7, 23, 1, 0, time.UTC))
	tt("2023-11-13 07:23:01.0", time.Date(2023, 11, 13, 7, 23, 1, 0, time.UTC))
	tt("2023-11-13 07:23:01.1", time.Date(2023, 11, 13, 7, 23, 1, 100000000, time.UTC))
	tt("202311-13 07", time.Date(2023, 11, 13, 7, 0, 0, 0, time.UTC))
	tt("20231113 0705", time.Date(2023, 11, 13, 7, 5, 0, 0, time.UTC))
}
