// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package rsync

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"io"
	"slices"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print
var _ = cmp.Diff

func run_roundtrip_test(t *testing.T, src_data, changed []byte, num_of_patches, total_patch_size int) {
	using_serialization := false
	t.Helper()
	prefix_msg := func() string {
		q := utils.IfElse(using_serialization, "with", "without")
		return fmt.Sprintf("Running %s serialization: src size: %d changed size: %d difference: %d\n",
			q, len(src_data), len(changed), len(changed)-len(src_data))
	}

	test_equal := func(src_data, output []byte) {
		if !bytes.Equal(src_data, output) {
			first_diff := min(len(src_data), len(output))
			for i := 0; i < first_diff; i++ {
				if src_data[i] != output[i] {
					first_diff = i
					break
				}
			}
			t.Fatalf("%sPatching failed: %d extra_bytes first different byte at: %d\nsrc:\n%s\nchanged:\n%s\noutput:\n%s\n",
				prefix_msg(), len(output)-len(src_data), first_diff, string(src_data), string(changed), string(output))
		}
	}

	// first try just the engine without serialization
	p := NewPatcher(int64(len(src_data)))
	signature := make([]BlockHash, 0, 128)
	s_it := p.rsync.CreateSignatureIterator(bytes.NewReader(changed))
	for {
		s, err := s_it()
		if err == nil {
			signature = append(signature, s)
		} else if err == io.EOF {
			break
		} else {
			t.Fatal(err)
		}
	}

	total_data_in_delta := 0
	apply_delta := func(signature []BlockHash) []byte {
		delta_ops, err := p.rsync.CreateDelta(bytes.NewReader(src_data), signature)
		if err != nil {
			t.Fatal(err)
		}
		if delta_ops[len(delta_ops)-1].Type != OpHash {
			t.Fatalf("Last operation was not OpHash")
		}
		total_data_in_delta = 0
		outputbuf := bytes.Buffer{}
		for _, op := range delta_ops {
			if op.Type == OpData {
				total_data_in_delta += len(op.Data)
			}
			p.rsync.ApplyDelta(&outputbuf, bytes.NewReader(changed), op)
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
	p = NewPatcher(int64(len(changed)))
	signature_of_changed := bytes.Buffer{}
	ss_it := p.CreateSignatureIterator(bytes.NewReader(changed), &signature_of_changed)
	var err error
	for {
		err = ss_it()
		if err == io.EOF {
			break
		} else if err != nil {
			t.Fatal(err)
		}
	}
	d := NewDiffer()
	if err := d.AddSignatureData(signature_of_changed.Bytes()); err != nil {
		t.Fatal(err)
	}
	db := bytes.Buffer{}
	it := d.CreateDelta(bytes.NewBuffer(src_data), &db)
	for {
		if err := it(); err != nil {
			if err == io.EOF {
				break
			}
			t.Fatal(err)
		}
	}
	deltabuf := db.Bytes()
	outputbuf := bytes.Buffer{}
	p.StartDelta(&outputbuf, bytes.NewReader(changed))
	for len(deltabuf) > 0 {
		n := min(123, len(deltabuf))
		if err := p.UpdateDelta(deltabuf[:n]); err != nil {
			t.Fatal(err)
		}
		deltabuf = deltabuf[n:]
	}
	if err := p.FinishDelta(); err != nil {
		t.Fatal(err)
	}

	test_equal(src_data, outputbuf.Bytes())
	if limit > -1 && p.total_data_in_delta > limit {
		t.Fatalf("%sUnexpectedly poor delta performance: total_patch_size: %d total_delta_size: %d limit: %d", prefix_msg(), total_patch_size, p.total_data_in_delta, limit)
	}
}

func generate_data(block_size, num_of_blocks int, extra ...string) []byte {
	e := strings.Join(extra, "")
	ans := make([]byte, num_of_blocks*block_size+len(e))
	utils.Memset(ans, '_')
	for i := 0; i < num_of_blocks; i++ {
		offset := i * block_size
		copy(ans[offset:], strconv.Itoa(i))
	}
	copy(ans[num_of_blocks*block_size:], e)
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
	num_of_patches, total_patch_size := patch_data(changed, "3:patch1", "16:patch2", "130:ptch3", "176:patch4", "222:XXYY")

	run_roundtrip_test(t, src_data, src_data[block_size:], 1, block_size)
	run_roundtrip_test(t, src_data, changed, num_of_patches, total_patch_size)
	run_roundtrip_test(t, src_data, []byte{}, -1, 0)
	run_roundtrip_test(t, src_data, src_data, 0, 0)
	run_roundtrip_test(t, src_data, changed[:len(changed)-3], num_of_patches, total_patch_size)
	run_roundtrip_test(t, src_data, append(changed[:37], changed[81:]...), num_of_patches, total_patch_size)

	block_size = 13
	src_data = generate_data(block_size, 17, "trailer")
	changed = slices.Clone(src_data)
	num_of_patches, total_patch_size = patch_data(changed, "0:patch1", "19:patch2")
	run_roundtrip_test(t, src_data, changed, num_of_patches, total_patch_size)
	run_roundtrip_test(t, src_data, changed[:len(changed)-3], num_of_patches, total_patch_size)
	run_roundtrip_test(t, src_data, append(changed, "xyz..."...), num_of_patches, total_patch_size)
}

func TestRsyncHashers(t *testing.T) {
	h := new_xxh3_64()
	h.Write([]byte("abcd"))
	if diff := cmp.Diff(hex.EncodeToString(h.Sum(nil)), `6497a96f53a89890`); diff != "" {
		t.Fatalf("%s", diff)
	}
	if diff := cmp.Diff(h.Sum64(), uint64(7248448420886124688)); diff != "" {
		t.Fatalf("%s", diff)
	}
	h2 := new_xxh3_128()
	h2.Write([]byte("abcd"))
	if diff := cmp.Diff(hex.EncodeToString(h2.Sum(nil)), `8d6b60383dfa90c21be79eecd1b1353d`); diff != "" {
		t.Fatalf("%s", diff)
	}
}
