package dnd

import (
	"errors"
	"fmt"
	"image"
	"io"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/emmansun/base64"
	"github.com/kovidgoyal/imaging"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/streaming_base64"
)

var _ = fmt.Print

type data_request struct {
	drag_source      *drag_source
	send_remote_data bool
	index            int
	write_id         loop.IdType
	base64           streaming_base64.StreamingBase64Encoder
}

type remote_data_item struct {
	path                             string
	metadata                         os.FileInfo
	file                             *os.File
	write_id                         loop.IdType
	base64                           streaming_base64.StreamingBase64Encoder
	parent_dir_handle, idx_in_parent int
	idx_in_uri_list                  int
}

type drag_status struct {
	active                 bool
	terminal_accepted_drag bool
	offered_mimes          []string
	accepted_mime          int
	accepted_operation     int
	dropped                bool
	data_requests          []*data_request
	remote_items           []*remote_data_item
	current_remote_file    *remote_data_item
	dir_handle_counter     int
	remote_item_write_id   loop.IdType
}

func find_drag_image(drag_sources map[string]*drag_source) image.Image {
	for mime, ds := range drag_sources {
		if strings.HasPrefix(mime, "image/") && ds.path != "" {
			q, err := imaging.Open(ds.path)
			if err == nil {
				return q
			}
		}
	}
	var uri_list []string
	if ds := drag_sources["text/uri-list"]; ds != nil && len(ds.data) > 0 {
		if q, err := parse_uri_list(string(ds.data)); err == nil {
			for _, path := range q {
				if path != "" {
					uri_list = append(uri_list, path)
				}
			}
		}
	}
	for _, path := range uri_list {
		q, err := imaging.Open(path)
		if err == nil {
			return q
		}
	}
	// TODO: Try to generate an image based preview using the machinery from the choose-files kitten
	return nil
}

func (dnd *dnd) set_drag_image() (err error) {
	img := dnd.drag_thumbnail
	if img == nil {
		img = find_drag_image(dnd.drag_sources)
	}
	if img == nil {
		return
	}
	num_channels := utils.IfElse(imaging.IsOpaque(img), 3, 4)
	sz := dnd.opts.DragThumbnailSize
	if max(img.Bounds().Dx(), img.Bounds().Dy()) > sz {
		w, h := 0, 0
		if img.Bounds().Dx() >= img.Bounds().Dy() {
			w = sz
		} else {
			h = sz
		}
		img = imaging.ResizeWithOpacity(img, w, h, imaging.Lanczos, num_channels == 3)
		if dnd.drag_thumbnail != nil {
			dnd.drag_thumbnail = img
		}
	}
	var pix []byte
	if imaging.IsOpaque(img) {
		_, pix = 3, imaging.AsRGBData8(img)
	} else {
		pix = imaging.AsRGBAData8(img)
	}
	cmd := DC{
		Type: 'p', X: -1, Y: utils.IfElse(num_channels == 3, 24, 32), Xp: img.Bounds().Dx(), Yp: img.Bounds().Dy(),
		Payload: pix}
	dnd.lp.QueueDnDData(cmd)
	cmd.Payload = nil
	dnd.lp.QueueDnDData(cmd)
	return nil
}

func (dnd *dnd) on_potential_drag_start(cell_x, cell_y int) (err error) {
	if !dnd.allow_drags || dnd.drag_status.active {
		return
	}
	mimes := slices.Collect(maps.Keys(dnd.drag_sources))
	actions := 3
	if dnd.copy_button_region.has(cell_x, cell_y) {
		actions = 1
	} else if dnd.move_button_region.has(cell_x, cell_y) {
		actions = 2
	}
	dnd.lp.QueueDnDData(DC{Type: 'o', Operation: actions, Payload: utils.UnsafeStringToBytes(strings.Join(mimes, " "))})
	total_preloaded_data_sz := 0
	for i, mt := range mimes {
		s := dnd.drag_sources[mt]
		if len(s.data) > 0 && len(s.data)+total_preloaded_data_sz < 64*1024*1024 {
			total_preloaded_data_sz += len(s.data)
			dnd.lp.QueueDnDData(DC{Type: 'p', X: i, Operation: actions, Payload: s.data})
			dnd.lp.QueueDnDData(DC{Type: 'p', X: i, Operation: actions})
		}
	}
	dnd.drag_status.offered_mimes = mimes
	err = dnd.set_drag_image()
	if err != nil {
		dnd.finish_drag("EIO")
		return err
	}
	dnd.lp.QueueDnDData(DC{Type: 'P', X: -1}) // start drag
	dnd.drag_status.active = true

	return dnd.render_screen()
}

