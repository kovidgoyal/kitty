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

func random_string_of_bytes(n int, alphabet string) string {
	var src = rand.NewSource(time.Now().UnixNano())
	const (
		letterIdxBits = 7                    // 7 bits to represent a letter index
		letterIdxMask = 1<<letterIdxBits - 1 // All 1-bits, as many as letterIdxBits
		letterIdxMax  = 63 / letterIdxBits   // # of letter indices fitting in 63 bits
	)
	b := make([]byte, n)
	// A src.Int63() generates 63 random bits, enough for letterIdxMax characters!
	for i, cache, remain := n-1, src.Int63(), letterIdxMax; i >= 0; {
		if remain == 0 {
			cache, remain = src.Int63(), letterIdxMax
		}
		if idx := int(cache & letterIdxMask); idx < len(alphabet) {
			b[i] = alphabet[idx]
			i--
		}
		cache >>= letterIdxBits
		remain--
	}
	return utils.UnsafeBytesToString(b)
}

type result struct {
	desc     string
	data_sz  int
	duration time.Duration
}

func simple_ascii() (r result, err error) {
	data := random_string_of_bytes(1024*1024+13, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ \n\t\r `~!@#$%^&*()_+-=[]{}\\|;:'\",<.>/?")
	duration, err := benchmark_data(data, default_benchmark_options())
	if err != nil {
		return result{}, err
	}
	return result{"Simple ascii characters", len(data), duration}, nil
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

func present_result(r result) {
	rate := float64(r.data_sz) / float64(r.duration)
	rate *= 1e3
	fmt.Println("\t"+r.desc+":", round(r.duration, 2), fmt.Sprintf("@ %.2fGiB/s", rate))
}

func main() (err error) {
	var results []result
	var r result
	if r, err = simple_ascii(); err != nil {
		return err
	}
	results = append(results, r)

	fmt.Println(reset + "Results:")
	for _, r := range results {
		present_result(r)
	}
	return
}

func EntryPoint(root *cli.Command) {
	sc := root.AddSubCommand(&cli.Command{
		Name:             "__benchmark__",
		ShortDescription: "Run various benchmarks",
		Hidden:           true,
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			if err = main(); err != nil {
				ret = 1
			}
			return
		},
	})
	_ = sc
}
