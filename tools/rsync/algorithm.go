// RSync/RDiff implementation.
//
// Algorithm found at: http://www.samba.org/~tridge/phd_thesis.pdf
// Source code in this file is modified version of: https://github.com/jbreiding/rsync-go
//
// Definitions
//
//	Source: The final content.
//	Target: The content to be made into final content.
//	Signature: The sequence of hashes used to identify the content.
package rsync

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"hash"
	"io"
	"os"
)

// If no BlockSize is specified in the RSync instance, this value is used.
const DefaultBlockSize = 1024 * 6
const DefaultMaxDataOp = DefaultBlockSize * 10

// Internal constant used in rolling checksum.
const _M = 1 << 16

// Operation Types.
type OpType byte

const (
	OpBlock OpType = iota
	OpData
	OpHash
	OpBlockRange
)

// Instruction to mutate target to align to source.
type Operation struct {
	Type          OpType
	BlockIndex    uint64
	BlockIndexEnd uint64
	Data          []byte

	serialized_repr []byte
}

var bin = binary.LittleEndian

func (self Operation) Serialize() []byte {
	if self.serialized_repr != nil {
		return self.serialized_repr
	}
	var ans []byte
	switch self.Type {
	case OpBlock:
		ans = make([]byte, 9)
		bin.PutUint64(ans[1:], self.BlockIndex)
	case OpBlockRange:
		ans = make([]byte, 13)
		bin.PutUint64(ans[1:], self.BlockIndex)
		bin.PutUint32(ans[9:], uint32(self.BlockIndexEnd-self.BlockIndex))
	case OpHash:
		ans = make([]byte, 3+len(self.Data))
		bin.PutUint16(ans[1:], uint16(len(self.Data)))
		copy(ans[3:], self.Data)
	case OpData:
		ans = make([]byte, 5+len(self.Data))
		bin.PutUint32(ans[1:], uint32(len(self.Data)))
		copy(ans[5:], self.Data)
	}
	ans[0] = byte(self.Type)
	return ans
}

func (self *Operation) Unserialize(data []byte) (n int, err error) {
	if len(data) < 1 {
		return -1, io.ErrShortBuffer
	}
	switch OpType(data[0]) {
	case OpBlock:
		n = 9
		if len(data) < n {
			return -1, io.ErrShortBuffer
		}
		self.BlockIndex = bin.Uint64(data[1:])
		self.Data = nil
	case OpBlockRange:
		n = 13
		if len(data) < n {
			return -1, io.ErrShortBuffer
		}
		self.BlockIndex = bin.Uint64(data[1:])
		self.BlockIndexEnd = self.BlockIndex + uint64(bin.Uint32(data[9:]))
		self.Data = nil
	case OpHash:
		n = 3
		if len(data) < n {
			return -1, io.ErrShortBuffer
		}
		sz := int(bin.Uint16(data[1:]))
		n += sz
		if len(data) < n {
			return -1, io.ErrShortBuffer
		}
		self.Data = data[3:n]
	case OpData:
		n = 5
		if len(data) < n {
			return -1, io.ErrShortBuffer
		}
		sz := int(bin.Uint32(data[1:]))
		n += sz
		if len(data) < n {
			return -1, io.ErrShortBuffer
		}
		self.Data = data[5:n]
	default:
		return 0, fmt.Errorf("record has unknown operation type: %d", data[0])
	}
	self.Type = OpType(data[0])
	return
}

// Signature hash item generated from target.
type BlockHash struct {
	Index      uint64
	StrongHash []byte
	WeakHash   uint32
}

func (self BlockHash) Serialize() []byte {
	ans := make([]byte, 12+len(self.StrongHash))
	bin.PutUint64(ans, self.Index)
	bin.PutUint32(ans[8:], self.WeakHash)
	copy(ans[12:], self.StrongHash)
	return ans
}

func (self *BlockHash) Unserialize(data []byte, hash_size int) (err error) {
	if len(data) < 12+hash_size {
		return fmt.Errorf("record too small to be a BlockHash: %d < %d", len(data), 12+hash_size)
	}
	self.Index = bin.Uint64(data)
	self.WeakHash = bin.Uint32(data[8:])
	self.StrongHash = data[12 : 12+hash_size]
	return
}

