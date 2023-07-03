// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package rsync

import (
	"bytes"
	"fmt"
	"kitty/tools/utils"
	"kitty/tools/utils/random"
	"testing"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

func TestRsyncRoundtrip(t *testing.T) {
	src_data := make([]byte, 4*1024*1024)
	random.Bytes(src_data)

	random_patch := func(data []byte) (size int) {
		if offset := random.Int(len(data)); offset < len(data) {
			max_size := utils.Min(256, len(data)-offset)
			if size = random.Int(max_size); size > 0 {
				random.Bytes(data[offset : offset+size])
			}
		}
		return
	}

	changed := slices.Clone(src_data)
	for i := 0; i < 8; i++ {
		random_patch(changed)
	}

	p := NewPatcher(int64(len(src_data)))
	sigbuf := bytes.Buffer{}
	if err := p.CreateSignature(bytes.NewReader(changed), func(p []byte) error { _, err := sigbuf.Write(p); return err }); err != nil {
		t.Fatal(err)
	}
	d := NewDiffer()
	if err := d.AddSignatureData(sigbuf.Bytes()); err != nil {
		t.Fatal(err)
	}
	deltabuf := bytes.Buffer{}
	if err := d.CreateDelta(bytes.NewReader(src_data), func(b []byte) error { _, err := deltabuf.Write(b); return err }); err != nil {
		t.Fatal(err)
	}
	outputbuf := bytes.Buffer{}
	p.StartDelta(&outputbuf, bytes.NewReader(src_data))
	b := make([]byte, 30*1024)
	for {
		n, _ := deltabuf.Read(b)
		if n <= 0 {
			break
		}
		if err := p.UpdateDelta(b[:n]); err != nil {
			t.Fatal(err)
		}
	}
	if err := p.FinishDelta(); err != nil {
		t.Fatal(err)
	}

	output := outputbuf.Bytes()
	if !bytes.Equal(src_data, output) {
		first_diff := utils.Min(len(src_data), len(output))
		for i := 0; i < first_diff; i++ {
			if src_data[i] != output[i] {
				first_diff = i
				break
			}
		}
		t.Fatalf("Patching failed: %d extra_bytes first different byte at: %d", len(outputbuf.Bytes())-len(src_data), first_diff)
	}

}
