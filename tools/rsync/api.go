// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

// First create a patcher with:
// p = NewPatcher()
// Create a signature for the file you want to update using
// p.CreateSignatureIterator(file_to_update)
// Now create a Differ with the created signature
// d = NewDiffer()
// d.AddSignatureData(signature_data_from_previous_step)
// Now create a delta based on the signature and the reference file
// d.CreateDelta(reference_file)
// Finally, apply this delta using the patcher to produce a file identical to reference_file
// based ont he delta data and file_to_update
// p.StartDelta(output_file, file_to_update)
// p.UpdateDelta(...)
// p.FinishDelta()
package rsync

import (
	"fmt"
	"io"
	"math"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const MaxBlockSize int = 1024 * 1024 // sqrt of 1TB

type StrongHashType uint16
type WeakHashType uint16
type ChecksumType uint16

const (
	XXH3 StrongHashType = iota
)
const (
	XXH3128Sum ChecksumType = iota
)
const (
	Rsync WeakHashType = iota
)

type GrowBufferFunction = func(slice []byte, sz int) []byte

type Api struct {
	rsync     rsync
	signature []BlockHash

	Checksum_type    ChecksumType
	Strong_hash_type StrongHashType
	Weak_hash_type   WeakHashType
}

type Differ struct {
	Api
	unconsumed_signature_data []byte
}

type Patcher struct {
	Api
	unconsumed_delta_data                        []byte
	expected_input_size_for_signature_generation int64
	delta_output                                 io.Writer
	delta_input                                  io.ReadSeeker
	total_data_in_delta                          int
}

// internal implementation {{{
func (self *Api) read_signature_header(data []byte) (consumed int, err error) {
	if len(data) < 12 {
		return -1, io.ErrShortBuffer
	}
	if version := bin.Uint16(data); version != 0 {
		return consumed, fmt.Errorf("Invalid version in signature header: %d", version)
	}
	switch csum := ChecksumType(bin.Uint16(data[2:])); csum {
	case XXH3128Sum:
		self.Checksum_type = XXH3128Sum
		self.rsync.SetChecksummer(new_xxh3_128)
	default:
		return consumed, fmt.Errorf("Invalid checksum_type in signature header: %d", csum)
	}
	switch strong_hash := StrongHashType(bin.Uint16(data[4:])); strong_hash {
	case XXH3:
		self.Strong_hash_type = strong_hash
		self.rsync.SetHasher(new_xxh3_64)
	default:
		return consumed, fmt.Errorf("Invalid strong_hash in signature header: %d", strong_hash)
	}
	switch weak_hash := WeakHashType(bin.Uint16(data[6:])); weak_hash {
	case Rsync:
		self.Weak_hash_type = weak_hash
	default:
		return consumed, fmt.Errorf("Invalid weak_hash in signature header: %d", weak_hash)
	}
	block_size := int(bin.Uint32(data[8:]))
	consumed = 12
	if block_size == 0 {
		return consumed, fmt.Errorf("rsync signature header has zero block size")
	}
	if block_size > MaxBlockSize {
		return consumed, fmt.Errorf("rsync signature header has too large block size %d > %d", block_size, MaxBlockSize)
	}
	self.rsync.BlockSize = block_size
	self.signature = make([]BlockHash, 0, 1024)
	return
}

func (self *Api) read_signature_blocks(data []byte) (consumed int) {
	block_hash_size := self.rsync.HashSize() + 12
	for ; len(data) >= block_hash_size; data = data[block_hash_size:] {
		bl := BlockHash{}
		bl.Unserialize(data[:block_hash_size])
		self.signature = append(self.signature, bl)
		consumed += block_hash_size
	}
	return
}

func (self *Differ) FinishSignatureData() (err error) {
	if len(self.unconsumed_signature_data) > 0 {
		return fmt.Errorf("There were %d leftover bytes in the signature data", len(self.unconsumed_signature_data))
	}
	self.unconsumed_signature_data = nil
	if !self.rsync.HasHasher() {
		return fmt.Errorf("No header was found in the signature data")
	}
	return
}

func (self *Patcher) update_delta(data []byte) (consumed int, err error) {
	op := Operation{}
	for len(data) > 0 {
		n, uerr := op.Unserialize(data)
		if uerr == nil {
			consumed += n
			data = data[n:]
			if err = self.rsync.ApplyDelta(self.delta_output, self.delta_input, op); err != nil {
				return
			}
			if op.Type == OpData {
				self.total_data_in_delta += len(op.Data)
			}
		} else {
			if n < 0 {
				return consumed, nil
			}
			return consumed, uerr
		}
	}
	return
}

// }}}

// Start applying serialized delta
func (self *Patcher) StartDelta(delta_output io.Writer, delta_input io.ReadSeeker) {
	self.delta_output = delta_output
	self.delta_input = delta_input
	self.total_data_in_delta = 0
	self.unconsumed_delta_data = nil
}

// Apply a chunk of delta data
func (self *Patcher) UpdateDelta(data []byte) (err error) {
	self.unconsumed_delta_data = append(self.unconsumed_delta_data, data...)
	consumed, err := self.update_delta(self.unconsumed_delta_data)
	if err != nil {
		return err
	}
	self.unconsumed_delta_data = utils.ShiftLeft(self.unconsumed_delta_data, consumed)
	return
}

// Finish applying delta data
func (self *Patcher) FinishDelta() (err error) {
	if err = self.UpdateDelta([]byte{}); err != nil {
		return err
	}
	if len(self.unconsumed_delta_data) > 0 {
		return fmt.Errorf("There are %d leftover bytes in the delta", len(self.unconsumed_delta_data))
	}
	self.delta_input = nil
	self.delta_output = nil
	self.unconsumed_delta_data = nil
	if !self.rsync.checksum_done {
		return fmt.Errorf("The checksum was not received at the end of the delta data")
	}
	return
}

// Create a signature for the data source in src.
func (self *Patcher) CreateSignatureIterator(src io.Reader, output io.Writer) func() error {
	var it func() (BlockHash, error)
	finished := false
	var b [BlockHashSize]byte
	return func() error {
		if finished {
			return io.EOF
		}
		if it == nil { // write signature header
			it = self.rsync.CreateSignatureIterator(src)
			bin.PutUint16(b[:], 0)
			bin.PutUint16(b[2:], uint16(self.Checksum_type))
			bin.PutUint16(b[4:], uint16(self.Strong_hash_type))
			bin.PutUint16(b[6:], uint16(self.Weak_hash_type))
			bin.PutUint32(b[8:], uint32(self.rsync.BlockSize))
			if _, err := output.Write(b[:12]); err != nil {
				return err
			}
		}
		bl, err := it()
		switch err {
		case io.EOF:
			finished = true
			return io.EOF
		case nil:
			bl.Serialize(b[:BlockHashSize])
			_, err = output.Write(b[:BlockHashSize])
			return err
		default:
			return err
		}
	}
}

// Create a serialized delta based on the previously loaded signature
func (self *Differ) CreateDelta(src io.Reader, output io.Writer) func() error {
	if err := self.FinishSignatureData(); err != nil {
		return func() error { return err }
	}
	if self.signature == nil {
		return func() error {
			return fmt.Errorf("Cannot call CreateDelta() before loading a signature")
		}
	}
	return self.rsync.CreateDiff(src, self.signature, output)
}

func (self *Differ) BlockSize() int {
	return self.rsync.BlockSize
}

// Add more external signature data
func (self *Differ) AddSignatureData(data []byte) (err error) {
	self.unconsumed_signature_data = append(self.unconsumed_signature_data, data...)
	if !self.rsync.HasHasher() {
		consumed, err := self.read_signature_header(self.unconsumed_signature_data)
		if err != nil {
			if consumed < 0 {
				return nil
			}
			return err
		}
		self.unconsumed_signature_data = utils.ShiftLeft(self.unconsumed_signature_data, consumed)
	}
	consumed := self.read_signature_blocks(self.unconsumed_signature_data)
	self.unconsumed_signature_data = utils.ShiftLeft(self.unconsumed_signature_data, consumed)
	return nil
}

// Use to calculate a delta based on a supplied signature, via AddSignatureData
func NewDiffer() *Differ {
	return &Differ{}
}

// Use to create a signature and possibly apply a delta
func NewPatcher(expected_input_size int64) (ans *Patcher) {
	bs := DefaultBlockSize
	sz := max(0, expected_input_size)
	if sz > 0 {
		bs = int(math.Round(math.Sqrt(float64(sz))))
	}
	ans = &Patcher{}
	ans.rsync.BlockSize = min(bs, MaxBlockSize)
	ans.rsync.SetHasher(new_xxh3_64)
	ans.rsync.SetChecksummer(new_xxh3_128)

	if ans.rsync.HashBlockSize() > 0 && ans.rsync.HashBlockSize() < ans.rsync.BlockSize {
		ans.rsync.BlockSize = (ans.rsync.BlockSize / ans.rsync.HashBlockSize()) * ans.rsync.HashBlockSize()
	}

	ans.expected_input_size_for_signature_generation = sz
	return
}
