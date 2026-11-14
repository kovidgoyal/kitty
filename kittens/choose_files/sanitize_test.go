package choose_files

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf8"
)

var _ = fmt.Print

func TestFileMetadataPreviewSanitizesNames(t *testing.T) {
	dir := t.TempDir()
	evil := "x\x1b]52;c;aGFja2Vk\x07\ny"
	path := filepath.Join(dir, evil)
	if err := os.Mkdir(path, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, evil+".\x1b[31m"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(evil, filepath.Join(path, "link")); err != nil {
		t.Fatal(err)
	}
	const sanitized = "x␛]52;c;aGFja2Vk␇␤y"
	check := func(mp *MessagePreview) {
		t.Helper()
		for _, text := range append([]string{mp.title, mp.msg}, mp.trailers...) {
			if strings.ContainsAny(text, "\x1b\x07") {
				t.Fatalf("preview contains unsanitized name: %#v", text)
			}
		}
		if all := mp.title + mp.msg + strings.Join(mp.trailers, "\n"); !strings.Contains(all, sanitized) {
			t.Fatalf("preview does not contain the sanitized name %#v: %#v", sanitized, all)
		}
	}
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	check(NewDirectoryPreview(path, st).(*MessagePreview))
	for _, name := range []string{evil + ".\x1b[31m", "link"} {
		fp := filepath.Join(path, name)
		st, err = os.Lstat(fp)
		if err != nil {
			t.Fatal(err)
		}
		check(NewFileMetadataPreview(fp, st))
		check(NewFileMetadataPreviewWithError(fp, st, fmt.Errorf("failed for %s", fp)))
	}
}

func TestSanitize(t *testing.T) {
	for _, tc := range []struct{ input, name, multiline string }{
		{"plain.txt", "plain.txt", "plain.txt"},
		{"a\x1b[31mb\x07", "a␛[31mb␇", "a␛[31mb␇"},
		{"a\tb\nc\x7f", "a␉b␤c␡", "a    b\nc␡"},
		{"a31mb52;c;eA", "a�31mb�52;c;eA�", "a�31mb�52;c;eA�"},
		{"é ", "é �", "é �"},
	} {
		if actual := sanitize_name(tc.input); actual != tc.name {
			t.Fatalf("sanitize_name(%#v) = %#v, expected %#v", tc.input, actual, tc.name)
		}
		if actual := sanitize(tc.input); actual != tc.multiline {
			t.Fatalf("sanitize(%#v) = %#v, expected %#v", tc.input, actual, tc.multiline)
		}
	}
	// match positions are rune offsets, so sanitize_name must preserve them
	input := "a\tb\nc\x1bd"
	if a, b := utf8.RuneCountInString(input), utf8.RuneCountInString(sanitize_name(input)); a != b {
		t.Fatalf("sanitize_name changed the number of runes from %d to %d", a, b)
	}
}

func TestKeepOnlySGR(t *testing.T) {
	for input, expected := range map[string]string{
		"plain":                               "plain",
		"\x1b[1;31mred\x1b[m":                 "\x1b[1;31mred\x1b[m",
		"\x1b[38:5:1mx":                       "\x1b[38:5:1mx",
		"a\x1b]52;c;aGFja2Vk\x07b":            "ab",
		"a\x1b]52;c;aGFja2Vk\x1b\\b":          "ab",
		"a\x1bP+q\x1b\\b":                     "ab",
		"a\x1b[2Jb\x1b[?1049hc":               "abc",
		"a\x1b[>1mb":                          "ab",
		"a\u009d52;c;eA\u009cb":               "ab",
		"a\nb\x07":                            "a␤b␇",
		"a\x1b[200~\x1b]52;c;eA\x07\x1b[201~": "a␛]52;c;eA␇",
	} {
		if actual := keep_only_sgr(input); actual != expected {
			t.Fatalf("keep_only_sgr(%#v) = %#v, expected %#v", input, actual, expected)
		}
	}
}
