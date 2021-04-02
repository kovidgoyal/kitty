// unicode data, built from the unicode standard on: 2021-04-02
// see gen-wcwidth.py
#pragma once
#include "data-types.h"

START_ALLOW_CASE_RANGE

static inline int
wcwidth_std(int32_t code) {
	if (LIKELY(0x20 <= code && code <= 0x7e)) return 1;
	switch(code) {
		// Flags (26 codepoints) {{{
		case 0x1f1e6 ... 0x1f1ff:
			return 2;
		// }}}

		// Marks (2302 codepoints) {{{
		case 0x0:
			return 0;
		case 0x300 ... 0x36f:
			return 0;
		case 0x483 ... 0x489:
			return 0;
		case 0x591 ... 0x5bd:
			return 0;
		case 0x5bf:
			return 0;
		case 0x5c1 ... 0x5c2:
			return 0;
		case 0x5c4 ... 0x5c5:
			return 0;
		case 0x5c7:
			return 0;
		case 0x610 ... 0x61a:
			return 0;
		case 0x64b ... 0x65f:
			return 0;
		case 0x670:
			return 0;
		case 0x6d6 ... 0x6dc:
			return 0;
		case 0x6df ... 0x6e4:
			return 0;
		case 0x6e7 ... 0x6e8:
			return 0;
		case 0x6ea ... 0x6ed:
			return 0;
		case 0x711:
			return 0;
		case 0x730 ... 0x74a:
			return 0;
		case 0x7a6 ... 0x7b0:
			return 0;
		case 0x7eb ... 0x7f3:
			return 0;
		case 0x7fd:
			return 0;
		case 0x816 ... 0x819:
			return 0;
		case 0x81b ... 0x823:
			return 0;
		case 0x825 ... 0x827:
			return 0;
		case 0x829 ... 0x82d:
			return 0;
		case 0x859 ... 0x85b:
			return 0;
		case 0x8d3 ... 0x8e1:
			return 0;
		case 0x8e3 ... 0x903:
			return 0;
		case 0x93a ... 0x93c:
			return 0;
		case 0x93e ... 0x94f:
			return 0;
		case 0x951 ... 0x957:
			return 0;
		case 0x962 ... 0x963:
			return 0;
		case 0x981 ... 0x983:
			return 0;
		case 0x9bc:
			return 0;
		case 0x9be ... 0x9c4:
			return 0;
		case 0x9c7 ... 0x9c8:
			return 0;
		case 0x9cb ... 0x9cd:
			return 0;
		case 0x9d7:
			return 0;
		case 0x9e2 ... 0x9e3:
			return 0;
		case 0x9fe:
			return 0;
		case 0xa01 ... 0xa03:
			return 0;
		case 0xa3c:
			return 0;
		case 0xa3e ... 0xa42:
			return 0;
		case 0xa47 ... 0xa48:
			return 0;
		case 0xa4b ... 0xa4d:
			return 0;
		case 0xa51:
			return 0;
		case 0xa70 ... 0xa71:
			return 0;
		case 0xa75:
			return 0;
		case 0xa81 ... 0xa83:
			return 0;
		case 0xabc:
			return 0;
		case 0xabe ... 0xac5:
			return 0;
		case 0xac7 ... 0xac9:
			return 0;
		case 0xacb ... 0xacd:
			return 0;
		case 0xae2 ... 0xae3:
			return 0;
		case 0xafa ... 0xaff:
			return 0;
		case 0xb01 ... 0xb03:
			return 0;
		case 0xb3c:
			return 0;
		case 0xb3e ... 0xb44:
			return 0;
		case 0xb47 ... 0xb48:
			return 0;
		case 0xb4b ... 0xb4d:
			return 0;
		case 0xb55 ... 0xb57:
			return 0;
		case 0xb62 ... 0xb63:
			return 0;
		case 0xb82:
			return 0;
		case 0xbbe ... 0xbc2:
			return 0;
		case 0xbc6 ... 0xbc8:
			return 0;
		case 0xbca ... 0xbcd:
			return 0;
		case 0xbd7:
			return 0;
		case 0xc00 ... 0xc04:
			return 0;
		case 0xc3e ... 0xc44:
			return 0;
		case 0xc46 ... 0xc48:
			return 0;
		case 0xc4a ... 0xc4d:
			return 0;
		case 0xc55 ... 0xc56:
			return 0;
		case 0xc62 ... 0xc63:
			return 0;
		case 0xc81 ... 0xc83:
			return 0;
		case 0xcbc:
			return 0;
		case 0xcbe ... 0xcc4:
			return 0;
		case 0xcc6 ... 0xcc8:
			return 0;
		case 0xcca ... 0xccd:
			return 0;
		case 0xcd5 ... 0xcd6:
			return 0;
		case 0xce2 ... 0xce3:
			return 0;
		case 0xd00 ... 0xd03:
			return 0;
		case 0xd3b ... 0xd3c:
			return 0;
		case 0xd3e ... 0xd44:
			return 0;
		case 0xd46 ... 0xd48:
			return 0;
		case 0xd4a ... 0xd4d:
			return 0;
		case 0xd57:
			return 0;
		case 0xd62 ... 0xd63:
			return 0;
		case 0xd81 ... 0xd83:
			return 0;
		case 0xdca:
			return 0;
		case 0xdcf ... 0xdd4:
			return 0;
		case 0xdd6:
			return 0;
		case 0xdd8 ... 0xddf:
			return 0;
		case 0xdf2 ... 0xdf3:
			return 0;
		case 0xe31:
			return 0;
		case 0xe34 ... 0xe3a:
			return 0;
		case 0xe47 ... 0xe4e:
			return 0;
		case 0xeb1:
			return 0;
		case 0xeb4 ... 0xebc:
			return 0;
		case 0xec8 ... 0xecd:
			return 0;
		case 0xf18 ... 0xf19:
			return 0;
		case 0xf35:
			return 0;
		case 0xf37:
			return 0;
		case 0xf39:
			return 0;
		case 0xf3e ... 0xf3f:
			return 0;
		case 0xf71 ... 0xf84:
			return 0;
		case 0xf86 ... 0xf87:
			return 0;
		case 0xf8d ... 0xf97:
			return 0;
		case 0xf99 ... 0xfbc:
			return 0;
		case 0xfc6:
			return 0;
		case 0x102b ... 0x103e:
			return 0;
		case 0x1056 ... 0x1059:
			return 0;
		case 0x105e ... 0x1060:
			return 0;
		case 0x1062 ... 0x1064:
			return 0;
		case 0x1067 ... 0x106d:
			return 0;
		case 0x1071 ... 0x1074:
			return 0;
		case 0x1082 ... 0x108d:
			return 0;
		case 0x108f:
			return 0;
		case 0x109a ... 0x109d:
			return 0;
		case 0x135d ... 0x135f:
			return 0;
		case 0x1712 ... 0x1714:
			return 0;
		case 0x1732 ... 0x1734:
			return 0;
		case 0x1752 ... 0x1753:
			return 0;
		case 0x1772 ... 0x1773:
			return 0;
		case 0x17b4 ... 0x17d3:
			return 0;
		case 0x17dd:
			return 0;
		case 0x180b ... 0x180d:
			return 0;
		case 0x1885 ... 0x1886:
			return 0;
		case 0x18a9:
			return 0;
		case 0x1920 ... 0x192b:
			return 0;
		case 0x1930 ... 0x193b:
			return 0;
		case 0x1a17 ... 0x1a1b:
			return 0;
		case 0x1a55 ... 0x1a5e:
			return 0;
		case 0x1a60 ... 0x1a7c:
			return 0;
		case 0x1a7f:
			return 0;
		case 0x1ab0 ... 0x1ac0:
			return 0;
		case 0x1b00 ... 0x1b04:
			return 0;
		case 0x1b34 ... 0x1b44:
			return 0;
		case 0x1b6b ... 0x1b73:
			return 0;
		case 0x1b80 ... 0x1b82:
			return 0;
		case 0x1ba1 ... 0x1bad:
			return 0;
		case 0x1be6 ... 0x1bf3:
			return 0;
		case 0x1c24 ... 0x1c37:
			return 0;
		case 0x1cd0 ... 0x1cd2:
			return 0;
		case 0x1cd4 ... 0x1ce8:
			return 0;
		case 0x1ced:
			return 0;
		case 0x1cf4:
			return 0;
		case 0x1cf7 ... 0x1cf9:
			return 0;
		case 0x1dc0 ... 0x1df9:
			return 0;
		case 0x1dfb ... 0x1dff:
			return 0;
		case 0x200d:
			return 0;
		case 0x20d0 ... 0x20f0:
			return 0;
		case 0x2cef ... 0x2cf1:
			return 0;
		case 0x2d7f:
			return 0;
		case 0x2de0 ... 0x2dff:
			return 0;
		case 0x302a ... 0x302f:
			return 0;
		case 0x3099 ... 0x309a:
			return 0;
		case 0xa66f ... 0xa672:
			return 0;
		case 0xa674 ... 0xa67d:
			return 0;
		case 0xa69e ... 0xa69f:
			return 0;
		case 0xa6f0 ... 0xa6f1:
			return 0;
		case 0xa802:
			return 0;
		case 0xa806:
			return 0;
		case 0xa80b:
			return 0;
		case 0xa823 ... 0xa827:
			return 0;
		case 0xa82c:
			return 0;
		case 0xa880 ... 0xa881:
			return 0;
		case 0xa8b4 ... 0xa8c5:
			return 0;
		case 0xa8e0 ... 0xa8f1:
			return 0;
		case 0xa8ff:
			return 0;
		case 0xa926 ... 0xa92d:
			return 0;
		case 0xa947 ... 0xa953:
			return 0;
		case 0xa980 ... 0xa983:
			return 0;
		case 0xa9b3 ... 0xa9c0:
			return 0;
		case 0xa9e5:
			return 0;
		case 0xaa29 ... 0xaa36:
			return 0;
		case 0xaa43:
			return 0;
		case 0xaa4c ... 0xaa4d:
			return 0;
		case 0xaa7b ... 0xaa7d:
			return 0;
		case 0xaab0:
			return 0;
		case 0xaab2 ... 0xaab4:
			return 0;
		case 0xaab7 ... 0xaab8:
			return 0;
		case 0xaabe ... 0xaabf:
			return 0;
		case 0xaac1:
			return 0;
		case 0xaaeb ... 0xaaef:
			return 0;
		case 0xaaf5 ... 0xaaf6:
			return 0;
		case 0xabe3 ... 0xabea:
			return 0;
		case 0xabec ... 0xabed:
			return 0;
		case 0xfb1e:
			return 0;
		case 0xfe00 ... 0xfe0f:
			return 0;
		case 0xfe20 ... 0xfe2f:
			return 0;
		case 0x101fd:
			return 0;
		case 0x102e0:
			return 0;
		case 0x10376 ... 0x1037a:
			return 0;
		case 0x10a01 ... 0x10a03:
			return 0;
		case 0x10a05 ... 0x10a06:
			return 0;
		case 0x10a0c ... 0x10a0f:
			return 0;
		case 0x10a38 ... 0x10a3a:
			return 0;
		case 0x10a3f:
			return 0;
		case 0x10ae5 ... 0x10ae6:
			return 0;
		case 0x10d24 ... 0x10d27:
			return 0;
		case 0x10eab ... 0x10eac:
			return 0;
		case 0x10f46 ... 0x10f50:
			return 0;
		case 0x11000 ... 0x11002:
			return 0;
		case 0x11038 ... 0x11046:
			return 0;
		case 0x1107f ... 0x11082:
			return 0;
		case 0x110b0 ... 0x110ba:
			return 0;
		case 0x11100 ... 0x11102:
			return 0;
		case 0x11127 ... 0x11134:
			return 0;
		case 0x11145 ... 0x11146:
			return 0;
		case 0x11173:
			return 0;
		case 0x11180 ... 0x11182:
			return 0;
		case 0x111b3 ... 0x111c0:
			return 0;
		case 0x111c9 ... 0x111cc:
			return 0;
		case 0x111ce ... 0x111cf:
			return 0;
		case 0x1122c ... 0x11237:
			return 0;
		case 0x1123e:
			return 0;
		case 0x112df ... 0x112ea:
			return 0;
		case 0x11300 ... 0x11303:
			return 0;
		case 0x1133b ... 0x1133c:
			return 0;
		case 0x1133e ... 0x11344:
			return 0;
		case 0x11347 ... 0x11348:
			return 0;
		case 0x1134b ... 0x1134d:
			return 0;
		case 0x11357:
			return 0;
		case 0x11362 ... 0x11363:
			return 0;
		case 0x11366 ... 0x1136c:
			return 0;
		case 0x11370 ... 0x11374:
			return 0;
		case 0x11435 ... 0x11446:
			return 0;
		case 0x1145e:
			return 0;
		case 0x114b0 ... 0x114c3:
			return 0;
		case 0x115af ... 0x115b5:
			return 0;
		case 0x115b8 ... 0x115c0:
			return 0;
		case 0x115dc ... 0x115dd:
			return 0;
		case 0x11630 ... 0x11640:
			return 0;
		case 0x116ab ... 0x116b7:
			return 0;
		case 0x1171d ... 0x1172b:
			return 0;
		case 0x1182c ... 0x1183a:
			return 0;
		case 0x11930 ... 0x11935:
			return 0;
		case 0x11937 ... 0x11938:
			return 0;
		case 0x1193b ... 0x1193e:
			return 0;
		case 0x11940:
			return 0;
		case 0x11942 ... 0x11943:
			return 0;
		case 0x119d1 ... 0x119d7:
			return 0;
		case 0x119da ... 0x119e0:
			return 0;
		case 0x119e4:
			return 0;
		case 0x11a01 ... 0x11a0a:
			return 0;
		case 0x11a33 ... 0x11a39:
			return 0;
		case 0x11a3b ... 0x11a3e:
			return 0;
		case 0x11a47:
			return 0;
		case 0x11a51 ... 0x11a5b:
			return 0;
		case 0x11a8a ... 0x11a99:
			return 0;
		case 0x11c2f ... 0x11c36:
			return 0;
		case 0x11c38 ... 0x11c3f:
			return 0;
		case 0x11c92 ... 0x11ca7:
			return 0;
		case 0x11ca9 ... 0x11cb6:
			return 0;
		case 0x11d31 ... 0x11d36:
			return 0;
		case 0x11d3a:
			return 0;
		case 0x11d3c ... 0x11d3d:
			return 0;
		case 0x11d3f ... 0x11d45:
			return 0;
		case 0x11d47:
			return 0;
		case 0x11d8a ... 0x11d8e:
			return 0;
		case 0x11d90 ... 0x11d91:
			return 0;
		case 0x11d93 ... 0x11d97:
			return 0;
		case 0x11ef3 ... 0x11ef6:
			return 0;
		case 0x16af0 ... 0x16af4:
			return 0;
		case 0x16b30 ... 0x16b36:
			return 0;
		case 0x16f4f:
			return 0;
		case 0x16f51 ... 0x16f87:
			return 0;
		case 0x16f8f ... 0x16f92:
			return 0;
		case 0x16fe4:
			return 0;
		case 0x16ff0 ... 0x16ff1:
			return 0;
		case 0x1bc9d ... 0x1bc9e:
			return 0;
		case 0x1d165 ... 0x1d169:
			return 0;
		case 0x1d16d ... 0x1d172:
			return 0;
		case 0x1d17b ... 0x1d182:
			return 0;
		case 0x1d185 ... 0x1d18b:
			return 0;
		case 0x1d1aa ... 0x1d1ad:
			return 0;
		case 0x1d242 ... 0x1d244:
			return 0;
		case 0x1da00 ... 0x1da36:
			return 0;
		case 0x1da3b ... 0x1da6c:
			return 0;
		case 0x1da75:
			return 0;
		case 0x1da84:
			return 0;
		case 0x1da9b ... 0x1da9f:
			return 0;
		case 0x1daa1 ... 0x1daaf:
			return 0;
		case 0x1e000 ... 0x1e006:
			return 0;
		case 0x1e008 ... 0x1e018:
			return 0;
		case 0x1e01b ... 0x1e021:
			return 0;
		case 0x1e023 ... 0x1e024:
			return 0;
		case 0x1e026 ... 0x1e02a:
			return 0;
		case 0x1e130 ... 0x1e136:
			return 0;
		case 0x1e2ec ... 0x1e2ef:
			return 0;
		case 0x1e8d0 ... 0x1e8d6:
			return 0;
		case 0x1e944 ... 0x1e94a:
			return 0;
		case 0x1f3fb ... 0x1f3ff:
			return 0;
		case 0xe0100 ... 0xe01ef:
			return 0;
		// }}}

		// Non-printing characters (2272 codepoints) {{{
		case 0x1 ... 0x1f:
			return -1;
		case 0x7f ... 0x9f:
			return -1;
		case 0xad:
			return -1;
		case 0x600 ... 0x605:
			return -1;
		case 0x61c:
			return -1;
		case 0x6dd:
			return -1;
		case 0x70f:
			return -1;
		case 0x8e2:
			return -1;
		case 0x180e:
			return -1;
		case 0x200b ... 0x200c:
			return -1;
		case 0x200e ... 0x200f:
			return -1;
		case 0x202a ... 0x202e:
			return -1;
		case 0x2060 ... 0x2064:
			return -1;
		case 0x2066 ... 0x206f:
			return -1;
		case 0xd800 ... 0xdfff:
			return -1;
		case 0xfeff:
			return -1;
		case 0xfff9 ... 0xfffb:
			return -1;
		case 0x110bd:
			return -1;
		case 0x110cd:
			return -1;
		case 0x13430 ... 0x13438:
			return -1;
		case 0x1bca0 ... 0x1bca3:
			return -1;
		case 0x1d173 ... 0x1d17a:
			return -1;
		case 0xe0001:
			return -1;
		case 0xe0020 ... 0xe007f:
			return -1;
		// }}}

		// Private use (137468 codepoints) {{{
		case 0xe000 ... 0xf8ff:
			return -3;
		case 0xf0000 ... 0xffffd:
			return -3;
		case 0x100000 ... 0x10fffd:
			return -3;
		// }}}

		// Text Presentation (219 codepoints) {{{
		case 0x23:
			return 1;
		case 0x2a:
			return 1;
		case 0x30 ... 0x39:
			return 1;
		case 0xa9:
			return 1;
		case 0xae:
			return 1;
		case 0x203c:
			return 1;
		case 0x2049:
			return 1;
		case 0x2122:
			return 1;
		case 0x2139:
			return 1;
		case 0x2194 ... 0x2199:
			return 1;
		case 0x21a9 ... 0x21aa:
			return 1;
		case 0x2328:
			return 1;
		case 0x23cf:
			return 1;
		case 0x23ed ... 0x23ef:
			return 1;
		case 0x23f1 ... 0x23f2:
			return 1;
		case 0x23f8 ... 0x23fa:
			return 1;
		case 0x24c2:
			return 1;
		case 0x25aa ... 0x25ab:
			return 1;
		case 0x25b6:
			return 1;
		case 0x25c0:
			return 1;
		case 0x25fb ... 0x25fc:
			return 1;
		case 0x2600 ... 0x2604:
			return 1;
		case 0x260e:
			return 1;
		case 0x2611:
			return 1;
		case 0x2618:
			return 1;
		case 0x261d:
			return 1;
		case 0x2620:
			return 1;
		case 0x2622 ... 0x2623:
			return 1;
		case 0x2626:
			return 1;
		case 0x262a:
			return 1;
		case 0x262e ... 0x262f:
			return 1;
		case 0x2638 ... 0x263a:
			return 1;
		case 0x2640:
			return 1;
		case 0x2642:
			return 1;
		case 0x265f ... 0x2660:
			return 1;
		case 0x2663:
			return 1;
		case 0x2665 ... 0x2666:
			return 1;
		case 0x2668:
			return 1;
		case 0x267b:
			return 1;
		case 0x267e:
			return 1;
		case 0x2692:
			return 1;
		case 0x2694 ... 0x2697:
			return 1;
		case 0x2699:
			return 1;
		case 0x269b ... 0x269c:
			return 1;
		case 0x26a0:
			return 1;
		case 0x26a7:
			return 1;
		case 0x26b0 ... 0x26b1:
			return 1;
		case 0x26c8:
			return 1;
		case 0x26cf:
			return 1;
		case 0x26d1:
			return 1;
		case 0x26d3:
			return 1;
		case 0x26e9:
			return 1;
		case 0x26f0 ... 0x26f1:
			return 1;
		case 0x26f4:
			return 1;
		case 0x26f7 ... 0x26f9:
			return 1;
		case 0x2702:
			return 1;
		case 0x2708 ... 0x2709:
			return 1;
		case 0x270c ... 0x270d:
			return 1;
		case 0x270f:
			return 1;
		case 0x2712:
			return 1;
		case 0x2714:
			return 1;
		case 0x2716:
			return 1;
		case 0x271d:
			return 1;
		case 0x2721:
			return 1;
		case 0x2733 ... 0x2734:
			return 1;
		case 0x2744:
			return 1;
		case 0x2747:
			return 1;
		case 0x2763 ... 0x2764:
			return 1;
		case 0x27a1:
			return 1;
		case 0x2934 ... 0x2935:
			return 1;
		case 0x2b05 ... 0x2b07:
			return 1;
		case 0x3030:
			return 1;
		case 0x303d:
			return 1;
		case 0x3297:
			return 1;
		case 0x3299:
			return 1;
		case 0x1f170 ... 0x1f171:
			return 1;
		case 0x1f17e ... 0x1f17f:
			return 1;
		case 0x1f202:
			return 1;
		case 0x1f237:
			return 1;
		case 0x1f321:
			return 1;
		case 0x1f324 ... 0x1f32c:
			return 1;
		case 0x1f336:
			return 1;
		case 0x1f37d:
			return 1;
		case 0x1f396 ... 0x1f397:
			return 1;
		case 0x1f399 ... 0x1f39b:
			return 1;
		case 0x1f39e ... 0x1f39f:
			return 1;
		case 0x1f3cb ... 0x1f3ce:
			return 1;
		case 0x1f3d4 ... 0x1f3df:
			return 1;
		case 0x1f3f3:
			return 1;
		case 0x1f3f5:
			return 1;
		case 0x1f3f7:
			return 1;
		case 0x1f43f:
			return 1;
		case 0x1f441:
			return 1;
		case 0x1f4fd:
			return 1;
		case 0x1f549 ... 0x1f54a:
			return 1;
		case 0x1f56f ... 0x1f570:
			return 1;
		case 0x1f573 ... 0x1f579:
			return 1;
		case 0x1f587:
			return 1;
		case 0x1f58a ... 0x1f58d:
			return 1;
		case 0x1f590:
			return 1;
		case 0x1f5a5:
			return 1;
		case 0x1f5a8:
			return 1;
		case 0x1f5b1 ... 0x1f5b2:
			return 1;
		case 0x1f5bc:
			return 1;
		case 0x1f5c2 ... 0x1f5c4:
			return 1;
		case 0x1f5d1 ... 0x1f5d3:
			return 1;
		case 0x1f5dc ... 0x1f5de:
			return 1;
		case 0x1f5e1:
			return 1;
		case 0x1f5e3:
			return 1;
		case 0x1f5e8:
			return 1;
		case 0x1f5ef:
			return 1;
		case 0x1f5f3:
			return 1;
		case 0x1f5fa:
			return 1;
		case 0x1f6cb:
			return 1;
		case 0x1f6cd ... 0x1f6cf:
			return 1;
		case 0x1f6e0 ... 0x1f6e5:
			return 1;
		case 0x1f6e9:
			return 1;
		case 0x1f6f0:
			return 1;
		case 0x1f6f3:
			return 1;
		// }}}

		// East Asian ambiguous width (869 codepoints) {{{
		case 0xa1:
			return -2;
		case 0xa4:
			return -2;
		case 0xa7 ... 0xa8:
			return -2;
		case 0xaa:
			return -2;
		case 0xb0 ... 0xb4:
			return -2;
		case 0xb6 ... 0xba:
			return -2;
		case 0xbc ... 0xbf:
			return -2;
		case 0xc6:
			return -2;
		case 0xd0:
			return -2;
		case 0xd7 ... 0xd8:
			return -2;
		case 0xde ... 0xe1:
			return -2;
		case 0xe6:
			return -2;
		case 0xe8 ... 0xea:
			return -2;
		case 0xec ... 0xed:
			return -2;
		case 0xf0:
			return -2;
		case 0xf2 ... 0xf3:
			return -2;
		case 0xf7 ... 0xfa:
			return -2;
		case 0xfc:
			return -2;
		case 0xfe:
			return -2;
		case 0x101:
			return -2;
		case 0x111:
			return -2;
		case 0x113:
			return -2;
		case 0x11b:
			return -2;
		case 0x126 ... 0x127:
			return -2;
		case 0x12b:
			return -2;
		case 0x131 ... 0x133:
			return -2;
		case 0x138:
			return -2;
		case 0x13f ... 0x142:
			return -2;
		case 0x144:
			return -2;
		case 0x148 ... 0x14b:
			return -2;
		case 0x14d:
			return -2;
		case 0x152 ... 0x153:
			return -2;
		case 0x166 ... 0x167:
			return -2;
		case 0x16b:
			return -2;
		case 0x1ce:
			return -2;
		case 0x1d0:
			return -2;
		case 0x1d2:
			return -2;
		case 0x1d4:
			return -2;
		case 0x1d6:
			return -2;
		case 0x1d8:
			return -2;
		case 0x1da:
			return -2;
		case 0x1dc:
			return -2;
		case 0x251:
			return -2;
		case 0x261:
			return -2;
		case 0x2c4:
			return -2;
		case 0x2c7:
			return -2;
		case 0x2c9 ... 0x2cb:
			return -2;
		case 0x2cd:
			return -2;
		case 0x2d0:
			return -2;
		case 0x2d8 ... 0x2db:
			return -2;
		case 0x2dd:
			return -2;
		case 0x2df:
			return -2;
		case 0x391 ... 0x3a1:
			return -2;
		case 0x3a3 ... 0x3a9:
			return -2;
		case 0x3b1 ... 0x3c1:
			return -2;
		case 0x3c3 ... 0x3c9:
			return -2;
		case 0x401:
			return -2;
		case 0x410 ... 0x44f:
			return -2;
		case 0x451:
			return -2;
		case 0x2010:
			return -2;
		case 0x2013 ... 0x2016:
			return -2;
		case 0x2018 ... 0x2019:
			return -2;
		case 0x201c ... 0x201d:
			return -2;
		case 0x2020 ... 0x2022:
			return -2;
		case 0x2024 ... 0x2027:
			return -2;
		case 0x2030:
			return -2;
		case 0x2032 ... 0x2033:
			return -2;
		case 0x2035:
			return -2;
		case 0x203b:
			return -2;
		case 0x203e:
			return -2;
		case 0x2074:
			return -2;
		case 0x207f:
			return -2;
		case 0x2081 ... 0x2084:
			return -2;
		case 0x20ac:
			return -2;
		case 0x2103:
			return -2;
		case 0x2105:
			return -2;
		case 0x2109:
			return -2;
		case 0x2113:
			return -2;
		case 0x2116:
			return -2;
		case 0x2121:
			return -2;
		case 0x2126:
			return -2;
		case 0x212b:
			return -2;
		case 0x2153 ... 0x2154:
			return -2;
		case 0x215b ... 0x215e:
			return -2;
		case 0x2160 ... 0x216b:
			return -2;
		case 0x2170 ... 0x2179:
			return -2;
		case 0x2189:
			return -2;
		case 0x2190 ... 0x2193:
			return -2;
		case 0x21b8 ... 0x21b9:
			return -2;
		case 0x21d2:
			return -2;
		case 0x21d4:
			return -2;
		case 0x21e7:
			return -2;
		case 0x2200:
			return -2;
		case 0x2202 ... 0x2203:
			return -2;
		case 0x2207 ... 0x2208:
			return -2;
		case 0x220b:
			return -2;
		case 0x220f:
			return -2;
		case 0x2211:
			return -2;
		case 0x2215:
			return -2;
		case 0x221a:
			return -2;
		case 0x221d ... 0x2220:
			return -2;
		case 0x2223:
			return -2;
		case 0x2225:
			return -2;
		case 0x2227 ... 0x222c:
			return -2;
		case 0x222e:
			return -2;
		case 0x2234 ... 0x2237:
			return -2;
		case 0x223c ... 0x223d:
			return -2;
		case 0x2248:
			return -2;
		case 0x224c:
			return -2;
		case 0x2252:
			return -2;
		case 0x2260 ... 0x2261:
			return -2;
		case 0x2264 ... 0x2267:
			return -2;
		case 0x226a ... 0x226b:
			return -2;
		case 0x226e ... 0x226f:
			return -2;
		case 0x2282 ... 0x2283:
			return -2;
		case 0x2286 ... 0x2287:
			return -2;
		case 0x2295:
			return -2;
		case 0x2299:
			return -2;
		case 0x22a5:
			return -2;
		case 0x22bf:
			return -2;
		case 0x2312:
			return -2;
		case 0x2460 ... 0x24c1:
			return -2;
		case 0x24c3 ... 0x24e9:
			return -2;
		case 0x24eb ... 0x254b:
			return -2;
		case 0x2550 ... 0x2573:
			return -2;
		case 0x2580 ... 0x258f:
			return -2;
		case 0x2592 ... 0x2595:
			return -2;
		case 0x25a0 ... 0x25a1:
			return -2;
		case 0x25a3 ... 0x25a9:
			return -2;
		case 0x25b2 ... 0x25b3:
			return -2;
		case 0x25b7:
			return -2;
		case 0x25bc ... 0x25bd:
			return -2;
		case 0x25c1:
			return -2;
		case 0x25c6 ... 0x25c8:
			return -2;
		case 0x25cb:
			return -2;
		case 0x25ce ... 0x25d1:
			return -2;
		case 0x25e2 ... 0x25e5:
			return -2;
		case 0x25ef:
			return -2;
		case 0x2605 ... 0x2606:
			return -2;
		case 0x2609:
			return -2;
		case 0x260f:
			return -2;
		case 0x261c:
			return -2;
		case 0x261e:
			return -2;
		case 0x2661:
			return -2;
		case 0x2664:
			return -2;
		case 0x2667:
			return -2;
		case 0x2669 ... 0x266a:
			return -2;
		case 0x266c ... 0x266d:
			return -2;
		case 0x266f:
			return -2;
		case 0x269e ... 0x269f:
			return -2;
		case 0x26bf:
			return -2;
		case 0x26c6 ... 0x26c7:
			return -2;
		case 0x26c9 ... 0x26cd:
			return -2;
		case 0x26d0:
			return -2;
		case 0x26d2:
			return -2;
		case 0x26d5 ... 0x26e1:
			return -2;
		case 0x26e3:
			return -2;
		case 0x26e8:
			return -2;
		case 0x26eb ... 0x26ef:
			return -2;
		case 0x26f6:
			return -2;
		case 0x26fb ... 0x26fc:
			return -2;
		case 0x26fe ... 0x26ff:
			return -2;
		case 0x273d:
			return -2;
		case 0x2776 ... 0x277f:
			return -2;
		case 0x2b56 ... 0x2b59:
			return -2;
		case 0x3248 ... 0x324f:
			return -2;
		case 0xfffd:
			return -2;
		case 0x1f100 ... 0x1f10a:
			return -2;
		case 0x1f110 ... 0x1f12d:
			return -2;
		case 0x1f130 ... 0x1f169:
			return -2;
		case 0x1f172 ... 0x1f17d:
			return -2;
		case 0x1f180 ... 0x1f18d:
			return -2;
		case 0x1f18f ... 0x1f190:
			return -2;
		case 0x1f19b ... 0x1f1ac:
			return -2;
		// }}}

		// East Asian double width (182418 codepoints) {{{
		case 0x1100 ... 0x115f:
			return 2;
		case 0x231a ... 0x231b:
			return 2;
		case 0x2329 ... 0x232a:
			return 2;
		case 0x23e9 ... 0x23ec:
			return 2;
		case 0x23f0:
			return 2;
		case 0x23f3:
			return 2;
		case 0x25fd ... 0x25fe:
			return 2;
		case 0x2614 ... 0x2615:
			return 2;
		case 0x2648 ... 0x2653:
			return 2;
		case 0x267f:
			return 2;
		case 0x2693:
			return 2;
		case 0x26a1:
			return 2;
		case 0x26aa ... 0x26ab:
			return 2;
		case 0x26bd ... 0x26be:
			return 2;
		case 0x26c4 ... 0x26c5:
			return 2;
		case 0x26ce:
			return 2;
		case 0x26d4:
			return 2;
		case 0x26ea:
			return 2;
		case 0x26f2 ... 0x26f3:
			return 2;
		case 0x26f5:
			return 2;
		case 0x26fa:
			return 2;
		case 0x26fd:
			return 2;
		case 0x2705:
			return 2;
		case 0x270a ... 0x270b:
			return 2;
		case 0x2728:
			return 2;
		case 0x274c:
			return 2;
		case 0x274e:
			return 2;
		case 0x2753 ... 0x2755:
			return 2;
		case 0x2757:
			return 2;
		case 0x2795 ... 0x2797:
			return 2;
		case 0x27b0:
			return 2;
		case 0x27bf:
			return 2;
		case 0x2b1b ... 0x2b1c:
			return 2;
		case 0x2b50:
			return 2;
		case 0x2b55:
			return 2;
		case 0x2e80 ... 0x2e99:
			return 2;
		case 0x2e9b ... 0x2ef3:
			return 2;
		case 0x2f00 ... 0x2fd5:
			return 2;
		case 0x2ff0 ... 0x2ffb:
			return 2;
		case 0x3000 ... 0x3029:
			return 2;
		case 0x3031 ... 0x303c:
			return 2;
		case 0x303e:
			return 2;
		case 0x3041 ... 0x3096:
			return 2;
		case 0x309b ... 0x30ff:
			return 2;
		case 0x3105 ... 0x312f:
			return 2;
		case 0x3131 ... 0x318e:
			return 2;
		case 0x3190 ... 0x31e3:
			return 2;
		case 0x31f0 ... 0x321e:
			return 2;
		case 0x3220 ... 0x3247:
			return 2;
		case 0x3250 ... 0x3296:
			return 2;
		case 0x3298:
			return 2;
		case 0x329a ... 0x4dbf:
			return 2;
		case 0x4e00 ... 0xa48c:
			return 2;
		case 0xa490 ... 0xa4c6:
			return 2;
		case 0xa960 ... 0xa97c:
			return 2;
		case 0xac00 ... 0xd7a3:
			return 2;
		case 0xf900 ... 0xfaff:
			return 2;
		case 0xfe10 ... 0xfe19:
			return 2;
		case 0xfe30 ... 0xfe52:
			return 2;
		case 0xfe54 ... 0xfe66:
			return 2;
		case 0xfe68 ... 0xfe6b:
			return 2;
		case 0xff01 ... 0xff60:
			return 2;
		case 0xffe0 ... 0xffe6:
			return 2;
		case 0x16fe0 ... 0x16fe3:
			return 2;
		case 0x17000 ... 0x187f7:
			return 2;
		case 0x18800 ... 0x18cd5:
			return 2;
		case 0x18d00 ... 0x18d08:
			return 2;
		case 0x1b000 ... 0x1b11e:
			return 2;
		case 0x1b150 ... 0x1b152:
			return 2;
		case 0x1b164 ... 0x1b167:
			return 2;
		case 0x1b170 ... 0x1b2fb:
			return 2;
		case 0x1f004:
			return 2;
		case 0x1f0cf:
			return 2;
		case 0x1f18e:
			return 2;
		case 0x1f191 ... 0x1f19a:
			return 2;
		case 0x1f200 ... 0x1f201:
			return 2;
		case 0x1f210 ... 0x1f236:
			return 2;
		case 0x1f238 ... 0x1f23b:
			return 2;
		case 0x1f240 ... 0x1f248:
			return 2;
		case 0x1f250 ... 0x1f251:
			return 2;
		case 0x1f260 ... 0x1f265:
			return 2;
		case 0x1f300 ... 0x1f320:
			return 2;
		case 0x1f32d ... 0x1f335:
			return 2;
		case 0x1f337 ... 0x1f37c:
			return 2;
		case 0x1f37e ... 0x1f393:
			return 2;
		case 0x1f3a0 ... 0x1f3ca:
			return 2;
		case 0x1f3cf ... 0x1f3d3:
			return 2;
		case 0x1f3e0 ... 0x1f3f0:
			return 2;
		case 0x1f3f4:
			return 2;
		case 0x1f3f8 ... 0x1f3fa:
			return 2;
		case 0x1f400 ... 0x1f43e:
			return 2;
		case 0x1f440:
			return 2;
		case 0x1f442 ... 0x1f4fc:
			return 2;
		case 0x1f4ff ... 0x1f53d:
			return 2;
		case 0x1f54b ... 0x1f54e:
			return 2;
		case 0x1f550 ... 0x1f567:
			return 2;
		case 0x1f57a:
			return 2;
		case 0x1f595 ... 0x1f596:
			return 2;
		case 0x1f5a4:
			return 2;
		case 0x1f5fb ... 0x1f64f:
			return 2;
		case 0x1f680 ... 0x1f6c5:
			return 2;
		case 0x1f6cc:
			return 2;
		case 0x1f6d0 ... 0x1f6d2:
			return 2;
		case 0x1f6d5 ... 0x1f6d7:
			return 2;
		case 0x1f6eb ... 0x1f6ec:
			return 2;
		case 0x1f6f4 ... 0x1f6fc:
			return 2;
		case 0x1f7e0 ... 0x1f7eb:
			return 2;
		case 0x1f90c ... 0x1f93a:
			return 2;
		case 0x1f93c ... 0x1f945:
			return 2;
		case 0x1f947 ... 0x1f978:
			return 2;
		case 0x1f97a ... 0x1f9cb:
			return 2;
		case 0x1f9cd ... 0x1f9ff:
			return 2;
		case 0x1fa70 ... 0x1fa74:
			return 2;
		case 0x1fa78 ... 0x1fa7a:
			return 2;
		case 0x1fa80 ... 0x1fa86:
			return 2;
		case 0x1fa90 ... 0x1faa8:
			return 2;
		case 0x1fab0 ... 0x1fab6:
			return 2;
		case 0x1fac0 ... 0x1fac2:
			return 2;
		case 0x1fad0 ... 0x1fad6:
			return 2;
		case 0x20000 ... 0x2fffd:
			return 2;
		case 0x30000 ... 0x3fffd:
			return 2;
		// }}}

		// Emoji Presentation (0 codepoints) {{{
		// }}}

		// Not assigned in the unicode character database (765365 codepoints) {{{
		case 0x378 ... 0x379:
			return -4;
		case 0x380 ... 0x383:
			return -4;
		case 0x38b:
			return -4;
		case 0x38d:
			return -4;
		case 0x3a2:
			return -4;
		case 0x530:
			return -4;
		case 0x557 ... 0x558:
			return -4;
		case 0x58b ... 0x58c:
			return -4;
		case 0x590:
			return -4;
		case 0x5c8 ... 0x5cf:
			return -4;
		case 0x5eb ... 0x5ee:
			return -4;
		case 0x5f5 ... 0x5ff:
			return -4;
		case 0x61d:
			return -4;
		case 0x70e:
			return -4;
		case 0x74b ... 0x74c:
			return -4;
		case 0x7b2 ... 0x7bf:
			return -4;
		case 0x7fb ... 0x7fc:
			return -4;
		case 0x82e ... 0x82f:
			return -4;
		case 0x83f:
			return -4;
		case 0x85c ... 0x85d:
			return -4;
		case 0x85f:
			return -4;
		case 0x86b ... 0x89f:
			return -4;
		case 0x8b5:
			return -4;
		case 0x8c8 ... 0x8d2:
			return -4;
		case 0x984:
			return -4;
		case 0x98d ... 0x98e:
			return -4;
		case 0x991 ... 0x992:
			return -4;
		case 0x9a9:
			return -4;
		case 0x9b1:
			return -4;
		case 0x9b3 ... 0x9b5:
			return -4;
		case 0x9ba ... 0x9bb:
			return -4;
		case 0x9c5 ... 0x9c6:
			return -4;
		case 0x9c9 ... 0x9ca:
			return -4;
		case 0x9cf ... 0x9d6:
			return -4;
		case 0x9d8 ... 0x9db:
			return -4;
		case 0x9de:
			return -4;
		case 0x9e4 ... 0x9e5:
			return -4;
		case 0x9ff ... 0xa00:
			return -4;
		case 0xa04:
			return -4;
		case 0xa0b ... 0xa0e:
			return -4;
		case 0xa11 ... 0xa12:
			return -4;
		case 0xa29:
			return -4;
		case 0xa31:
			return -4;
		case 0xa34:
			return -4;
		case 0xa37:
			return -4;
		case 0xa3a ... 0xa3b:
			return -4;
		case 0xa3d:
			return -4;
		case 0xa43 ... 0xa46:
			return -4;
		case 0xa49 ... 0xa4a:
			return -4;
		case 0xa4e ... 0xa50:
			return -4;
		case 0xa52 ... 0xa58:
			return -4;
		case 0xa5d:
			return -4;
		case 0xa5f ... 0xa65:
			return -4;
		case 0xa77 ... 0xa80:
			return -4;
		case 0xa84:
			return -4;
		case 0xa8e:
			return -4;
		case 0xa92:
			return -4;
		case 0xaa9:
			return -4;
		case 0xab1:
			return -4;
		case 0xab4:
			return -4;
		case 0xaba ... 0xabb:
			return -4;
		case 0xac6:
			return -4;
		case 0xaca:
			return -4;
		case 0xace ... 0xacf:
			return -4;
		case 0xad1 ... 0xadf:
			return -4;
		case 0xae4 ... 0xae5:
			return -4;
		case 0xaf2 ... 0xaf8:
			return -4;
		case 0xb00:
			return -4;
		case 0xb04:
			return -4;
		case 0xb0d ... 0xb0e:
			return -4;
		case 0xb11 ... 0xb12:
			return -4;
		case 0xb29:
			return -4;
		case 0xb31:
			return -4;
		case 0xb34:
			return -4;
		case 0xb3a ... 0xb3b:
			return -4;
		case 0xb45 ... 0xb46:
			return -4;
		case 0xb49 ... 0xb4a:
			return -4;
		case 0xb4e ... 0xb54:
			return -4;
		case 0xb58 ... 0xb5b:
			return -4;
		case 0xb5e:
			return -4;
		case 0xb64 ... 0xb65:
			return -4;
		case 0xb78 ... 0xb81:
			return -4;
		case 0xb84:
			return -4;
		case 0xb8b ... 0xb8d:
			return -4;
		case 0xb91:
			return -4;
		case 0xb96 ... 0xb98:
			return -4;
		case 0xb9b:
			return -4;
		case 0xb9d:
			return -4;
		case 0xba0 ... 0xba2:
			return -4;
		case 0xba5 ... 0xba7:
			return -4;
		case 0xbab ... 0xbad:
			return -4;
		case 0xbba ... 0xbbd:
			return -4;
		case 0xbc3 ... 0xbc5:
			return -4;
		case 0xbc9:
			return -4;
		case 0xbce ... 0xbcf:
			return -4;
		case 0xbd1 ... 0xbd6:
			return -4;
		case 0xbd8 ... 0xbe5:
			return -4;
		case 0xbfb ... 0xbff:
			return -4;
		case 0xc0d:
			return -4;
		case 0xc11:
			return -4;
		case 0xc29:
			return -4;
		case 0xc3a ... 0xc3c:
			return -4;
		case 0xc45:
			return -4;
		case 0xc49:
			return -4;
		case 0xc4e ... 0xc54:
			return -4;
		case 0xc57:
			return -4;
		case 0xc5b ... 0xc5f:
			return -4;
		case 0xc64 ... 0xc65:
			return -4;
		case 0xc70 ... 0xc76:
			return -4;
		case 0xc8d:
			return -4;
		case 0xc91:
			return -4;
		case 0xca9:
			return -4;
		case 0xcb4:
			return -4;
		case 0xcba ... 0xcbb:
			return -4;
		case 0xcc5:
			return -4;
		case 0xcc9:
			return -4;
		case 0xcce ... 0xcd4:
			return -4;
		case 0xcd7 ... 0xcdd:
			return -4;
		case 0xcdf:
			return -4;
		case 0xce4 ... 0xce5:
			return -4;
		case 0xcf0:
			return -4;
		case 0xcf3 ... 0xcff:
			return -4;
		case 0xd0d:
			return -4;
		case 0xd11:
			return -4;
		case 0xd45:
			return -4;
		case 0xd49:
			return -4;
		case 0xd50 ... 0xd53:
			return -4;
		case 0xd64 ... 0xd65:
			return -4;
		case 0xd80:
			return -4;
		case 0xd84:
			return -4;
		case 0xd97 ... 0xd99:
			return -4;
		case 0xdb2:
			return -4;
		case 0xdbc:
			return -4;
		case 0xdbe ... 0xdbf:
			return -4;
		case 0xdc7 ... 0xdc9:
			return -4;
		case 0xdcb ... 0xdce:
			return -4;
		case 0xdd5:
			return -4;
		case 0xdd7:
			return -4;
		case 0xde0 ... 0xde5:
			return -4;
		case 0xdf0 ... 0xdf1:
			return -4;
		case 0xdf5 ... 0xe00:
			return -4;
		case 0xe3b ... 0xe3e:
			return -4;
		case 0xe5c ... 0xe80:
			return -4;
		case 0xe83:
			return -4;
		case 0xe85:
			return -4;
		case 0xe8b:
			return -4;
		case 0xea4:
			return -4;
		case 0xea6:
			return -4;
		case 0xebe ... 0xebf:
			return -4;
		case 0xec5:
			return -4;
		case 0xec7:
			return -4;
		case 0xece ... 0xecf:
			return -4;
		case 0xeda ... 0xedb:
			return -4;
		case 0xee0 ... 0xeff:
			return -4;
		case 0xf48:
			return -4;
		case 0xf6d ... 0xf70:
			return -4;
		case 0xf98:
			return -4;
		case 0xfbd:
			return -4;
		case 0xfcd:
			return -4;
		case 0xfdb ... 0xfff:
			return -4;
		case 0x10c6:
			return -4;
		case 0x10c8 ... 0x10cc:
			return -4;
		case 0x10ce ... 0x10cf:
			return -4;
		case 0x1249:
			return -4;
		case 0x124e ... 0x124f:
			return -4;
		case 0x1257:
			return -4;
		case 0x1259:
			return -4;
		case 0x125e ... 0x125f:
			return -4;
		case 0x1289:
			return -4;
		case 0x128e ... 0x128f:
			return -4;
		case 0x12b1:
			return -4;
		case 0x12b6 ... 0x12b7:
			return -4;
		case 0x12bf:
			return -4;
		case 0x12c1:
			return -4;
		case 0x12c6 ... 0x12c7:
			return -4;
		case 0x12d7:
			return -4;
		case 0x1311:
			return -4;
		case 0x1316 ... 0x1317:
			return -4;
		case 0x135b ... 0x135c:
			return -4;
		case 0x137d ... 0x137f:
			return -4;
		case 0x139a ... 0x139f:
			return -4;
		case 0x13f6 ... 0x13f7:
			return -4;
		case 0x13fe ... 0x13ff:
			return -4;
		case 0x169d ... 0x169f:
			return -4;
		case 0x16f9 ... 0x16ff:
			return -4;
		case 0x170d:
			return -4;
		case 0x1715 ... 0x171f:
			return -4;
		case 0x1737 ... 0x173f:
			return -4;
		case 0x1754 ... 0x175f:
			return -4;
		case 0x176d:
			return -4;
		case 0x1771:
			return -4;
		case 0x1774 ... 0x177f:
			return -4;
		case 0x17de ... 0x17df:
			return -4;
		case 0x17ea ... 0x17ef:
			return -4;
		case 0x17fa ... 0x17ff:
			return -4;
		case 0x180f:
			return -4;
		case 0x181a ... 0x181f:
			return -4;
		case 0x1879 ... 0x187f:
			return -4;
		case 0x18ab ... 0x18af:
			return -4;
		case 0x18f6 ... 0x18ff:
			return -4;
		case 0x191f:
			return -4;
		case 0x192c ... 0x192f:
			return -4;
		case 0x193c ... 0x193f:
			return -4;
		case 0x1941 ... 0x1943:
			return -4;
		case 0x196e ... 0x196f:
			return -4;
		case 0x1975 ... 0x197f:
			return -4;
		case 0x19ac ... 0x19af:
			return -4;
		case 0x19ca ... 0x19cf:
			return -4;
		case 0x19db ... 0x19dd:
			return -4;
		case 0x1a1c ... 0x1a1d:
			return -4;
		case 0x1a5f:
			return -4;
		case 0x1a7d ... 0x1a7e:
			return -4;
		case 0x1a8a ... 0x1a8f:
			return -4;
		case 0x1a9a ... 0x1a9f:
			return -4;
		case 0x1aae ... 0x1aaf:
			return -4;
		case 0x1ac1 ... 0x1aff:
			return -4;
		case 0x1b4c ... 0x1b4f:
			return -4;
		case 0x1b7d ... 0x1b7f:
			return -4;
		case 0x1bf4 ... 0x1bfb:
			return -4;
		case 0x1c38 ... 0x1c3a:
			return -4;
		case 0x1c4a ... 0x1c4c:
			return -4;
		case 0x1c89 ... 0x1c8f:
			return -4;
		case 0x1cbb ... 0x1cbc:
			return -4;
		case 0x1cc8 ... 0x1ccf:
			return -4;
		case 0x1cfb ... 0x1cff:
			return -4;
		case 0x1dfa:
			return -4;
		case 0x1f16 ... 0x1f17:
			return -4;
		case 0x1f1e ... 0x1f1f:
			return -4;
		case 0x1f46 ... 0x1f47:
			return -4;
		case 0x1f4e ... 0x1f4f:
			return -4;
		case 0x1f58:
			return -4;
		case 0x1f5a:
			return -4;
		case 0x1f5c:
			return -4;
		case 0x1f5e:
			return -4;
		case 0x1f7e ... 0x1f7f:
			return -4;
		case 0x1fb5:
			return -4;
		case 0x1fc5:
			return -4;
		case 0x1fd4 ... 0x1fd5:
			return -4;
		case 0x1fdc:
			return -4;
		case 0x1ff0 ... 0x1ff1:
			return -4;
		case 0x1ff5:
			return -4;
		case 0x1fff:
			return -4;
		case 0x2065:
			return -4;
		case 0x2072 ... 0x2073:
			return -4;
		case 0x208f:
			return -4;
		case 0x209d ... 0x209f:
			return -4;
		case 0x20c0 ... 0x20cf:
			return -4;
		case 0x20f1 ... 0x20ff:
			return -4;
		case 0x218c ... 0x218f:
			return -4;
		case 0x2427 ... 0x243f:
			return -4;
		case 0x244b ... 0x245f:
			return -4;
		case 0x2b74 ... 0x2b75:
			return -4;
		case 0x2b96:
			return -4;
		case 0x2c2f:
			return -4;
		case 0x2c5f:
			return -4;
		case 0x2cf4 ... 0x2cf8:
			return -4;
		case 0x2d26:
			return -4;
		case 0x2d28 ... 0x2d2c:
			return -4;
		case 0x2d2e ... 0x2d2f:
			return -4;
		case 0x2d68 ... 0x2d6e:
			return -4;
		case 0x2d71 ... 0x2d7e:
			return -4;
		case 0x2d97 ... 0x2d9f:
			return -4;
		case 0x2da7:
			return -4;
		case 0x2daf:
			return -4;
		case 0x2db7:
			return -4;
		case 0x2dbf:
			return -4;
		case 0x2dc7:
			return -4;
		case 0x2dcf:
			return -4;
		case 0x2dd7:
			return -4;
		case 0x2ddf:
			return -4;
		case 0x2e53 ... 0x2e7f:
			return -4;
		case 0x2e9a:
			return -4;
		case 0x2ef4 ... 0x2eff:
			return -4;
		case 0x2fd6 ... 0x2fef:
			return -4;
		case 0x2ffc ... 0x2fff:
			return -4;
		case 0x3040:
			return -4;
		case 0x3097 ... 0x3098:
			return -4;
		case 0x3100 ... 0x3104:
			return -4;
		case 0x3130:
			return -4;
		case 0x318f:
			return -4;
		case 0x31e4 ... 0x31ef:
			return -4;
		case 0x321f:
			return -4;
		case 0xa48d ... 0xa48f:
			return -4;
		case 0xa4c7 ... 0xa4cf:
			return -4;
		case 0xa62c ... 0xa63f:
			return -4;
		case 0xa6f8 ... 0xa6ff:
			return -4;
		case 0xa7c0 ... 0xa7c1:
			return -4;
		case 0xa7cb ... 0xa7f4:
			return -4;
		case 0xa82d ... 0xa82f:
			return -4;
		case 0xa83a ... 0xa83f:
			return -4;
		case 0xa878 ... 0xa87f:
			return -4;
		case 0xa8c6 ... 0xa8cd:
			return -4;
		case 0xa8da ... 0xa8df:
			return -4;
		case 0xa954 ... 0xa95e:
			return -4;
		case 0xa97d ... 0xa97f:
			return -4;
		case 0xa9ce:
			return -4;
		case 0xa9da ... 0xa9dd:
			return -4;
		case 0xa9ff:
			return -4;
		case 0xaa37 ... 0xaa3f:
			return -4;
		case 0xaa4e ... 0xaa4f:
			return -4;
		case 0xaa5a ... 0xaa5b:
			return -4;
		case 0xaac3 ... 0xaada:
			return -4;
		case 0xaaf7 ... 0xab00:
			return -4;
		case 0xab07 ... 0xab08:
			return -4;
		case 0xab0f ... 0xab10:
			return -4;
		case 0xab17 ... 0xab1f:
			return -4;
		case 0xab27:
			return -4;
		case 0xab2f:
			return -4;
		case 0xab6c ... 0xab6f:
			return -4;
		case 0xabee ... 0xabef:
			return -4;
		case 0xabfa ... 0xabff:
			return -4;
		case 0xd7a4 ... 0xd7af:
			return -4;
		case 0xd7c7 ... 0xd7ca:
			return -4;
		case 0xd7fc ... 0xd7ff:
			return -4;
		case 0xfb07 ... 0xfb12:
			return -4;
		case 0xfb18 ... 0xfb1c:
			return -4;
		case 0xfb37:
			return -4;
		case 0xfb3d:
			return -4;
		case 0xfb3f:
			return -4;
		case 0xfb42:
			return -4;
		case 0xfb45:
			return -4;
		case 0xfbc2 ... 0xfbd2:
			return -4;
		case 0xfd40 ... 0xfd4f:
			return -4;
		case 0xfd90 ... 0xfd91:
			return -4;
		case 0xfdc8 ... 0xfdef:
			return -4;
		case 0xfdfe ... 0xfdff:
			return -4;
		case 0xfe1a ... 0xfe1f:
			return -4;
		case 0xfe53:
			return -4;
		case 0xfe67:
			return -4;
		case 0xfe6c ... 0xfe6f:
			return -4;
		case 0xfe75:
			return -4;
		case 0xfefd ... 0xfefe:
			return -4;
		case 0xff00:
			return -4;
		case 0xffbf ... 0xffc1:
			return -4;
		case 0xffc8 ... 0xffc9:
			return -4;
		case 0xffd0 ... 0xffd1:
			return -4;
		case 0xffd8 ... 0xffd9:
			return -4;
		case 0xffdd ... 0xffdf:
			return -4;
		case 0xffe7:
			return -4;
		case 0xffef ... 0xfff8:
			return -4;
		case 0xfffe ... 0xffff:
			return -4;
		case 0x1000c:
			return -4;
		case 0x10027:
			return -4;
		case 0x1003b:
			return -4;
		case 0x1003e:
			return -4;
		case 0x1004e ... 0x1004f:
			return -4;
		case 0x1005e ... 0x1007f:
			return -4;
		case 0x100fb ... 0x100ff:
			return -4;
		case 0x10103 ... 0x10106:
			return -4;
		case 0x10134 ... 0x10136:
			return -4;
		case 0x1018f:
			return -4;
		case 0x1019d ... 0x1019f:
			return -4;
		case 0x101a1 ... 0x101cf:
			return -4;
		case 0x101fe ... 0x1027f:
			return -4;
		case 0x1029d ... 0x1029f:
			return -4;
		case 0x102d1 ... 0x102df:
			return -4;
		case 0x102fc ... 0x102ff:
			return -4;
		case 0x10324 ... 0x1032c:
			return -4;
		case 0x1034b ... 0x1034f:
			return -4;
		case 0x1037b ... 0x1037f:
			return -4;
		case 0x1039e:
			return -4;
		case 0x103c4 ... 0x103c7:
			return -4;
		case 0x103d6 ... 0x103ff:
			return -4;
		case 0x1049e ... 0x1049f:
			return -4;
		case 0x104aa ... 0x104af:
			return -4;
		case 0x104d4 ... 0x104d7:
			return -4;
		case 0x104fc ... 0x104ff:
			return -4;
		case 0x10528 ... 0x1052f:
			return -4;
		case 0x10564 ... 0x1056e:
			return -4;
		case 0x10570 ... 0x105ff:
			return -4;
		case 0x10737 ... 0x1073f:
			return -4;
		case 0x10756 ... 0x1075f:
			return -4;
		case 0x10768 ... 0x107ff:
			return -4;
		case 0x10806 ... 0x10807:
			return -4;
		case 0x10809:
			return -4;
		case 0x10836:
			return -4;
		case 0x10839 ... 0x1083b:
			return -4;
		case 0x1083d ... 0x1083e:
			return -4;
		case 0x10856:
			return -4;
		case 0x1089f ... 0x108a6:
			return -4;
		case 0x108b0 ... 0x108df:
			return -4;
		case 0x108f3:
			return -4;
		case 0x108f6 ... 0x108fa:
			return -4;
		case 0x1091c ... 0x1091e:
			return -4;
		case 0x1093a ... 0x1093e:
			return -4;
		case 0x10940 ... 0x1097f:
			return -4;
		case 0x109b8 ... 0x109bb:
			return -4;
		case 0x109d0 ... 0x109d1:
			return -4;
		case 0x10a04:
			return -4;
		case 0x10a07 ... 0x10a0b:
			return -4;
		case 0x10a14:
			return -4;
		case 0x10a18:
			return -4;
		case 0x10a36 ... 0x10a37:
			return -4;
		case 0x10a3b ... 0x10a3e:
			return -4;
		case 0x10a49 ... 0x10a4f:
			return -4;
		case 0x10a59 ... 0x10a5f:
			return -4;
		case 0x10aa0 ... 0x10abf:
			return -4;
		case 0x10ae7 ... 0x10aea:
			return -4;
		case 0x10af7 ... 0x10aff:
			return -4;
		case 0x10b36 ... 0x10b38:
			return -4;
		case 0x10b56 ... 0x10b57:
			return -4;
		case 0x10b73 ... 0x10b77:
			return -4;
		case 0x10b92 ... 0x10b98:
			return -4;
		case 0x10b9d ... 0x10ba8:
			return -4;
		case 0x10bb0 ... 0x10bff:
			return -4;
		case 0x10c49 ... 0x10c7f:
			return -4;
		case 0x10cb3 ... 0x10cbf:
			return -4;
		case 0x10cf3 ... 0x10cf9:
			return -4;
		case 0x10d28 ... 0x10d2f:
			return -4;
		case 0x10d3a ... 0x10e5f:
			return -4;
		case 0x10e7f:
			return -4;
		case 0x10eaa:
			return -4;
		case 0x10eae ... 0x10eaf:
			return -4;
		case 0x10eb2 ... 0x10eff:
			return -4;
		case 0x10f28 ... 0x10f2f:
			return -4;
		case 0x10f5a ... 0x10faf:
			return -4;
		case 0x10fcc ... 0x10fdf:
			return -4;
		case 0x10ff7 ... 0x10fff:
			return -4;
		case 0x1104e ... 0x11051:
			return -4;
		case 0x11070 ... 0x1107e:
			return -4;
		case 0x110c2 ... 0x110cc:
			return -4;
		case 0x110ce ... 0x110cf:
			return -4;
		case 0x110e9 ... 0x110ef:
			return -4;
		case 0x110fa ... 0x110ff:
			return -4;
		case 0x11135:
			return -4;
		case 0x11148 ... 0x1114f:
			return -4;
		case 0x11177 ... 0x1117f:
			return -4;
		case 0x111e0:
			return -4;
		case 0x111f5 ... 0x111ff:
			return -4;
		case 0x11212:
			return -4;
		case 0x1123f ... 0x1127f:
			return -4;
		case 0x11287:
			return -4;
		case 0x11289:
			return -4;
		case 0x1128e:
			return -4;
		case 0x1129e:
			return -4;
		case 0x112aa ... 0x112af:
			return -4;
		case 0x112eb ... 0x112ef:
			return -4;
		case 0x112fa ... 0x112ff:
			return -4;
		case 0x11304:
			return -4;
		case 0x1130d ... 0x1130e:
			return -4;
		case 0x11311 ... 0x11312:
			return -4;
		case 0x11329:
			return -4;
		case 0x11331:
			return -4;
		case 0x11334:
			return -4;
		case 0x1133a:
			return -4;
		case 0x11345 ... 0x11346:
			return -4;
		case 0x11349 ... 0x1134a:
			return -4;
		case 0x1134e ... 0x1134f:
			return -4;
		case 0x11351 ... 0x11356:
			return -4;
		case 0x11358 ... 0x1135c:
			return -4;
		case 0x11364 ... 0x11365:
			return -4;
		case 0x1136d ... 0x1136f:
			return -4;
		case 0x11375 ... 0x113ff:
			return -4;
		case 0x1145c:
			return -4;
		case 0x11462 ... 0x1147f:
			return -4;
		case 0x114c8 ... 0x114cf:
			return -4;
		case 0x114da ... 0x1157f:
			return -4;
		case 0x115b6 ... 0x115b7:
			return -4;
		case 0x115de ... 0x115ff:
			return -4;
		case 0x11645 ... 0x1164f:
			return -4;
		case 0x1165a ... 0x1165f:
			return -4;
		case 0x1166d ... 0x1167f:
			return -4;
		case 0x116b9 ... 0x116bf:
			return -4;
		case 0x116ca ... 0x116ff:
			return -4;
		case 0x1171b ... 0x1171c:
			return -4;
		case 0x1172c ... 0x1172f:
			return -4;
		case 0x11740 ... 0x117ff:
			return -4;
		case 0x1183c ... 0x1189f:
			return -4;
		case 0x118f3 ... 0x118fe:
			return -4;
		case 0x11907 ... 0x11908:
			return -4;
		case 0x1190a ... 0x1190b:
			return -4;
		case 0x11914:
			return -4;
		case 0x11917:
			return -4;
		case 0x11936:
			return -4;
		case 0x11939 ... 0x1193a:
			return -4;
		case 0x11947 ... 0x1194f:
			return -4;
		case 0x1195a ... 0x1199f:
			return -4;
		case 0x119a8 ... 0x119a9:
			return -4;
		case 0x119d8 ... 0x119d9:
			return -4;
		case 0x119e5 ... 0x119ff:
			return -4;
		case 0x11a48 ... 0x11a4f:
			return -4;
		case 0x11aa3 ... 0x11abf:
			return -4;
		case 0x11af9 ... 0x11bff:
			return -4;
		case 0x11c09:
			return -4;
		case 0x11c37:
			return -4;
		case 0x11c46 ... 0x11c4f:
			return -4;
		case 0x11c6d ... 0x11c6f:
			return -4;
		case 0x11c90 ... 0x11c91:
			return -4;
		case 0x11ca8:
			return -4;
		case 0x11cb7 ... 0x11cff:
			return -4;
		case 0x11d07:
			return -4;
		case 0x11d0a:
			return -4;
		case 0x11d37 ... 0x11d39:
			return -4;
		case 0x11d3b:
			return -4;
		case 0x11d3e:
			return -4;
		case 0x11d48 ... 0x11d4f:
			return -4;
		case 0x11d5a ... 0x11d5f:
			return -4;
		case 0x11d66:
			return -4;
		case 0x11d69:
			return -4;
		case 0x11d8f:
			return -4;
		case 0x11d92:
			return -4;
		case 0x11d99 ... 0x11d9f:
			return -4;
		case 0x11daa ... 0x11edf:
			return -4;
		case 0x11ef9 ... 0x11faf:
			return -4;
		case 0x11fb1 ... 0x11fbf:
			return -4;
		case 0x11ff2 ... 0x11ffe:
			return -4;
		case 0x1239a ... 0x123ff:
			return -4;
		case 0x1246f:
			return -4;
		case 0x12475 ... 0x1247f:
			return -4;
		case 0x12544 ... 0x12fff:
			return -4;
		case 0x1342f:
			return -4;
		case 0x13439 ... 0x143ff:
			return -4;
		case 0x14647 ... 0x167ff:
			return -4;
		case 0x16a39 ... 0x16a3f:
			return -4;
		case 0x16a5f:
			return -4;
		case 0x16a6a ... 0x16a6d:
			return -4;
		case 0x16a70 ... 0x16acf:
			return -4;
		case 0x16aee ... 0x16aef:
			return -4;
		case 0x16af6 ... 0x16aff:
			return -4;
		case 0x16b46 ... 0x16b4f:
			return -4;
		case 0x16b5a:
			return -4;
		case 0x16b62:
			return -4;
		case 0x16b78 ... 0x16b7c:
			return -4;
		case 0x16b90 ... 0x16e3f:
			return -4;
		case 0x16e9b ... 0x16eff:
			return -4;
		case 0x16f4b ... 0x16f4e:
			return -4;
		case 0x16f88 ... 0x16f8e:
			return -4;
		case 0x16fa0 ... 0x16fdf:
			return -4;
		case 0x16fe5 ... 0x16fef:
			return -4;
		case 0x16ff2 ... 0x16fff:
			return -4;
		case 0x187f8 ... 0x187ff:
			return -4;
		case 0x18cd6 ... 0x18cff:
			return -4;
		case 0x18d09 ... 0x1afff:
			return -4;
		case 0x1b11f ... 0x1b14f:
			return -4;
		case 0x1b153 ... 0x1b163:
			return -4;
		case 0x1b168 ... 0x1b16f:
			return -4;
		case 0x1b2fc ... 0x1bbff:
			return -4;
		case 0x1bc6b ... 0x1bc6f:
			return -4;
		case 0x1bc7d ... 0x1bc7f:
			return -4;
		case 0x1bc89 ... 0x1bc8f:
			return -4;
		case 0x1bc9a ... 0x1bc9b:
			return -4;
		case 0x1bca4 ... 0x1cfff:
			return -4;
		case 0x1d0f6 ... 0x1d0ff:
			return -4;
		case 0x1d127 ... 0x1d128:
			return -4;
		case 0x1d1e9 ... 0x1d1ff:
			return -4;
		case 0x1d246 ... 0x1d2df:
			return -4;
		case 0x1d2f4 ... 0x1d2ff:
			return -4;
		case 0x1d357 ... 0x1d35f:
			return -4;
		case 0x1d379 ... 0x1d3ff:
			return -4;
		case 0x1d455:
			return -4;
		case 0x1d49d:
			return -4;
		case 0x1d4a0 ... 0x1d4a1:
			return -4;
		case 0x1d4a3 ... 0x1d4a4:
			return -4;
		case 0x1d4a7 ... 0x1d4a8:
			return -4;
		case 0x1d4ad:
			return -4;
		case 0x1d4ba:
			return -4;
		case 0x1d4bc:
			return -4;
		case 0x1d4c4:
			return -4;
		case 0x1d506:
			return -4;
		case 0x1d50b ... 0x1d50c:
			return -4;
		case 0x1d515:
			return -4;
		case 0x1d51d:
			return -4;
		case 0x1d53a:
			return -4;
		case 0x1d53f:
			return -4;
		case 0x1d545:
			return -4;
		case 0x1d547 ... 0x1d549:
			return -4;
		case 0x1d551:
			return -4;
		case 0x1d6a6 ... 0x1d6a7:
			return -4;
		case 0x1d7cc ... 0x1d7cd:
			return -4;
		case 0x1da8c ... 0x1da9a:
			return -4;
		case 0x1daa0:
			return -4;
		case 0x1dab0 ... 0x1dfff:
			return -4;
		case 0x1e007:
			return -4;
		case 0x1e019 ... 0x1e01a:
			return -4;
		case 0x1e022:
			return -4;
		case 0x1e025:
			return -4;
		case 0x1e02b ... 0x1e0ff:
			return -4;
		case 0x1e12d ... 0x1e12f:
			return -4;
		case 0x1e13e ... 0x1e13f:
			return -4;
		case 0x1e14a ... 0x1e14d:
			return -4;
		case 0x1e150 ... 0x1e2bf:
			return -4;
		case 0x1e2fa ... 0x1e2fe:
			return -4;
		case 0x1e300 ... 0x1e7ff:
			return -4;
		case 0x1e8c5 ... 0x1e8c6:
			return -4;
		case 0x1e8d7 ... 0x1e8ff:
			return -4;
		case 0x1e94c ... 0x1e94f:
			return -4;
		case 0x1e95a ... 0x1e95d:
			return -4;
		case 0x1e960 ... 0x1ec70:
			return -4;
		case 0x1ecb5 ... 0x1ed00:
			return -4;
		case 0x1ed3e ... 0x1edff:
			return -4;
		case 0x1ee04:
			return -4;
		case 0x1ee20:
			return -4;
		case 0x1ee23:
			return -4;
		case 0x1ee25 ... 0x1ee26:
			return -4;
		case 0x1ee28:
			return -4;
		case 0x1ee33:
			return -4;
		case 0x1ee38:
			return -4;
		case 0x1ee3a:
			return -4;
		case 0x1ee3c ... 0x1ee41:
			return -4;
		case 0x1ee43 ... 0x1ee46:
			return -4;
		case 0x1ee48:
			return -4;
		case 0x1ee4a:
			return -4;
		case 0x1ee4c:
			return -4;
		case 0x1ee50:
			return -4;
		case 0x1ee53:
			return -4;
		case 0x1ee55 ... 0x1ee56:
			return -4;
		case 0x1ee58:
			return -4;
		case 0x1ee5a:
			return -4;
		case 0x1ee5c:
			return -4;
		case 0x1ee5e:
			return -4;
		case 0x1ee60:
			return -4;
		case 0x1ee63:
			return -4;
		case 0x1ee65 ... 0x1ee66:
			return -4;
		case 0x1ee6b:
			return -4;
		case 0x1ee73:
			return -4;
		case 0x1ee78:
			return -4;
		case 0x1ee7d:
			return -4;
		case 0x1ee7f:
			return -4;
		case 0x1ee8a:
			return -4;
		case 0x1ee9c ... 0x1eea0:
			return -4;
		case 0x1eea4:
			return -4;
		case 0x1eeaa:
			return -4;
		case 0x1eebc ... 0x1eeef:
			return -4;
		case 0x1eef2 ... 0x1efff:
			return -4;
		case 0x1f02c ... 0x1f02f:
			return -4;
		case 0x1f094 ... 0x1f09f:
			return -4;
		case 0x1f0af ... 0x1f0b0:
			return -4;
		case 0x1f0c0:
			return -4;
		case 0x1f0d0:
			return -4;
		case 0x1f0f6 ... 0x1f0ff:
			return -4;
		case 0x1f1ae ... 0x1f1e5:
			return -4;
		case 0x1f203 ... 0x1f20f:
			return -4;
		case 0x1f23c ... 0x1f23f:
			return -4;
		case 0x1f249 ... 0x1f24f:
			return -4;
		case 0x1f252 ... 0x1f25f:
			return -4;
		case 0x1f266 ... 0x1f2ff:
			return -4;
		case 0x1f6d8 ... 0x1f6df:
			return -4;
		case 0x1f6ed ... 0x1f6ef:
			return -4;
		case 0x1f6fd ... 0x1f6ff:
			return -4;
		case 0x1f774 ... 0x1f77f:
			return -4;
		case 0x1f7d9 ... 0x1f7df:
			return -4;
		case 0x1f7ec ... 0x1f7ff:
			return -4;
		case 0x1f80c ... 0x1f80f:
			return -4;
		case 0x1f848 ... 0x1f84f:
			return -4;
		case 0x1f85a ... 0x1f85f:
			return -4;
		case 0x1f888 ... 0x1f88f:
			return -4;
		case 0x1f8ae ... 0x1f8af:
			return -4;
		case 0x1f8b2 ... 0x1f8ff:
			return -4;
		case 0x1f979:
			return -4;
		case 0x1f9cc:
			return -4;
		case 0x1fa54 ... 0x1fa5f:
			return -4;
		case 0x1fa6e ... 0x1fa6f:
			return -4;
		case 0x1fa75 ... 0x1fa77:
			return -4;
		case 0x1fa7b ... 0x1fa7f:
			return -4;
		case 0x1fa87 ... 0x1fa8f:
			return -4;
		case 0x1faa9 ... 0x1faaf:
			return -4;
		case 0x1fab7 ... 0x1fabf:
			return -4;
		case 0x1fac3 ... 0x1facf:
			return -4;
		case 0x1fad7 ... 0x1faff:
			return -4;
		case 0x1fb93:
			return -4;
		case 0x1fbcb ... 0x1fbef:
			return -4;
		case 0x1fbfa ... 0x1ffff:
			return -4;
		case 0x2fffe ... 0x2ffff:
			return -4;
		case 0x3fffe ... 0xe0000:
			return -4;
		case 0xe0002 ... 0xe001f:
			return -4;
		case 0xe0080 ... 0xe00ff:
			return -4;
		case 0xe01f0 ... 0xeffff:
			return -4;
		case 0xffffe ... 0xfffff:
			return -4;
		case 0x10fffe:
			return -4;
		// }}}

		default: return 1;
	}
	return 1;
}
static inline bool
is_emoji_presentation_base(uint32_t code) {
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
		case 0x203c:
			return true;
		case 0x2049:
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
		case 0x2600 ... 0x2604:
			return true;
		case 0x260e:
			return true;
		case 0x2611:
			return true;
		case 0x2614 ... 0x2615:
			return true;
		case 0x2618:
			return true;
		case 0x261d:
			return true;
		case 0x2620:
			return true;
		case 0x2622 ... 0x2623:
			return true;
		case 0x2626:
			return true;
		case 0x262a:
			return true;
		case 0x262e ... 0x262f:
			return true;
		case 0x2638 ... 0x263a:
			return true;
		case 0x2640:
			return true;
		case 0x2642:
			return true;
		case 0x2648 ... 0x2653:
			return true;
		case 0x265f ... 0x2660:
			return true;
		case 0x2663:
			return true;
		case 0x2665 ... 0x2666:
			return true;
		case 0x2668:
			return true;
		case 0x267b:
			return true;
		case 0x267e ... 0x267f:
			return true;
		case 0x2692 ... 0x2697:
			return true;
		case 0x2699:
			return true;
		case 0x269b ... 0x269c:
			return true;
		case 0x26a0 ... 0x26a1:
			return true;
		case 0x26a7:
			return true;
		case 0x26aa ... 0x26ab:
			return true;
		case 0x26b0 ... 0x26b1:
			return true;
		case 0x26bd ... 0x26be:
			return true;
		case 0x26c4 ... 0x26c5:
			return true;
		case 0x26c8:
			return true;
		case 0x26ce ... 0x26cf:
			return true;
		case 0x26d1:
			return true;
		case 0x26d3 ... 0x26d4:
			return true;
		case 0x26e9 ... 0x26ea:
			return true;
		case 0x26f0 ... 0x26f5:
			return true;
		case 0x26f7 ... 0x26fa:
			return true;
		case 0x26fd:
			return true;
		case 0x2702:
			return true;
		case 0x2705:
			return true;
		case 0x2708 ... 0x270d:
			return true;
		case 0x270f:
			return true;
		case 0x2712:
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
		case 0x2763 ... 0x2764:
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
		case 0x1f004:
			return true;
		case 0x1f0cf:
			return true;
		case 0x1f170 ... 0x1f171:
			return true;
		case 0x1f17e ... 0x1f17f:
			return true;
		case 0x1f18e:
			return true;
		case 0x1f191 ... 0x1f19a:
			return true;
		case 0x1f1e6 ... 0x1f1ff:
			return true;
		case 0x1f201 ... 0x1f202:
			return true;
		case 0x1f21a:
			return true;
		case 0x1f22f:
			return true;
		case 0x1f232 ... 0x1f23a:
			return true;
		case 0x1f250 ... 0x1f251:
			return true;
		case 0x1f300 ... 0x1f321:
			return true;
		case 0x1f324 ... 0x1f393:
			return true;
		case 0x1f396 ... 0x1f397:
			return true;
		case 0x1f399 ... 0x1f39b:
			return true;
		case 0x1f39e ... 0x1f3f0:
			return true;
		case 0x1f3f3 ... 0x1f3f5:
			return true;
		case 0x1f3f7 ... 0x1f4fd:
			return true;
		case 0x1f4ff ... 0x1f53d:
			return true;
		case 0x1f549 ... 0x1f54e:
			return true;
		case 0x1f550 ... 0x1f567:
			return true;
		case 0x1f56f ... 0x1f570:
			return true;
		case 0x1f573 ... 0x1f57a:
			return true;
		case 0x1f587:
			return true;
		case 0x1f58a ... 0x1f58d:
			return true;
		case 0x1f590:
			return true;
		case 0x1f595 ... 0x1f596:
			return true;
		case 0x1f5a4 ... 0x1f5a5:
			return true;
		case 0x1f5a8:
			return true;
		case 0x1f5b1 ... 0x1f5b2:
			return true;
		case 0x1f5bc:
			return true;
		case 0x1f5c2 ... 0x1f5c4:
			return true;
		case 0x1f5d1 ... 0x1f5d3:
			return true;
		case 0x1f5dc ... 0x1f5de:
			return true;
		case 0x1f5e1:
			return true;
		case 0x1f5e3:
			return true;
		case 0x1f5e8:
			return true;
		case 0x1f5ef:
			return true;
		case 0x1f5f3:
			return true;
		case 0x1f5fa ... 0x1f64f:
			return true;
		case 0x1f680 ... 0x1f6c5:
			return true;
		case 0x1f6cb ... 0x1f6d2:
			return true;
		case 0x1f6d5 ... 0x1f6d7:
			return true;
		case 0x1f6e0 ... 0x1f6e5:
			return true;
		case 0x1f6e9:
			return true;
		case 0x1f6eb ... 0x1f6ec:
			return true;
		case 0x1f6f0:
			return true;
		case 0x1f6f3 ... 0x1f6fc:
			return true;
		case 0x1f7e0 ... 0x1f7eb:
			return true;
		case 0x1f90c ... 0x1f93a:
			return true;
		case 0x1f93c ... 0x1f945:
			return true;
		case 0x1f947 ... 0x1f978:
			return true;
		case 0x1f97a ... 0x1f9cb:
			return true;
		case 0x1f9cd ... 0x1f9ff:
			return true;
		case 0x1fa70 ... 0x1fa74:
			return true;
		case 0x1fa78 ... 0x1fa7a:
			return true;
		case 0x1fa80 ... 0x1fa86:
			return true;
		case 0x1fa90 ... 0x1faa8:
			return true;
		case 0x1fab0 ... 0x1fab6:
			return true;
		case 0x1fac0 ... 0x1fac2:
			return true;
		case 0x1fad0 ... 0x1fad6:
			return true;
		default: return false;
	}
	return 1;
}

END_ALLOW_CASE_RANGE
