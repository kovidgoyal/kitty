// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print
var cwd string

const OSC_NUMBER = "5522"

type Output struct {
	arg                    string
	ext                    string
	arg_is_stream          bool
	mime_type              string
	remote_mime_type       string
	image_needs_conversion bool
	is_stream              bool
	dest_is_tty            bool
	dest                   *os.File
	err                    error
	started                bool
	all_data_received      bool
}

func (self *Output) cleanup() {
	if self.dest != nil {
		self.dest.Close()
		if !self.is_stream {
			os.Remove(self.dest.Name())
		}
		self.dest = nil
	}
}

func (self *Output) add_data(data []byte) {
	if self.err != nil {
		return
	}
	if self.dest == nil {
		if !self.image_needs_conversion && self.arg_is_stream {
			self.is_stream = true
			self.dest = os.Stdout
			if self.arg == "/dev/stderr" {
				self.dest = os.Stderr
			}
			self.dest_is_tty = tty.IsTerminal(self.dest.Fd())
		} else {
			d := cwd
			if strings.ContainsRune(self.arg, os.PathSeparator) && !self.arg_is_stream {
				d = filepath.Dir(self.arg)
			}
			f, err := os.CreateTemp(d, "."+filepath.Base(self.arg))
			if err != nil {
				self.err = err
				return
			}
			self.dest = f
		}
		self.started = true
	}
	if self.dest_is_tty {
		data = bytes.ReplaceAll(data, utils.UnsafeStringToBytes("\n"), utils.UnsafeStringToBytes("\r\n"))
	}
	_, self.err = self.dest.Write(data)
}

func (self *Output) write_image(img image.Image) (err error) {
	var output *os.File
	if self.arg_is_stream {
		output = os.Stdout
		if self.arg == "/dev/stderr" {
			output = os.Stderr
		}
	} else {
		output, err = os.Create(self.arg)
		if err != nil {
			return err
		}
	}
	defer func() {
		output.Close()
		if err != nil && !self.arg_is_stream {
			os.Remove(output.Name())
		}
	}()
	return images.Encode(output, img, self.mime_type)
}

func (self *Output) commit() {
	if self.err != nil {
		return
	}
	if self.image_needs_conversion {
		self.dest.Seek(0, io.SeekStart)
		img, _, err := image.Decode(self.dest)
		self.dest.Close()
		os.Remove(self.dest.Name())
		if err == nil {
			err = self.write_image(img)
		}
		if err != nil {
			self.err = fmt.Errorf("Failed to encode image data to %s with error: %w", self.mime_type, err)
		}
	} else {
		self.dest.Close()
		if !self.is_stream {
			f, err := os.OpenFile(self.arg, os.O_CREATE|os.O_RDONLY, 0666)
			if err == nil {
				fi, err := f.Stat()
				if err == nil {
					self.dest.Chmod(fi.Mode().Perm())
				}
				f.Close()
				os.Remove(f.Name())
			}
			self.err = os.Rename(self.dest.Name(), self.arg)
			if self.err != nil {
				os.Remove(self.dest.Name())
				self.err = fmt.Errorf("Failed to rename temporary file used for downloading to destination: %s with error: %w", self.arg, self.err)
			}
		}
	}
	self.dest = nil
}

func (self *Output) assign_mime_type(available_mimes []string, aliases map[string][]string) (err error) {
	if self.mime_type == "." {
		self.remote_mime_type = "."
		return
	}
	if slices.Contains(available_mimes, self.mime_type) {
		self.remote_mime_type = self.mime_type
		return
	}
	if len(aliases[self.mime_type]) > 0 {
		for _, alias := range aliases[self.mime_type] {
			if slices.Contains(available_mimes, alias) {
				self.remote_mime_type = alias
				return
			}
		}
	}
	for _, mt := range available_mimes {
		if matched, _ := filepath.Match(self.mime_type, mt); matched {
			self.remote_mime_type = mt
			return
		}
	}
	if images.EncodableImageTypes[self.mime_type] {
		for _, mt := range available_mimes {
			if images.DecodableImageTypes[mt] {
				self.remote_mime_type = mt
				self.image_needs_conversion = true
				return
			}
		}
	}
	if is_textual_mime(self.mime_type) {
		for _, mt := range available_mimes {
			if mt == "text/plain" {
				self.remote_mime_type = mt
				return
			}
		}
	}
	return fmt.Errorf("The MIME type %s for %s not available on the clipboard", self.mime_type, self.arg)
}

