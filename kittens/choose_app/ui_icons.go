// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"image"
	_ "image/png"
	"math/rand/v2"
	"os"
	"runtime"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print

// A rendered icon ready for display
type icon_info struct {
	// The path to the rendered icon, a PNG file
	path          string
	width, height int
}

// icon_loader finds and renders icons in the background
type icon_loader struct {
	mutex sync.Mutex
	// incremented for every request to load icons, used to cancel previous requests
	request int
	// incremented whenever the loaded icons are discarded
	epoch  int
	theme  string
	px     int
	icons  map[string]icon_info // icon name -> rendered icon
	errors []error
}

func (l *icon_loader) get(name string) (icon_info, bool) {
	l.mutex.Lock()
	defer l.mutex.Unlock()
	ans, found := l.icons[name]
	return ans, found
}

func (l *icon_loader) Epoch() int {
	l.mutex.Lock()
	defer l.mutex.Unlock()
	return l.epoch
}

func (l *icon_loader) Errors() []error {
	l.mutex.Lock()
	defer l.mutex.Unlock()
	return l.errors
}

// load starts loading the icons for the specified names at the specified size
// in pixels. names should be in order of priority. theme_for is called in a
// background goroutine as it can be slow. If the theme and size are unchanged
// from the previous load, nothing is done, otherwise the previously loaded
// icons are discarded. wakeup is called from a background goroutine whenever
// an icon becomes available.
func (l *icon_loader) load(dirs *XDGDirs, renderer *IconRenderer, theme_for func() string, px int, names []string, wakeup func()) {
	l.mutex.Lock()
	l.request++
	request := l.request
	l.mutex.Unlock()
	names = utils.Uniq(utils.Filter(names, func(x string) bool { return x != "" }))
	go func() {
		theme := theme_for()
		l.mutex.Lock()
		if l.request != request || (l.icons != nil && l.theme == theme && l.px == px) {
			l.mutex.Unlock()
			return
		}
		l.epoch++
		epoch := l.epoch
		l.theme, l.px, l.icons, l.errors = theme, px, map[string]icon_info{}, nil
		l.mutex.Unlock()
		wakeup()
		paths := find_icon_paths(dirs, theme, px, names)
		jobs := make(chan string, len(names))
		for _, n := range names {
			if _, found := paths[n]; found {
				jobs <- n
			}
		}
		close(jobs)
		var wg sync.WaitGroup
		for range max(1, runtime.NumCPU()) {
			wg.Go(func() {
				for name := range jobs {
					rendered, err := renderer.Render(paths[name], px)
					var ii icon_info
					if err == nil {
						ii, err = read_icon_info(rendered)
					}
					l.mutex.Lock()
					if l.epoch != epoch {
						// the icons have since been reloaded
						l.mutex.Unlock()
						return
					}
					if err == nil {
						l.icons[name] = ii
					} else {
						l.errors = append(l.errors, fmt.Errorf("failed to render the icon %s with error: %w", paths[name], err))
					}
					l.mutex.Unlock()
					if err == nil {
						wakeup()
					}
				}
			})
		}
		wg.Wait()
	}()
}

func read_icon_info(path string) (ans icon_info, err error) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	cfg, _, err := image.DecodeConfig(f)
	if err != nil {
		return ans, fmt.Errorf("%s is not a valid image: %w", path, err)
	}
	if cfg.Width < 1 || cfg.Height < 1 {
		return ans, fmt.Errorf("%s has zero size", path)
	}
	return icon_info{path: path, width: cfg.Width, height: cfg.Height}, nil
}

// icon_display handles transmitting icons to the terminal and placing them
type icon_display struct {
	running_in_tmux bool
	// Whether the terminal has responded to the graphics protocol query,
	// if it never does, it does not support the protocol
	detection_done  bool
	files_supported bool
	detection_id    uint32
	temp_files      []string

	next_id     uint32
	transmitted map[string]uint32 // rendered icon path -> image id
	// placements made in the previous and current renders, the same image
	// can be placed multiple times, as applications can share icons
	placed, placing *utils.Set[placement_key]
}

type placement_key struct {
	image_id, placement_id uint32
}

func (d *icon_display) new_command() *graphics.GraphicsCommand {
	gc := &graphics.GraphicsCommand{}
	if d.running_in_tmux {
		gc.WrapPrefix = "\033Ptmux;"
		gc.WrapSuffix = "\033\\"
		gc.EncodeSerializedDataFunc = func(x string) string { return strings.ReplaceAll(x, "\033", "\033\033") }
	}
	return gc
}

func (d *icon_display) Initialize(lp *loop.Loop) {
	// Use ids unlikely to collide with images from other programs
	d.next_id = 1 + uint32(rand.Int32N(1<<24))<<6
	d.transmitted = map[string]uint32{}
	d.placed, d.placing = utils.NewSet[placement_key](), utils.NewSet[placement_key]()
	if tui.TmuxSocketAddress() != "" && tui.TmuxAllowPassthrough() == nil {
		// Transmission by file cannot be detected through tmux
		d.running_in_tmux, d.detection_done = true, true
		return
	}
	tf, err := images.CreateTempInRAM()
	if err != nil {
		d.detection_done = true
		return
	}
	defer tf.Close()
	d.temp_files = append(d.temp_files, tf.Name())
	if _, err = tf.Write([]byte{1, 2, 3}); err != nil {
		d.detection_done = true
		return
	}
	d.detection_id = d.next_id
	d.next_id++
	gc := d.new_command()
	gc.SetTransmission(graphics.GRT_transmission_tempfile).SetAction(graphics.GRT_action_query).SetImageId(d.detection_id).SetDataWidth(1).SetDataHeight(1).SetFormat(graphics.GRT_format_rgb)
	_ = gc.WriteWithPayloadToLoop(lp, []byte(tf.Name()))
}

