// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"reflect"
	"testing"
)

var _ = fmt.Print

func TestRingBuffer(t *testing.T) {
	r := NewRingBuffer[int](8)

	test_contents := func(expected ...int) {
		actual := make([]int, len(expected))
		num_read := r.ReadTillEmpty(actual)
		if num_read != uint64(len(actual)) {
			t.Fatalf("Did not read expected num of items: %d != %d", num_read, len(expected))
		}
		if !reflect.DeepEqual(expected, actual) {
			t.Fatalf("Did not read expected items:\n%#v != %#v", actual, expected)
		}
		if r.Len() != 0 {
			t.Fatalf("Reading contents did not empty the buffer")
		}
	}
	r.WriteTillFull(1, 2, 3, 4)
	test_contents(1, 2, 3, 4)
	r.WriteTillFull(1, 2, 3, 4)
	test_contents(1, 2, 3, 4)

	r.Clear()
	r.WriteTillFull(1, 2, 3, 4)
	r.ReadTillEmpty([]int{0, 1})
	test_contents(3, 4)
	r.WriteTillFull(1, 2, 3, 4, 5)
	test_contents(1, 2, 3, 4, 5)

	r.Clear()
	r.WriteTillFull(1, 2, 3, 4)
	r.WriteAllAndDiscardOld(5, 6, 7, 8, 9)
	test_contents(2, 3, 4, 5, 6, 7, 8, 9)

}
