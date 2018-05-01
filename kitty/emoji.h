// unicode data, built from the unicode standard on: 2018-05-01
// see gen-wcwidth.py
#pragma once
#include "data-types.h"

START_ALLOW_CASE_RANGE

static inline bool
is_emoji(char_type code) {
	switch(code) {
		case 0x23:
			return true;
		case 0x2a:
			return true;
		case 0x30 ... 0x39:
			return true;
		case 0xa9:
			return true;
		case 0xae:
			return true;
		case 0x200d:
			return true;
		case 0x203c:
			return true;
		case 0x2049:
			return true;
		case 0x20e3:
			return true;
		case 0x2122:
			return true;
		case 0x2139:
			return true;
		case 0x2194 ... 0x2199:
			return true;
		case 0x21a9 ... 0x21aa:
			return true;
		case 0x231a ... 0x231b:
			return true;
		case 0x2328:
			return true;
		case 0x2388:
			return true;
		case 0x23cf:
			return true;
		case 0x23e9 ... 0x23f3:
			return true;
		case 0x23f8 ... 0x23fa:
			return true;
		case 0x24c2:
			return true;
		case 0x25aa ... 0x25ab:
			return true;
		case 0x25b6:
			return true;
		case 0x25c0:
			return true;
		case 0x25fb ... 0x25fe:
			return true;
		case 0x2600 ... 0x2605:
			return true;
		case 0x2607 ... 0x2612:
			return true;
		case 0x2614 ... 0x2685:
			return true;
		case 0x2690 ... 0x2705:
			return true;
		case 0x2708 ... 0x2712:
			return true;
		case 0x2714:
			return true;
		case 0x2716:
			return true;
		case 0x271d:
			return true;
		case 0x2721:
			return true;
		case 0x2728:
			return true;
		case 0x2733 ... 0x2734:
			return true;
		case 0x2744:
			return true;
		case 0x2747:
			return true;
		case 0x274c:
			return true;
		case 0x274e:
			return true;
		case 0x2753 ... 0x2755:
			return true;
		case 0x2757:
			return true;
		case 0x2763 ... 0x2767:
			return true;
		case 0x2795 ... 0x2797:
			return true;
		case 0x27a1:
			return true;
		case 0x27b0:
			return true;
		case 0x27bf:
			return true;
		case 0x2934 ... 0x2935:
			return true;
		case 0x2b05 ... 0x2b07:
			return true;
		case 0x2b1b ... 0x2b1c:
			return true;
		case 0x2b50:
			return true;
		case 0x2b55:
			return true;
		case 0x3030:
			return true;
		case 0x303d:
			return true;
		case 0x3297:
			return true;
		case 0x3299:
			return true;
		case 0xfe0f:
			return true;
		case 0x1f000 ... 0x1f0ff:
			return true;
		case 0x1f10d ... 0x1f10f:
			return true;
		case 0x1f12f:
			return true;
		case 0x1f16c ... 0x1f171:
			return true;
		case 0x1f17e ... 0x1f17f:
			return true;
		case 0x1f18e:
			return true;
		case 0x1f191 ... 0x1f19a:
			return true;
		case 0x1f1ad ... 0x1f1ff:
			return true;
		case 0x1f201 ... 0x1f20f:
			return true;
		case 0x1f21a:
			return true;
		case 0x1f22f:
			return true;
		case 0x1f232 ... 0x1f23a:
			return true;
		case 0x1f23c ... 0x1f23f:
			return true;
		case 0x1f249 ... 0x1f53d:
			return true;
		case 0x1f546 ... 0x1f64f:
			return true;
		case 0x1f680 ... 0x1f6ff:
			return true;
		case 0x1f774 ... 0x1f77f:
			return true;
		case 0x1f7d5 ... 0x1f7ff:
			return true;
		case 0x1f80c ... 0x1f80f:
			return true;
		case 0x1f848 ... 0x1f84f:
			return true;
		case 0x1f85a ... 0x1f85f:
			return true;
		case 0x1f888 ... 0x1f88f:
			return true;
		case 0x1f8ae ... 0x1f8ff:
			return true;
		case 0x1f90c ... 0x1f93a:
			return true;
		case 0x1f93c ... 0x1f945:
			return true;
		case 0x1f947 ... 0x1fffd:
			return true;
		case 0xe0020 ... 0xe007f:
			return true;
		default: return false;
	}
	return false;
}
static inline bool
is_emoji_modifier(char_type code) {
	switch(code) {
		case 0x1f3fb ... 0x1f3ff:
			return true;
		default: return false;
	}
	return false;
}

END_ALLOW_CASE_RANGE