// HandleGraphicsCommand processes responses from the terminal, returning
// true if a redraw is needed
func (d *icon_display) HandleGraphicsCommand(gc *graphics.GraphicsCommand) bool {
	if gc.ImageId() == d.detection_id && !d.detection_done {
		d.detection_done = true
		d.files_supported = gc.ResponseMessage() == "OK"
		return true
	}
	return false
}

func (d *icon_display) CanDisplay() bool { return d.detection_done }

func (d *icon_display) Cleanup() {
	for _, f := range d.temp_files {
		_ = os.Remove(f)
	}
}

// Finalize frees all transmitted images from the terminal
func (d *icon_display) Finalize(lp *loop.Loop) {
	for _, id := range d.transmitted {
		_ = d.new_command().SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_free_by_id).SetImageId(id).SetQuiet(graphics.GRT_quiet_silent).WriteWithPayloadToLoop(lp, nil)
	}
	d.transmitted = map[string]uint32{}
}

// Forget discards transmitted images, for example, when the icons are reloaded
func (d *icon_display) Forget(lp *loop.Loop) {
	d.Finalize(lp)
	d.placed.Clear()
}

func (d *icon_display) transmit(lp *loop.Loop, ii icon_info) (id uint32, err error) {
	if id = d.transmitted[ii.path]; id > 0 {
		return
	}
	id = d.next_id
	d.next_id++
	gc := d.new_command()
	gc.SetAction(graphics.GRT_action_transmit).SetImageId(id).SetFormat(graphics.GRT_format_png).SetQuiet(graphics.GRT_quiet_silent)
	if d.files_supported {
		gc.SetTransmission(graphics.GRT_transmission_file)
		err = gc.WriteWithPayloadToLoop(lp, []byte(ii.path))
	} else {
		var data []byte
		if data, err = os.ReadFile(ii.path); err != nil {
			return 0, err
		}
		gc.SetTransmission(graphics.GRT_transmission_direct)
		// Large escape codes must not be sent inside an atomic update
		atomic := lp.IsAtomicUpdateActive()
		lp.EndAtomicUpdate()
		err = gc.WriteWithPayloadToLoop(lp, data)
		if atomic {
			lp.StartAtomicUpdate()
		}
	}
	if err != nil {
		return 0, err
	}
	d.transmitted[ii.path] = id
	return id, nil
}

// StartRender must be called before placing icons for a render
func (d *icon_display) StartRender() {
	d.placing.Clear()
}

// Place displays the icon with its top left corner in the specified cell
// (zero based), scaled to fit in a box of the specified size in cells,
// centered. placement_id must be unique among the icons on screen and
// non-zero. The first skip_rows rows of the box are not drawn, for boxes
// that start above the area in which they are displayed, as images cannot
// be placed above the screen.
func (d *icon_display) Place(lp *loop.Loop, ii icon_info, placement_id uint32, x, y, width_cells, height_cells, skip_rows int, sz loop.ScreenSize) error {
	if skip_rows >= height_cells {
		return nil
	}
	id, err := d.transmit(lp, ii)
	if err != nil {
		return err
	}
	cw, ch := max(1, int(sz.CellWidth)), max(1, int(sz.CellHeight))
	box_w, box_h := width_cells*cw, height_cells*ch
	// The top of the part of the box that is drawn, in pixels
	visible_top := skip_rows * ch
	gc := d.new_command()
	gc.SetAction(graphics.GRT_action_display).SetImageId(id).SetPlacementId(placement_id).SetCursorMovement(graphics.GRT_cursor_static).SetQuiet(graphics.GRT_quiet_silent)
	// The terminal scales the image to exactly fill the specified number of
	// rows or columns, preserving the aspect ratio when only one is
	// specified. When part of the image is not drawn, only the rest of it
	// is placed, using a source rectangle.
	if ii.width*box_h <= ii.height*box_w {
		// fills the height, center horizontally
		left := (box_w - ii.width*box_h/ii.height) / 2
		x += left / cw
		gc.SetXOffset(uint64(left % cw))
		if skip_rows > 0 {
			src_top := visible_top * ii.height / box_h
			gc.SetTopEdge(uint64(src_top)).SetHeight(uint64(ii.height - src_top))
			y += skip_rows
		}
		gc.SetRows(uint64(height_cells - skip_rows))
	} else {
		// fills the width, center vertically
		height := ii.height * box_w / ii.width
		top := (box_h - height) / 2
		if top >= visible_top {
			y += top / ch
			gc.SetYOffset(uint64(top % ch))
		} else {
			src_top := (visible_top - top) * ii.height / max(1, height)
			gc.SetTopEdge(uint64(src_top)).SetHeight(uint64(max(1, ii.height-src_top)))
			y += skip_rows
		}
		gc.SetColumns(uint64(width_cells))
	}
	lp.MoveCursorTo(x+1, y+1)
	if err = gc.WriteWithPayloadToLoop(lp, nil); err != nil {
		return err
	}
	k := placement_key{id, placement_id}
	d.placing.Add(k)
	// Icons are also placed between renders, as the grid is scrolled, so
	// that FinishRender() can remove them if they are not placed again
	d.placed.Add(k)
	return nil
}

// FinishRender removes the placements of icons that were not placed in this render
func (d *icon_display) FinishRender(lp *loop.Loop) {
	for k := range d.placed.Iterable() {
		if !d.placing.Has(k) {
			_ = d.new_command().SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_delete_by_id).SetImageId(k.image_id).SetPlacementId(k.placement_id).SetQuiet(graphics.GRT_quiet_silent).WriteWithPayloadToLoop(lp, nil)
		}
	}
	d.placed, d.placing = d.placing, d.placed
}
