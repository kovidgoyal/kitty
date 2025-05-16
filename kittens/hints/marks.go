// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"unicode"
	"unicode/utf8"

	"github.com/dlclark/regexp2"
	"github.com/seancfoley/ipaddress-go/ipaddr"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const (
	DEFAULT_HINT_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
	FILE_EXTENSION        = `\.(?:[a-zA-Z0-9]{2,7}|[ahcmo])(?:\b|[^.])`
)

func path_regex() string {
	return fmt.Sprintf(`(?:\S*?/[\r\S]+)|(?:\S[\r\S]*%s)\b`, FILE_EXTENSION)
}

func default_linenum_regex() string {
	return fmt.Sprintf(`(?P<path>%s):(?P<line>\d+)`, path_regex())
}

type Mark struct {
	Index        int            `json:"index"`
	Start        int            `json:"start"`
	End          int            `json:"end"`
	Text         string         `json:"text"`
	Group_id     string         `json:"group_id"`
	Is_hyperlink bool           `json:"is_hyperlink"`
	Groupdict    map[string]any `json:"groupdict"`
}

func process_escape_codes(text string) (ans string, hyperlinks []Mark) {
	removed_size, idx := 0, 0
	active_hyperlink_url := ""
	active_hyperlink_id := ""
	active_hyperlink_start_offset := 0

	add_hyperlink := func(end int) {
		hyperlinks = append(hyperlinks, Mark{
			Index: idx, Start: active_hyperlink_start_offset, End: end, Text: active_hyperlink_url, Is_hyperlink: true, Group_id: active_hyperlink_id})
		active_hyperlink_url, active_hyperlink_id = "", ""
		active_hyperlink_start_offset = 0
		idx++
	}

	ans = utils.ReplaceAll(utils.MustCompile("\x1b(?:\\[[0-9;:]*?m|\\].*?\x1b\\\\)"), text, func(raw string, groupdict map[string]utils.SubMatch) string {
		if !strings.HasPrefix(raw, "\x1b]8") {
			removed_size += len(raw)
			return ""
		}
		start := groupdict[""].Start - removed_size
		removed_size += len(raw)
		if active_hyperlink_url != "" {
			add_hyperlink(start)
		}
		raw = raw[4 : len(raw)-2]
		if metadata, url, found := strings.Cut(raw, ";"); found && url != "" {
			active_hyperlink_url = url
			active_hyperlink_start_offset = start
			if metadata != "" {
				for _, entry := range strings.Split(metadata, ":") {
					if strings.HasPrefix(entry, "id=") && len(entry) > 3 {
						active_hyperlink_id = entry[3:]
					}
				}
			}
		}
		return ""
	})
	if active_hyperlink_url != "" {
		add_hyperlink(len(ans))
	}
	return
}

type PostProcessorFunc = func(string, int, int) (int, int)
type GroupProcessorFunc = func(map[string]string)

func is_punctuation(b string) bool {
	switch b {
	case ",", ".", "?", "!":
		return true
	}
	return false
}

func closing_bracket_for(ch string) string {
	switch ch {
	case "(":
		return ")"
	case "[":
		return "]"
	case "{":
		return "}"
	case "<":
		return ">"
	case "*":
		return "*"
	case `"`:
		return `"`
	case "'":
		return "'"
	case "“":
		return "”"
	case "‘":
		return "’"
	}
	return ""
}

func char_at(s string, i int) string {
	ans, _ := utf8.DecodeRuneInString(s[i:])
	if ans == utf8.RuneError {
		return ""
	}
	return string(ans)
}

func matching_remover(openers ...string) PostProcessorFunc {
	return func(text string, s, e int) (int, int) {
		if s < e && e <= len(text) {
			before := char_at(text, s)
			if slices.Index(openers, before) > -1 {
				q := closing_bracket_for(before)
				if e > 0 && char_at(text, e-1) == q {
					s++
					e--
				} else if char_at(text, e) == q {
					s++
				}
			}
		}
		return s, e
	}
}

