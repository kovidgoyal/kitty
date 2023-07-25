// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bytes"
	"compress/zlib"
	"crypto/rand"
	"fmt"
	"io"
	"testing"
)

var _ = fmt.Print

func TestStreamDecompressor(t *testing.T) {
	input := make([]byte, 9723)
	io.ReadFull(rand.Reader, input)
	b := bytes.Buffer{}
	w := zlib.NewWriter(&b)
	io.Copy(w, bytes.NewReader(input))
	w.Close()
	o := bytes.Buffer{}
	sd := NewStreamDecompressor(zlib.NewReader, &o)
	data := b.Bytes()
	for len(data) > 0 {
		chunk := data[:Min(117, len(data))]
		data = data[len(chunk):]
		if err := sd(chunk, len(data) == 0); err != nil {
			t.Fatal(err)
		}
	}
	if !bytes.Equal(o.Bytes(), input) {
		t.Fatalf("Roundtripping via zlib failed output (%d) != input (%d)", len(o.Bytes()), len(input))
	}

	o.Reset()
	sd = NewStreamDecompressor(zlib.NewReader, &o)
	err := sd([]byte("abcd"), true)
	if err == nil {
		t.Fatalf("Did not get an invalid header error from zlib")
	}

	o.Reset()
	sd = NewStreamDecompressor(zlib.NewReader, &o)
	err = sd(b.Bytes(), false)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(o.Bytes(), input) {
		t.Fatalf("Roundtripping via zlib failed output (%d) != input (%d)", len(o.Bytes()), len(input))
	}
	err = sd([]byte("extra trailing data"), true)
	if err == nil {
		t.Fatalf("Did not get an invalid header error from zlib")
	}
}
