package notify

import (
	"encoding/base64"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

const ESC_CODE_PREFIX = "\x1b]99;"
const ESC_CODE_SUFFIX = "\x1b\\"
const CHUNK_SIZE = 4096

func b64encode(x string) string {
	return base64.RawStdEncoding.EncodeToString(utils.UnsafeStringToBytes(x))
}

func create_metadata(opts *Options, wait_till_closed bool, expire_time time.Duration) string {
	ans := []string{}
	if opts.AppName != "" {
		ans = append(ans, "f="+b64encode(opts.AppName))
	}
	switch opts.Urgency {
	case "low":
		ans = append(ans, "u=0")
	case "critical":
		ans = append(ans, "u=2")
	}
	if expire_time >= 0 {
		ans = append(ans, "w="+strconv.FormatInt(expire_time.Milliseconds(), 10))
	}
	if opts.Type != "" {
		ans = append(ans, "t="+b64encode(opts.Type))
	}
	if wait_till_closed {
		ans = append(ans, "c=1")
	}
	m := strings.Join(ans, ":")
	if m != "" {
		m = ":" + m
	}
	return m
}

var debugprintln = tty.DebugPrintln

func generate_chunks(title, body, identifier string, opts *Options, wait_till_closed bool, expire_time time.Duration, callback func(string)) {
	prefix := ESC_CODE_PREFIX + "i=" + identifier
	write_chunk := func(middle string) {
		callback(prefix + middle + ESC_CODE_SUFFIX)
	}

	add_payload := func(payload_type, payload string) {
		p := utils.IfElse(payload_type == "title", "", ":p="+payload_type)
		for len(payload) > 0 {
			chunk := payload[:min(CHUNK_SIZE, len(payload))]
			payload = utils.IfElse(len(payload) > len(chunk), payload[len(chunk):], "")
			enc := b64encode(chunk)
			write_chunk(":d=0:e=1" + p + ";" + enc)
		}
	}
	metadata := create_metadata(opts, wait_till_closed, expire_time)
	write_chunk(":d=0" + metadata + ";")
	add_payload("title", title)
	if body != "" {
		add_payload("body", body)
	}
	write_chunk(";")
}

func run_loop(title, body, identifier string, opts *Options, wait_till_closed bool, expire_time time.Duration) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return err
	}

	lp.OnInitialize = func() (string, error) {
		generate_chunks(title, body, identifier, opts, wait_till_closed, expire_time, func(x string) { lp.QueueWriteString(x) })
		return "", nil
	}
	err = lp.Run()
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
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

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	if len(args) == 0 {
		return 1, fmt.Errorf("Must specify a TITLE for the notification")
	}
	title := args[0]
	if len(title) == 0 {
		return 1, fmt.Errorf("Must specify a non-empty TITLE for the notification")
	}
	body := ""
	if len(args) > 1 {
		body = strings.Join(args[1:], " ")
	}
	ident := opts.Identifier
	if ident == "" {
		if ident, err = random_ident(); err != nil {
			return 1, fmt.Errorf("Failed to generate a random identifier with error: %w", err)
		}
	}
	var expire_time time.Duration
	if expire_time, err = parse_duration(opts.ExpireTime); err != nil {
		return 1, fmt.Errorf("Invalid expire time: %s with error: %w", opts.ExpireTime, err)
	}
	wait_till_closed := opts.WaitTillClosed
	if opts.OnlyPrintEscapeCode {
		generate_chunks(title, body, ident, opts, wait_till_closed, expire_time, func(x string) {
			if err == nil {
				_, err = os.Stdout.WriteString(x)
			}
		})
	} else {
		if opts.PrintIdentifier {
			fmt.Println(ident)
		}
		if wait_till_closed {
			err = run_loop(title, body, ident, opts, wait_till_closed, expire_time)
		} else {
			var term *tty.Term
			if term, err = tty.OpenControllingTerm(); err != nil {
				return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", err)
			}
			generate_chunks(title, body, ident, opts, wait_till_closed, expire_time, func(x string) {
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
