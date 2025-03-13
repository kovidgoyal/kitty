package wcswidth

type GraphemeBreakProperty uint8

const (
	None = iota
	Prepend
	CR
	LF
	Control
	Extend
	Regional_Indicator
	SpacingMark
	L
	V
	T
	LV
	LVT
	ZWJ
)

func GraphemeBreakPropertyFor(code rune) GraphemeBreakProperty {
	switch code {
	// Prepend (28 codepoints {{{
	// }}}

	// CR (1 codepoints {{{
	// }}}

	// LF (1 codepoints {{{
	// }}}

	// Control (3893 codepoints {{{
	// }}}

	// Extend (2198 codepoints {{{
	// }}}

	// Regional_Indicator (26 codepoints {{{
	// }}}

	// SpacingMark (378 codepoints {{{
	// }}}

	// L (125 codepoints {{{
	// }}}

	// V (100 codepoints {{{
	// }}}

	// T (137 codepoints {{{
	// }}}

	// LV (399 codepoints {{{
	// }}}

	// LVT (10773 codepoints {{{
	// }}}

	// ZWJ (1 codepoints {{{
	// }}}

	}
	return None
}