func linenum_group_processor(gd map[string]string) {
	pat := utils.MustCompile(`:\d+$`)
	gd[`path`] = pat.ReplaceAllStringFunc(gd["path"], func(m string) string {
		gd["line"] = m[1:]
		return ``
	})
	gd[`path`] = utils.Expanduser(gd[`path`])
}

var PostProcessorMap = sync.OnceValue(func() map[string]PostProcessorFunc {
	return map[string]PostProcessorFunc{
		"url": func(text string, s, e int) (int, int) {
			if s > 4 && text[s-5:s] == "link:" { // asciidoc URLs
				url := text[s:e]
				idx := strings.LastIndex(url, "[")
				if idx > -1 {
					e -= len(url) - idx
				}
			}
			for e > 1 && is_punctuation(char_at(text, e)) { // remove trailing punctuation
				e--
			}
			// truncate url at closing bracket/quote
			if s > 0 && e <= len(text) && closing_bracket_for(char_at(text, s-1)) != "" {
				q := closing_bracket_for(char_at(text, s-1))
				idx := strings.Index(text[s:], q)
				if idx > 0 {
					e = s + idx
				}
			}
			// reStructuredText URLs
			if e > 3 && text[e-2:e] == "`_" {
				e -= 2
			}
			return s, e
		},

		"brackets": matching_remover("(", "{", "[", "<"),
		"quotes":   matching_remover("'", `"`, "“", "‘"),
		"ip": func(text string, s, e int) (int, int) {
			addr := ipaddr.NewHostName(text[s:e])
			if !addr.IsAddress() {
				return -1, -1
			}
			return s, e
		},
	}
})

type KittyOpts struct {
	Url_prefixes              *utils.Set[string]
	Url_excluded_characters   string
	Select_by_word_characters string
}

func read_relevant_kitty_opts() KittyOpts {
	ans := KittyOpts{
		Select_by_word_characters: kitty.KittyConfigDefaults.Select_by_word_characters,
		Url_excluded_characters:   kitty.KittyConfigDefaults.Url_excluded_characters}
	handle_line := func(key, val string) error {
		switch key {
		case "url_prefixes":
			ans.Url_prefixes = utils.NewSetWithItems(strings.Split(val, " ")...)
		case "select_by_word_characters":
			ans.Select_by_word_characters = strings.TrimSpace(val)
		case "url_excluded_characters":
			if s, err := config.StringLiteral(val); err == nil {
				ans.Url_excluded_characters = s
			}
		}
		return nil
	}
	config.ReadKittyConfig(handle_line)
	if ans.Url_prefixes == nil {
		ans.Url_prefixes = utils.NewSetWithItems(kitty.KittyConfigDefaults.Url_prefixes...)
	}
	return ans
}

