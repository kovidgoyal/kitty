package ignorefiles

import (
	"fmt"
	"io"
	"io/fs"
)

var _ = fmt.Print

type IgnoreFile interface {
	LoadString(string) error
	LoadBytes([]byte) error
	LoadLines(...string) error
	LoadFile(io.Reader) error
	LoadPath(string) error

	// relpath is the path relative to the directory containing the ignorefile.
	// When is_ignored is true, linenum_of_matching_rule will be the line
	// number of the rule causing relpath to be ignored and pattern is the
	// textual representation of the matching pattern.
	IsIgnored(relpath string, ftype fs.FileMode) (is_ignored bool, linenum_of_matching_rule int, pattern string)
}

func NewGitignore() IgnoreFile { return &Gitignore{index_of_last_negated_rule: -1} }
