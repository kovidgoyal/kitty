// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package graphics

import (
	"bytes"
	"compress/zlib"
	"encoding/base64"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/utils/shm"
)

var _ = fmt.Print

const TempTemplate = "kitty-tty-graphics-protocol-*"

func CreateTemp() (*os.File, error) {
	return os.CreateTemp("", TempTemplate)
}

func CreateTempInRAM() (*os.File, error) {
	if shm.SHM_DIR != "" {
		f, err := os.CreateTemp(shm.SHM_DIR, TempTemplate)
		if err == nil {
			return f, err
		}
	}
	return CreateTemp()
}

// Enums {{{
type GRT_a int

const (
	GRT_action_transmit GRT_a = iota
	GRT_action_transmit_and_display
	GRT_action_query
	GRT_action_display
	GRT_action_delete
	GRT_action_frame
	GRT_action_animate
	GRT_action_compose
)

func (self GRT_a) String() string {
	switch self {
	default:
		return "t"
	case GRT_action_transmit_and_display:
		return "T"
	case GRT_action_query:
		return "q"
	case GRT_action_display:
		return "p"
	case GRT_action_delete:
		return "d"
	case GRT_action_frame:
		return "f"
	case GRT_action_animate:
		return "a"
	case GRT_action_compose:
		return "c"
	}
}

func GRT_a_from_string(a string) (ans GRT_a, err error) {
	switch a {
	default:
		err = fmt.Errorf("Not a valid action: %#v", a)
	case "t":
	case "T":
		ans = GRT_action_transmit_and_display
	case "q":
		ans = GRT_action_query
	case "p":
		ans = GRT_action_display
	case "d":
		ans = GRT_action_delete
	case "f":
		ans = GRT_action_frame
	case "a":
		ans = GRT_action_animate
	case "c":
		ans = GRT_action_compose
	}
	return
}

type GRT_q int

const (
	GRT_quiet_noisy GRT_q = iota
	GRT_quiet_only_errors
	GRT_quiet_silent
)

func (self GRT_q) String() string {
	return strconv.Itoa(int(self))
}

func GRT_q_from_string(a string) (ans GRT_q, err error) {
	switch a {
	case "0":
	case "1":
		ans = GRT_quiet_only_errors
	case "2":
		ans = GRT_quiet_silent
	default:
		err = fmt.Errorf("Not a valid quiet value: %#v", a)
	}
	return
}

type GRT_f int

const (
	GRT_format_rgba GRT_f = iota
	GRT_format_rgb
	GRT_format_png
)

func (self GRT_f) String() string {
	switch self {
	default:
		return "32"
	case GRT_format_rgb:
		return "24"
	case GRT_format_png:
		return "100"
	}
}

func GRT_f_from_string(a string) (ans GRT_f, err error) {
	switch a {
	case "32":
	case "24":
		ans = GRT_format_rgb
	case "100":
		ans = GRT_format_png
	default:
		err = fmt.Errorf("Not a valid format value: %#v", a)
	}
	return
}

type GRT_t int

const (
	GRT_transmission_direct GRT_t = iota
	GRT_transmission_file
	GRT_transmission_tempfile
	GRT_transmission_sharedmem
)

func (self GRT_t) String() string {
	switch self {
	default:
		return "d"
	case GRT_transmission_file:
		return "f"
	case GRT_transmission_tempfile:
		return "t"
	case GRT_transmission_sharedmem:
		return "s"
	}
}

func GRT_t_from_string(a string) (ans GRT_t, err error) {
	switch a {
	case "d":
	case "f":
		ans = GRT_transmission_file
	case "t":
		ans = GRT_transmission_tempfile
	case "s":
		ans = GRT_transmission_sharedmem
	default:
		err = fmt.Errorf("Not a valid transmission value: %#v", a)
	}
	return
}

type GRT_o int

const (
	GRT_compression_none GRT_o = iota
	GRT_compression_zlib
)

func (self GRT_o) String() string {
	switch self {
	default:
		return ""
	case GRT_compression_zlib:
		return "z"
	}
}

func GRT_o_from_string(a string) (ans GRT_o, err error) {
	switch a {
	case "":
	case "z":
		ans = GRT_compression_zlib
	default:
		err = fmt.Errorf("Not a valid compression value: %#v", a)
	}
	return
}

