package notify

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"io"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const ESC_CODE_PREFIX = "\x1b]99;"
const ESC_CODE_SUFFIX = "\x1b\\"
const CHUNK_SIZE = 4096

func b64encode(x string) string {
	return base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(x))
}

func check_id_valid(x string) bool {
	pat := utils.MustCompile(`[^a-zA-Z0-9_+.-]`)
	return pat.ReplaceAllString(x, "") == x
}

type parsed_data struct {
	opts                    *Options
	wait_till_closed        bool
	expire_time             time.Duration
	title, body, identifier string
	image_data              []byte
	initial_msg             string
}

func (p *parsed_data) create_metadata() string {
	ans := []string{}
	if p.opts.AppName != "" {
		ans = append(ans, "f="+b64encode(p.opts.AppName))
	}
	switch p.opts.Urgency {
	case "low":
		ans = append(ans, "u=0")
	case "critical":
		ans = append(ans, "u=2")
	}
	if p.expire_time >= 0 {
		ans = append(ans, "w="+strconv.FormatInt(p.expire_time.Milliseconds(), 10))
	}
	if p.opts.Type != "" {
		ans = append(ans, "t="+b64encode(p.opts.Type))
	}
	if p.wait_till_closed {
		ans = append(ans, "c=1:a=report")
	}
	for _, x := range p.opts.Icon {
		ans = append(ans, "n="+b64encode(x))
	}
	if p.opts.IconCacheId != "" {
		ans = append(ans, "g="+p.opts.IconCacheId)
	}
	if p.opts.SoundName != "system" {
		ans = append(ans, "s="+b64encode(p.opts.SoundName))
	}
	m := strings.Join(ans, ":")
	if m != "" {
		m = ":" + m
	}
	return m
}

var debugprintln = tty.DebugPrintln

func (p *parsed_data) generate_chunks(callback func(string)) {
	prefix := ESC_CODE_PREFIX + "i=" + p.identifier
	write_chunk := func(middle string) {
		callback(prefix + middle + ESC_CODE_SUFFIX)
	}

	add_payload := func(payload_type, payload string) {
		if payload == "" {
			return
		}
		p := utils.IfElse(payload_type == "title", "", ":p="+payload_type)
		payload = b64encode(payload)
		for len(payload) > 0 {
			chunk := payload[:min(CHUNK_SIZE, len(payload))]
			payload = utils.IfElse(len(payload) > len(chunk), payload[len(chunk):], "")
			write_chunk(":d=0:e=1" + p + ";" + chunk)
		}
	}
	metadata := p.create_metadata()
	write_chunk(":d=0" + metadata + ";")
	add_payload("title", p.title)
	add_payload("body", p.body)
	if len(p.image_data) > 0 {
		add_payload("icon", utils.UnsafeBytesToString(p.image_data))
	}
	if len(p.opts.Button) > 0 {
		add_payload("buttons", strings.Join(p.opts.Button, "\u2028"))
	}
	write_chunk(";")
}

func (p *parsed_data) run_loop() (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking, loop.NoInBandResizeNotifications)
	if err != nil {
		return err
	}
	activated := -1
	prefix := ESC_CODE_PREFIX + "i=" + p.identifier

	poll_for_close := func() {
		lp.AddTimer(time.Millisecond*50, false, func(_ loop.IdType) error {
			lp.QueueWriteString(prefix + ":p=alive;" + ESC_CODE_SUFFIX)
			return nil
		})
	}
	lp.OnInitialize = func() (string, error) {
		if p.initial_msg != "" {
			return p.initial_msg, nil
		}
		p.generate_chunks(func(x string) { lp.QueueWriteString(x) })
		return "", nil
	}
	lp.OnEscapeCode = func(ect loop.EscapeCodeType, data []byte) error {
		if ect == loop.OSC && bytes.HasPrefix(data, []byte(ESC_CODE_PREFIX[2:])) {
			raw := utils.UnsafeBytesToString(data[len(ESC_CODE_PREFIX[2:]):])
			metadata, payload, _ := strings.Cut(raw, ";")
			sent_identifier, payload_type := "", ""
			for _, x := range strings.Split(metadata, ":") {
				key, val, _ := strings.Cut(x, "=")
				switch key {
				case "i":
					sent_identifier = val
				case "p":
					payload_type = val
				}
			}
			if sent_identifier == p.identifier {
				switch payload_type {
				case "close":
					if payload == "untracked" {
						poll_for_close()
					} else {
						lp.Quit(0)
					}
				case "alive":
					live_ids := strings.Split(payload, ",")
					if slices.Contains(live_ids, p.identifier) {
						poll_for_close()
					} else {
						lp.Quit(0)
					}
				case "":
					if activated, err = strconv.Atoi(utils.IfElse(payload == "", "0", payload)); err != nil {
						return fmt.Errorf("Got invalid activation response from terminal: %#v", payload)
					}
				}
			}
		}
		return nil
	}
	close_requested := 0
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			switch close_requested {
			case 0:
				lp.QueueWriteString(prefix + ":p=close;" + ESC_CODE_SUFFIX)
				lp.Println("Closing notification, please wait...")
				close_requested++
			case 1:
				key := "Esc"
				if event.MatchesPressOrRepeat("ctrl+c") {
					key = "Ctrl+C"
				}
				lp.Println(fmt.Sprintf("Waiting for response from terminal, press the %s key again to abort. Note that this might result in garbage being printed to the terminal.", key))
				close_requested++
			default:
				return fmt.Errorf("Aborted by user!")
			}
		}
		return nil
	}

	err = lp.Run()
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}
	if activated > -1 && err == nil {
		fmt.Println(activated)
	}
	return
}

