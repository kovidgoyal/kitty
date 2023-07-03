// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package rsync

import (
	"bytes"
	"fmt"
	"kitty/tools/utils"
	"kitty/tools/utils/random"
	"testing"

	"github.com/google/go-cmp/cmp"
	"golang.org/x/exp/slices"
)

var _ = fmt.Print
var _ = cmp.Diff

func run_roundtrip_test(t *testing.T, src_data, changed []byte, num_of_patches, total_patch_size int) {
	using_serialization := false
	prefix_msg := func() string {
		q := utils.IfElse(using_serialization, "with", "without")
		return fmt.Sprintf("Running %s serialization: src size: %d changed size: %d difference: %d\n", q, len(src_data), len(changed), len(changed)-len(src_data))
	}

	test_equal := func(src_data, output []byte) {
		if !bytes.Equal(src_data, output) {
			first_diff := utils.Min(len(src_data), len(output))
			for i := 0; i < first_diff; i++ {
				if src_data[i] != output[i] {
					first_diff = i
					break
				}
			}
			t.Fatalf("%sPatching failed: %d extra_bytes first different byte at: %d", prefix_msg(), len(output)-len(src_data), first_diff)
		}
	}

	// first try just the engine without serialization
	p := NewPatcher(int64(len(src_data)))
	signature := make([]BlockHash, 0, 128)
	p.rsync.CreateSignature(bytes.NewReader(changed), func(s BlockHash) error {
		signature = append(signature, s)
		return nil
	})

	total_data_in_delta := 0
	apply_delta := func(signature []BlockHash) []byte {
		delta_ops := make([]Operation, 0, 1024)
		p.rsync.CreateDelta(bytes.NewReader(src_data), signature, func(op Operation) error {
			op.Data = slices.Clone(op.Data)
			delta_ops = append(delta_ops, op)
			return nil
		})
		total_data_in_delta = 0
		outputbuf := bytes.Buffer{}
		for _, op := range delta_ops {
			total_data_in_delta += len(op.Data)
			p.rsync.ApplyDelta(&outputbuf, bytes.NewReader(src_data), op)
		}
		return outputbuf.Bytes()
	}
	test_equal(src_data, apply_delta(signature))
	limit := 2 * (p.rsync.BlockSize * num_of_patches)
	if limit > -1 && total_data_in_delta > limit {
		t.Fatalf("%sUnexpectedly poor delta performance: total_patch_size: %d total_delta_size: %d limit: %d", prefix_msg(), total_patch_size, total_data_in_delta, limit)
	}

	// Now try with serialization
	using_serialization = true
	p = NewPatcher(int64(len(src_data)))
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

	test_equal(src_data, outputbuf.Bytes())
	if limit > -1 && p.total_data_in_delta > limit {
		t.Fatalf("%sUnexpectedly poor delta performance: total_patch_size: %d total_delta_size: %d limit: %d", prefix_msg(), total_patch_size, p.total_data_in_delta, limit)
	}

}

func TestRsyncRoundtrip(t *testing.T) {
	src_data := make([]byte, 4*1024*1024)
	random.Bytes(src_data)
	total_patch_size := 0
	num_of_patches := 8

	random_patch := func(data []byte) (size int) {
		if offset := random.Int(len(data)); offset < len(data) {
			max_size := utils.Min(257, len(data)-offset)
			if size = random.Int(max_size); size > 0 {
				total_patch_size += size
				random.Bytes(data[offset : offset+size])
			}
		}
		return
	}
	changed := slices.Clone(src_data)
	for i := 0; i < num_of_patches; i++ {
		random_patch(changed)
	}

	run_roundtrip_test(t, src_data, changed, num_of_patches, total_patch_size)
	run_roundtrip_test(t, src_data, []byte{}, -1, 0)
	run_roundtrip_test(t, src_data, src_data, 0, 0)

	// p := NewPatcher(int64(len(src_data)))
	// block_size := p.rsync.BlockSize
	// run_roundtrip_test(t, src_data, src_data[block_size:], 0, 0)

}