func (dnd *dnd) on_drag_error(cmd DC) (err error) {
	payload := string(cmd.Payload)
	switch payload {
	case "OK":
		if dnd.drag_status.active && !dnd.drag_status.terminal_accepted_drag {
			dnd.drag_status.terminal_accepted_drag = true
			err = dnd.render_screen()
		}
	default:
		err = fmt.Errorf("terminal responded with drag source error: %s", payload)
	}
	return
}

func (dnd *dnd) reset_drag() {
	for _, dr := range dnd.drag_status.data_requests {
		if dr.drag_source.file != nil {
			dr.drag_source.file.Close()
			dr.drag_source.file = nil
		}
	}
	if dnd.drag_status.current_remote_file != nil && dnd.drag_status.current_remote_file.file != nil {
		dnd.drag_status.current_remote_file.file.Close()
	}
	dnd.drag_status = drag_status{}
}

func (dnd *dnd) on_drag_event(x, y, operation, Y int) (err error) {
	switch x {
	case 1:
		dnd.drag_status.accepted_mime = y
	case 2:
		dnd.drag_status.accepted_operation = operation
	case 3:
		dnd.drag_status.dropped = true
	case 4:
		dnd.reset_drag()
	case 5:
		if err = dnd.handle_data_request(y, Y == 1); err != nil {
			return err
		}
	}
	return dnd.render_screen()
}

func (dnd *dnd) finish_drag(errname string) {
	if errname == "" { // cancel drag
		dnd.lp.QueueDnDData(DC{Type: 'E', Y: -1})
	} else {
		dnd.lp.QueueDnDData(DC{Type: 'E', Payload: []byte(errname)})
	}
	dnd.reset_drag()
}

func (dnd *dnd) handle_data_request(idx int, send_remote_data bool) (err error) {
	if idx < 0 || idx >= len(dnd.drag_status.offered_mimes) {
		dnd.finish_drag("EINVAL")
		return fmt.Errorf("terminal asked for drag data from MIME list with out of bounds index: %d", idx)
	}
	mime := dnd.drag_status.offered_mimes[idx]
	ds := dnd.drag_sources[mime]
	send_remote_data = send_remote_data && mime == "text/uri-list" && len(ds.uri_list) > 0
	for _, dr := range dnd.drag_status.data_requests {
		if dr.index == idx {
			dnd.finish_drag("EINVAL")
			return fmt.Errorf("terminal sent a duplicate drag data request")
		}
	}
	dr := &data_request{drag_source: ds, send_remote_data: send_remote_data, index: idx}
	if ds.path == "" {
		dnd.lp.QueueDnDData(DC{Type: 'e', Y: idx, Payload: utils.UnsafeStringToBytes(base64.RawStdEncoding.EncodeToString(ds.data))})
		dnd.lp.QueueDnDData(DC{Type: 'e', Y: idx}) // EOF
		if !dr.send_remote_data {
			return
		}
		return dnd.start_remote_data_send(ds)
	} else {
		if ds.file != nil {
			ds.file.Close()
		}
		if ds.file, err = os.Open(ds.path); err != nil {
			dnd.finish_drag("EIO")
			return err
		}
	}
	dnd.drag_status.data_requests = append(dnd.drag_status.data_requests, dr)
	return dnd.send_data_for_data_request(len(dnd.drag_status.data_requests) - 1)
}

var read_buf [64 * 1024]byte
var encode_buf [128 * 1024]byte

