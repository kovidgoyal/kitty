package streaming_base64

import (
	"encoding/base64"
	"fmt"
	"iter"
)

var _ = fmt.Print

type StreamingBase64Decoder struct {
	leftover     [4]byte
	num_leftover int
	total_read   int64
}

func wrap_error(err error, chunkOffset int64) error {
	if e, ok := err.(base64.CorruptInputError); ok {
		// CorruptInputError is an int64 representing the relative byte offset
		return base64.CorruptInputError(int64(e) + chunkOffset)
	}
	return err
}

func (s *StreamingBase64Decoder) Decode(input []byte, output []byte) iter.Seq2[[]byte, error] {
	// Base64 decoding: 4 input bytes -> 3 output bytes.
	// We check if output is large enough for this chunk + any buffered data.
	maxPossibleOutput := ((len(input) + s.num_leftover) / 4) * 3
	return func(yield func([]byte, error) bool) {
		if len(output) < maxPossibleOutput {
			yield(nil, fmt.Errorf("output slice too small: need at least %d, got %d", maxPossibleOutput, len(output)))
			return
		}
		currIn := input
		outOffset := 0

		// 1. Handle leftover bytes from previous call
		if s.num_leftover > 0 {
			need := 4 - s.num_leftover
			if len(currIn) >= need {
				copy(s.leftover[s.num_leftover:], currIn[:need])

				// Decode the bridge block
				n, err := base64.StdEncoding.Decode(output[outOffset:], s.leftover[:4])
				if err != nil {
					yield(nil, wrap_error(err, s.total_read-int64(s.num_leftover)))
					return
				}

				if !yield(output[outOffset:outOffset+n], nil) {
					return
				}
				outOffset += n
				currIn = currIn[need:]
				s.total_read += int64(need)
				s.num_leftover = 0
			} else {
				// Still not enough to complete a block
				copy(s.leftover[s.num_leftover:], currIn)
				s.num_leftover += len(currIn)
				s.total_read += int64(len(currIn))
				return
			}
		}

		// 2. Decode the bulk of the current chunk
		processableLen := (len(currIn) / 4) * 4
		if processableLen > 0 {
			if n, err := base64.StdEncoding.Decode(output[outOffset:], currIn[:processableLen]); err != nil {
				yield(nil, wrap_error(err, s.total_read))
				return
			} else if n > 0 {
				if !yield(output[outOffset:outOffset+n], nil) {
					return
				}
				outOffset += n
			}
			currIn = currIn[processableLen:]
			s.total_read += int64(processableLen)
		}

		// 3. Buffer remaining bytes (1-3) for the next Decode call
		if len(currIn) > 0 {
			copy(s.leftover[:], currIn)
			s.num_leftover = len(currIn)
			s.total_read += int64(len(currIn))
		}
	}
}

func (s *StreamingBase64Decoder) Finish() ([]byte, error) {
	switch s.num_leftover {
	case 0:
		return nil, nil
	case 1:
		return nil, base64.CorruptInputError(s.total_read - 1)
	case 2:
		s.leftover[2] = '='
		s.leftover[3] = '='
	case 3:
		s.leftover[3] = '='
	}
	output := [3]byte{}
	n, err := base64.StdEncoding.Decode(output[:3], s.leftover[:4])
	return output[:n], wrap_error(err, s.total_read-int64(s.num_leftover))
}
