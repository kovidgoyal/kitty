// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package streaming_base64

import (
	"bytes"
	"fmt"
	"testing"

	"github.com/emmansun/base64"
)

var _ = fmt.Print

// collectDecode feeds input to the decoder in chunks of chunkSize bytes and
// accumulates all decoded output into a single slice.  It uses a generously-
// sized output buffer so buffer-size issues never mask correctness bugs.
func collectDecode(t *testing.T, d *StreamingBase64Decoder, encoded []byte, chunkSize int) ([]byte, error) {
	t.Helper()
	var result []byte
	for len(encoded) > 0 {
		end := min(chunkSize, len(encoded))
		chunk := encoded[:end]
		encoded = encoded[end:]

		// Output buffer: worst-case 3 bytes per 4 input bytes, plus the
		// 3 bytes for a buffered leftover block.
		outBuf := make([]byte, (len(chunk)+4)*3)
		for decoded, err := range d.Decode(chunk, outBuf) {
			if err != nil {
				return nil, err
			}
			result = append(result, decoded...)
		}
	}
	return result, nil
}

// roundtrip encodes plaintext with standard base64, then decodes it through
// the streaming decoder in chunkSize pieces and verifies the result.
func roundtrip(t *testing.T, plaintext []byte, chunkSize int) {
	t.Helper()
	encoded := []byte(base64.StdEncoding.EncodeToString(plaintext))
	var d StreamingBase64Decoder
	got, err := collectDecode(t, &d, encoded, chunkSize)
	if err != nil {
		t.Fatalf("chunkSize=%d: unexpected decode error: %v", chunkSize, err)
	}
	tail, err := d.Finish()
	if err != nil {
		t.Fatalf("chunkSize=%d: unexpected Finish error: %v", chunkSize, err)
	}
	got = append(got, tail...)
	if !bytes.Equal(got, plaintext) {
		t.Fatalf("chunkSize=%d: roundtrip mismatch:\n  want %q\n   got %q", chunkSize, plaintext, got)
	}
}

// roundtripNoPadding is like roundtrip but strips the trailing '=' padding
// characters from the encoded string.  The Finish method must add them back.
func roundtripNoPadding(t *testing.T, plaintext []byte, chunkSize int) {
	t.Helper()
	encoded := []byte(base64.RawStdEncoding.EncodeToString(plaintext)) // no padding
	var d StreamingBase64Decoder
	got, err := collectDecode(t, &d, encoded, chunkSize)
	if err != nil {
		t.Fatalf("noPad chunkSize=%d: unexpected decode error: %v", chunkSize, err)
	}
	tail, err := d.Finish()
	if err != nil {
		t.Fatalf("noPad chunkSize=%d: unexpected Finish error: %v", chunkSize, err)
	}
	got = append(got, tail...)
	if !bytes.Equal(got, plaintext) {
		t.Fatalf("noPad chunkSize=%d: roundtrip mismatch:\n  want %q\n   got %q", chunkSize, plaintext, got)
	}
}

// TestRoundtripAllChunkSizes exercises every chunk size from 1 to 7 with
// plaintexts whose lengths produce all possible num_leftover values (0-3)
// after encoding: 0 mod 3 → 0 leftover, 1 mod 3 → 2 leftover, 2 mod 3 → 1
// leftover after decoding (but 2 base64 chars left when unpadded).
func TestRoundtripAllChunkSizes(t *testing.T) {
	plaintexts := [][]byte{
		{},                      // 0 bytes  → 0 encoded  → num_leftover=0
		[]byte("a"),             // 1 byte   → 4 encoded  → no leftover (padded)
		[]byte("ab"),            // 2 bytes  → 4 encoded  → no leftover (padded)
		[]byte("abc"),           // 3 bytes  → 4 encoded  → no leftover
		[]byte("abcd"),          // 4 bytes  → 8 encoded  → no leftover
		[]byte("abcde"),         // 5 bytes  → 8 encoded  → no leftover (padded)
		[]byte("abcdef"),        // 6 bytes  → 8 encoded  → no leftover (padded)
		[]byte("Hello, World!"), // 13 bytes → 20 encoded
		[]byte("The quick brown fox jumps over the"), // 34 bytes → 48 encoded
		bytes.Repeat([]byte{0x00, 0xff, 0x80}, 17),   // binary data
	}
	for _, plain := range plaintexts {
		for chunkSize := 1; chunkSize <= 7; chunkSize++ {
			if len(plain) == 0 && chunkSize > 1 {
				continue // only test once for empty input
			}
			roundtrip(t, plain, chunkSize)
		}
	}
}