func (dnd *dnd) send_data_for_data_request(i int) (err error) {
	dr := dnd.drag_status.data_requests[i]
	n, err := dr.drag_source.file.Read(read_buf[:])
	if n > 0 {
		for chunk := range dr.base64.Encode(read_buf[:n], encode_buf[:]) {
			dr.write_id = dnd.lp.QueueDnDData(DC{Type: 'e', Y: dr.index, Payload: chunk})
		}
	}
	if err == nil {
		return nil
	}
	if errors.Is(err, io.EOF) {
		chunk := dr.base64.Finish()
		if len(chunk) > 0 {
			dr.write_id = dnd.lp.QueueDnDData(DC{Type: 'e', Y: dr.index, Payload: chunk})
		}
		dr.write_id = dnd.lp.QueueDnDData(DC{Type: 'e', Y: dr.index}) // EOF
		return dnd.on_data_request_finished(i)
	}
	dnd.finish_drag("EIO")
	return err
}

func (dnd *dnd) on_send_done(id loop.IdType) (err error) {
	for i, dr := range dnd.drag_status.data_requests {
		if dr.write_id == id {
			return dnd.send_data_for_data_request(i)
		}
	}
	if id == dnd.drag_status.remote_item_write_id {
		if dnd.drag_status.current_remote_file != nil {
			err = dnd.send_next_file_chunk()
		} else {
			err = dnd.next_remote_item()
		}
	}
	return
}

func (dnd *dnd) on_data_request_finished(i int) (err error) {
	dr := dnd.drag_status.data_requests[i]
	if dr.drag_source.file != nil {
		dr.drag_source.file.Close()
		dr.drag_source.file = nil
	}
	dnd.drag_status.data_requests = slices.Delete(dnd.drag_status.data_requests, i, i+1)
	if dr.send_remote_data {
		err = dnd.start_remote_data_send(dr.drag_source)
	} else if len(dnd.drag_status.data_requests) > 0 {
		err = dnd.send_data_for_data_request(0)
	}
	return
}

func (dnd *dnd) send_remote_item_payload(parent_dir_handle, idx_in_parent, idx_in_uri_list, item_type int, payload []byte) loop.IdType {
	cmd := DC{Type: 'k', Xp: item_type, X: idx_in_uri_list + 1}
	if len(payload) > 0 {
		if item_type == 0 {
			cmd.Payload = payload
		} else {
			cmd.Payload = utils.UnsafeStringToBytes(base64.RawStdEncoding.EncodeToString(payload))
		}
	}
	if parent_dir_handle != 0 {
		cmd.Yp = parent_dir_handle
		cmd.Y = idx_in_parent + 1
	}
	return dnd.lp.QueueDnDData(cmd)
}

func (dnd *dnd) send_remote_dir(path string, idx_in_uri_list, parent_dir_handle, idx int) (children []*remote_data_item, err error) {
	entries, err := os.ReadDir(path)
	if err != nil {
		dnd.finish_drag("EIO")
		return nil, err
	}
	handle := dnd.drag_status.dir_handle_counter
	dnd.drag_status.dir_handle_counter++
	names := make([]string, 0, len(entries))
	for i, entry := range entries {
		st, err := entry.Info()
		if err != nil {
			dnd.finish_drag("EIO")
			return nil, err
		}
		x := remote_data_item{
			parent_dir_handle: handle, idx_in_parent: i, metadata: st, idx_in_uri_list: idx_in_uri_list,
			path: filepath.Join(path, entry.Name())}
		children = append(children, &x)
		names = append(names, entry.Name())
	}
	payload := utils.UnsafeStringToBytes(strings.Join(names, "\x00"))
	dnd.send_remote_item_payload(parent_dir_handle, idx, idx_in_uri_list, handle, payload)
	dnd.drag_status.remote_item_write_id = dnd.send_remote_item_payload(parent_dir_handle, idx, idx_in_uri_list, handle, nil)
	return
}