type GRT_m int

const (
	GRT_more_nomore GRT_m = iota
	GRT_more_more
)

func (self GRT_m) String() string {
	return strconv.Itoa(int(self))
}

func GRT_m_from_string(a string) (ans GRT_m, err error) {
	switch a {
	case "0":
	case "1":
		ans = GRT_more_more
	default:
		err = fmt.Errorf("Not a valid more value: %#v", a)
	}
	return
}

type GRT_C int

const (
	GRT_cursor_move GRT_C = iota
	GRT_cursor_static
)

func (self GRT_C) String() string {
	return strconv.Itoa(int(self))
}

func GRT_C_from_string(a string) (ans GRT_C, err error) {
	switch a {
	case "0":
	case "1":
		ans = GRT_cursor_static
	default:
		err = fmt.Errorf("Not a valid cursor movement value: %#v", a)
	}
	return
}

type CompositionMode int

const (
	AlphaBlend CompositionMode = iota
	Overwrite
)

func (self CompositionMode) String() string {
	return strconv.Itoa(int(self))
}

func CompositionMode_from_string(a string) (ans CompositionMode, err error) {
	switch a {
	case "0":
	case "1":
		ans = Overwrite
	default:
		err = fmt.Errorf("Not a valid composition mode value: %#v", a)
	}
	return
}

type GRT_d int

const (
	GRT_delete_visible GRT_d = iota
	GRT_free_visible

	GRT_delete_by_id
	GRT_free_by_id

	GRT_delete_by_number
	GRT_free_by_number

	GRT_delete_by_cursor
	GRT_free_by_cursor

	GRT_delete_by_frame
	GRT_free_by_frame

	GRT_delete_by_cell
	GRT_free_by_cell

	GRT_delete_by_cell_zindex
	GRT_free_by_cell_zindex

	GRT_delete_by_column
	GRT_free_by_column

	GRT_delete_by_row
	GRT_free_by_row

	GRT_delete_by_zindex
	GRT_free_by_zindex
)

func (self GRT_d) String() string {
	switch self {
	default:
		return "a"
	case GRT_free_visible:
		return "A"

	case GRT_delete_by_id:
		return "i"
	case GRT_free_by_id:
		return "I"

	case GRT_delete_by_number:
		return "n"
	case GRT_free_by_number:
		return "N"

	case GRT_delete_by_cursor:
		return "c"
	case GRT_free_by_cursor:
		return "C"

	case GRT_delete_by_frame:
		return "f"
	case GRT_free_by_frame:
		return "F"

	case GRT_delete_by_cell:
		return "p"
	case GRT_free_by_cell:
		return "P"

	case GRT_delete_by_cell_zindex:
		return "q"
	case GRT_free_by_cell_zindex:
		return "Q"

	case GRT_delete_by_column:
		return "x"
	case GRT_free_by_column:
		return "X"

	case GRT_delete_by_row:
		return "y"
	case GRT_free_by_row:
		return "Y"

	case GRT_delete_by_zindex:
		return "z"
	case GRT_free_by_zindex:
		return "Z"
	}
}

func GRT_d_from_string(a string) (ans GRT_d, err error) {
	switch a {
	case "a":
		ans = GRT_delete_visible
	case "A":
		ans = GRT_free_visible

	case "i":
		ans = GRT_delete_by_id
	case "I":
		ans = GRT_free_by_id

	case "n":
		ans = GRT_delete_by_number
	case "N":
		ans = GRT_free_by_number

	case "c":
		ans = GRT_delete_by_cursor
	case "C":
		ans = GRT_free_by_cursor

	case "f":
		ans = GRT_delete_by_frame
	case "F":
		ans = GRT_free_by_frame

	case "p":
		ans = GRT_delete_by_cell
	case "P":
		ans = GRT_free_by_cell

	case "q":
		ans = GRT_delete_by_cell_zindex
	case "Q":
		ans = GRT_free_by_cell_zindex

	case "x":
		ans = GRT_delete_by_column
	case "X":
		ans = GRT_free_by_column

	case "y":
		ans = GRT_delete_by_row
	case "Y":
		ans = GRT_free_by_row

	case "z":
		ans = GRT_delete_by_zindex
	case "Z":
		ans = GRT_free_by_zindex

	default:
		err = fmt.Errorf("Not a valid delete value: %#v", a)
	}
	return
}