// Write signatures as they are generated.
type SignatureWriter func(bl BlockHash) error
type OperationWriter func(op Operation) error

// Properties to use while working with the rsync algorithm.
// A single RSync should not be used concurrently as it may contain
// internal buffers and hash sums.
type RSync struct {
	BlockSize int
	MaxDataOp int

	// This must be non-nil before using any functions
	UniqueHasher hash.Hash

	buffer []byte
}

// If the target length is known the number of hashes in the
// signature can be determined.
func (r *RSync) BlockHashCount(targetLength int64) (count int64) {
	bs := int64(r.BlockSize)
	count = targetLength / bs
	if targetLength%bs != 0 {
		count++
	}
	return
}

// Calculate the signature of target.
func (r *RSync) CreateSignature(target io.Reader, sw SignatureWriter) error {
	var err error
	var n int

	minBufferSize := r.BlockSize
	if len(r.buffer) < minBufferSize {
		r.buffer = make([]byte, minBufferSize)
	}
	buffer := r.buffer

	var block []byte
	loop := true
	var index uint64
	for loop {
		n, err = io.ReadAtLeast(target, buffer, r.BlockSize)
		if err != nil {
			// n == 0.
			if err == io.EOF {
				return nil
			}
			if err != io.ErrUnexpectedEOF {
				return err
			}
			// n > 0.
			loop = false
		}
		block = buffer[:n]
		weak, _, _ := βhash(block)
		err = sw(BlockHash{StrongHash: r.uniqueHash(block), WeakHash: weak, Index: index})
		if err != nil {
			return err
		}
		index++
	}
	return nil
}

// Apply the difference to the target.
func (r *RSync) ApplyDelta(alignedTarget io.Writer, target io.ReadSeeker, op Operation) error {
	var err error
	var n int
	var block []byte

	r.set_buffer_to_size(r.BlockSize)
	buffer := r.buffer

	writeBlock := func(op Operation) error {
		if _, err = target.Seek(int64(r.BlockSize*int(op.BlockIndex)), os.SEEK_SET); err != nil {
			return err
		}
		n, err = io.ReadAtLeast(target, buffer, r.BlockSize)
		if err != nil {
			if err != io.ErrUnexpectedEOF {
				return err
			}
		}
		block = buffer[:n]
		_, err = alignedTarget.Write(block)
		if err != nil {
			return err
		}
		return nil
	}

	switch op.Type {
	case OpBlockRange:
		for i := op.BlockIndex; i <= op.BlockIndexEnd; i++ {
			err = writeBlock(Operation{
				Type:       OpBlock,
				BlockIndex: i,
			})
			if err != nil {
				if err == io.EOF {
					break
				}
				return err
			}
		}
	case OpBlock:
		err = writeBlock(op)
		if err != nil {
			if err == io.EOF {
				break
			}
			return err
		}
	case OpData:
		_, err = alignedTarget.Write(op.Data)
		if err != nil {
			return err
		}
	}
	return nil
}

func (r *RSync) set_buffer_to_size(sz int) {
	if cap(r.buffer) < sz {
		r.buffer = make([]byte, sz)
	} else {
		r.buffer = r.buffer[:sz]
	}
}

type section struct {
	tail int
	head int
}

type node struct {
	op   *Operation
	next *node
}

type list struct {
	head *node
}

func (self *list) push_back(op *Operation) {
	n := &node{op: op}
	n.next = self.head
	self.head = n
}

func (self *list) is_empty() bool { return self.head == nil }

func (self *list) front() *Operation {
	for c := self.head; c != nil; c = c.next {
		if c.next == nil {
			return c.op
		}
	}
	return nil
}

func (self *list) pop_front() *Operation {
	c := self.head
	var prev *node
	for c != nil {
		if c.next == nil {
			if prev == nil {
				self.head = nil
			} else {
				prev.next = nil
			}
			return c.op
		}
		prev = c
		c = c.next
	}
	return nil
}