var RelevantKittyOpts = sync.OnceValue(func() KittyOpts {
	return read_relevant_kitty_opts()
})

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func url_excluded_characters_as_ranges_for_regex(extra_excluded string) string {
	// See https://url.spec.whatwg.org/#url-code-points
	ans := strings.Builder{}
	ans.Grow(4096)
	type cr struct{ start, end rune }
	ranges := []cr{}
	r := func(start rune, end ...rune) {
		if len(end) == 0 {
			ranges = append(ranges, cr{start, start})
		} else {
			ranges = append(ranges, cr{start, end[0]})
		}
	}
	if !strings.Contains(extra_excluded, "\n") {
		r('\n')
	}
	if !strings.Contains(extra_excluded, "\r") {
		r('\r')
	}
	r('!')
	r('$')
	r('&')
	r('#')
	r('\'')
	r('/')
	r(':')
	r(';')
	r('@')
	r('_')
	r('~')
	r('(')
	r(')')
	r('*')
	r('+')
	r(',')
	r('-')
	r('.')
	r('=')
	r('?')
	r('%')
	r('a', 'z')
	r('A', 'Z')
	r('0', '9')
	slices.SortFunc(ranges, func(a, b cr) int { return int(a.start - b.start) })
	var prev rune = -1
	for _, cr := range ranges {
		if cr.start-1 > prev+1 {
			ans.WriteString(regexp.QuoteMeta(string(prev + 1)))
			ans.WriteRune('-')
			ans.WriteString(regexp.QuoteMeta(string(cr.start - 1)))
		}
		prev = cr.end
	}
	ans.WriteString(regexp.QuoteMeta(string(ranges[len(ranges)-1].end + 1)))
	ans.WriteRune('-')
	ans.WriteRune(0x9f)
	ans.WriteString(`\x{d800}-\x{dfff}`)
	ans.WriteString(`\x{fdd0}-\x{fdef}`)
	w := func(x rune) { ans.WriteRune(x) }

	w(0xFFFE)
	w(0xFFFF)
	w(0x1FFFE)
	w(0x1FFFF)
	w(0x2FFFE)
	w(0x2FFFF)
	w(0x3FFFE)
	w(0x3FFFF)
	w(0x4FFFE)
	w(0x4FFFF)
	w(0x5FFFE)
	w(0x5FFFF)
	w(0x6FFFE)
	w(0x6FFFF)
	w(0x7FFFE)
	w(0x7FFFF)
	w(0x8FFFE)
	w(0x8FFFF)
	w(0x9FFFE)
	w(0x9FFFF)
	w(0xAFFFE)
	w(0xAFFFF)
	w(0xBFFFE)
	w(0xBFFFF)
	w(0xCFFFE)
	w(0xCFFFF)
	w(0xDFFFE)
	w(0xDFFFF)
	w(0xEFFFE)
	w(0xEFFFF)
	w(0xFFFFE)
	w(0xFFFFF)

	if strings.Contains(extra_excluded, "-") {
		extra_excluded = strings.ReplaceAll(extra_excluded, "-", "")
		extra_excluded = regexp.QuoteMeta(extra_excluded) + "-"
	} else {
		extra_excluded = regexp.QuoteMeta(extra_excluded)
	}
	ans.WriteString(extra_excluded)
	return ans.String()

}

func functions_for(opts *Options) (pattern string, post_processors []PostProcessorFunc, group_processors []GroupProcessorFunc, err error) {
	switch opts.Type {
	case "url":
		var url_prefixes *utils.Set[string]
		if opts.UrlPrefixes == "default" {
			url_prefixes = RelevantKittyOpts().Url_prefixes
		} else {
			url_prefixes = utils.NewSetWithItems(strings.Split(opts.UrlPrefixes, ",")...)
		}
		url_excluded_characters := RelevantKittyOpts().Url_excluded_characters
		if opts.UrlExcludedCharacters != "default" {
			if url_excluded_characters, err = config.StringLiteral(opts.UrlExcludedCharacters); err != nil {
				err = fmt.Errorf("Failed to parse --url-excluded-characters value: %#v with error: %w", opts.UrlExcludedCharacters, err)
				return
			}
		}
		pattern = fmt.Sprintf(`(?:%s)://[^%s]{3,}`, strings.Join(url_prefixes.AsSlice(), "|"), url_excluded_characters_as_ranges_for_regex(url_excluded_characters))
		post_processors = append(post_processors, PostProcessorMap()["url"])
	case "path":
		pattern = path_regex()
		post_processors = append(post_processors, PostProcessorMap()["brackets"], PostProcessorMap()["quotes"])
	case "line":
		pattern = "(?m)^\\s*(.+)[\\s\x00]*$"
	case "hash":
		pattern = "[0-9a-f][0-9a-f\r]{6,127}"
	case "ip":
		pattern = (
		// IPv4 with no validation
		`((?:\d{1,3}\.){3}\d{1,3}` + "|" +
			// IPv6 with no validation
			`(?:[a-fA-F0-9]{0,4}:){2,7}[a-fA-F0-9]{1,4})`)
		post_processors = append(post_processors, PostProcessorMap()["ip"])
	default:
		pattern = opts.Regex
		if opts.Type == "linenum" {
			if pattern == kitty.HintsDefaultRegex {
				pattern = default_linenum_regex()
			}
			post_processors = append(post_processors, PostProcessorMap()["brackets"], PostProcessorMap()["quotes"])
			group_processors = append(group_processors, linenum_group_processor)
		}
	}
	return
}