func (dnd *dnd) send_remote_symlink(path string, idx_in_uri_list, parent_dir_handle, idx int) (err error) {
	target, err := os.Readlink(path)
	if err != nil {
		dnd.finish_drag("EIO")
		return err
	}
	dnd.send_remote_item_payload(parent_dir_handle, idx, idx_in_uri_list, 1, utils.UnsafeStringToBytes(target))
	dnd.drag_status.remote_item_write_id = dnd.send_remote_item_payload(parent_dir_handle, idx, idx_in_uri_list, 1, nil)
	return
}

func (dnd *dnd) send_next_file_chunk() (err error) {
	cr := dnd.drag_status.current_remote_file
	if cr == nil {
		return dnd.next_remote_item()
	}
	n, err := cr.file.Read(read_buf[:])
	if n > 0 {
		for chunk := range cr.base64.Encode(read_buf[:n], encode_buf[:]) {
			dnd.drag_status.remote_item_write_id = dnd.send_remote_item_payload(cr.parent_dir_handle, cr.idx_in_parent, cr.idx_in_uri_list, 0, chunk)
		}
	}
	if err != nil {
		if errors.Is(err, io.EOF) {
			cr.file.Close()
			dnd.drag_status.current_remote_file = nil
			if chunk := cr.base64.Finish(); len(chunk) > 0 {
				dnd.send_remote_item_payload(cr.parent_dir_handle, cr.idx_in_parent, cr.idx_in_uri_list, 0, chunk)
			}
			dnd.drag_status.remote_item_write_id = dnd.send_remote_item_payload(cr.parent_dir_handle, cr.idx_in_parent, cr.idx_in_uri_list, 0, nil)
			return nil
		}
		dnd.finish_drag("EIO")
		return err
	}
	return
}

func (dnd *dnd) next_remote_item() (err error) {
	if len(dnd.drag_status.remote_items) < 1 {
		dnd.lp.QueueDnDData(DC{Type: 'k'}) // inform terminal remote data is finished
		if len(dnd.drag_status.data_requests) > 0 {
			err = dnd.send_data_for_data_request(0)
		}
		return
	}
	x := dnd.drag_status.remote_items[0]
	dnd.drag_status.remote_items = dnd.drag_status.remote_items[1:]
	if x.metadata.IsDir() {
		children, err := dnd.send_remote_dir(x.path, x.idx_in_uri_list, x.parent_dir_handle, x.idx_in_parent)
		if err != nil {
			return err
		}
		dnd.drag_status.remote_items = append(dnd.drag_status.remote_items, children...)
	} else if x.metadata.Mode().Type()&os.ModeSymlink != 0 {
		if err = dnd.send_remote_symlink(x.path, x.idx_in_uri_list, x.parent_dir_handle, x.idx_in_parent); err != nil {
			return
		}
	} else {
		if x.file, err = os.Open(x.path); err != nil {
			dnd.finish_drag("EIO")
			return err
		}
		dnd.drag_status.current_remote_file = x
		if err = dnd.send_next_file_chunk(); err != nil {
			return err
		}
	}
	return
}

func (dnd *dnd) start_remote_data_send(ds *drag_source) (err error) {
	dnd.drag_status.dir_handle_counter = 2
	dnd.drag_status.remote_item_write_id = 0
	items := []*remote_data_item{}
	for i, x := range ds.uri_list {
		if x.metadata.IsDir() {
			if children, err := dnd.send_remote_dir(x.path, i, 0, i); err != nil {
				return err
			} else {
				items = append(items, children...)
			}
		} else if x.metadata.Mode().Type()&os.ModeSymlink != 0 {
			if err = dnd.send_remote_symlink(x.path, i, 0, i); err != nil {
				return err
			}
		} else {
			f := remote_data_item{idx_in_parent: i, idx_in_uri_list: i, metadata: x.metadata, path: x.path}
			dnd.drag_status.remote_items = append(dnd.drag_status.remote_items, &f)
		}
	}
	dnd.drag_status.remote_items = append(dnd.drag_status.remote_items, items...)
	if dnd.drag_status.remote_item_write_id == 0 {
		return dnd.next_remote_item()
	}
	return
}
