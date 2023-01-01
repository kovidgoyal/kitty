// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"errors"
	"fmt"
	"io"
	"kitty/tools/tui/graphics"
	"kitty/tools/utils/shm"
	"os"
)

var _ = fmt.Print

func gc_for_image(imgd *image_data) *graphics.GraphicsCommand {
}

func transmit_shm(imgd *image_data, frame_num int, frame *image_frame) error {
	var data_size int
	if frame.in_memory_bytes == nil {
		f, err := os.Open(frame.filename)
		if err != nil {
			return err
		}
		defer f.Close()
		sz, _ := f.Seek(0, io.SeekEnd)
		f.Seek(0, io.SeekStart)
		mmap, err := shm.CreateTemp("icat-*", uint64(sz))
		if err != nil {
			return err
		}
		defer mmap.Close()
		dest := mmap.Slice()
		for len(dest) > 0 {
			n, err := f.Read(dest)
			dest = dest[n:]
			if err != nil {
				if errors.Is(err, io.EOF) {
					break
				}
				mmap.Unlink()
				return err
			}
		}
		data_size = len(mmap.Slice()) - len(dest)
	} else {
		mmap, err := shm.CreateTemp("icat-*", uint64(len(frame.in_memory_bytes)))
		if err != nil {
			return err
		}
		defer mmap.Close()
		data_size = copy(mmap.Slice(), frame.in_memory_bytes)
	}
}

func transmit_file(imgd *image_data, frame_num int, frame *image_frame) error {
}

func transmit_stream(imgd *image_data, frame_num int, frame *image_frame) error {
}

func transmit_image(imgd *image_data) {
	defer func() {
		for _, frame := range imgd.frames {
			if frame.filename_is_temporary && frame.filename != "" {
				os.Remove(frame.filename)
				frame.filename = ""
			}
			frame.in_memory_bytes = nil
		}
	}()
	var f func(*image_data, int, *image_frame) error
	if opts.TransferMode != "detect" {
		switch opts.TransferMode {
		case "file":
			f = transmit_file
		case "memory":
			f = transmit_shm
		case "stream":
			f = transmit_stream
			return
		}
	}
	if f == nil && transfer_by_memory == supported && imgd.frames[0].in_memory_bytes != nil {
		f = transmit_shm
	}
	if f == nil && transfer_by_file == supported {
		f = transmit_file
	}
	if f == nil {
		f = transmit_stream
	}
	for frame_num, frame := range imgd.frames {
		err := f(imgd, frame_num, &frame)
		if err != nil {
			print_error("Failed to transmit %s with error: %v", imgd.source_name, err)
		}
	}
}
