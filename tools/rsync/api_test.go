// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package rsync

import (
	"bytes"
	"fmt"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"golang.org/x/exp/slices"

	"kitty/tools/utils"
)

var _ = fmt.Print
var _ = cmp.Diff

func run_roundtrip_test(t *testing.T, src_data, changed []byte, num_of_patches, total_patch_size int) {
	using_serialization := false
	prefix_msg := func() string {
		q := utils.IfElse(using_serialization, "with", "without")
		return fmt.Sprintf("%s: Running %s serialization: src size: %d changed size: %d difference: %d\n",
			utils.SourceLoc(1), q, len(src_data), len(changed), len(changed)-len(src_data))
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

func generate_data(block_size, num_of_blocks int) []byte {
	ans := make([]byte, num_of_blocks*block_size)
	utils.Memset(ans, '_')
	for i := 0; i < num_of_blocks; i++ {
		offset := i * block_size
		copy(ans[offset:], strconv.Itoa(i+1))
	}
	return ans
}

func patch_data(data []byte, patches ...string) (num_of_patches, total_patch_size int) {
	num_of_patches = len(patches)
	for _, patch := range patches {
		o, r, _ := strings.Cut(patch, ":")
		total_patch_size += len(r)
		if offset, err := strconv.Atoi(o); err == nil {
			copy(data[offset:], r)
		} else {
			panic(err)
		}
	}
	return
}

func TestRsyncRoundtrip(t *testing.T) {
	block_size := 16
	src_data := generate_data(block_size, 16)
	changed := slices.Clone(src_data)
	num_of_patches, total_patch_size := patch_data(changed, "3:patch1", "16:patch2", "130:ptch3")

	run_roundtrip_test(t, src_data, changed, num_of_patches, total_patch_size)
	run_roundtrip_test(t, src_data, []byte{}, -1, 0)
	run_roundtrip_test(t, src_data, src_data, 0, 0)

	// run_roundtrip_test(t, src_data, src_data[block_size:], 0, 0)

}
