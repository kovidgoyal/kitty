package choose_files

import (
	"fmt"
	"io/fs"
	"math/rand"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/ignorefiles"
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
	data     string
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

func (n node) ReadFile(name string) ([]byte, error) {
	if name == string(os.PathSeparator) {
		return nil, fs.ErrNotExist
	}
	p := &n
	for _, x := range strings.Split(strings.Trim(name, string(os.PathSeparator)), string(os.PathSeparator)) {
		c, found := p.children[x]
		if !found {
			return nil, fs.ErrNotExist
		}
		p = c
	}
	return []byte(p.data), nil
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

func TestChooseFilesIgnore(t *testing.T) {
	root := node{name: string(os.PathSeparator), children: map[string]*node{
		"a":          {name: "a"},
		"b":          {name: "b"},
		"c.png":      {name: "c.png"},
		".ignore":    {name: ".ignore", data: "a\nx/s/n"},
		".gitignore": {name: ".gitignore", data: "b"},
		"x": {name: "x", children: map[string]*node{
			"1": {name: "1"}, "2": {name: "2"}, "3": {name: "3"},
			"s": {name: "s", children: map[string]*node{
				"m": {name: "m"}, "n": {name: "n"},
			}},
		}},
		"y": {name: "y", children: map[string]*node{
			"3": {name: "3"}, "4": {name: "4"}, "5": {name: "5"},
			"s": {name: "s", children: map[string]*node{
				"3": {name: "3"}, "4": {name: "4"}, "5": {name: "5"}, "6": {name: "6"},
			}},
			".gitignore": {name: ".gitignore", data: "/s/5"},
			".git": {name: ".git", children: map[string]*node{
				"info": {name: "info", children: map[string]*node{
					"exclude": {name: "exclude", data: "s/4"},
				}},
			}},
		}},
	}}
	r := func(respect_ignores bool, expected string) {
		ch := make(chan bool)
		s := new_filesystem_scanner("/", ch, nil)
		s.dir_reader = root.ReadDir
		s.file_reader = root.ReadFile
		s.global_gitignore = ignorefiles.NewGitignore()
		s.global_ignore = ignorefiles.NewGitignore()
		s.respect_ignores = respect_ignores
		if err := s.global_gitignore.LoadLines("*.png", "s/3"); err != nil {
			t.Fatal(err)
		}
		if err := s.global_ignore.LoadLines("x/3"); err != nil {
			t.Fatal(err)
		}
		s.Start()
		for range ch {
		}
		if s.err != nil {
			t.Fatal(s.err)
		}
		ci := CollectionIndex{}
		actual := utils.Map(func(x ResultItem) string { return x.text }, s.Batch(&ci))
		if diff := cmp.Diff(strings.Split(expected, ` `), actual); diff != "" {
			t.Fatalf("Incorrect ignoring:\n%s", diff)
		}
	}
	r(true, `x y b c.png x/s x/1 x/2 y/s y/3 y/4 y/5 x/s/m y/s/6`)
	r(false, `x y a b c.png x/s x/1 x/2 x/3 y/s y/3 y/4 y/5 x/s/m x/s/n y/s/3 y/s/4 y/s/5 y/s/6`)
}

func TestChooseFilesScoring(t *testing.T) {
	root := node{name: string(os.PathSeparator), children: map[string]*node{
		"b":     {name: "b"},
		"a":     {name: "a"},
		"c.png": {name: "c.png"},
		"x": {name: "x", children: map[string]*node{
			"1": {name: "1"}, "2": {name: "2"}, "3": {name: "3"},
			"s": {name: "s", children: map[string]*node{
				"m": {name: "m"}, "n": {name: "n"},
			}},
		}},
		"y": {name: "y", children: map[string]*node{
			"3": {name: "3"}, "4": {name: "4"}, "5": {name: "5"},
		}},
	}}
	wg := sync.WaitGroup{}
	wg.Add(1)
	s := NewFileSystemScorer(string(os.PathSeparator), "", Filter{}, false, func(err error, is_complete bool) {
		if is_complete {
			wg.Done()
		}
	})
	s.dir_reader = root.ReadDir
	s.global_gitignore = ignorefiles.NewGitignore()
	s.Start()
	wg.Wait()
	results := func() (ans []string) {
		rr, _ := s.Results()
		for _, r := range rr.RenderedMatches(CollectionIndex{}, -1) {
			ans = append(ans, r.text)
		}
		return
	}
	ae := func(query string, expected ...string) {
		wg.Add(1)
		s.Change_query(query)
		wg.Wait()
		if diff := cmp.Diff(expected, results()); diff != "" {
			t.Fatalf("Query less scoring failed\n%s", diff)
		}
	}
	ae("a", "a")
	ae("3", "x/3", "y/3")
	ae("s", "x/s", "x/s/m", "x/s/n")
	ae("sn", "x/s/n")
	ae("", "x", "y", "a", "b", "c.png", "x/s", "x/1", "x/2", "x/3", "y/3", "y/4", "y/5", "x/s/m", "x/s/n")

	af := func(filter string, expected ...string) {
		f, _ := NewFilter(filter)
		wg.Add(1)
		s.Change_filter(*f)
		wg.Wait()
		if diff := cmp.Diff(expected, results()); diff != "" {
			t.Fatalf("filter %s failed\n%s", filter, diff)
		}
	}
	af("glob:a:A", "x", "y", "a", "x/s")
	af("glob:[ab]:A", "x", "y", "a", "b", "x/s")
	af("mime:image/png:A", "x", "y", "c.png", "x/s")
	af("mime:image/*:A", "x", "y", "c.png", "x/s")
	af("glob:*:All", "x", "y", "a", "b", "c.png", "x/s", "x/1", "x/2", "x/3", "y/3", "y/4", "y/5", "x/s/m", "x/s/n")
}

func TestSortedResults(t *testing.T) {
	r := NewSortedResults()
	idx := CollectionIndex{}
	m := func(items ...int) []*ResultItem {
		ans := make([]*ResultItem, len(items))
		for i, x := range items {
			ans[i] = &ResultItem{text: strconv.Itoa(x), score: CombinedScore(x)}
		}
		return ans
	}
	v := func(slice, pos, num int) []int {
		if num == 0 {
			num = r.Len()
		}
		return utils.Map(func(r *ResultItem) int { return int(r.score) }, r.RenderedMatches(CollectionIndex{slice, pos}, num))
	}
	tv := func(slice, pos, num int, expected ...int) {
		if diff := cmp.Diff(expected, v(slice, pos, num)); diff != "" {
			t.Fatalf("view failed for %v num:%d\n%s", CollectionIndex{slice, pos}, num, diff)
		}
	}
	tci := func(increment int, expected int) {
		orig := idx
		idx = r.IncrementIndexWithWrapAround(idx, increment)
		actual := int(r.At(idx).score)
		if actual != expected {
			t.Fatalf("increment: %d on %v failed\nexpected: %d actual: %d idx: %v", increment, orig, expected, actual, idx)
		}
	}
	dt := func(a, b CollectionIndex, expected int) {
		actual := r.distance(a, b)
		if expected != actual {
			t.Fatalf("distance on %v and %v failed\nexpected: %d actual: %d ", a, b, expected, actual)
		}
		if r.distance(b, a) != actual {
			t.Fatalf("distance on %v and %v not commutative %d != %d", a, b, actual, r.distance(b, a))
		}
	}
	tc := func(num_before, expected_new_before int, ci CollectionIndex, expected ...[]int) {
		ac, new_num_before, _ := r.SplitIntoColumns(func(int) int { return 2 }, 2, num_before, ci)
		actual := make([][]int, len(ac))
		for i, x := range ac {
			actual[i] = utils.Map(func(r *ResultItem) int { return int(r.score) }, x)
		}
		if expected_new_before != new_num_before {
			t.Fatalf("new_num_before not as expected for num_before: %d ci: %v\n%d != %d", num_before, ci, expected_new_before, new_num_before)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("wrong columns for num_before: %d ci: %v\n%s", num_before, ci, diff)
		}
	}
	r.AddSortedSlice(m(10, 20, 30))
	r.AddSortedSlice(m(40, 50, 60))
	r.AddSortedSlice(m(70, 80, 90))

	tc(0, 0, CollectionIndex{}, []int{10, 20}, []int{30, 40})
	tc(1, 1, CollectionIndex{Pos: 1}, []int{10, 20}, []int{30, 40})
	tc(1, 1, CollectionIndex{Pos: 2}, []int{20, 30}, []int{40, 50})
	tc(2, 2, CollectionIndex{Pos: 2}, []int{10, 20}, []int{30, 40})
	tc(20, 2, CollectionIndex{Pos: 2}, []int{10, 20}, []int{30, 40})
	for num_before := range 4 {
		tc(num_before, 3, CollectionIndex{2, 2}, []int{60, 70}, []int{80, 90})
	}
	tc(1, 1, CollectionIndex{1, 1}, []int{40, 50}, []int{60, 70})

	dt(CollectionIndex{Pos: 0}, CollectionIndex{Pos: 2}, 2)
	dt(CollectionIndex{Pos: 0}, CollectionIndex{Slice: 1}, 3)
	dt(CollectionIndex{Pos: 0}, CollectionIndex{Slice: 1, Pos: 1}, 4)

	tv(0, 0, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90)
	tv(0, 2, 3, 30, 40, 50)
	tv(0, 3, 3, 40, 50, 60)
	tv(1, 0, 4, 40, 50, 60, 70)

	tci(1, 20)
	tci(3, 50)
	tci(-1, 40)
	tci(-3, 10)
	tci(-2, 80)
	tci(3, 20)
	tci(9, 20)
	tci(-9, 20)

	r.AddSortedSlice(m(100, 110, 120))
	r.AddSortedSlice(m(41, 61, 71, 99))
	tv(0, 0, 0, 10, 20, 30, 40, 41, 50, 60, 61, 70, 71, 80, 90, 99, 100, 110, 120)
	r.AddSortedSlice(m(1, 2, 3))
	tv(0, 0, 0, 1, 2, 3, 10, 20, 30, 40, 41, 50, 60, 61, 70, 71, 80, 90, 99, 100, 110, 120)
	r.AddSortedSlice(m(1000, 2000))
	tv(0, 0, 0, 1, 2, 3, 10, 20, 30, 40, 41, 50, 60, 61, 70, 71, 80, 90, 99, 100, 110, 120, 1000, 2000)
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
		s := NewFileSystemScorer(string(os.PathSeparator), query, Filter{}, false, func(err error, is_complete bool) {
			if is_complete {
				wg.Done()
			}
		})
		s.dir_reader = root.ReadDir
		s.global_gitignore = ignorefiles.NewGitignore()
		b.StartTimer()
		s.scanner.Start()
		s.Start()
		wg.Wait()
	}
	fmt.Println("\nnumber of iterations: ", b.N)
	fmt.Println("time per iteration:", b.Elapsed()/time.Duration(b.N))
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
