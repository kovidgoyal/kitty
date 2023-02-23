// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bytes"
	"compress/bzip2"
	"encoding/binary"
	"fmt"
	"io"
)

var _ = fmt.Print

func ReadAll(r io.Reader, expected_size int) ([]byte, error) {
	b := make([]byte, 0, expected_size)
	for {
		if len(b) == cap(b) {
			// Add more capacity (let append pick how much).
			b = append(b, 0)[:len(b)]
		}
		n, err := r.Read(b[len(b):cap(b)])
		b = b[:len(b)+n]
		if err != nil {
			if err == io.EOF {
				err = nil
			}
			return b, err
		}
	}
}

func ReadCompressedEmbeddedData(raw string) []byte {
	compressed := UnsafeStringToBytes(raw)
	uncompressed_size := binary.LittleEndian.Uint32(compressed)
	r := bzip2.NewReader(bytes.NewReader(compressed[4:]))
	ans, err := ReadAll(r, int(uncompressed_size))
	if err != nil {
		panic(err)
	}
	return ans
}

func ReaderForCompressedEmbeddedData(raw string) io.Reader {
	return bzip2.NewReader(bytes.NewReader(UnsafeStringToBytes(raw)[4:]))
}
