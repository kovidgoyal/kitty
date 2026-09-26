// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package subseq

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"math/rand"
	"slices"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestSubseq(t *testing.T) {
	var positions [][]int
	sort_by_score := false

	simple := func(items, query string, expected ...string) {
		matches := ScoreItems(query, utils.Splitlines(items), Options{})
		if sort_by_score {
			matches = utils.StableSort(matches, func(a, b *Match) int {
				if b.Score < a.Score {
					return -1
				}
				if b.Score > a.Score {
					return 1
				}
				return 0
			})
		}
		actual := make([]string, 0, len(matches))
		actual_positions := make([][]int, 0, len(matches))
		for _, m := range matches {
			if m.Score > 0 {
				actual = append(actual, m.Text)
				actual_positions = append(actual_positions, m.Positions)
			}
		}
		if expected == nil {
			expected = []string{}
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed for items: %v\nMatches: %#v\n%s", utils.Splitlines(items), matches, diff)
		}
		if positions != nil {
			if diff := cmp.Diff(positions, actual_positions); diff != "" {
				t.Fatalf("Failed positions for items: %v\n%s", utils.Splitlines(items), diff)
			}
			positions = nil
		}
	}
	simple("test\nxyz", "te", "test")
	simple("abc\nxyz", "ba")
	simple("abc\n123", "abc", "abc")
	simple("test\nxyz", "Te", "test")
	simple("test\nxyz", "XY", "xyz")
	simple("test\nXYZ", "xy", "XYZ")
	simple("test\nXYZ", "mn")

	positions = [][]int{{0, 2}, {0, 1}}
	simple("abc\nac", "ac", "abc", "ac")
	positions = [][]int{{0}}
	simple("abc\nv", "a", "abc")
	positions = [][]int{{len("汉"), 7}}
	simple("汉a字b\nxyz", "ab", "汉a字b")

	sort_by_score = true
	// Match at start
	simple("archer\nelementary", "e", "elementary", "archer")
	// Match at level factor
	simple("xxxy\nxx/y", "y", "xx/y", "xxxy")
	// CamelCase
	simple("xxxy\nxxxY", "y", "xxxY", "xxxy")
	// Total length
	simple("xxxya\nxxxy", "y", "xxxy", "xxxya")
	// Distance
	simple("abbc\nabc", "ac", "abc", "abbc")
	// Extreme chars
	simple("xxa\naxx", "a", "axx", "xxa")
	// Highest score
	positions = [][]int{{3}}
	simple("xa/a", "a", "xa/a")

	sort_by_score = false
	items := make([]string, 256)
	for i := range items {
		items[i] = strconv.Itoa(i)
	}
	expected := make([]string, 0, len(items))
	for _, x := range items {
		if strings.ContainsRune(x, rune('2')) {
			expected = append(expected, x)
		}
	}
	simple(strings.Join(items, "\n"), "2", expected...)
}

var theme_names = []string{
	"1984 Dark", "Adwaita darker", "Aquarium Light", "Atelier Plateau Dark", "Ayu Mirage", "Base2Tone Heath Dark",
	"Base2Tone Sea Dark", "Base4Tone_Modern_W Dark", "Bluloco Dark", "C64", "Catppuccin-Latte", "Chalkboard",
	"Copland OS", "Darkside", "Doom Vibrant", "Earthsong", "Everforest Light Hard", "Flexoki (Dark)",
	"GitHub Dark Colorblind", "GitHub Light High Contrast", "Gnome-ish gray-on-black", "Gruvbox Light Soft",
	"Gruvbox Material Light Medium", "HardHacker", "IC Green PPL", "Kanagawa_dragon", "Kibble", "Linh", "Mayukai",
	"Modus Vivendi", "N0tch2k", "Nord", "One Half Dark", "Pastel EGA", "Red Alert", "Ryoccino", "Selenized White",
	"Serendipity Sunset", "Soft Server", "Solarized Dark Higher Contrast", "Sonokai Sushia", "Spring", "Teerb",
	"Tokyo Night", "Tomorrow", "Tomorrow Night Eighties", "Ubuntu", "Wez", "Yorumi Kraken", "ferra", "pink lavender",
	"zenbones_light",
}

func score_positions(w *workspace_type, positions []int) (ans float64) {
	for i, pos := range positions {
		distance := pos + 1
		if i > 0 {
			distance = pos - positions[i-1]
			if distance < 2 {
				ans += w.max_score_per_char
				continue
			}
		}
		if w.level_factors[pos] > 0 {
			ans += (100.0 * w.max_score_per_char) / float64(w.level_factors[pos])
		} else {
			ans += (0.75 * w.max_score_per_char) / float64(distance)
		}
	}
	return
}

// Try every monotonic set of positions for the item last scored with w
func brute_force(w *workspace_type) (best float64) {
	positions := make([]int, len(w.positions))
	var recurse func(j int)
	recurse = func(j int) {
		if j == len(positions) {
			best = max(best, score_positions(w, positions))
			return
		}
		for _, pos := range w.positions[j] {
			if j == 0 || pos > positions[j-1] {
				positions[j] = pos
				recurse(j + 1)
			}
		}
	}
	recurse(0)
	return
}

func TestSubseqBruteForce(t *testing.T) {
	opts := resolved_options_type{level1: []rune(" "), level2: []rune(LEVEL2), level3: []rune(LEVEL3)}
	w := workspace_type{}
	r := rand.New(rand.NewSource(1))
	for range 200 {
		name := []rune(strings.ToLower(theme_names[r.Intn(len(theme_names))]))
		idx := r.Perm(len(name))[:1+r.Intn(min(6, len(name)))]
		slices.Sort(idx)
		needle := make([]rune, len(idx))
		for i, x := range idx {
			needle[i] = name[x]
		}
		for _, item := range theme_names {
			m := score_item(item, 0, needle, &opts, &w)
			if expected := brute_force(&w); m.Score != expected {
				t.Fatalf("Score for %#v in %#v: %v != %v", string(needle), item, m.Score, expected)
			}
			if m.Score > 0 {
				ok := score_positions(&w, m.Positions) == m.Score
				for i, pos := range m.Positions {
					ok = ok && strings.ToLower(item)[pos] == byte(needle[i]) && (i == 0 || pos > m.Positions[i-1])
				}
				if !ok {
					t.Fatalf("Positions for %#v in %#v: %v do not give the score %v", string(needle), item, m.Positions, m.Score)
				}
			}
		}
	}
	// the old code tried every combination of positions here, which never finishes
	m := ScoreItems(strings.Repeat("a", 100), []string{strings.Repeat("a", 200)}, Options{})[0]
	expected := make([]int, 100)
	for i := range expected {
		expected[i] = i
	}
	if diff := cmp.Diff(expected, m.Positions); diff != "" {
		t.Fatalf("Failed positions for long needle:\n%s", diff)
	}
}

func BenchmarkScoreItems(b *testing.B) {
	for _, query := range []string{"dark", "tokyo night", "solarized dark higher contrast"} {
		b.Run(query, func(b *testing.B) {
			for b.Loop() {
				for i := range len(query) { // as if typed one char at a time
					ScoreItems(query[:i+1], theme_names, Options{Level1: " "})
				}
			}
		})
	}
}
