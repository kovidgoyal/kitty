// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package rsync

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"

	"github.com/zeebo/xxh3"

	"kitty/tools/utils"
)

var _ = fmt.Print

const MaxBlockSize int = 256 * 1024
const DefaultStrongHash string = "xxh3"
const DefaultWeakHash string = "beta"

type Api struct {
	rsync                                            RSync
	signature                                        []BlockHash
	delta_output                                     io.Writer
	delta_input                                      io.ReadSeeker
	unconsumed_signature_data, unconsumed_delta_data []byte
	expected_input_size_for_signature_generation     int64

	Strong_hash_name, Weak_hash_name string
}

type SignatureHeader struct {
	Weak_hash_name   string `json:"weak_hash,omitempty"`
	Strong_hash_name string `json:"strong_hash,omitempty"`
	Block_size       int    `json:"block_size,omitempty"`
}

// internal implementation {{{
func (self *Api) read_signature_header(data []byte) (consumed int, err error) {
	if len(data) < 6 {
		return -1, io.ErrShortBuffer
	}
	sz := int(binary.LittleEndian.Uint32(data))
	if len(data) < sz+4 {
		return -1, io.ErrShortBuffer
	}
	consumed = 4 + sz
	h := SignatureHeader{}
	if err = json.Unmarshal(data[4:consumed], &h); err != nil {
		return consumed, fmt.Errorf("Invalid JSON in signature header with error: %w", err)
	}
	if h.Block_size == 0 {
		return consumed, fmt.Errorf("rsync signature header has no or zero block size")
	}
	if h.Block_size > MaxBlockSize {
		return consumed, fmt.Errorf("rsync signature header has too large block size %d > %d", h.Block_size, MaxBlockSize)
	}
	self.rsync.BlockSize = h.Block_size
	self.rsync.MaxDataOp = 10 * h.Block_size
	if h.Weak_hash_name != "" && h.Weak_hash_name != DefaultWeakHash {
		return consumed, fmt.Errorf("rsync signature header has unknown weak hash algorithm: %#v", h.Weak_hash_name)
	}
	self.Weak_hash_name = h.Weak_hash_name
	switch h.Strong_hash_name {
	case "", DefaultStrongHash:
		self.rsync.UniqueHasher = xxh3.New()
		self.Strong_hash_name = DefaultStrongHash
	default:
		return consumed, fmt.Errorf("rsync signature header has unknown strong hash algorithm: %#v", h.Strong_hash_name)
	}
	self.signature = make([]BlockHash, 0, 64)
	return
}

func (self *Api) read_signature_blocks(data []byte) (consumed int) {
	hash_size := self.rsync.UniqueHasher.Size()
	block_hash_size := hash_size + 12
	for ; len(data) >= block_hash_size; data = data[block_hash_size:] {
		bl := BlockHash{}
		bl.Unserialize(data[:block_hash_size], hash_size)
		self.signature = append(self.signature, bl)
		consumed += block_hash_size
	}
	return
}

