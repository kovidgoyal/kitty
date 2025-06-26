package choose_files

import (
	"fmt"
	"io/fs"
	"math/rand"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func TestAsLower(t *testing.T) {
	buf := [512]byte{}
	for _, q := range []string{
		"abc", "aBc", "aBCCf83Dx", "mOoseÇa", "89ÇĞxxA", "", "23", "aIİBc",
	} {
		n := as_lower(q, buf[:])
		actual := utils.UnsafeBytesToString(buf[:n])
		if diff := cmp.Diff(strings.ToLower(q), actual); diff != "" {
			t.Fatalf("Failed to lowercase: %#v\n%s", q, diff)
		}
	}
}

type node struct {
	name     string
	children map[string]*node
}

func (n node) Name() string {
	return n.name
}

func (n node) IsDir() bool {
	return n.children != nil
}

func (n node) String() string {
	return fmt.Sprintf("{name: %s num_children: %d}", n.name, len(n.children))
}

func (n node) Type() fs.FileMode {
	if n.children == nil {
		return 0
	}
	return fs.ModeDir
}

func (n node) Info() (fs.FileInfo, error) {
	return nil, fmt.Errorf("Info() not implemented")
}

func random_name(r *rand.Rand) string {
	length := 3 + r.Intn(23)
	bytes := make([]byte, length)
	for i := range length {
		bytes[i] = byte(r.Intn(26) + 'a')
	}
	return string(bytes)
}

func (n *node) generate_random_tree(depth, breadth int) {
	r := rand.New(rand.NewSource(111))
	n.children = make(map[string]*node)
	for range breadth {
		c := &node{name: random_name(r)}
		n.children[c.name] = c
		if depth > 0 && r.Intn(10) < 3 {
			c.generate_random_tree(depth-1, breadth)
		}
	}
}

func (n node) dir_entries() []fs.DirEntry {
	entries := make([]fs.DirEntry, 0, len(n.children))
	for _, v := range n.children {
		entries = append(entries, v)
	}
	return entries
}

func (n node) ReadDir(name string) ([]fs.DirEntry, error) {
	if name == string(os.PathSeparator) {
		return n.dir_entries(), nil
	}
	p := &n
	for _, x := range strings.Split(strings.Trim(name, string(os.PathSeparator)), string(os.PathSeparator)) {
		c, found := p.children[x]
		if !found {
			return nil, fs.ErrNotExist
		}
		if !c.IsDir() {
			return nil, fs.ErrExist
		}
		p = c
	}
	return p.dir_entries(), nil
}

func TestChooseFilesScoring(t *testing.T) {
	root := node{name: string(os.PathSeparator), children: map[string]*node{
		"b": {name: "b"},
		"a": {name: "a"},
		"c": {name: "c"},
		"x": {name: "x", children: map[string]*node{
			"1": {"1", nil}, "2": {"2", nil}, "3": {"3", nil},
			"s": {"s", map[string]*node{
				"m": {"m", nil}, "n": {"n", nil},
			}},
		}},
		"y": {name: "y", children: map[string]*node{
			"3": {"3", nil}, "4": {"4", nil}, "5": {"5", nil},
		}},
	}}
	wg := sync.WaitGroup{}
	wg.Add(1)
	s := NewFileSystemScorer(string(os.PathSeparator), "", false, func(err error, is_complete bool) {
		if is_complete {
			wg.Done()
		}
	})
	sc := NewFileSystemScanner(s.root_dir, make(chan bool))
	s.scanner = sc
	sc.dir_reader = root.ReadDir
	s.scanner.Start()
	s.Start()
	wg.Wait()
	results := func() (ans []string) {
		rr, _ := s.Results()
		for _, r := range rr {
			ans = append(ans, r.text)
		}
		return
	}
	ae := func(query string, expected ...string) {
		if query != "" {
			wg.Add(1)
			s.Change_query(query)
			wg.Wait()
		}
		if diff := cmp.Diff(expected, results()); diff != "" {
			t.Fatalf("Query less scoring failed\n%s", diff)
		}
	}
	ae("", "x", "y", "a", "b", "c", "x/s", "x/1", "x/2", "x/3", "y/3", "y/4", "y/5", "x/s/m", "x/s/n")
	ae("a", "a")
	ae("3", "x/3", "y/3")
	ae("s", "x/s", "x/s/m", "x/s/n")
	ae("sn", "x/s/n")
}

func run_scoring(b *testing.B, depth, breadth int, query string) {
	b.StopTimer()
	root := node{name: string(os.PathSeparator)}
	root.generate_random_tree(depth, breadth)
	b.StartTimer()
	for range b.N {
		b.StopTimer()
		wg := sync.WaitGroup{}
		wg.Add(1)
		s := NewFileSystemScorer(string(os.PathSeparator), query, false, func(err error, is_complete bool) {
			if is_complete {
				wg.Done()
			}
		})
		sc := NewFileSystemScanner(s.root_dir, make(chan bool))
		s.scanner = sc
		sc.dir_reader = root.ReadDir
		b.StartTimer()
		s.scanner.Start()
		s.Start()
		wg.Wait()
	}
}

// To run this benchmark with profiling use:
// go test -bench=FileNameScoringWithoutQuery -benchmem -cpuprofile=/tmp/cpu.prof -memprofile=/tmp/mem.prof github.com/kovidgoyal/kitty/kittens/choose_files -o /tmp/cfexe
func BenchmarkFileNameScoringWithoutQuery(b *testing.B) {
	run_scoring(b, 5, 20, "")
}

// To run this benchmark with profiling use:
// go test -bench=FileNameScoringWithQuery -benchmem -cpuprofile=/tmp/cpu.prof -memprofile=/tmp/mem.prof github.com/kovidgoyal/kitty/kittens/choose_files -o /tmp/cfexe
func BenchmarkFileNameScoringWithQuery(b *testing.B) {
	run_scoring(b, 5, 20, "abc")
}