func random_ident() (string, error) {
	return utils.HumanUUID4()
}

func parse_duration(x string) (ans time.Duration, err error) {
	switch x {
	case "never":
		return 0, nil
	case "":
		return -1, nil
	}
	trailer := x[len(x)-1]
	multipler := time.Second
	switch trailer {
	case 's':
		x = x[:len(x)-1]
	case 'm':
		x = x[:len(x)-1]
		multipler = time.Minute
	case 'h':
		x = x[:len(x)-1]
		multipler = time.Hour
	case 'd':
		x = x[:len(x)-1]
		multipler = time.Hour * 24
	}
	val, err := strconv.ParseFloat(x, 64)
	if err != nil {
		return ans, err
	}
	ans = time.Duration(float64(multipler) * val)
	return
}

func (p *parsed_data) load_image_data() (err error) {
	if p.opts.IconPath == "" {
		return nil
	}
	f, err := os.Open(p.opts.IconPath)
	if err != nil {
		return err
	}
	defer f.Close()
	_, imgfmt, err := image.DecodeConfig(f)
	if _, err = f.Seek(0, io.SeekStart); err != nil {
		return err
	}
	if err == nil && imgfmt != "" && strings.Contains("jpeg jpg gif png", strings.ToLower(imgfmt)) {
		p.image_data, err = io.ReadAll(f)
		return
	}
	return fmt.Errorf("The icon must be in PNG, JPEG or GIF formats")
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	if len(args) == 0 {
		return 1, fmt.Errorf("Must specify a TITLE for the notification")
	}
	var p parsed_data
	p.opts = opts
	p.title = args[0]
	if len(args) > 1 {
		p.body = strings.Join(args[1:], " ")
	}
	ident := opts.Identifier
	if ident == "" {
		if ident, err = random_ident(); err != nil {
			return 1, fmt.Errorf("Failed to generate a random identifier with error: %w", err)
		}
	}
	bad_ident := func(which string) error {
		return fmt.Errorf("Invalid identifier: %s must be only English letters, numbers, hyphens and underscores.", which)
	}
	if !check_id_valid(ident) {
		return 1, bad_ident(ident)
	}
	p.identifier = ident
	if !check_id_valid(opts.IconCacheId) {
		return 1, bad_ident(opts.IconCacheId)
	}
	if len(p.title) == 0 {
		if ident == "" {
			return 1, fmt.Errorf("Must specify a non-empty TITLE for the notification or specify an identifier to close a notification.")
		}
		msg := ESC_CODE_PREFIX + "i=" + ident + ":p=close;" + ESC_CODE_SUFFIX
		if opts.OnlyPrintEscapeCode {
			_, err = os.Stdout.WriteString(msg)
		} else if p.wait_till_closed {
			p.initial_msg = msg
			err = p.run_loop()
		} else {
			var term *tty.Term
			if term, err = tty.OpenControllingTerm(); err != nil {
				return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", err)
			}
			if _, err = term.WriteString(msg); err != nil {
				term.RestoreAndClose()
				return 1, err
			}
			term.RestoreAndClose()
		}
	}
	if p.expire_time, err = parse_duration(opts.ExpireAfter); err != nil {
		return 1, fmt.Errorf("Invalid expire time: %s with error: %w", opts.ExpireAfter, err)
	}
	p.wait_till_closed = opts.WaitTillClosed
	if err = p.load_image_data(); err != nil {
		return 1, fmt.Errorf("Failed to load image data from %s with error %w", opts.IconPath, err)
	}
	if opts.OnlyPrintEscapeCode {
		p.generate_chunks(func(x string) {
			if err == nil {
				_, err = os.Stdout.WriteString(x)
			}
		})
	} else {
		if opts.PrintIdentifier {
			fmt.Println(ident)
		}
		if p.wait_till_closed {
			err = p.run_loop()
		} else {
			var term *tty.Term
			if term, err = tty.OpenControllingTerm(); err != nil {
				return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", err)
			}
			p.generate_chunks(func(x string) {
				if err == nil {
					_, err = term.WriteString(x)
				}
			})
			term.RestoreAndClose()
		}

	}
	if err != nil {
		rc = 1
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