// }}}

type GraphicsCommand struct {
	a GRT_a
	q GRT_q
	f GRT_f
	t GRT_t
	o GRT_o
	m GRT_m
	C GRT_C
	d GRT_d

	s, v, S, O, x, y, w, h, X, Y, c, r uint64

	i, I, p uint32

	z int32

	response_message string
}

func (self *GraphicsCommand) serialize_non_default_fields() (ans []string) {
	var null GraphicsCommand
	ans = make([]string, 0, 16)

	write_key := func(k byte, val, defval any) {
		if val != defval {
			ans = append(ans, fmt.Sprintf("%c=%v", k, val))
		}
	}

	write_key('a', self.a, null.a)
	write_key('q', self.q, null.q)
	write_key('f', self.f, null.f)
	write_key('t', self.t, null.t)
	write_key('o', self.o, null.o)
	write_key('m', self.m, null.m)
	write_key('C', self.C, null.C)
	write_key('d', self.d, null.d)

	write_key('s', self.s, null.s)
	write_key('v', self.v, null.v)
	write_key('S', self.S, null.S)
	write_key('O', self.O, null.O)
	write_key('x', self.x, null.x)
	write_key('y', self.y, null.y)
	write_key('w', self.w, null.w)
	write_key('h', self.h, null.h)
	write_key('X', self.X, null.X)
	write_key('Y', self.Y, null.Y)
	write_key('c', self.c, null.c)
	write_key('r', self.r, null.r)

	write_key('i', self.i, null.i)
	write_key('I', self.I, null.I)
	write_key('p', self.p, null.p)

	write_key('z', self.z, null.z)
	return
}

func (self GraphicsCommand) String() string {
	return "GraphicsCommand(" + strings.Join(self.serialize_non_default_fields(), ", ") + ")"
}

func (self *GraphicsCommand) WriteMetadata(o io.StringWriter) (err error) {
	items := self.serialize_non_default_fields()
	_, err = o.WriteString(strings.Join(items, ","))
	return
}

func (self *GraphicsCommand) serialize_to(buf io.StringWriter, chunk string) (err error) {
	ws := func(s string) {
		_, err = buf.WriteString(s)
	}
	ws("\033_G")
	if err == nil {
		err = self.WriteMetadata(buf)
		if err == nil {
			if len(chunk) > 0 {
				ws(";")
				if err == nil {
					_, err = buf.WriteString(chunk)
				}
			}
			if err == nil {
				ws("\033\\")
			}
		}
	}
	return
}

func compress_with_zlib(data []byte) []byte {
	var b bytes.Buffer
	b.Grow(len(data) + 128)
	w := zlib.NewWriter(&b)
	w.Write(data)
	w.Close()
	return b.Bytes()
}

func (self *GraphicsCommand) AsAPC(payload []byte) string {
	buf := strings.Builder{}
	buf.Grow(1024)
	self.WriteWithPayloadTo(&buf, payload)
	return buf.String()
}

func (self *GraphicsCommand) WriteWithPayloadTo(o io.StringWriter, payload []byte) (err error) {
	const compression_threshold = 2048
	if len(payload) == 0 {
		return self.serialize_to(o, "")
	}
	if len(payload) <= compression_threshold {
		return self.serialize_to(o, base64.StdEncoding.EncodeToString(payload))
	}
	gc := *self
	if self.Format() != GRT_format_png {
		compressed := compress_with_zlib(payload)
		if len(compressed) < len(payload) {
			gc.SetCompression(GRT_compression_zlib)
			payload = compressed
		}
	}
	data := base64.StdEncoding.EncodeToString(payload)
	for len(data) > 0 && err == nil {
		chunk := data
		if len(data) > 4096 {
			chunk = data[:4096]
			data = data[4096:]
		} else {
			data = ""
		}
		if len(data) > 0 {
			gc.m = GRT_more_more
		} else {
			gc.m = GRT_more_nomore
		}
		err = gc.serialize_to(o, chunk)
		if err != nil {
			return err
		}
		gc = GraphicsCommand{q: self.q, a: self.a}
	}
	return
}

