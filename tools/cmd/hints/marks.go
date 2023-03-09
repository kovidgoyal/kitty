// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"fmt"
	"kitty"
	"kitty/tools/config"
	"kitty/tools/utils"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/seancfoley/ipaddress-go/ipaddr"
	"golang.org/x/exp/slices"
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
	Index, Start, End int
	Text, Group_id    string
	Is_hyperlink      bool
	Groupdict         map[string]string
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

var PostProcessorMap = (&utils.Once[map[string]PostProcessorFunc]{Run: func() map[string]PostProcessorFunc {
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
}}).Get

type KittyOpts struct {
	Url_prefixes              *utils.Set[string]
	Select_by_word_characters string
}

func read_relevant_kitty_opts(path string) KittyOpts {
	ans := KittyOpts{Select_by_word_characters: kitty.KittyConfigDefaults.Select_by_word_characters}
	handle_line := func(key, val string) error {
		switch key {
		case "url_prefixes":
			ans.Url_prefixes = utils.NewSetWithItems(strings.Split(val, " ")...)
		case "select_by_word_characters":
			ans.Select_by_word_characters = strings.TrimSpace(val)
		}
		return nil
	}
	cp := config.ConfigParser{LineHandler: handle_line}
	cp.ParseFiles(path)
	if ans.Url_prefixes == nil {
		ans.Url_prefixes = utils.NewSetWithItems(kitty.KittyConfigDefaults.Url_prefixes...)
	}
	return ans
}

var RelevantKittyOpts = (&utils.Once[KittyOpts]{Run: func() KittyOpts {
	return read_relevant_kitty_opts(filepath.Join(utils.ConfigDir(), "kitty.conf"))
}}).Get

func functions_for(opts *Options) (pattern string, post_processors []PostProcessorFunc, group_processors []GroupProcessorFunc) {
	switch opts.Type {
	case "url":
		var url_prefixes *utils.Set[string]
		if opts.UrlPrefixes == "default" {
			url_prefixes = RelevantKittyOpts().Url_prefixes
		} else {
			url_prefixes = utils.NewSetWithItems(strings.Split(opts.UrlPrefixes, ",")...)
		}
		pattern = fmt.Sprintf(`(?:%s)://[^%s]{3,}`, strings.Join(url_prefixes.AsSlice(), "|"), URL_DELIMITERS)
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
	case "word":
		chars := opts.WordCharacters
		if chars == "" {
			chars = RelevantKittyOpts().Select_by_word_characters
		}
		chars = regexp.QuoteMeta(chars)
		pattern = fmt.Sprintf(`(?u)[%s\pL\pN]{%d,}`, chars, opts.MinimumMatchLength)
		post_processors = append(post_processors, PostProcessorMap()["brackets"], PostProcessorMap()["quotes"])
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

func mark(r *regexp.Regexp, post_processors []PostProcessorFunc, group_processors []GroupProcessorFunc, text string, opts *Options) (ans []Mark) {
	sanitize_pat := regexp.MustCompile("[\r\n\x00]")
	names := r.SubexpNames()
	for i, v := range r.FindAllStringSubmatchIndex(text, -1) {
		match_start, match_end := v[0], v[1]
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
		gd := make(map[string]string, len(names))
		for x, name := range names {
			if name != "" {
				idx := 2 * x
				if s, e := v[idx], v[idx+1]; s > -1 && e > -1 {
					s = utils.Max(s, match_start)
					e = utils.Min(e, match_end)
					gd[name] = sanitize_pat.ReplaceAllLiteralString(text[s:e], "")
				}
			}
		}
		for _, f := range group_processors {
			f(gd)
		}
		ans = append(ans, Mark{
			Index: i, Start: match_start, End: match_end, Text: full_match, Groupdict: gd,
		})
	}
	return
}

type ErrNoMatches struct{ Type string }

func (self *ErrNoMatches) Error() string {
	none_of := "matches"
	switch self.Type {
	case "urls":
		none_of = "URLs"
	case "hyperlinks":
		none_of = "hyperlinks"
	}
	return fmt.Sprintf("No %s found", none_of)
}

func find_marks(text string, opts *Options) (ans []Mark, index_map map[int]*Mark, err error) {
	text, hyperlinks := process_escape_codes(text)
	pattern, post_processors, group_processors := functions_for(opts)
	if opts.Type == "hyperlink" {
		ans = hyperlinks
	} else {
		r, err := regexp.Compile(pattern)
		if err != nil {
			return nil, nil, fmt.Errorf("Failed to compile the regex pattern: %#v with error: %w", pattern, err)
		}
		ans = mark(r, post_processors, group_processors, text, opts)
	}
	if len(ans) == 0 {
		return nil, nil, &ErrNoMatches{Type: opts.Type}
	}
	largest_index := ans[len(ans)-1].Index
	offset := utils.Max(0, opts.HintsOffset)
	index_map = make(map[int]*Mark, len(ans))
	for _, m := range ans {
		if opts.Ascending {
			m.Index += offset
		} else {
			m.Index = largest_index - m.Index + offset
		}
		index_map[m.Index] = &m
	}
	return
}