type Capture struct {
	Text          string
	Text_as_runes []rune
	Byte_Offsets  struct {
		Start, End int
	}
	Rune_Offsets struct {
		Start, End int
	}
}

func (self Capture) String() string {
	return fmt.Sprintf("Capture(start=%d, end=%d, %#v)", self.Byte_Offsets.Start, self.Byte_Offsets.End, self.Text)
}

type Group struct {
	Name     string
	IsNamed  bool
	Captures []Capture
}

func (self Group) LastCapture() Capture {
	if len(self.Captures) == 0 {
		return Capture{}
	}
	return self.Captures[len(self.Captures)-1]
}

func (self Group) String() string {
	return fmt.Sprintf("Group(name=%#v, captures=%v)", self.Name, self.Captures)
}

type Match struct {
	Groups []Group
}

func (self Match) HasNamedGroups() bool {
	for _, g := range self.Groups {
		if g.IsNamed {
			return true
		}
	}
	return false
}

func find_all_matches(re *regexp2.Regexp, text string) (ans []Match, err error) {
	m, err := re.FindStringMatch(text)
	if err != nil {
		return
	}
	rune_to_bytes := utils.RuneOffsetsToByteOffsets(text)
	get_byte_offset_map := func(groups []regexp2.Group) (ans map[int]int, err error) {
		ans = make(map[int]int, len(groups)*2)
		rune_offsets := make([]int, 0, len(groups)*2)
		for _, g := range groups {
			for _, c := range g.Captures {
				if _, found := ans[c.Index]; !found {
					rune_offsets = append(rune_offsets, c.Index)
					ans[c.Index] = -1
				}
				end := c.Index + c.Length
				if _, found := ans[end]; !found {
					rune_offsets = append(rune_offsets, end)
					ans[end] = -1
				}
			}
		}
		slices.Sort(rune_offsets)
		for _, pos := range rune_offsets {
			if ans[pos] = rune_to_bytes(pos); ans[pos] < 0 {
				return nil, fmt.Errorf("Matches are not monotonic cannot map rune offsets to byte offsets")
			}
		}
		return
	}

	for m != nil {
		groups := m.Groups()
		bom, err := get_byte_offset_map(groups)
		if err != nil {
			return nil, err
		}
		match := Match{Groups: make([]Group, len(groups))}
		for i, g := range m.Groups() {
			match.Groups[i].Name = g.Name
			match.Groups[i].IsNamed = g.Name != "" && g.Name != strconv.Itoa(i)
			for _, c := range g.Captures {
				cn := Capture{Text: c.String(), Text_as_runes: c.Runes()}
				cn.Rune_Offsets.End = c.Index + c.Length
				cn.Rune_Offsets.Start = c.Index
				cn.Byte_Offsets.Start, cn.Byte_Offsets.End = bom[c.Index], bom[cn.Rune_Offsets.End]
				match.Groups[i].Captures = append(match.Groups[i].Captures, cn)
			}
		}
		ans = append(ans, match)
		m, _ = re.FindNextMatch(m)
	}
	return
}

