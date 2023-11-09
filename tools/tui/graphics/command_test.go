// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package graphics

import (
	"bytes"
	"compress/zlib"
	"encoding/base64"
	"fmt"
	"io"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"golang.org/x/exp/rand"
)

var _ = fmt.Print

func from_full_apc_escape_code(raw string) *GraphicsCommand {
	return GraphicsCommandFromAPC([]byte(raw[2 : len(raw)-2]))
}

func TestGraphicsCommandSerialization(t *testing.T) {
	gc := &GraphicsCommand{}

	test_serialize := func(payload string, vals ...string) {
		expected := "\033_G" + strings.Join(vals, ",")
		if payload != "" {
			expected += ";" + base64.RawStdEncoding.EncodeToString([]byte(payload))
		}
		expected += "\033\\"
		if diff := cmp.Diff(expected, gc.AsAPC([]byte(payload))); diff != "" {
			t.Fatalf("Failed to write vals: %#v with payload: %#v\n%s", vals, payload, diff)
		}
	}

	test_chunked_payload := func(payload []byte) {
		c := &GraphicsCommand{}
		data := c.AsAPC([]byte(payload))
		encoded := strings.Builder{}
		compressed := false
		is_first := true
		for {
			idx := strings.Index(data, "\033_")
			if idx < 0 {
				break
			}
			l := strings.Index(data, "\033\\")
			apc := data[idx+2 : l]
			data = data[l+2:]
			g := GraphicsCommandFromAPC([]byte(apc))
			if is_first {
				compressed = g.Compression() != 0
				is_first = false
			}
			encoded.WriteString(g.ResponseMessage())
			if g.m == GRT_more_nomore {
				break
			}
		}
		if len(data) > 0 {
			t.Fatalf("Unparsed remnant: %#v", string(data))
		}
		decoded, err := base64.RawStdEncoding.DecodeString(encoded.String())
		if err != nil {
			t.Fatalf("Encoded data not valid base-64 with error: %v", err)
		}
		if compressed {
			b := bytes.Buffer{}
			b.Write(decoded)
			r, _ := zlib.NewReader(&b)
			o := bytes.Buffer{}
			if _, err = io.Copy(&o, r); err != nil {
				t.Fatal(err)
			}
			r.Close()
			decoded = o.Bytes()
		}
		if diff := cmp.Diff(payload, decoded); diff != "" {
			t.Fatalf("Decoded payload does not match original\nlen decoded=%d len payload=%d", len(decoded), len(payload))
		}
	}

	test_serialize("")
	gc.SetTransmission(GRT_transmission_sharedmem).SetAction(GRT_action_query).SetZIndex(-3).SetWidth(33).SetImageId(11)
	test_serialize("abcd", "a=q", "t=s", "w=33", "i=11", "z=-3")
	q := from_full_apc_escape_code(gc.AsAPC([]byte("abcd")))
	if diff := cmp.Diff(gc.AsAPC(nil), q.AsAPC(nil)); diff != "" {
		t.Fatalf("Parsing failed:\n%s", diff)
	}
	if diff := cmp.Diff(q.response_message, base64.RawStdEncoding.EncodeToString([]byte("abcd"))); diff != "" {
		t.Fatalf("Failed to parse payload:\n%s", diff)
	}

	test_chunked_payload([]byte("abcd"))
	data := make([]byte, 8111)
	_, _ = rand.Read(data)
	test_chunked_payload(data)
	test_chunked_payload([]byte(strings.Repeat("a", 8007)))

}
