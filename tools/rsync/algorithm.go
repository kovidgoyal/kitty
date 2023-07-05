// Algorithm found at: https://rsync.samba.org/tech_report/tech_report.html
// Code in this file is inspired by: https://github.com/jbreiding/rsync-go
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

// Internal constant used in rolling checksum.
const _M = 1 << 16

// Operation Types.
type OpType byte // enum

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

	// This must be non-nil before using any functions
	hasher             hash.Hash
	hasher_constructor func() hash.Hash
	buffer             []byte
}

func (r *RSync) SetHasher(c func() hash.Hash) {
	r.hasher_constructor = c
	r.hasher = c()
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
	rc := rolling_checksum{}
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
		weak := rc.full(block)
		err = sw(BlockHash{StrongHash: r.hash(block), WeakHash: weak, Index: index})
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

// see https://rsync.samba.org/tech_report/node3.html
type rolling_checksum struct {
	alpha, beta, val, l           uint32
	first_byte_of_previous_window uint32
}

func (self *rolling_checksum) full(data []byte) uint32 {
	var alpha, beta uint32
	self.l = uint32(len(data)) // actually should be len(data) - 1 but the equations always use l+1
	for i, b := range data {
		alpha += uint32(b)
		beta += (self.l - uint32(i)) * uint32(b)
	}
	self.first_byte_of_previous_window = uint32(data[0])
	self.alpha = alpha % _M
	self.beta = beta % _M
	self.val = self.alpha + _M*self.beta
	return self.val
}

func (self *rolling_checksum) add_one_byte(first_byte, last_byte byte) {
	self.alpha = (self.alpha - self.first_byte_of_previous_window + uint32(last_byte)) % _M
	self.beta = (self.beta - (self.l)*self.first_byte_of_previous_window + self.alpha) % _M
	self.val = self.alpha + _M*self.beta
	self.first_byte_of_previous_window = uint32(first_byte)
}

type diff struct {
	buffer []byte
	// A single β hash may correlate with many unique hashes.
	hash_lookup map[uint32][]BlockHash
	source      io.Reader
	hasher      hash.Hash
	hash_buf    []byte

	window, data struct{ pos, sz int }
	block_size   int
	finished     bool
	rc           rolling_checksum

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
	case OpData, OpHash:
		if self.pending_op != nil {
			self.ready_ops.push_back(self.pending_op)
			self.pending_op = nil
		}
		self.ready_ops.push_back(&op)
	}
	return

}

func (self *diff) send_data() {
	if self.data.sz > 0 {
		data := self.buffer[self.data.pos : self.data.pos+self.data.sz]
		srepr := make([]byte, len(data)+5)
		copy(srepr[5:], data)
		bin.PutUint32(srepr[1:], uint32(len(data)))
		srepr[0] = byte(OpData)
		op := Operation{Type: OpData, Data: srepr[5:], serialized_repr: srepr}
		self.enqueue(op)
		self.data.pos += self.data.sz
		self.data.sz = 0
	}
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

func (self *diff) ensure_idx_valid(idx int) (ok bool, err error) {
	if idx < len(self.buffer) {
		return true, nil
	}
	if idx >= cap(self.buffer) {
		// need to wrap the buffer, so send off any data present behind the window
		self.send_data()
		// copy the window and any data present after it to the start of the buffer
		distance_from_window_pos := idx - self.window.pos
		amt_to_copy := len(self.buffer) - self.window.pos
		copy(self.buffer, self.buffer[self.window.pos:self.window.pos+amt_to_copy])
		self.buffer = self.buffer[:amt_to_copy]
		self.window.pos = 0
		self.data.pos = 0
		return self.ensure_idx_valid(distance_from_window_pos)
	}
	extra := idx - len(self.buffer) + 1
	var n int
	n, err = io.ReadAtLeast(self.source, self.buffer[len(self.buffer):cap(self.buffer)], extra)
	switch err {
	case nil:
		ok = true
		self.buffer = self.buffer[:len(self.buffer)+n]
	case io.ErrUnexpectedEOF, io.EOF:
		err = nil
		self.buffer = self.buffer[:len(self.buffer)+n]
	}
	return
}

func (self *diff) finish_up() {
	self.send_data()
	self.data.pos = self.window.pos
	self.data.sz = len(self.buffer) - self.window.pos
	self.send_data()
	self.finished = true
}

// See https://rsync.samba.org/tech_report/node4.html for the design of this algorithm
func (self *diff) read_at_least_one_operation() (err error) {
	if self.window.sz > 0 {
		if ok, err := self.ensure_idx_valid(self.window.pos + self.window.sz); !ok {
			if err != nil {
				return err
			}
			self.finish_up()
			return nil
		}
		self.window.pos++
		self.data.sz++
		self.rc.add_one_byte(self.buffer[self.window.pos], self.buffer[self.window.pos+self.window.sz-1])
	} else {
		if ok, err := self.ensure_idx_valid(self.window.pos + self.block_size - 1); !ok {
			if err != nil {
				return err
			}
			self.finish_up()
			return nil
		}
		self.window.sz = self.block_size
		self.rc.full(self.buffer[self.window.pos : self.window.pos+self.window.sz])
	}
	found_hash := false
	var block_index uint64
	if hh, ok := self.hash_lookup[self.rc.val]; ok {
		block_index, found_hash = find_hash(hh, self.hash(self.buffer[self.window.pos:self.window.pos+self.window.sz]))
	}
	if found_hash {
		self.send_data()
		self.enqueue(Operation{Type: OpBlock, BlockIndex: block_index})
		self.window.pos += self.window.sz
		self.data.pos = self.window.pos
		self.window.sz = 0
	}
	return nil
}

func (r *RSync) CreateDiff(source io.Reader, signature []BlockHash) func() (*Operation, error) {
	ans := &diff{
		block_size: r.BlockSize, buffer: make([]byte, 0, (r.BlockSize * 8)),
		hash_lookup: make(map[uint32][]BlockHash, len(signature)),
		source:      source, hasher: r.hasher_constructor(),
		hash_buf: make([]byte, 0, r.hasher.Size()),
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
func (r *RSync) hash(v []byte) []byte {
	r.hasher.Reset()
	r.hasher.Write(v)
	return r.hasher.Sum(nil)
}

func (r *RSync) HashSize() int      { return r.hasher.Size() }
func (r *RSync) HashBlockSize() int { return r.hasher.BlockSize() }
func (r *RSync) HasHasher() bool    { return r.hasher != nil }

// Searches for a given strong hash among all strong hashes in this bucket.
func find_hash(hh []BlockHash, hv []byte) (uint64, bool) {
	if len(hv) == 0 {
		return 0, false
	}
	for _, block := range hh {
		if bytes.Equal(block.StrongHash, hv) {
			return block.Index, true
		}
	}
	return 0, false
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