func mark(r *regexp2.Regexp, post_processors []PostProcessorFunc, group_processors []GroupProcessorFunc, text string, opts *Options) (ans []Mark) {
	sanitize_pat := regexp.MustCompile("[\r\n\x00]")
	all_matches, _ := find_all_matches(r, text)
	for i, m := range all_matches {
		full_capture := m.Groups[0].LastCapture()
		match_start, match_end := full_capture.Byte_Offsets.Start, full_capture.Byte_Offsets.End
		for match_end > match_start+1 && text[match_end-1] == 0 {
			match_end--
		}
		full_match := text[match_start:match_end]
		if len([]rune(full_match)) < opts.MinimumMatchLength {
			continue
		}
		for _, f := range post_processors {
			match_start, match_end = f(text, match_start, match_end)
			if match_start < 0 {
				break
			}
		}
		if match_start < 0 {
			continue
		}
		full_match = sanitize_pat.ReplaceAllLiteralString(text[match_start:match_end], "")
		gd := make(map[string]string, len(m.Groups))
		for idx, g := range m.Groups {
			if idx > 0 && g.IsNamed {
				c := g.LastCapture()
				if s, e := c.Byte_Offsets.Start, c.Byte_Offsets.End; s > -1 && e > -1 {
					s = max(s, match_start)
					e = min(e, match_end)
					gd[g.Name] = sanitize_pat.ReplaceAllLiteralString(text[s:e], "")
				}
			}
		}
		for _, f := range group_processors {
			f(gd)
		}
		gd2 := make(map[string]any, len(gd))
		for k, v := range gd {
			gd2[k] = v
		}
		if opts.Type == "regex" && len(m.Groups) > 1 && !m.HasNamedGroups() {
			cp := m.Groups[1].LastCapture()
			ms, me := cp.Byte_Offsets.Start, cp.Byte_Offsets.End
			match_start = max(match_start, ms)
			match_end = min(match_end, me)
			full_match = sanitize_pat.ReplaceAllLiteralString(text[match_start:match_end], "")
		}
		if full_match != "" {
			ans = append(ans, Mark{
				Index: i, Start: match_start, End: match_end, Text: full_match, Groupdict: gd2,
			})
		}
	}
	return
}

type ErrNoMatches struct{ Type, Pattern string }

func is_word_char(ch rune, current_chars []rune) bool {
	return unicode.IsLetter(ch) || unicode.IsNumber(ch) || (unicode.IsMark(ch) && len(current_chars) > 0 && unicode.IsLetter(current_chars[len(current_chars)-1]))
}

func mark_words(text string, opts *Options) (ans []Mark) {
	left := text
	var current_run struct {
		chars       []rune
		start, size int
	}
	chars := opts.WordCharacters
	if chars == "" {
		chars = RelevantKittyOpts().Select_by_word_characters
	}
	allowed_chars := make(map[rune]bool, len(chars))
	for _, ch := range chars {
		allowed_chars[ch] = true
	}
	pos := 0
	post_processors := []PostProcessorFunc{PostProcessorMap()["brackets"], PostProcessorMap()["quotes"]}

	commit_run := func() {
		if len(current_run.chars) >= opts.MinimumMatchLength {
			match_start, match_end := current_run.start, current_run.start+current_run.size
			for _, f := range post_processors {
				match_start, match_end = f(text, match_start, match_end)
				if match_start < 0 {
					break
				}
			}
			if match_start > -1 && match_end > match_start {
				full_match := text[match_start:match_end]
				if len([]rune(full_match)) >= opts.MinimumMatchLength {
					ans = append(ans, Mark{
						Index: len(ans), Start: match_start, End: match_end, Text: full_match,
					})
				}
			}
		}
		current_run.chars = nil
		current_run.start = 0
		current_run.size = 0
	}

	for {
		ch, size := utf8.DecodeRuneInString(left)
		if ch == utf8.RuneError {
			break
		}
		if allowed_chars[ch] || is_word_char(ch, current_run.chars) {
			if len(current_run.chars) == 0 {
				current_run.start = pos
			}
			current_run.chars = append(current_run.chars, ch)
			current_run.size += size
		} else {
			commit_run()
		}
		left = left[size:]
		pos += size
	}
	commit_run()
	return
}

