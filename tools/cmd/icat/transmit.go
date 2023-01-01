// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"kitty/tools/tui/graphics"
	"kitty/tools/utils"
	"kitty/tools/utils/shm"
	"math/rand"
	"os"
	"path/filepath"
)

var _ = fmt.Print

func gc_for_image(imgd *image_data, frame_num int, frame *image_frame) *graphics.GraphicsCommand {
	gc := graphics.GraphicsCommand{}
	gc.SetAction(graphics.GRT_action_transmit_and_display)
	gc.SetDataWidth(uint64(frame.width)).SetDataHeight(uint64(frame.height))
	gc.SetQuiet(graphics.GRT_quiet_silent)
	if z_index != 0 {
		gc.SetZIndex(z_index)
	}
	if imgd.image_number != 0 {
		gc.SetImageNumber(imgd.image_number)
	}
	switch imgd.format_uppercase {
	case "PNG":
		gc.SetFormat(graphics.GRT_format_png)
	default:
		gc.SetFormat(graphics.GRT_format_rgb)
	case "RGBA":
		gc.SetFormat(graphics.GRT_format_rgba)
	}

	return &gc
}

func transmit_shm(imgd *image_data, frame_num int, frame *image_frame) (err error) {
	var mmap shm.MMap
	var data_size int64
	if frame.in_memory_bytes == nil {
		f, err := os.Open(frame.filename)
		if err != nil {
			return fmt.Errorf("Failed to open image data output file: %s with error: %w", frame.filename, err)
		}
		defer f.Close()
		data_size, _ = f.Seek(0, io.SeekEnd)
		f.Seek(0, io.SeekStart)
		mmap, err = shm.CreateTemp("icat-*", uint64(data_size))
		if err != nil {
			return fmt.Errorf("Failed to create a SHM file for transmission: %w", err)
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
				return fmt.Errorf("Failed to read data from image output data file: %w", err)
			}
		}
	} else {
		data_size = int64(len(frame.in_memory_bytes))
		mmap, err = shm.CreateTemp("icat-*", uint64(data_size))
		if err != nil {
			return fmt.Errorf("Failed to create a SHM file for transmission: %w", err)
		}
		defer mmap.Close()
		copy(mmap.Slice(), frame.in_memory_bytes)
	}
	gc := gc_for_image(imgd, frame_num, frame)
	gc.SetTransmission(graphics.GRT_transmission_sharedmem)
	gc.SetDataSize(uint64(data_size))
	gc.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(mmap.Name()))

	return nil
}

func transmit_file(imgd *image_data, frame_num int, frame *image_frame) (err error) {
	is_temp := false
	fname := ""
	var data_size int
	if frame.in_memory_bytes == nil {
		is_temp = frame.filename_is_temporary
		fname, err = filepath.Abs(frame.filename)
		if err != nil {
			return fmt.Errorf("Failed to convert image data output file: %s to absolute path with error: %w", frame.filename, err)
		}
		frame.filename = "" // so it isnt deleted in cleanup
	} else {
		f, err := graphics.CreateTempInRAM()
		if err != nil {
			return fmt.Errorf("Failed to create a temp file for image data transmission: %w", err)
		}
		data_size = len(frame.in_memory_bytes)
		_, err = bytes.NewBuffer(frame.in_memory_bytes).WriteTo(f)
		f.Close()
		if err != nil {
			return fmt.Errorf("Failed to write image data to temp file for transmission: %w", err)
		}
		is_temp = true
		fname = f.Name()
	}
	gc := gc_for_image(imgd, frame_num, frame)
	if is_temp {
		gc.SetTransmission(graphics.GRT_transmission_tempfile)
	} else {
		gc.SetTransmission(graphics.GRT_transmission_file)
	}
	if data_size > 0 {
		gc.SetDataSize(uint64(data_size))
	}
	gc.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(fname))
	return nil
}

func transmit_stream(imgd *image_data, frame_num int, frame *image_frame) (err error) {
	data := frame.in_memory_bytes
	if data == nil {
		f, err := os.Open(frame.filename)
		if err != nil {
			return fmt.Errorf("Failed to open image data output file: %s with error: %w", frame.filename, err)
		}
		data, err = io.ReadAll(f)
		f.Close()
		if err != nil {
			return fmt.Errorf("Failed to read data from image output data file: %w", err)
		}
	}
	gc := gc_for_image(imgd, frame_num, frame)
	gc.WriteWithPayloadToLoop(lp, data)
	return nil
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
	if len(imgd.frames) > 1 {
		imgd.image_number = rand.Uint32()
	}
	for frame_num, frame := range imgd.frames {
		err := f(imgd, frame_num, frame)
		if err != nil {
			print_error("Failed to transmit %s with error: %v", imgd.source_name, err)
		}
	}
}
