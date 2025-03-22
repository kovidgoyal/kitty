package wcswidth


type GraphemeBreakProperty uint8

const (
GBP_AtStart GraphemeBreakProperty = iota
GBP_None
GBP_Prepend
GBP_CR
GBP_LF
GBP_Control
GBP_Extend
GBP_Regional_Indicator
GBP_SpacingMark
GBP_L
GBP_V
GBP_T
GBP_LV
GBP_LVT
GBP_ZWJ
)

type IndicConjunctBreak uint8

const (
ICB_None IndicConjunctBreak = iota
ICB_Linker
ICB_Consonant
ICB_Extend
)

