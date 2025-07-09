package ignorefiles

import (
	"fmt"
	"io"
	"io/fs"
	"sync"
)

var _ = fmt.Print

type IgnoreFile interface {
	Len() int // number of rules
	LoadString(string) error
	LoadBytes([]byte) error
	LoadLines(...string) error
	LoadFile(io.Reader) error
	LoadPath(string) error

	// relpath is the path relative to the directory containing the ignorefile.
	// When the result is due to a rule matching, linenum_of_matching_rule is
	// >=0 and pattern is the textual representation of the rule. Otherwise
	// linenum_of_matching_rule is -1 and pattern is the empty string.
	IsIgnored(relpath string, ftype fs.FileMode) (is_ignored bool, linenum_of_matching_rule int, pattern string)
}

func NewGitignore() IgnoreFile { return &Gitignore{index_of_last_negated_rule: -1} }

// The global gitignore from ~/.config/git/ignore
var GlobalGitignore = sync.OnceValue(func() IgnoreFile {
	return get_global_gitignore()
})
