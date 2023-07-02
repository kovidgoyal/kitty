// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package rsync

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"strings"

	"github.com/zeebo/xxh3"

	"kitty/tools/utils"
)

var _ = fmt.Print

const MaxBlockSize int = 256 * 1024

type Api struct {
	rsync        RSync
	signature    []BlockHash
	delta_output io.Writer
	delta_input  io.ReadSeeker
	delta_buffer []byte

	Strong_hash_name, Weak_hash_name string
}

type SignatureHeader struct {
	Weak_hash_name   string `json:"weak_hash,omitempty"`
	Strong_hash_name string `json:"strong_hash,omitempty"`
	Block_size       int    `json:"block_size,omitempty"`
}

func (self *Api) StartDelta(delta_output io.Writer, delta_input io.ReadSeeker) {
	self.delta_output = delta_output
	self.delta_input = delta_input
	self.delta_buffer = self.delta_buffer[:0]
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

func (self *Api) UpdateDelta(data []byte) (err error) {
	if len(self.delta_buffer) == 0 {
		consumed, err := self.update_delta(data)
		if err != nil {
			return err
		}
		data = data[consumed:]
		if len(data) > 0 {
			self.delta_buffer = append(self.delta_buffer, data...)
		}
	} else {
		self.delta_buffer = append(self.delta_buffer, data...)
		consumed, err := self.update_delta(self.delta_buffer)
		if err != nil {
			return err
		}
		leftover := len(self.delta_buffer) - consumed
		copy(self.delta_buffer, self.delta_buffer[consumed:])
		self.delta_buffer = self.delta_buffer[:leftover]
	}
	return
}

func (self *Api) FinishDelta() (err error) {
	if len(self.delta_buffer) > 0 {
		data := self.delta_buffer
		self.delta_buffer = self.delta_buffer[:0]
		if err = self.UpdateDelta(data); err != nil {
			return err
		}
		if len(self.delta_buffer) > 0 {
			return fmt.Errorf("There are %d leftover bytes in the delta", len(self.delta_buffer))
		}
	}
	self.delta_input = nil
	self.delta_output = nil
	return
}

func (self *Api) CreateDelta(src io.Reader, output_callback func(string) error) (err error) {
	if len(self.signature) == 0 {
		return fmt.Errorf("Cannot call CreateDelta() before loading a signature")
	}
	self.rsync.CreateDelta(src, self.signature, func(op Operation) error {
		return output_callback(op.Serialize())
	})
	return
}

func (self *Api) setup_from_signature(signature string) (err error) {
	h := SignatureHeader{}
	dec := json.NewDecoder(strings.NewReader(signature))
	if err = dec.Decode(&h); err != nil {
		return fmt.Errorf("rsync signature header not valid JSON with error: %w", err)
	}
	signature = signature[dec.InputOffset():]
	if h.Block_size == 0 {
		return fmt.Errorf("rsync signature header has no or zero block size")
	}
	if h.Block_size > MaxBlockSize {
		return fmt.Errorf("rsync signature header has too large block size %d > %d", h.Block_size, MaxBlockSize)
	}
	self.rsync.BlockSize = h.Block_size
	self.rsync.MaxDataOp = 10 * h.Block_size
	if h.Weak_hash_name != "" && h.Weak_hash_name != "beta" {
		return fmt.Errorf("rsync signature header has unknown weak hash algorithm: %#v", h.Weak_hash_name)
	}
	self.Weak_hash_name = h.Weak_hash_name
	switch h.Strong_hash_name {
	case "", "xxh3":
		self.rsync.UniqueHasher = xxh3.New()
		self.Strong_hash_name = "xxh3"
	default:
		return fmt.Errorf("rsync signature header has unknown strong hash algorithm: %#v", h.Strong_hash_name)
	}
	self.signature = make([]BlockHash, 0, 64)
	hash_size := self.rsync.UniqueHasher.Size()
	block_hash_size := self.rsync.UniqueHasher.Size() + 12
	for ; len(signature) >= block_hash_size; signature = signature[block_hash_size:] {
		data := utils.UnsafeStringToBytes(signature[:block_hash_size])
		bl := BlockHash{}
		bl.Unserialize(data, hash_size)
		self.signature = append(self.signature, bl)
	}
	return
}

func NewFromSignature(signature string) (ans *Api, err error) {
	ans = &Api{}
	err = ans.setup_from_signature(signature)
	return
}

func New(src io.Reader) (ans *Api, err error) {
	bs := DefaultBlockSize
	var sz int64
	if v, ok := src.(io.ReadSeeker); ok {
		if pos, err := v.Seek(0, os.SEEK_CUR); err != nil {
			return nil, err
		} else {
			if sz, err = v.Seek(0, os.SEEK_END); err != nil {
				sz -= pos
				bs = int(math.Round(math.Sqrt(float64(sz))))
				if _, err = v.Seek(pos, os.SEEK_SET); err != nil {
					return nil, err
				}
			}
		}
	}
	ans = &Api{Weak_hash_name: "beta", Strong_hash_name: "xxh3"}
	ans.rsync.BlockSize = utils.Min(bs, MaxBlockSize)
	ans.rsync.UniqueHasher = xxh3.New()

	if ans.rsync.UniqueHasher.BlockSize() > 0 && ans.rsync.UniqueHasher.BlockSize() < ans.rsync.BlockSize {
		ans.rsync.BlockSize = (ans.rsync.BlockSize / ans.rsync.UniqueHasher.BlockSize()) * ans.rsync.UniqueHasher.BlockSize()
	}

	ans.rsync.MaxDataOp = ans.rsync.BlockSize * 10
	if sz > 0 {
		ans.signature = make([]BlockHash, 0, ans.rsync.BlockHashCount(sz))
	}
	err = ans.rsync.CreateSignature(src, func(bl BlockHash) error {
		ans.signature = append(ans.signature, bl)
		return nil
	})
	return
}