type loop_io_writer struct {
	lp *loop.Loop
}

func (self *loop_io_writer) WriteString(data string) (n int, err error) {
	self.lp.QueueWriteString(data)
	return
}

func (self *GraphicsCommand) WriteWithPayloadToLoop(lp *loop.Loop, payload []byte) (err error) {
	w := loop_io_writer{lp}
	return self.WriteWithPayloadTo(&w, payload)
}

func set_val[T any](loc *T, parser func(string) (T, error), value string) (err error) {
	var temp T
	temp, err = parser(value)
	if err == nil {
		*loc = temp
	}
	return err
}

func set_uval(loc *uint64, value string) (err error) {
	temp, err := strconv.ParseUint(value, 10, 64)
	if err == nil {
		*loc = temp
	}
	return err
}

func set_u32val(loc *uint32, value string) (err error) {
	temp, err := strconv.ParseUint(value, 10, 32)
	if err == nil {
		*loc = uint32(temp)
	}
	return err
}

func set_i32val(loc *int32, value string) (err error) {
	temp, err := strconv.ParseInt(value, 10, 32)
	if err == nil {
		*loc = int32(temp)
	}
	return err
}

func (self *GraphicsCommand) SetString(key byte, value string) (err error) {
	switch key {
	case 'a':
		err = set_val(&self.a, GRT_a_from_string, value)
	case 'q':
		err = set_val(&self.q, GRT_q_from_string, value)
	case 'f':
		err = set_val(&self.f, GRT_f_from_string, value)
	case 't':
		err = set_val(&self.t, GRT_t_from_string, value)
	case 'o':
		err = set_val(&self.o, GRT_o_from_string, value)
	case 'm':
		err = set_val(&self.m, GRT_m_from_string, value)
	case 'C':
		err = set_val(&self.C, GRT_C_from_string, value)
	case 'd':
		err = set_val(&self.d, GRT_d_from_string, value)
	case 's':
		err = set_uval(&self.s, value)
	case 'v':
		err = set_uval(&self.v, value)
	case 'S':
		err = set_uval(&self.S, value)
	case 'O':
		err = set_uval(&self.O, value)
	case 'x':
		err = set_uval(&self.x, value)
	case 'y':
		err = set_uval(&self.y, value)
	case 'w':
		err = set_uval(&self.w, value)
	case 'h':
		err = set_uval(&self.h, value)
	case 'X':
		err = set_uval(&self.X, value)
	case 'Y':
		err = set_uval(&self.Y, value)
	case 'c':
		err = set_uval(&self.c, value)
	case 'r':
		err = set_uval(&self.r, value)
	case 'i':
		err = set_u32val(&self.i, value)
	case 'I':
		err = set_u32val(&self.I, value)
	case 'p':
		err = set_u32val(&self.p, value)
	case 'z':
		err = set_i32val(&self.z, value)
	default:
		return fmt.Errorf("Unknown key: %c", key)
	}
	return
}

func GraphicsCommandFromAPCPayload(raw []byte) *GraphicsCommand {
	const (
		expecting_key int = iota
		expecting_equals
		expecting_value
	)
	state := expecting_key
	var current_key byte
	var value_start_at int
	var payload_start_at int = -1
	var gc GraphicsCommand

	add_key := func(pos int) {
		gc.SetString(current_key, utils.UnsafeBytesToString(raw[value_start_at:pos]))
	}

	for pos, ch := range raw {
		if ch == ';' {
			if state == expecting_value {
				add_key(pos)
			}
			state = expecting_key
			payload_start_at = pos + 1
			break
		}
		switch state {
		case expecting_key:
			current_key = ch
			state = expecting_equals
		case expecting_equals:
			if ch == '=' {
				state = expecting_value
				value_start_at = pos + 1
			} else {
				state = expecting_key
			}
		case expecting_value:
			if ch == ',' {
				add_key(pos)
				state = expecting_key
			}
		}
	}
	if state == expecting_value {
		add_key(len(raw))
	}
	if payload_start_at > -1 {
		payload := raw[payload_start_at:]
		if len(payload) > 0 {
			gc.response_message = string(payload)
		}
	}
	return &gc
}

