package wcswidth

import (
	"fmt"
)

var _ = fmt.Print

type GraphemeSegmentationState struct {
	last_char_prop GraphemeBreakProperty

	/* True if the last character ends a sequence of Indic_Conjunct_Break
	values:  consonant {extend|linker}*  */
	incb_consonant_extended bool
	/* True if the last character ends a sequence of Indic_Conjunct_Break
	values:  consonant {extend|linker}* linker  */
	incb_consonant_extended_linker bool
	/* True if the last character ends a sequence of Indic_Conjunct_Break
	values:  consonant {extend|linker}* linker {extend|linker}*  */
	incb_consonant_extended_linker_extended bool

	/* True if the last character ends an emoji modifier sequence
	   \p{Extended_Pictographic} Extend*.  */
	emoji_modifier_sequence bool
	/* True if the last character was immediately preceded by an
	   emoji modifier sequence   \p{Extended_Pictographic} Extend*.  */
	emoji_modifier_sequence_before_last_char bool

	/* Number of consecutive regional indicator (RI) characters seen
	   immediately before the current point.  */
	ri_count uint
}

func Char_props_for(ch rune) CharProps {
	return charprops_t2[(rune(charprops_t1[ch>>charprops_shift])<<charprops_shift)+(ch&charprops_mask)]
}

func (i IndicConjunctBreak) is_linker_or_extend() bool {
	return i == ICB_Linker || i == ICB_Extend
}

func (s *GraphemeSegmentationState) Step(ch CharProps) bool {
	// Grapheme segmentation as per UAX29-C1-1 as defined in https://www.unicode.org/reports/tr29/
	// Returns true iff ch should be added to the current cell based on s which
	// must reflect the state of the current cell. s is updated by ch.
	prop := GraphemeBreakProperty(ch.Grapheme_break())
	incb := IndicConjunctBreak(ch.Indic_conjunct_break())
	add_to_cell := false
	if s.last_char_prop == GBP_AtStart {
		add_to_cell = true
	} else {
		/* No break between CR and LF (GB3).  */
		if s.last_char_prop == GBP_CR && prop == GBP_LF {
			add_to_cell = true
		} else if
		/* Break before and after newlines (GB4, GB5).  */
		(s.last_char_prop == GBP_CR || s.last_char_prop == GBP_LF || s.last_char_prop == GBP_Control) ||
			(prop == GBP_CR || prop == GBP_LF || prop == GBP_Control) {
		} else if
		/* No break between Hangul syllable sequences (GB6, GB7, GB8).  */
		(s.last_char_prop == GBP_L && (prop == GBP_L || prop == GBP_V || prop == GBP_LV || prop == GBP_LVT)) ||
			((s.last_char_prop == GBP_LV || s.last_char_prop == GBP_V) && (prop == GBP_V || prop == GBP_T)) ||
			((s.last_char_prop == GBP_LVT || s.last_char_prop == GBP_T) && prop == GBP_T) {
			add_to_cell = true
		} else if
		/* No break before: extending characters or ZWJ (GB9), SpacingMarks (GB9a), Prepend characters (GB9b)  */
		prop == GBP_Extend || prop == GBP_ZWJ || prop == GBP_SpacingMark || s.last_char_prop == GBP_Prepend {
			add_to_cell = true
		} else if
		/* No break within certain combinations of Indic_Conjunct_Break values:
		 * Between consonant {extend|linker}* linker {extend|linker}* and consonant (GB9c).  */
		s.incb_consonant_extended_linker_extended && incb == ICB_Consonant {
			add_to_cell = true
		} else if
		/* No break within emoji modifier sequences or emoji zwj sequences (GB11).  */
		s.last_char_prop == GBP_ZWJ && s.emoji_modifier_sequence_before_last_char && (ch.Is_extended_pictographic() == 1) {
			add_to_cell = true
		} else if
		/* No break between RI if there is an odd number of RI characters before (GB12, GB13).  */
		prop == GBP_Regional_Indicator && (s.ri_count%2) != 0 {
			add_to_cell = true
		} else
		/* Break everywhere else */
		{
		}
	}

	s.incb_consonant_extended_linker = s.incb_consonant_extended && incb == ICB_Linker
	s.incb_consonant_extended_linker_extended = (s.incb_consonant_extended_linker || (s.incb_consonant_extended_linker_extended && incb.is_linker_or_extend()))
	s.incb_consonant_extended = (incb == ICB_Consonant || (s.incb_consonant_extended && incb.is_linker_or_extend()))
	s.emoji_modifier_sequence_before_last_char = s.emoji_modifier_sequence
	s.emoji_modifier_sequence = (s.emoji_modifier_sequence && prop == GBP_Extend) || (ch.Is_extended_pictographic() == 1)
	s.last_char_prop = prop

	if prop == GBP_Regional_Indicator {
		s.ri_count++
	} else {
		s.ri_count = 0
	}
	return add_to_cell
}
