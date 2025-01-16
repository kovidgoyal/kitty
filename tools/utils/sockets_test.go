// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"runtime"
	"testing"
)

func TestParseSocketAddress(t *testing.T) {
	en := "unix"
	ea := "/tmp/test"
	var eerr error = nil

	test := func(spec string) {
		n, a, err := ParseSocketAddress(spec)
		if err != eerr {
			if eerr == nil {
				t.Fatalf("Parsing of %s failed with unexpected error: %s", spec, err)
			}
			if err == nil {
				t.Fatalf("Parsing of %s did not fail, unexpectedly", spec)
			}
			return
		}
		if a != ea {
			t.Fatalf("actual != expected, %s != %s, when parsing %s", a, ea, spec)
		}
		if n != en {
			t.Fatalf("actual != expected, %s != %s, when parsing %s", n, en, spec)
		}
	}

	testf := func(spec string, netw string, addr string) {
		eerr = nil
		en = netw
		ea = addr
		test(spec)
	}
	teste := func(spec string, e string) {
		eerr = fmt.Errorf("%s", e)
		test(spec)
	}

	test("unix:/tmp/test")
	if runtime.GOOS == "linux" {
		ea = "@test"
	} else {
		eerr = fmt.Errorf("bad kitty")
	}
	test("unix:@test")
	testf("tcp:localhost:123", "tcp", "localhost:123")
	testf("tcp:1.1.1.1:123", "ip", "1.1.1.1:123")
	testf("tcp:fe80::1", "ip", "fe80::1")
	teste("xxx", "bad kitty")
	teste("xxx:yyy", "bad kitty")
	teste(":yyy", "bad kitty")
}