func (self *Api) update_delta(data []byte) (consumed int, err error) {
	op := Operation{}
	for len(data) > 0 {
		n, uerr := op.Unserialize(data)
		if uerr == nil {
			consumed += n
			data = data[n:]
			if err = self.rsync.ApplyDelta(self.delta_output, self.delta_input, op); err != nil {
				return
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
func (self *Api) StartDelta(delta_output io.Writer, delta_input io.ReadSeeker) {
	self.delta_output = delta_output
	self.delta_input = delta_input
	self.unconsumed_delta_data = nil
}

// Apply a chunk of delta data
func (self *Api) UpdateDelta(data []byte) (err error) {
	if len(self.unconsumed_delta_data) > 0 {
		data = append(self.unconsumed_delta_data, data...)
		self.unconsumed_delta_data = nil
	}
	consumed, err := self.update_delta(data)
	if err != nil {
		return err
	}
	data = data[consumed:]
	if len(data) > 0 {
		self.unconsumed_delta_data = data
	}
	return
}

// Finish applying delta data
func (self *Api) FinishDelta() (err error) {
	if err = self.UpdateDelta([]byte{}); err != nil {
		return err
	}
	if len(self.unconsumed_delta_data) > 0 {
		return fmt.Errorf("There are %d leftover bytes in the delta", len(self.unconsumed_delta_data))
	}
	self.delta_input = nil
	self.delta_output = nil
	self.unconsumed_delta_data = nil
	return
}

// Create a serialized delta based on the previously loaded signature
func (self *Api) CreateDelta(src io.Reader, output_callback func(string) error) (err error) {
	if len(self.signature) == 0 {
		return fmt.Errorf("Cannot call CreateDelta() before loading a signature")
	}
	self.rsync.CreateDelta(src, self.signature, func(op Operation) error {
		return output_callback(op.Serialize())
	})
	return
}

// Create a signature for the data source in src
func (self *Api) CreateSignature(src io.Reader, callback func([]byte) error) (err error) {
	sh := SignatureHeader{Strong_hash_name: self.Strong_hash_name, Weak_hash_name: self.Weak_hash_name, Block_size: self.rsync.BlockSize}
	if sh.Strong_hash_name == DefaultStrongHash {
		sh.Strong_hash_name = ""
	}
	if sh.Weak_hash_name == DefaultWeakHash {
		sh.Weak_hash_name = ""
	}
	if b, err := json.Marshal(&sh); err != nil {
		return err
	} else if err = callback(b); err != nil {
		return err
	}
	if self.expected_input_size_for_signature_generation > 0 {
		self.signature = make([]BlockHash, 0, self.rsync.BlockHashCount(self.expected_input_size_for_signature_generation))
	} else {
		self.signature = make([]BlockHash, 0, 1024)
	}
	return self.rsync.CreateSignature(src, func(bl BlockHash) error {
		if err = callback(bl.Serialize()); err != nil {
			return err
		}
		self.signature = append(self.signature, bl)
		return nil
	})
}

// Add more external signature data
func (self *Api) AddSignatureData(data []byte) (err error) {
	if len(self.unconsumed_signature_data) > 0 {
		data = append(self.unconsumed_signature_data, data...)
		self.unconsumed_signature_data = nil
	}
	if self.rsync.UniqueHasher == nil {
		consumed, err := self.read_signature_header(data)
		if err != nil {
			if consumed < 0 {
				self.unconsumed_signature_data = data
				return nil
			}
			return err
		}
		data = data[consumed:]
	}
	consumed := self.read_signature_blocks(data)
	data = data[consumed:]
	if len(data) > 0 {
		self.unconsumed_signature_data = data
	}
	return nil
}

// Finish adding external signature data
func (self *Api) FinishSignatureData() (err error) {
	if len(self.unconsumed_signature_data) > 0 {
		return fmt.Errorf("There were %d leftover bytes in the signature data", len(self.unconsumed_signature_data))
	}
	self.unconsumed_signature_data = nil
	if self.rsync.UniqueHasher == nil {
		return fmt.Errorf("No header was found in the signature data")
	}
	return
}

// Use to calculate a delta based on a supplied signature, via AddSignatureData
func NewToCreateDelta() *Api {
	return &Api{}
}

// Use to create a signature and possibly apply a delta
func NewToCreateSignature(expected_input_size int64) (ans *Api, err error) {
	bs := DefaultBlockSize
	sz := utils.Max(0, expected_input_size)
	if sz > 0 {
		bs = int(math.Round(math.Sqrt(float64(sz))))
	}
	ans = &Api{Weak_hash_name: DefaultWeakHash, Strong_hash_name: DefaultStrongHash}
	ans.rsync.BlockSize = utils.Min(bs, MaxBlockSize)
	ans.rsync.UniqueHasher = xxh3.New()

	if ans.rsync.UniqueHasher.BlockSize() > 0 && ans.rsync.UniqueHasher.BlockSize() < ans.rsync.BlockSize {
		ans.rsync.BlockSize = (ans.rsync.BlockSize / ans.rsync.UniqueHasher.BlockSize()) * ans.rsync.UniqueHasher.BlockSize()
	}

	ans.rsync.MaxDataOp = ans.rsync.BlockSize * 10
	ans.expected_input_size_for_signature_generation = sz
	return
}