type diff struct {
	buffer []byte
	// A single β hash may correlate with many unique hashes.
	hash_lookup map[uint32][]BlockHash
	source      io.Reader
	max_data_op int
	hasher      hash.Hash
	hash_buf    []byte

	data, sum                                 section
	block_size                                int
	n, valid_to                               int
	alpha_pop, alpha_push, beta, beta1, beta2 uint32
	finished, rolling                         bool

	pending_op *Operation
	ready_ops  list
}

func (self *diff) Next() (op *Operation, err error) {
	if self.ready_ops.is_empty() {
		if err = self.pump_till_op_available(); err != nil {
			return
		}
	}
	return self.ready_ops.pop_front(), nil
}

func (self *diff) hash(b []byte) []byte {
	self.hasher.Reset()
	self.hasher.Write(b)
	return self.hasher.Sum(self.hash_buf[:0])
}

// Combine OpBlock into OpBlockRange. To do this store the previous
// non-data operation and determine if it can be extended.
func (self *diff) enqueue(op Operation) {
	switch op.Type {
	case OpBlock:
		if self.pending_op != nil {
			switch self.pending_op.Type {
			case OpBlock:
				if self.pending_op.BlockIndex+1 == op.BlockIndex {
					self.pending_op = &Operation{
						Type:          OpBlockRange,
						BlockIndex:    self.pending_op.BlockIndex,
						BlockIndexEnd: op.BlockIndex,
					}
					return
				}
			case OpBlockRange:
				if self.pending_op.BlockIndexEnd+1 == op.BlockIndex {
					self.pending_op.BlockIndexEnd = op.BlockIndex
					return
				}
			}
			self.ready_ops.push_back(self.pending_op)
			self.pending_op = nil
		}
		self.pending_op = &op
	case OpData:
		// Never save a data operation, as it would corrupt the buffer.
		if self.pending_op != nil {
			self.ready_ops.push_back(self.pending_op)
			self.pending_op = nil
		}
		self.ready_ops.push_back(&op)
	}
	return

}

func (self *diff) send_data() {
	data := self.buffer[self.data.tail:self.data.head]
	srepr := make([]byte, len(data)+5)
	copy(srepr[5:], data)
	bin.PutUint32(srepr[1:], uint32(len(data)))
	srepr[0] = byte(OpData)
	op := Operation{Type: OpData, Data: srepr[5:], serialized_repr: srepr}
	self.enqueue(op)
	self.data.tail = self.data.head
}

func (self *diff) pump_till_op_available() error {
	for self.ready_ops.is_empty() && !self.finished {
		if err := self.read_at_least_one_operation(); err != nil {
			return err
		}
	}
	if self.finished && self.pending_op != nil {
		self.ready_ops.push_back(self.pending_op)
		self.pending_op = nil
	}
	return nil
}