// TestRoundtripNoPaddingAllChunkSizes tests decoding without trailing '='
// padding bytes for all relevant chunk sizes.
func TestRoundtripNoPaddingAllChunkSizes(t *testing.T) {
	plaintexts := [][]byte{
		[]byte("a"),                    // 1 byte  → "YQ" (2 base64 chars, no pad)
		[]byte("ab"),                   // 2 bytes → "YWI" (3 base64 chars, no pad)
		[]byte("abc"),                  // 3 bytes → "YWJj" (4 chars, no leftover)
		[]byte("abcd"),                 // 4 bytes → "YWJjZA" (6 chars)
		[]byte("Hello, World!"),        // mixed
		bytes.Repeat([]byte{0xde}, 10), // binary, 1 mod 3 remainder
		bytes.Repeat([]byte{0xbe}, 11), // binary, 2 mod 3 remainder
		bytes.Repeat([]byte{0xef}, 12), // binary, 0 mod 3 remainder
	}
	for _, plain := range plaintexts {
		for chunkSize := 1; chunkSize <= 7; chunkSize++ {
			roundtripNoPadding(t, plain, chunkSize)
		}
	}
}

// TestNumLeftoverInDecode checks that the bridge-block path in Decode (the
// path that fires when num_leftover > 0 at the start of a new call) produces
// correct results.  We achieve specific num_leftover values by feeding exactly
// that many bytes in the first call.
func TestNumLeftoverInDecode(t *testing.T) {
	// plaintext whose encoding is long enough to exercise all leftover values
	plain := []byte("abcdefghijklmnopqrstuvwxyz") // 26 bytes → 36 encoded chars

	for firstCallLen := 1; firstCallLen <= 3; firstCallLen++ {
		encoded := []byte(base64.StdEncoding.EncodeToString(plain))
		var d StreamingBase64Decoder
		outBuf := make([]byte, 64)

		// Feed exactly firstCallLen bytes → num_leftover = firstCallLen % 4
		var got []byte
		for dec, err := range d.Decode(encoded[:firstCallLen], outBuf) {
			if err != nil {
				t.Fatalf("firstCallLen=%d first Decode error: %v", firstCallLen, err)
			}
			got = append(got, dec...)
		}
		// Feed the rest
		rest, err := collectDecode(t, &d, encoded[firstCallLen:], 4)
		if err != nil {
			t.Fatalf("firstCallLen=%d rest Decode error: %v", firstCallLen, err)
		}
		got = append(got, rest...)
		tail, err := d.Finish()
		if err != nil {
			t.Fatalf("firstCallLen=%d Finish error: %v", firstCallLen, err)
		}
		got = append(got, tail...)
		if !bytes.Equal(got, plain) {
			t.Fatalf("firstCallLen=%d mismatch:\n  want %q\n   got %q", firstCallLen, plain, got)
		}
	}
}

// TestFinishNumLeftover directly exercises all four branches of Finish.
//
//   - num_leftover=0 → (nil, nil)
//   - num_leftover=1 → error pointing to correct byte offset
//   - num_leftover=2 → decode 1 byte, pad "=="
//   - num_leftover=3 → decode 2 bytes, pad "="
func TestFinishNumLeftover(t *testing.T) {
	// num_leftover=0: empty decoder, Finish must return (nil, nil).
	t.Run("leftover=0", func(t *testing.T) {
		var d StreamingBase64Decoder
		out, err := d.Finish()
		if err != nil || out != nil {
			t.Fatalf("expected (nil,nil), got (%v,%v)", out, err)
		}
	})

	// num_leftover=0 after a complete stream: also (nil, nil).
	t.Run("leftover=0_after_stream", func(t *testing.T) {
		// "abc" encodes to "YWJj" — exactly 4 chars, no leftover
		var d StreamingBase64Decoder
		outBuf := make([]byte, 16)
		for _, err := range d.Decode([]byte("YWJj"), outBuf) {
			if err != nil {
				t.Fatal(err)
			}
		}
		out, err := d.Finish()
		if err != nil || out != nil {
			t.Fatalf("expected (nil,nil), got (%v,%v)", out, err)
		}
	})

	// num_leftover=1 → CorruptInputError pointing to total_read - 1.
	t.Run("leftover=1", func(t *testing.T) {
		// Feed 5 base64 chars: 4 will be consumed, 1 leftover.
		encoded := []byte(base64.StdEncoding.EncodeToString([]byte("abc"))) // "YWJj" (4)
		encoded = append(encoded, 'Y')                                      // + 1 → total 5
		var d StreamingBase64Decoder
		outBuf := make([]byte, 16)
		for _, err := range d.Decode(encoded, outBuf) {
			if err != nil {
				t.Fatalf("unexpected Decode error: %v", err)
			}
		}
		// num_leftover should now be 1; total_read = 5
		_, err := d.Finish()
		if err == nil {
			t.Fatal("expected error for leftover=1, got nil")
		}
		ce, ok := err.(base64.CorruptInputError)
		if !ok {
			t.Fatalf("expected base64.CorruptInputError, got %T: %v", err, err)
		}
		// total_read=5, num_leftover=1 → offset should be 4
		if int64(ce) != 4 {
			t.Fatalf("wrong error offset: want 4, got %d", int64(ce))
		}
	})

	// num_leftover=2 → Finish pads "==" and decodes 1 byte.
	t.Run("leftover=2", func(t *testing.T) {
		// "a" encodes to "YQ==" with padding, or "YQ" without.
		// Feed "YQ" (2 chars) so num_leftover=2.
		var d StreamingBase64Decoder
		outBuf := make([]byte, 16)
		for _, err := range d.Decode([]byte("YQ"), outBuf) {
			if err != nil {
				t.Fatalf("unexpected Decode error: %v", err)
			}
		}
		out, err := d.Finish()
		if err != nil {
			t.Fatalf("unexpected Finish error: %v", err)
		}
		if !bytes.Equal(out, []byte("a")) {
			t.Fatalf("want %q, got %q", "a", out)
		}
	})

	// num_leftover=3 → Finish pads "=" and decodes 2 bytes.
	t.Run("leftover=3", func(t *testing.T) {
		// "ab" encodes to "YWI=" with padding, or "YWI" without.
		// Feed "YWI" (3 chars) so num_leftover=3.
		var d StreamingBase64Decoder
		outBuf := make([]byte, 16)
		for _, err := range d.Decode([]byte("YWI"), outBuf) {
			if err != nil {
				t.Fatalf("unexpected Decode error: %v", err)
			}
		}
		out, err := d.Finish()
		if err != nil {
			t.Fatalf("unexpected Finish error: %v", err)
		}
		if !bytes.Equal(out, []byte("ab")) {
			t.Fatalf("want %q, got %q", "ab", out)
		}
	})
}