func escape_metadata_value(k, x string) (ans string) {
	if k == "mime" {
		x = base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(x))
	}
	return x
}

func unescape_metadata_value(k, x string) (ans string) {
	if k == "mime" {
		b, err := base64.StdEncoding.DecodeString(x)
		if err == nil {
			x = string(b)
		}
	}
	return x
}

func Encode_bytes(metadata map[string]string, payload []byte) string {
	ans := strings.Builder{}
	enc_payload := ""
	if len(payload) > 0 {
		enc_payload = base64.StdEncoding.EncodeToString(payload)
	}
	ans.Grow(2048 + len(enc_payload))
	ans.WriteString("\x1b]")
	ans.WriteString(OSC_NUMBER)
	ans.WriteString(";")
	for k, v := range metadata {
		if !strings.HasSuffix(ans.String(), ";") {
			ans.WriteString(":")
		}
		ans.WriteString(k)
		ans.WriteString("=")
		ans.WriteString(escape_metadata_value(k, v))
	}
	if len(payload) > 0 {
		ans.WriteString(";")
		ans.WriteString(enc_payload)
	}
	ans.WriteString("\x1b\\")
	return ans.String()
}

func encode(metadata map[string]string, payload string) string {
	return Encode_bytes(metadata, utils.UnsafeStringToBytes(payload))
}

func error_from_status(status string) error {
	switch status {
	case "ENOSYS":
		return fmt.Errorf("no primary selection available on this system")
	case "EPERM":
		return fmt.Errorf("permission denied")
	case "EBUSY":
		return fmt.Errorf("a temporary error occurred, try again later.")
	default:
		return fmt.Errorf("%s", status)
	}
}

func parse_escape_code(etype loop.EscapeCodeType, data []byte) (metadata map[string]string, payload []byte, err error) {
	if etype != loop.OSC || !bytes.HasPrefix(data, utils.UnsafeStringToBytes(OSC_NUMBER+";")) {
		return
	}
	parts := bytes.SplitN(data, utils.UnsafeStringToBytes(";"), 3)
	metadata = make(map[string]string)
	if len(parts) > 2 && len(parts[2]) > 0 {
		payload, err = base64.StdEncoding.DecodeString(utils.UnsafeBytesToString(parts[2]))
		if err != nil {
			err = fmt.Errorf("Received OSC %s packet from terminal with invalid base64 encoded payload", OSC_NUMBER)
			return
		}
	}
	if len(parts) > 1 {
		for _, record := range bytes.Split(parts[1], utils.UnsafeStringToBytes(":")) {
			rp := bytes.SplitN(record, utils.UnsafeStringToBytes("="), 2)
			v := ""
			if len(rp) == 2 {
				v = string(rp[1])
			}
			k := string(rp[0])
			metadata[k] = unescape_metadata_value(k, v)
		}
	}

	return
}

func parse_aliases(raw []string) (map[string][]string, error) {
	ans := make(map[string][]string, len(raw))
	for _, x := range raw {
		k, v, found := strings.Cut(x, "=")
		if !found {
			return nil, fmt.Errorf("%s is not valid MIME alias specification", x)
		}
		ans[k] = append(ans[k], v)
		ans[v] = append(ans[v], k)
	}
	return ans, nil
}

