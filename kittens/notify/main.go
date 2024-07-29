package notify

import (
	"encoding/base64"
	"fmt"
	"os"
	"strconv"
	"strings"

	"kitty/tools/cli"
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

func create_metadata(opts *Options) string {
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
	if opts.ExpireTime >= 0 {
		ans = append(ans, "w="+strconv.Itoa(opts.ExpireTime))
	}
	if opts.Type != "" {
		ans = append(ans, "t="+b64encode(opts.Type))
	}
	if opts.WaitTillClosed {
		ans = append(ans, "c=1")
	}
	m := strings.Join(ans, ":")
	if m != "" {
		m = ":" + m
	}
	return m
}

func generate_chunks(title, body, identifier string, opts *Options, wait_till_closed bool, callback func(string)) {
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
			write_chunk(":d=0" + p + ";" + enc)
		}
	}
	metadata := create_metadata(opts)
	write_chunk(":d=0" + metadata + ";")
	add_payload("title", title)
	if body != "" {
		add_payload("body", body)
	}
	write_chunk(";")
}

func run_loop(title, body, identifier string, opts *Options, wait_till_closed bool) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return err
	}

	lp.OnInitialize = func() (string, error) {
		generate_chunks(title, body, identifier, opts, wait_till_closed, func(x string) { lp.QueueWriteString(x) })
		return "", nil
	}
}

func random_ident() (string, error) {
	return utils.HumanUUID4()
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
	wait_till_closed := opts.WaitTillClosed
	if opts.OnlyPrintEscapeCode {
		generate_chunks(title, body, ident, opts, wait_till_closed, func(x string) {
			if err == nil {
				_, err = os.Stdout.WriteString(x)
			}
		})
	} else {
		if opts.PrintIdentifier {
			fmt.Println(ident)
		}
		err = run_loop(title, body, ident, opts, wait_till_closed)
	}
	if err != nil {
		rc = 1
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