func GraphicsCommandFromAPC(raw []byte) *GraphicsCommand {
	if len(raw) < 1 || raw[0] != 'G' {
		return nil
	}
	return GraphicsCommandFromAPCPayload(raw[1:])
}

// Getters and Setters {{{
func (self *GraphicsCommand) Action() GRT_a {
	return self.a
}

func (self *GraphicsCommand) SetAction(a GRT_a) *GraphicsCommand {
	self.a = a
	return self
}

func (self *GraphicsCommand) Delete() GRT_d {
	return self.d
}

func (self *GraphicsCommand) SetDelete(d GRT_d) *GraphicsCommand {
	self.d = d
	return self
}

func (self *GraphicsCommand) Quiet() GRT_q {
	return self.q
}

func (self *GraphicsCommand) SetQuiet(q GRT_q) *GraphicsCommand {
	self.q = q
	return self
}

func (self *GraphicsCommand) CursorMovement() GRT_C {
	return self.C
}

func (self *GraphicsCommand) SetCursorMovement(c GRT_C) *GraphicsCommand {
	self.C = c
	return self
}

func (self *GraphicsCommand) Format() GRT_f {
	return self.f
}

func (self *GraphicsCommand) SetFormat(f GRT_f) *GraphicsCommand {
	self.f = f
	return self
}

func (self *GraphicsCommand) Transmission() GRT_t {
	return self.t
}

func (self *GraphicsCommand) SetTransmission(t GRT_t) *GraphicsCommand {
	self.t = t
	return self
}

func (self *GraphicsCommand) Compression() GRT_o {
	return self.o
}

func (self *GraphicsCommand) SetCompression(o GRT_o) *GraphicsCommand {
	self.o = o
	return self
}

func (self *GraphicsCommand) Width() uint64 {
	return self.w
}

func (self *GraphicsCommand) SetWidth(w uint64) *GraphicsCommand {
	self.w = w
	return self
}

func (self *GraphicsCommand) Height() uint64 {
	return self.h
}

func (self *GraphicsCommand) SetHeight(h uint64) *GraphicsCommand {
	self.h = h
	return self
}

func (self *GraphicsCommand) DataWidth() uint64 {
	return self.s
}

func (self *GraphicsCommand) SetDataWidth(w uint64) *GraphicsCommand {
	self.s = w
	return self
}

func (self *GraphicsCommand) DataHeight() uint64 {
	return self.v
}

func (self *GraphicsCommand) SetDataHeight(h uint64) *GraphicsCommand {
	self.v = h
	return self
}

func (self *GraphicsCommand) NumberOfLoops() uint64 {
	return self.v
}

func (self *GraphicsCommand) SetNumberOfLoops(n uint64) *GraphicsCommand {
	self.v = n
	return self
}

func (self *GraphicsCommand) DataSize() uint64 {
	return self.S
}

func (self *GraphicsCommand) SetDataSize(s uint64) *GraphicsCommand {
	self.S = s
	return self
}

func (self *GraphicsCommand) DataOffset() uint64 {
	return self.O
}

func (self *GraphicsCommand) SetDataOffset(o uint64) *GraphicsCommand {
	self.O = o
	return self
}

func (self *GraphicsCommand) LeftEdge() uint64 {
	return self.x
}

func (self *GraphicsCommand) SetLeftEdge(x uint64) *GraphicsCommand {
	self.x = x
	return self
}

func (self *GraphicsCommand) TopEdge() uint64 {
	return self.y
}

func (self *GraphicsCommand) SetTopEdge(y uint64) *GraphicsCommand {
	self.y = y
	return self
}

func (self *GraphicsCommand) SourceLeftEdge() uint64 {
	return self.X
}

func (self *GraphicsCommand) SetSourceLeftEdge(x uint64) *GraphicsCommand {
	self.X = x
	return self
}

func (self *GraphicsCommand) XOffset() uint64 {
	return self.X
}

func (self *GraphicsCommand) SetXOffset(x uint64) *GraphicsCommand {
	self.X = x
	return self
}

func (self *GraphicsCommand) BlendMode() CompositionMode {
	switch self.X {
	case 1:
		return Overwrite
	default:
		return AlphaBlend
	}
}

