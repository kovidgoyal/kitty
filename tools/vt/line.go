package vt

import (
	"fmt"
)

var _ = fmt.Print

type PromptKind uint8

const (
	UNKNOWN_PROMPT_KIND PromptKind = iota
	PROMPT_START
	SECONDARY_PROMPT
	OUTPUT_START
)

type Line struct {
	Cells []Cell
	Attrs LineAttrs
}
