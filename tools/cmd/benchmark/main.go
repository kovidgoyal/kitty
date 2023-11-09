// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package benchmark

import (
	"bytes"
	"fmt"
	"math/rand"
	"strings"
	"sync"
	"time"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

const reset = "\x1b]\x1b\\\x1bc"

type benchmark_options struct {
	alternate_screen bool
	repeat_count     int
}

func default_benchmark_options() benchmark_options {
	return benchmark_options{alternate_screen: true, repeat_count: 10}
}

func benchmark_data(data string, opts benchmark_options) (duration time.Duration, err error) {
	term, err := tty.OpenControllingTerm(tty.SetRaw)
	if err != nil {
		return 0, err
	}
	defer term.RestoreAndClose()
	state := loop.TerminalStateOptions{Alternate_screen: opts.alternate_screen}
	if _, err = term.WriteString(state.SetStateEscapeCodes()); err != nil {
		return 0, err
	}
	defer func() { _, _ = term.WriteString(state.ResetStateEscapeCodes() + reset) }()
	lock := sync.Mutex{}
	const count = 3

	go func() {
		lock.Lock()
		defer lock.Unlock()
		buf := make([]byte, 8192)
		var data []byte
		q := []byte(strings.Repeat("\x1b[0n", count))
		for !bytes.Contains(data, q) {
			n, err := term.Read(buf)
			if err != nil {
				break
			}
			data = append(data, buf[:n]...)
		}
	}()

	start := time.Now()
	repeat_count := opts.repeat_count
	for ; repeat_count > 0; repeat_count-- {
		if _, err = term.WriteString(data); err != nil {
			return 0, err
		}
	}
	if _, err = term.WriteString(strings.Repeat("\x1b[5n", count)); err != nil {
		return 0, err
	}
	lock.Lock()
	duration = time.Since(start) / time.Duration(opts.repeat_count)
	lock.Unlock()
	return duration, nil
}

var rand_src = sync.OnceValue(func() *rand.Rand {
	return rand.New(rand.NewSource(time.Now().UnixNano()))
})

func random_string_of_bytes(n int, alphabet string) string {
	b := make([]byte, n)
	al := len(alphabet)
	src := rand_src()
	for i := 0; i < n; i++ {
		b[i] = alphabet[src.Intn(al)]
	}
	return utils.UnsafeBytesToString(b)
}

type result struct {
	desc     string
	data_sz  int
	duration time.Duration
}

const ascii_printable = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ \n\t\r `~!@#$%^&*()_+-=[]{}\\|;:'\",<.>/?"

func simple_ascii() (r result, err error) {
	data := random_string_of_bytes(1024*1024+13, ascii_printable)
	duration, err := benchmark_data(data, default_benchmark_options())
	if err != nil {
		return result{}, err
	}
	return result{"Simple ascii characters", len(data), duration}, nil
}

func ascii_with_csi() (r result, err error) {
	const sz = 1024 * 1024 * 17
	out := make([]byte, 0, sz+48)
	src := rand_src()
	chunk := ""
	for len(out) < sz {
		q := src.Intn(100)
		switch {
		case (q < 10):
			chunk = random_string_of_bytes(src.Intn(72)+1, ascii_printable)
		case (10 <= q && q < 30):
			chunk = "\x1b[m;\x1b[?1h\x1b[H"
		case (30 <= q && q < 40):
			chunk = "\x1b[1;2;3;4:3;31m"
		case (40 <= q && q < 50):
			chunk = "\x1b[38:5:24;48:2:125:136:147m"
		case (50 <= q && q < 60):
			chunk = "\x1b[58;5;44;2m"
		case (60 <= q && q < 80):
			chunk = "\x1b[m;\x1b[10A\x1b[3E\x1b[2K"
		case (80 <= q && q < 100):
			chunk = "\x1b[39m;\x1b[10`a\x1b[100b\x1b[?1l"
		}
		out = append(out, utils.UnsafeStringToBytes(chunk)...)
	}
	duration, err := benchmark_data(utils.UnsafeBytesToString(out), default_benchmark_options())
	if err != nil {
		return result{}, err
	}
	return result{"CSI codes with ASCII text", len(out), duration}, nil
}

var divs = []time.Duration{
	time.Duration(1), time.Duration(10), time.Duration(100), time.Duration(1000)}

func round(d time.Duration, digits int) time.Duration {
	switch {
	case d > time.Second:
		d = d.Round(time.Second / divs[digits])
	case d > time.Millisecond:
		d = d.Round(time.Millisecond / divs[digits])
	case d > time.Microsecond:
		d = d.Round(time.Microsecond / divs[digits])
	}
	return d
}

func present_result(r result, col_width int) {
	rate := float64(r.data_sz) / float64(r.duration)
	rate *= 1e3
	f := fmt.Sprintf("%%-%ds", col_width)
	fmt.Printf("  "+f+" : %-10v @ \x1b[32m%.1f\x1b[m GiB/s\n", r.desc, round(r.duration, 2), rate)
}

var all_benchamrks = []string{
	"ascii", "csi",
}

func main(args []string) (err error) {
	if len(args) == 0 {
		args = all_benchamrks
	}
	var results []result
	var r result
	if slices.Index(args, "ascii") >= 0 {
		if r, err = simple_ascii(); err != nil {
			return err
		}
		results = append(results, r)
	}

	if slices.Index(args, "csi") >= 0 {
		if r, err = ascii_with_csi(); err != nil {
			return err
		}
		results = append(results, r)
	}

	fmt.Print(reset)
	fmt.Println(
		"These results measure the time it takes the terminal to fully parse all the data sent to it. Some terminals will not render all the data, skipping frames, thereby \"cheating\" in their results. kitty does render all data.")
	fmt.Println()
	fmt.Println("Results:")
	mlen := 10
	for _, r := range results {
		mlen = max(mlen, len(r.desc))
	}
	for _, r := range results {
		present_result(r, mlen)
	}
	return
}

func EntryPoint(root *cli.Command) {
	sc := root.AddSubCommand(&cli.Command{
		Name:             "__benchmark__",
		ShortDescription: "Run various benchmarks",
		HelpText:         "To run only particular benchmarks, specify them on the command line from the set: " + strings.Join(all_benchamrks, ", "),
		Usage:            "[options] [optional benchmark to run ...]",
		Hidden:           true,
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			if err = main(args); err != nil {
				ret = 1
			}
			return
		},
	})
	_ = sc
}