// TestErrorOffsetInDecode checks that when Decode encounters an invalid byte
// the returned error is a base64.CorruptInputError with the correct absolute
// byte offset within the full stream.
func TestErrorOffsetInDecode(t *testing.T) {
	tests := []struct {
		name       string
		chunks     []string // successive calls to Decode
		wantOffset int64
	}{
		{
			// Error in the very first block (no leftovers involved).
			name:       "error_in_first_block",
			chunks:     []string{"YWJj", "YW!j"},
			wantOffset: 4 + 2, // 4 bytes of good data, then offset 2 within chunk
		},
		{
			// Error in the bridge block built from leftover + new bytes.
			// Feed 3 chars (leftover=3), then 1 invalid char.
			// The bridge block is "YWJ!" (positions 0–3 in the stream).
			// base64 reports the '!' as relative byte 3 within "YWJ!";
			// wrap_error adds chunk_offset = total_read - num_leftover = 3 - 3 = 0,
			// so the absolute error offset is 3.
			name:       "error_in_bridge_block",
			chunks:     []string{"YWJ", "!"},
			wantOffset: 3,
		},
		{
			// Error well into the stream after multiple complete blocks.
			// "YWJj" × 3 = 12 valid chars, then invalid at position 0 of next chunk.
			name:       "error_after_multiple_blocks",
			chunks:     []string{"YWJjYWJjYWJj", "!WJj"},
			wantOffset: 12,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var d StreamingBase64Decoder
			var gotErr error
			outBuf := make([]byte, 64)
		outer:
			for _, chunk := range tc.chunks {
				for _, err := range d.Decode([]byte(chunk), outBuf) {
					if err != nil {
						gotErr = err
						break outer
					}
				}
			}
			if gotErr == nil {
				t.Fatal("expected a decode error, got nil")
			}
			ce, ok := gotErr.(base64.CorruptInputError)
			if !ok {
				t.Fatalf("expected base64.CorruptInputError, got %T: %v", gotErr, gotErr)
			}
			if int64(ce) != tc.wantOffset {
				t.Fatalf("wrong error offset: want %d, got %d", tc.wantOffset, int64(ce))
			}
		})
	}
}

// TestOutputBufferTooSmall verifies that Decode returns an error (not a panic)
// when the supplied output buffer is too small.
func TestOutputBufferTooSmall(t *testing.T) {
	var d StreamingBase64Decoder
	tinyBuf := make([]byte, 0) // definitely too small for any decoded output
	encoded := []byte("YWJj")  // decodes to 3 bytes
	var gotErr error
	for _, err := range d.Decode(encoded, tinyBuf) {
		if err != nil {
			gotErr = err
			break
		}
	}
	if gotErr == nil {
		t.Fatal("expected an error for too-small output buffer, got nil")
	}
}

// TestEmptyInput verifies that decoding an empty input followed by Finish
// produces no output and no error.
func TestEmptyInput(t *testing.T) {
	var d StreamingBase64Decoder
	outBuf := make([]byte, 16)
	for _, err := range d.Decode([]byte{}, outBuf) {
		if err != nil {
			t.Fatalf("unexpected error on empty input: %v", err)
		}
	}
	out, err := d.Finish()
	if err != nil || out != nil {
		t.Fatalf("expected (nil,nil) for empty input, got (%v,%v)", out, err)
	}
}

// TestLargeInput stress-tests the decoder with a large binary payload across
// every chunk size from 1 to 13 to catch off-by-one errors in the leftover
// accumulation logic.
func TestLargeInput(t *testing.T) {
	plain := make([]byte, 1000)
	for i := range plain {
		plain[i] = byte(i * 7)
	}
	for chunkSize := 1; chunkSize <= 13; chunkSize++ {
		roundtrip(t, plain, chunkSize)
		roundtripNoPadding(t, plain, chunkSize)
	}
}
