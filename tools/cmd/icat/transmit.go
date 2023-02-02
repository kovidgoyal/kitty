// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"bytes"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
	not_rand "math/rand"
	"os"
	"path/filepath"

	"kitty/tools/tui/graphics"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/utils/shm"
)

var _ = fmt.Print

func gc_for_image(imgd *image_data, frame_num int, frame *image_frame) *graphics.GraphicsCommand {
	gc := graphics.GraphicsCommand{}
	gc.SetDataWidth(uint64(frame.width)).SetDataHeight(uint64(frame.height))
	gc.SetQuiet(graphics.GRT_quiet_silent)
	gc.SetFormat(frame.transmission_format)
	if imgd.image_number != 0 {
		gc.SetImageNumber(imgd.image_number)
	}
	if frame_num == 0 {
		gc.SetAction(graphics.GRT_action_transmit_and_display)
		if imgd.cell_x_offset > 0 {
			gc.SetXOffset(uint64(imgd.cell_x_offset))
		}
		if z_index != 0 {
			gc.SetZIndex(z_index)
		}
		if place != nil {
			gc.SetCursorMovement(graphics.GRT_cursor_static)
		}
	} else {
		gc.SetAction(graphics.GRT_action_frame)
		gc.SetGap(int32(frame.delay_ms))
		if frame.compose_onto > 0 {
			gc.SetOverlaidFrame(uint64(frame.compose_onto))
		} else {
			bg := (uint32(frame.disposal_background.R) << 24) | (uint32(frame.disposal_background.G) << 16) | (uint32(frame.disposal_background.B) << 8) | uint32(frame.disposal_background.A)
			gc.SetBackgroundColor(bg)
		}
		gc.SetLeftEdge(uint64(frame.left)).SetTopEdge(uint64(frame.top))
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
		if frame.shm == nil {
			data_size = int64(len(frame.in_memory_bytes))
			mmap, err = shm.CreateTemp("icat-*", uint64(data_size))
			if err != nil {
				return fmt.Errorf("Failed to create a SHM file for transmission: %w", err)
			}
			copy(mmap.Slice(), frame.in_memory_bytes)
		} else {
			mmap = frame.shm
			frame.shm = nil
		}
	}
	gc := gc_for_image(imgd, frame_num, frame)
	gc.SetTransmission(graphics.GRT_transmission_sharedmem)
	gc.SetDataSize(uint64(data_size))
	gc.WriteWithPayloadTo(os.Stdout, utils.UnsafeStringToBytes(mmap.Name()))
	mmap.Close()

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
		is_temp = true
		if frame.shm != nil && frame.shm.FileSystemName() != "" {
			fname = frame.shm.FileSystemName()
			frame.shm.Close()
			frame.shm = nil
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
			fname = f.Name()
		}
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
	gc.WriteWithPayloadTo(os.Stdout, utils.UnsafeStringToBytes(fname))
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
	gc.WriteWithPayloadTo(os.Stdout, data)
	return nil
}

func calculate_in_cell_x_offset(width, cell_width int) int {
	extra_pixels := width % cell_width
	if extra_pixels == 0 {
		return 0
	}
	switch opts.Align {
	case "left":
		return 0
	case "right":
		return cell_width - extra_pixels
	default:
		return (cell_width - extra_pixels) / 2
	}
}

func place_cursor(imgd *image_data) {
	cw := int(screen_size.Xpixel) / int(int(screen_size.Col))
	imgd.cell_x_offset = calculate_in_cell_x_offset(imgd.canvas_width, cw)
	num_of_cells_needed := int(math.Ceil(float64(imgd.canvas_width) / float64(cw)))
	if place == nil {
		switch opts.Align {
		case "center":
			imgd.move_x_by = (int(screen_size.Col) - num_of_cells_needed) / 2
		case "right":
			imgd.move_x_by = (int(screen_size.Col) - num_of_cells_needed)
		}
	} else {
		imgd.move_to.x = place.left + 1
		imgd.move_to.y = place.top + 1
		switch opts.Align {
		case "center":
			imgd.move_to.x += (place.width - num_of_cells_needed) / 2
		case "right":
			imgd.move_to.x += (place.width - num_of_cells_needed)
		}
	}
}

func next_random() (ans uint32) {
	for ans == 0 {
		b := make([]byte, 4)
		_, err := rand.Read(b)
		if err == nil {
			ans = binary.LittleEndian.Uint32(b[:])
		} else {
			ans = not_rand.Uint32()
		}
	}
	return ans
}

func transmit_image(imgd *image_data) {
	defer func() {
		for _, frame := range imgd.frames {
			if frame.filename_is_temporary && frame.filename != "" {
				os.Remove(frame.filename)
				frame.filename = ""
			}
			if frame.shm != nil {
				frame.shm.Unlink()
				frame.shm.Close()
				frame.shm = nil
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
		for imgd.image_number == 0 {
			imgd.image_number = next_random()
		}
	}
	place_cursor(imgd)
	fmt.Print("\r")
	if imgd.move_x_by > 0 {
		fmt.Printf("\x1b[%dC", imgd.move_x_by)
	}
	if imgd.move_to.x > 0 {
		fmt.Printf(loop.MoveCursorToTemplate, imgd.move_to.y, imgd.move_to.x)
	}
	frame_control_cmd := graphics.GraphicsCommand{}
	frame_control_cmd.SetAction(graphics.GRT_action_animate).SetImageNumber(imgd.image_number)
	is_animated := len(imgd.frames) > 1

	for frame_num, frame := range imgd.frames {
		err := f(imgd, frame_num, frame)
		if err != nil {
			print_error("\rFailed to transmit %s with error: %v", imgd.source_name, err)
			return
		}
		if is_animated {
			switch frame_num {
			case 0:
				// set gap for the first frame and number of loops for the animation
				c := frame_control_cmd
				c.SetTargetFrame(uint64(frame.number))
				c.SetGap(int32(frame.delay_ms))
				switch {
				case opts.Loop < 0:
					c.SetNumberOfLoops(1)
				case opts.Loop > 0:
					c.SetNumberOfLoops(uint64(opts.Loop) + 1)
				}
				c.WriteWithPayloadTo(os.Stdout, nil)
			case 1:
				c := frame_control_cmd
				c.SetAnimationControl(2) // set animation to loading mode
				c.WriteWithPayloadTo(os.Stdout, nil)
			}
		}
	}
	if is_animated {
		c := frame_control_cmd
		c.SetAnimationControl(3) // set animation to normal mode
		c.WriteWithPayloadTo(os.Stdout, nil)
	}
	if imgd.move_to.x == 0 {
		fmt.Println() // ensure cursor is on new line
	}
}