// See https://rsync.samba.org/tech_report/node4.html for the design of this algorithm
func (self *diff) read_at_least_one_operation() error {
	last_run := false
	required_pos_for_sum := self.sum.tail + self.block_size
	if required_pos_for_sum > self.valid_to { // need more data in buffer
		// Determine if the buffer should be wrapped.
		if self.valid_to+self.block_size > len(self.buffer) {
			// Before wrapping the buffer, send any trailing data off.
			if self.data.tail < self.data.head {
				self.send_data()
			}
			// Wrap the buffer.
			l := self.valid_to - self.sum.tail
			copy(self.buffer[:l], self.buffer[self.sum.tail:self.valid_to])

			// Reset indexes.
			self.valid_to = l
			self.sum.tail = 0
			self.data.head = 0
			self.data.tail = 0
		}

		n, err := io.ReadAtLeast(self.source, self.buffer[self.valid_to:self.valid_to+self.block_size], self.block_size)
		self.valid_to += n
		if err != nil {
			if err != io.EOF && err != io.ErrUnexpectedEOF {
				return err
			}
			last_run = true
			self.data.head = self.valid_to
		}
		if n == 0 {
			if self.data.tail < self.data.head {
				self.send_data()
			}
		}
	}

	// Set the hash sum window head. Must either be a block size
	// or be at the end of the buffer.
	self.sum.head = min(self.sum.tail+self.block_size, self.valid_to)

	// Compute the rolling hash.
	if !self.rolling {
		self.beta, self.beta1, self.beta2 = βhash(self.buffer[self.sum.tail:self.sum.head])
		self.rolling = true
	} else {
		self.alpha_push = uint32(self.buffer[self.sum.head-1])
		self.beta1 = (self.beta1 - self.alpha_pop + self.alpha_push) % _M
		self.beta2 = (self.beta2 - uint32(self.sum.head-self.sum.tail)*self.alpha_pop + self.beta1) % _M
		self.beta = self.beta1 + _M*self.beta2
	}

	// Determine if there is a hash match.
	found_hash := false
	var block_index uint64
	if hh, ok := self.hash_lookup[self.beta]; ok && !last_run {
		block_index, found_hash = findUniqueHash(hh, self.hash(self.buffer[self.sum.tail:self.sum.head]))
	}
	// Send data off if there is data available and a hash is found (so the buffer before it
	// must be flushed first), or the data chunk size has reached it's maximum size (for buffer
	// allocation purposes) or to flush the end of the data.
	if self.data.tail < self.data.head && (found_hash || self.data.head-self.data.tail >= self.max_data_op || last_run) {
		self.send_data()
	}

	if found_hash {
		self.enqueue(Operation{Type: OpBlock, BlockIndex: block_index})
		self.rolling = false
		self.sum.tail += self.block_size

		// There is prior knowledge that any available data
		// buffered will have already been sent. Thus we can
		// assume data.head and data.tail are the same.
		// May trigger "data wrap".
		self.data.head = self.sum.tail
		self.data.tail = self.sum.tail
	} else {
		// The following is for the next loop iteration, so don't try to calculate if last.
		if !last_run && self.rolling {
			self.alpha_pop = uint32(self.buffer[self.sum.tail])
		}
		self.sum.tail += 1

		// May trigger "data wrap".
		self.data.head = self.sum.tail
	}
	if last_run {
		self.finished = true
	}
	return nil
}

func (r *RSync) CreateDiff(source io.Reader, signature []BlockHash) func() (*Operation, error) {
	ans := &diff{
		block_size: r.BlockSize, buffer: make([]byte, (r.BlockSize*2)+(r.MaxDataOp)),
		hash_lookup: make(map[uint32][]BlockHash, len(signature)),
		source:      source, max_data_op: r.MaxDataOp, hasher: r.UniqueHasher,
		hash_buf: make([]byte, 0, r.UniqueHasher.Size()),
	}
	for _, h := range signature {
		key := h.WeakHash
		ans.hash_lookup[key] = append(ans.hash_lookup[key], h)
	}

	return ans.Next
}

func (r *RSync) CreateDelta(source io.Reader, signature []BlockHash, ops OperationWriter) (err error) {
	diff := r.CreateDiff(source, signature)
	var op *Operation
	for {
		op, err = diff()
		if op == nil {
			return
		}
		if err = ops(*op); err != nil {
			return err
		}
	}
}

// Use a more unique way to identify a set of bytes.
func (r *RSync) uniqueHash(v []byte) []byte {
	r.UniqueHasher.Reset()
	r.UniqueHasher.Write(v)
	return r.UniqueHasher.Sum(nil)
}

// Searches for a given strong hash among all strong hashes in this bucket.
func findUniqueHash(hh []BlockHash, hashValue []byte) (uint64, bool) {
	if len(hashValue) == 0 {
		return 0, false
	}
	for _, block := range hh {
		if bytes.Equal(block.StrongHash, hashValue) {
			return block.Index, true
		}
	}
	return 0, false
}

// Use a faster way to identify a set of bytes.
func βhash(block []byte) (β uint32, β1 uint32, β2 uint32) {
	var a, b uint32
	sz := uint32(len(block) - 1)
	for i, val := range block {
		a += uint32(val)
		b += (sz - uint32(i) + 1) * uint32(val)
	}
	β = (a % _M) + (_M * (b % _M))
	β1 = a % _M
	β2 = b % _M
	return
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