func run_get_loop(opts *Options, args []string) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking, loop.NoInBandResizeNotifications)
	if err != nil {
		return err
	}
	var available_mimes []string
	var wg sync.WaitGroup
	var getting_data_for string
	requested_mimes := make(map[string]*Output)
	reading_available_mimes := true
	outputs := make([]*Output, len(args))
	aliases, merr := parse_aliases(opts.Alias)
	if merr != nil {
		return merr
	}

	for i, arg := range args {
		outputs[i] = &Output{arg: arg, arg_is_stream: arg == "/dev/stdout" || arg == "/dev/stderr", ext: filepath.Ext(arg)}
		if len(opts.Mime) > i {
			outputs[i].mime_type = opts.Mime[i]
		} else {
			if outputs[i].arg_is_stream {
				outputs[i].mime_type = "text/plain"
			} else {
				outputs[i].mime_type = utils.GuessMimeType(outputs[i].arg)
			}
		}
		if outputs[i].mime_type == "" {
			return fmt.Errorf("Could not detect the MIME type for: %s use --mime to specify it manually", arg)
		}
	}

	defer func() {
		for _, o := range outputs {
			if o.dest != nil {
				o.cleanup()
			}
		}
	}()

	basic_metadata := map[string]string{"type": "read"}
	if opts.UsePrimary {
		basic_metadata["loc"] = "primary"
	}
	lp.OnInitialize = func() (string, error) {
		lp.QueueWriteString(encode(basic_metadata, "."))
		if opts.Password != "" {
			basic_metadata["pw"] = base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(opts.Password))
		}
		if opts.HumanName != "" {
			basic_metadata["name"] = base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(opts.HumanName))
		}
		return "", nil
	}

	lp.OnEscapeCode = func(etype loop.EscapeCodeType, data []byte) (err error) {
		metadata, payload, err := parse_escape_code(etype, data)
		if err != nil {
			return err
		}
		if metadata == nil {
			return nil
		}
		if reading_available_mimes {
			switch metadata["status"] {
			case "DATA":
				available_mimes = utils.Map(strings.TrimSpace, strings.Split(utils.UnsafeBytesToString(payload), " "))
			case "OK":
			case "DONE":
				reading_available_mimes = false
				if len(available_mimes) == 0 {
					return fmt.Errorf("The clipboard is empty")
				}
				for _, o := range outputs {
					err = o.assign_mime_type(available_mimes, aliases)
					if err != nil {
						return err
					}
					if o.remote_mime_type == "." {
						o.started = true
						o.add_data(utils.UnsafeStringToBytes(strings.Join(available_mimes, "\n")))
						o.all_data_received = true
					} else {
						requested_mimes[o.remote_mime_type] = o
					}
				}
				if len(requested_mimes) > 0 {
					lp.QueueWriteString(encode(basic_metadata, strings.Join(utils.Keys(requested_mimes), " ")))
				} else {
					lp.Quit(0)
				}
			default:
				return fmt.Errorf("Failed to read list of available data types in the clipboard with error: %w", error_from_status(metadata["status"]))
			}
		} else {
			switch metadata["status"] {
			case "DATA":
				current_mime := metadata["mime"]
				o := requested_mimes[current_mime]
				if o != nil {
					if getting_data_for != current_mime {
						if prev := requested_mimes[getting_data_for]; prev != nil && !prev.all_data_received {
							prev.all_data_received = true
							wg.Add(1)
							go func() {
								prev.commit()
								wg.Done()
							}()

						}
						getting_data_for = current_mime
					}
					if !o.all_data_received {
						o.add_data(payload)
					}
				}
			case "OK":
			case "DONE":
				if prev := requested_mimes[getting_data_for]; getting_data_for != "" && prev != nil && !prev.all_data_received {
					prev.all_data_received = true
					wg.Add(1)
					go func() {
						prev.commit()
						wg.Done()
					}()
					getting_data_for = ""
				}
				lp.Quit(0)
			default:
				return fmt.Errorf("Failed to read data from the clipboard with error: %w", error_from_status(metadata["status"]))
			}
		}
		return
	}

	esc_count := 0
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			esc_count++
			if esc_count < 2 {
				key := "Esc"
				if event.MatchesPressOrRepeat("ctrl+c") {
					key = "Ctrl+C"
				}
				lp.QueueWriteString(fmt.Sprintf("Waiting for response from terminal, press %s again to abort. This could cause garbage to be spewed to the screen.\r\n", key))
			} else {
				return fmt.Errorf("Aborted by user!")
			}
		}
		return nil
	}

	err = lp.Run()
	wg.Wait()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}
	for _, o := range outputs {
		if o.err != nil {
			err = fmt.Errorf("Failed to get %s with error: %w", o.arg, o.err)
			return
		}
		if !o.started {
			err = fmt.Errorf("No data for %s with MIME type: %s", o.arg, o.mime_type)
			return
		}
	}

	return
}