func (self *GraphicsCommand) SetBlendMode(x CompositionMode) *GraphicsCommand {
	self.X = uint64(x)
	return self
}

func (self *GraphicsCommand) CompositionMode() CompositionMode {
	switch self.C {
	case 1:
		return Overwrite
	default:
		return AlphaBlend
	}
}

func (self *GraphicsCommand) SetCompositionMode(x CompositionMode) *GraphicsCommand {
	switch x {
	case Overwrite:
		self.C = 1
	case AlphaBlend:
		self.C = 0
	}
	return self
}

func (self *GraphicsCommand) YOffset() uint64 {
	return self.Y
}

func (self *GraphicsCommand) SetYOffset(y uint64) *GraphicsCommand {
	self.Y = y
	return self
}

func (self *GraphicsCommand) SourceTopEdge() uint64 {
	return self.Y
}

func (self *GraphicsCommand) SetSourceTopEdge(y uint64) *GraphicsCommand {
	self.Y = y
	return self
}

func (self *GraphicsCommand) BackgroundColor() uint32 {
	return uint32(self.Y)
}

func (self *GraphicsCommand) SetBackgroundColor(y uint32) *GraphicsCommand {
	self.Y = uint64(y)
	return self
}

func (self *GraphicsCommand) Rows() uint64 {
	return self.r
}

func (self *GraphicsCommand) SetRows(r uint64) *GraphicsCommand {
	self.r = r
	return self
}

func (self *GraphicsCommand) Columns() uint64 {
	return self.c
}

func (self *GraphicsCommand) SetColumns(c uint64) *GraphicsCommand {
	self.c = c
	return self
}

func (self *GraphicsCommand) TargetFrame() uint64 {
	return self.r
}

func (self *GraphicsCommand) SetTargetFrame(r uint64) *GraphicsCommand {
	self.r = r
	return self
}

func (self *GraphicsCommand) BaseFrame() uint64 {
	return self.c
}

func (self *GraphicsCommand) SetBaseFrame(c uint64) *GraphicsCommand {
	self.c = c
	return self
}

func (self *GraphicsCommand) OverlaidFrame() uint64 {
	return self.c
}

func (self *GraphicsCommand) SetOverlaidFrame(c uint64) *GraphicsCommand {
	self.c = c
	return self
}

func (self *GraphicsCommand) FrameToMakeCurrent() uint64 {
	return self.c
}

func (self *GraphicsCommand) SetFrameToMakeCurrent(c uint64) *GraphicsCommand {
	self.c = c
	return self
}

func (self *GraphicsCommand) ImageId() uint32 {
	return self.i
}

func (self *GraphicsCommand) SetImageId(i uint32) *GraphicsCommand {
	self.i = i
	return self
}

func (self *GraphicsCommand) ImageNumber() uint32 {
	return self.I
}

func (self *GraphicsCommand) SetImageNumber(n uint32) *GraphicsCommand {
	self.I = n
	return self
}

func (self *GraphicsCommand) PlacementId() uint32 {
	return self.p
}

func (self *GraphicsCommand) SetPlacementId(p uint32) *GraphicsCommand {
	self.p = p
	return self
}

func (self *GraphicsCommand) ZIndex() int32 {
	return self.z
}

func (self *GraphicsCommand) SetZIndex(z int32) *GraphicsCommand {
	self.z = z
	return self
}

func (self *GraphicsCommand) Gap() int32 {
	return self.z
}

func (self *GraphicsCommand) SetGap(z int32) *GraphicsCommand {
	self.z = z
	return self
}

type AnimationControl uint

const (
	NoAnimationAction AnimationControl = iota
	StopAnimation
	RunAnimationButWaitForNewFrames
	RunAnimation
)

func (self *GraphicsCommand) AnimationControl() AnimationControl {
	switch AnimationControl(self.s) {
	default:
		return NoAnimationAction
	case StopAnimation:
		return StopAnimation
	case RunAnimationButWaitForNewFrames:
		return RunAnimationButWaitForNewFrames
	case RunAnimation:
		return RunAnimation
	}

}

func (self *GraphicsCommand) SetAnimationControl(z uint) *GraphicsCommand {
	self.s = uint64(z)
	return self
}

func (self *GraphicsCommand) ResponseMessage() string {
	return self.response_message
}

// }}}