func adjust_python_offsets(text string, marks []Mark) error {
	// python returns rune based offsets (unicode chars not utf-8 bytes)
	adjust := utils.RuneOffsetsToByteOffsets(text)
	for i := range marks {
		mark := &marks[i]
		if mark.End < mark.Start {
			return fmt.Errorf("The end of a mark must not be before its start")
		}
		s, e := adjust(mark.Start), adjust(mark.End)
		if s < 0 || e < 0 {
			return fmt.Errorf("Overlapping marks are not supported")
		}
		mark.Start, mark.End = s, e
	}
	return nil
}

func (self *ErrNoMatches) Error() string {
	none_of := "matches"
	switch self.Type {
	case "urls":
		none_of = "URLs"
	case "hyperlinks":
		none_of = "hyperlinks"
	}
	if self.Pattern != "" {
		return fmt.Sprintf("No %s found with pattern: %s", none_of, self.Pattern)
	}
	return fmt.Sprintf("No %s found", none_of)
}

func find_marks(text string, opts *Options, cli_args ...string) (sanitized_text string, ans []Mark, index_map map[int]*Mark, err error) {
	sanitized_text, hyperlinks := process_escape_codes(text)
	used_pattern := ""

	run_basic_matching := func() error {
		pattern, post_processors, group_processors, err := functions_for(opts)
		if err != nil {
			return err
		}
		r, err := regexp2.Compile(pattern, regexp2.RE2)
		if err != nil {
			return fmt.Errorf("Failed to compile the regex pattern: %#v with error: %w", pattern, err)
		}
		ans = mark(r, post_processors, group_processors, sanitized_text, opts)
		used_pattern = pattern
		return nil
	}

	if opts.CustomizeProcessing != "" {
		cmd := exec.Command(utils.KittyExe(), append([]string{"+runpy", "from kittens.hints.main import custom_marking; custom_marking()"}, cli_args...)...)
		cmd.Stdin = strings.NewReader(sanitized_text)
		stdout, stderr := bytes.Buffer{}, bytes.Buffer{}
		cmd.Stdout, cmd.Stderr = &stdout, &stderr
		err = cmd.Run()
		if err != nil {
			var e *exec.ExitError
			if errors.As(err, &e) && e.ExitCode() == 2 {
				err = run_basic_matching()
				if err != nil {
					return
				}
				goto process_answer
			} else {
				return "", nil, nil, fmt.Errorf("Failed to run custom processor %#v with error: %w\n%s", opts.CustomizeProcessing, err, stderr.String())
			}
		}
		ans = make([]Mark, 0, 32)
		err = json.Unmarshal(stdout.Bytes(), &ans)
		if err != nil {
			return "", nil, nil, fmt.Errorf("Failed to load output from custom processor %#v with error: %w", opts.CustomizeProcessing, err)
		}
		err = adjust_python_offsets(sanitized_text, ans)
		if err != nil {
			return "", nil, nil, fmt.Errorf("Custom processor %#v produced invalid mark output with error: %w", opts.CustomizeProcessing, err)
		}
	} else if opts.Type == "hyperlink" {
		ans = hyperlinks
	} else if opts.Type == "word" {
		ans = mark_words(sanitized_text, opts)
	} else {
		err = run_basic_matching()
		if err != nil {
			return
		}
	}
process_answer:
	if len(ans) == 0 {
		return "", nil, nil, &ErrNoMatches{Type: opts.Type, Pattern: used_pattern}
	}
	largest_index := ans[len(ans)-1].Index
	offset := max(0, opts.HintsOffset)
	index_map = make(map[int]*Mark, len(ans))
	for i := range ans {
		m := &ans[i]
		if opts.Ascending {
			m.Index += offset
		} else {
			m.Index = largest_index - m.Index + offset
		}
		index_map[m.Index] = m
	}
	return
}
