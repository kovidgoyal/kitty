// unicode data, built from the unicode standard on: 2021-04-02
// see gen-wcwidth.py
#include "data-types.h"

START_ALLOW_CASE_RANGE

#include "unicode-data.h"
bool
is_combining_char(char_type code) {
	// M category (marks) (2301 codepoints) {{{
	if (LIKELY(code < 768)) return false;
	switch(code) {
		case 0x300 ... 0x36f:
			return true;
		case 0x483 ... 0x489:
			return true;
		case 0x591 ... 0x5bd:
			return true;
		case 0x5bf:
			return true;
		case 0x5c1 ... 0x5c2:
			return true;
		case 0x5c4 ... 0x5c5:
			return true;
		case 0x5c7:
			return true;
		case 0x610 ... 0x61a:
			return true;
		case 0x64b ... 0x65f:
			return true;
		case 0x670:
			return true;
		case 0x6d6 ... 0x6dc:
			return true;
		case 0x6df ... 0x6e4:
			return true;
		case 0x6e7 ... 0x6e8:
			return true;
		case 0x6ea ... 0x6ed:
			return true;
		case 0x711:
			return true;
		case 0x730 ... 0x74a:
			return true;
		case 0x7a6 ... 0x7b0:
			return true;
		case 0x7eb ... 0x7f3:
			return true;
		case 0x7fd:
			return true;
		case 0x816 ... 0x819:
			return true;
		case 0x81b ... 0x823:
			return true;
		case 0x825 ... 0x827:
			return true;
		case 0x829 ... 0x82d:
			return true;
		case 0x859 ... 0x85b:
			return true;
		case 0x8d3 ... 0x8e1:
			return true;
		case 0x8e3 ... 0x903:
			return true;
		case 0x93a ... 0x93c:
			return true;
		case 0x93e ... 0x94f:
			return true;
		case 0x951 ... 0x957:
			return true;
		case 0x962 ... 0x963:
			return true;
		case 0x981 ... 0x983:
			return true;
		case 0x9bc:
			return true;
		case 0x9be ... 0x9c4:
			return true;
		case 0x9c7 ... 0x9c8:
			return true;
		case 0x9cb ... 0x9cd:
			return true;
		case 0x9d7:
			return true;
		case 0x9e2 ... 0x9e3:
			return true;
		case 0x9fe:
			return true;
		case 0xa01 ... 0xa03:
			return true;
		case 0xa3c:
			return true;
		case 0xa3e ... 0xa42:
			return true;
		case 0xa47 ... 0xa48:
			return true;
		case 0xa4b ... 0xa4d:
			return true;
		case 0xa51:
			return true;
		case 0xa70 ... 0xa71:
			return true;
		case 0xa75:
			return true;
		case 0xa81 ... 0xa83:
			return true;
		case 0xabc:
			return true;
		case 0xabe ... 0xac5:
			return true;
		case 0xac7 ... 0xac9:
			return true;
		case 0xacb ... 0xacd:
			return true;
		case 0xae2 ... 0xae3:
			return true;
		case 0xafa ... 0xaff:
			return true;
		case 0xb01 ... 0xb03:
			return true;
		case 0xb3c:
			return true;
		case 0xb3e ... 0xb44:
			return true;
		case 0xb47 ... 0xb48:
			return true;
		case 0xb4b ... 0xb4d:
			return true;
		case 0xb55 ... 0xb57:
			return true;
		case 0xb62 ... 0xb63:
			return true;
		case 0xb82:
			return true;
		case 0xbbe ... 0xbc2:
			return true;
		case 0xbc6 ... 0xbc8:
			return true;
		case 0xbca ... 0xbcd:
			return true;
		case 0xbd7:
			return true;
		case 0xc00 ... 0xc04:
			return true;
		case 0xc3e ... 0xc44:
			return true;
		case 0xc46 ... 0xc48:
			return true;
		case 0xc4a ... 0xc4d:
			return true;
		case 0xc55 ... 0xc56:
			return true;
		case 0xc62 ... 0xc63:
			return true;
		case 0xc81 ... 0xc83:
			return true;
		case 0xcbc:
			return true;
		case 0xcbe ... 0xcc4:
			return true;
		case 0xcc6 ... 0xcc8:
			return true;
		case 0xcca ... 0xccd:
			return true;
		case 0xcd5 ... 0xcd6:
			return true;
		case 0xce2 ... 0xce3:
			return true;
		case 0xd00 ... 0xd03:
			return true;
		case 0xd3b ... 0xd3c:
			return true;
		case 0xd3e ... 0xd44:
			return true;
		case 0xd46 ... 0xd48:
			return true;
		case 0xd4a ... 0xd4d:
			return true;
		case 0xd57:
			return true;
		case 0xd62 ... 0xd63:
			return true;
		case 0xd81 ... 0xd83:
			return true;
		case 0xdca:
			return true;
		case 0xdcf ... 0xdd4:
			return true;
		case 0xdd6:
			return true;
		case 0xdd8 ... 0xddf:
			return true;
		case 0xdf2 ... 0xdf3:
			return true;
		case 0xe31:
			return true;
		case 0xe34 ... 0xe3a:
			return true;
		case 0xe47 ... 0xe4e:
			return true;
		case 0xeb1:
			return true;
		case 0xeb4 ... 0xebc:
			return true;
		case 0xec8 ... 0xecd:
			return true;
		case 0xf18 ... 0xf19:
			return true;
		case 0xf35:
			return true;
		case 0xf37:
			return true;
		case 0xf39:
			return true;
		case 0xf3e ... 0xf3f:
			return true;
		case 0xf71 ... 0xf84:
			return true;
		case 0xf86 ... 0xf87:
			return true;
		case 0xf8d ... 0xf97:
			return true;
		case 0xf99 ... 0xfbc:
			return true;
		case 0xfc6:
			return true;
		case 0x102b ... 0x103e:
			return true;
		case 0x1056 ... 0x1059:
			return true;
		case 0x105e ... 0x1060:
			return true;
		case 0x1062 ... 0x1064:
			return true;
		case 0x1067 ... 0x106d:
			return true;
		case 0x1071 ... 0x1074:
			return true;
		case 0x1082 ... 0x108d:
			return true;
		case 0x108f:
			return true;
		case 0x109a ... 0x109d:
			return true;
		case 0x135d ... 0x135f:
			return true;
		case 0x1712 ... 0x1714:
			return true;
		case 0x1732 ... 0x1734:
			return true;
		case 0x1752 ... 0x1753:
			return true;
		case 0x1772 ... 0x1773:
			return true;
		case 0x17b4 ... 0x17d3:
			return true;
		case 0x17dd:
			return true;
		case 0x180b ... 0x180d:
			return true;
		case 0x1885 ... 0x1886:
			return true;
		case 0x18a9:
			return true;
		case 0x1920 ... 0x192b:
			return true;
		case 0x1930 ... 0x193b:
			return true;
		case 0x1a17 ... 0x1a1b:
			return true;
		case 0x1a55 ... 0x1a5e:
			return true;
		case 0x1a60 ... 0x1a7c:
			return true;
		case 0x1a7f:
			return true;
		case 0x1ab0 ... 0x1ac0:
			return true;
		case 0x1b00 ... 0x1b04:
			return true;
		case 0x1b34 ... 0x1b44:
			return true;
		case 0x1b6b ... 0x1b73:
			return true;
		case 0x1b80 ... 0x1b82:
			return true;
		case 0x1ba1 ... 0x1bad:
			return true;
		case 0x1be6 ... 0x1bf3:
			return true;
		case 0x1c24 ... 0x1c37:
			return true;
		case 0x1cd0 ... 0x1cd2:
			return true;
		case 0x1cd4 ... 0x1ce8:
			return true;
		case 0x1ced:
			return true;
		case 0x1cf4:
			return true;
		case 0x1cf7 ... 0x1cf9:
			return true;
		case 0x1dc0 ... 0x1df9:
			return true;
		case 0x1dfb ... 0x1dff:
			return true;
		case 0x200d:
			return true;
		case 0x20d0 ... 0x20f0:
			return true;
		case 0x2cef ... 0x2cf1:
			return true;
		case 0x2d7f:
			return true;
		case 0x2de0 ... 0x2dff:
			return true;
		case 0x302a ... 0x302f:
			return true;
		case 0x3099 ... 0x309a:
			return true;
		case 0xa66f ... 0xa672:
			return true;
		case 0xa674 ... 0xa67d:
			return true;
		case 0xa69e ... 0xa69f:
			return true;
		case 0xa6f0 ... 0xa6f1:
			return true;
		case 0xa802:
			return true;
		case 0xa806:
			return true;
		case 0xa80b:
			return true;
		case 0xa823 ... 0xa827:
			return true;
		case 0xa82c:
			return true;
		case 0xa880 ... 0xa881:
			return true;
		case 0xa8b4 ... 0xa8c5:
			return true;
		case 0xa8e0 ... 0xa8f1:
			return true;
		case 0xa8ff:
			return true;
		case 0xa926 ... 0xa92d:
			return true;
		case 0xa947 ... 0xa953:
			return true;
		case 0xa980 ... 0xa983:
			return true;
		case 0xa9b3 ... 0xa9c0:
			return true;
		case 0xa9e5:
			return true;
		case 0xaa29 ... 0xaa36:
			return true;
		case 0xaa43:
			return true;
		case 0xaa4c ... 0xaa4d:
			return true;
		case 0xaa7b ... 0xaa7d:
			return true;
		case 0xaab0:
			return true;
		case 0xaab2 ... 0xaab4:
			return true;
		case 0xaab7 ... 0xaab8:
			return true;
		case 0xaabe ... 0xaabf:
			return true;
		case 0xaac1:
			return true;
		case 0xaaeb ... 0xaaef:
			return true;
		case 0xaaf5 ... 0xaaf6:
			return true;
		case 0xabe3 ... 0xabea:
			return true;
		case 0xabec ... 0xabed:
			return true;
		case 0xfb1e:
			return true;
		case 0xfe00 ... 0xfe0f:
			return true;
		case 0xfe20 ... 0xfe2f:
			return true;
		case 0x101fd:
			return true;
		case 0x102e0:
			return true;
		case 0x10376 ... 0x1037a:
			return true;
		case 0x10a01 ... 0x10a03:
			return true;
		case 0x10a05 ... 0x10a06:
			return true;
		case 0x10a0c ... 0x10a0f:
			return true;
		case 0x10a38 ... 0x10a3a:
			return true;
		case 0x10a3f:
			return true;
		case 0x10ae5 ... 0x10ae6:
			return true;
		case 0x10d24 ... 0x10d27:
			return true;
		case 0x10eab ... 0x10eac:
			return true;
		case 0x10f46 ... 0x10f50:
			return true;
		case 0x11000 ... 0x11002:
			return true;
		case 0x11038 ... 0x11046:
			return true;
		case 0x1107f ... 0x11082:
			return true;
		case 0x110b0 ... 0x110ba:
			return true;
		case 0x11100 ... 0x11102:
			return true;
		case 0x11127 ... 0x11134:
			return true;
		case 0x11145 ... 0x11146:
			return true;
		case 0x11173:
			return true;
		case 0x11180 ... 0x11182:
			return true;
		case 0x111b3 ... 0x111c0:
			return true;
		case 0x111c9 ... 0x111cc:
			return true;
		case 0x111ce ... 0x111cf:
			return true;
		case 0x1122c ... 0x11237:
			return true;
		case 0x1123e:
			return true;
		case 0x112df ... 0x112ea:
			return true;
		case 0x11300 ... 0x11303:
			return true;
		case 0x1133b ... 0x1133c:
			return true;
		case 0x1133e ... 0x11344:
			return true;
		case 0x11347 ... 0x11348:
			return true;
		case 0x1134b ... 0x1134d:
			return true;
		case 0x11357:
			return true;
		case 0x11362 ... 0x11363:
			return true;
		case 0x11366 ... 0x1136c:
			return true;
		case 0x11370 ... 0x11374:
			return true;
		case 0x11435 ... 0x11446:
			return true;
		case 0x1145e:
			return true;
		case 0x114b0 ... 0x114c3:
			return true;
		case 0x115af ... 0x115b5:
			return true;
		case 0x115b8 ... 0x115c0:
			return true;
		case 0x115dc ... 0x115dd:
			return true;
		case 0x11630 ... 0x11640:
			return true;
		case 0x116ab ... 0x116b7:
			return true;
		case 0x1171d ... 0x1172b:
			return true;
		case 0x1182c ... 0x1183a:
			return true;
		case 0x11930 ... 0x11935:
			return true;
		case 0x11937 ... 0x11938:
			return true;
		case 0x1193b ... 0x1193e:
			return true;
		case 0x11940:
			return true;
		case 0x11942 ... 0x11943:
			return true;
		case 0x119d1 ... 0x119d7:
			return true;
		case 0x119da ... 0x119e0:
			return true;
		case 0x119e4:
			return true;
		case 0x11a01 ... 0x11a0a:
			return true;
		case 0x11a33 ... 0x11a39:
			return true;
		case 0x11a3b ... 0x11a3e:
			return true;
		case 0x11a47:
			return true;
		case 0x11a51 ... 0x11a5b:
			return true;
		case 0x11a8a ... 0x11a99:
			return true;
		case 0x11c2f ... 0x11c36:
			return true;
		case 0x11c38 ... 0x11c3f:
			return true;
		case 0x11c92 ... 0x11ca7:
			return true;
		case 0x11ca9 ... 0x11cb6:
			return true;
		case 0x11d31 ... 0x11d36:
			return true;
		case 0x11d3a:
			return true;
		case 0x11d3c ... 0x11d3d:
			return true;
		case 0x11d3f ... 0x11d45:
			return true;
		case 0x11d47:
			return true;
		case 0x11d8a ... 0x11d8e:
			return true;
		case 0x11d90 ... 0x11d91:
			return true;
		case 0x11d93 ... 0x11d97:
			return true;
		case 0x11ef3 ... 0x11ef6:
			return true;
		case 0x16af0 ... 0x16af4:
			return true;
		case 0x16b30 ... 0x16b36:
			return true;
		case 0x16f4f:
			return true;
		case 0x16f51 ... 0x16f87:
			return true;
		case 0x16f8f ... 0x16f92:
			return true;
		case 0x16fe4:
			return true;
		case 0x16ff0 ... 0x16ff1:
			return true;
		case 0x1bc9d ... 0x1bc9e:
			return true;
		case 0x1d165 ... 0x1d169:
			return true;
		case 0x1d16d ... 0x1d172:
			return true;
		case 0x1d17b ... 0x1d182:
			return true;
		case 0x1d185 ... 0x1d18b:
			return true;
		case 0x1d1aa ... 0x1d1ad:
			return true;
		case 0x1d242 ... 0x1d244:
			return true;
		case 0x1da00 ... 0x1da36:
			return true;
		case 0x1da3b ... 0x1da6c:
			return true;
		case 0x1da75:
			return true;
		case 0x1da84:
			return true;
		case 0x1da9b ... 0x1da9f:
			return true;
		case 0x1daa1 ... 0x1daaf:
			return true;
		case 0x1e000 ... 0x1e006:
			return true;
		case 0x1e008 ... 0x1e018:
			return true;
		case 0x1e01b ... 0x1e021:
			return true;
		case 0x1e023 ... 0x1e024:
			return true;
		case 0x1e026 ... 0x1e02a:
			return true;
		case 0x1e130 ... 0x1e136:
			return true;
		case 0x1e2ec ... 0x1e2ef:
			return true;
		case 0x1e8d0 ... 0x1e8d6:
			return true;
		case 0x1e944 ... 0x1e94a:
			return true;
		case 0x1f3fb ... 0x1f3ff:
			return true;
		case 0xe0100 ... 0xe01ef:
			return true;
	} // }}}

	return false;
}

bool
is_ignored_char(char_type code) {
	// Control characters and non-characters (2339 codepoints) {{{
	if (LIKELY(0x20 <= code && code <= 0x7e)) return false;
	switch(code) {
		case 0x0 ... 0x1f:
			return true;
		case 0x7f ... 0x9f:
			return true;
		case 0xad:
			return true;
		case 0x600 ... 0x605:
			return true;
		case 0x61c:
			return true;
		case 0x6dd:
			return true;
		case 0x70f:
			return true;
		case 0x8e2:
			return true;
		case 0x180e:
			return true;
		case 0x200b ... 0x200c:
			return true;
		case 0x200e ... 0x200f:
			return true;
		case 0x202a ... 0x202e:
			return true;
		case 0x2060 ... 0x2064:
			return true;
		case 0x2066 ... 0x206f:
			return true;
		case 0xd800 ... 0xdfff:
			return true;
		case 0xfdd0 ... 0xfdef:
			return true;
		case 0xfeff:
			return true;
		case 0xfff9 ... 0xfffb:
			return true;
		case 0xfffe ... 0xffff:
			return true;
		case 0x110bd:
			return true;
		case 0x110cd:
			return true;
		case 0x13430 ... 0x13438:
			return true;
		case 0x1bca0 ... 0x1bca3:
			return true;
		case 0x1d173 ... 0x1d17a:
			return true;
		case 0x1fffe ... 0x1ffff:
			return true;
		case 0x2fffe ... 0x2ffff:
			return true;
		case 0x3fffe ... 0x3ffff:
			return true;
		case 0x4fffe ... 0x4ffff:
			return true;
		case 0x5fffe ... 0x5ffff:
			return true;
		case 0x6fffe ... 0x6ffff:
			return true;
		case 0x7fffe ... 0x7ffff:
			return true;
		case 0x8fffe ... 0x8ffff:
			return true;
		case 0x9fffe ... 0x9ffff:
			return true;
		case 0xafffe ... 0xaffff:
			return true;
		case 0xbfffe ... 0xbffff:
			return true;
		case 0xcfffe ... 0xcffff:
			return true;
		case 0xdfffe ... 0xdffff:
			return true;
		case 0xe0001:
			return true;
		case 0xe0020 ... 0xe007f:
			return true;
		case 0xefffe ... 0xeffff:
			return true;
		case 0xffffe ... 0xfffff:
			return true;
		case 0x10fffe ... 0x10ffff:
			return true;
	} // }}}

	return false;
}

bool
is_word_char(char_type code) {
	// L and N categories (133022 codepoints) {{{
	switch(code) {
		case 0x30 ... 0x39:
			return true;
		case 0x41 ... 0x5a:
			return true;
		case 0x61 ... 0x7a:
			return true;
		case 0xaa:
			return true;
		case 0xb2 ... 0xb3:
			return true;
		case 0xb5:
			return true;
		case 0xb9 ... 0xba:
			return true;
		case 0xbc ... 0xbe:
			return true;
		case 0xc0 ... 0xd6:
			return true;
		case 0xd8 ... 0xf6:
			return true;
		case 0xf8 ... 0x2c1:
			return true;
		case 0x2c6 ... 0x2d1:
			return true;
		case 0x2e0 ... 0x2e4:
			return true;
		case 0x2ec:
			return true;
		case 0x2ee:
			return true;
		case 0x370 ... 0x374:
			return true;
		case 0x376 ... 0x377:
			return true;
		case 0x37a ... 0x37d:
			return true;
		case 0x37f:
			return true;
		case 0x386:
			return true;
		case 0x388 ... 0x38a:
			return true;
		case 0x38c:
			return true;
		case 0x38e ... 0x3a1:
			return true;
		case 0x3a3 ... 0x3f5:
			return true;
		case 0x3f7 ... 0x481:
			return true;
		case 0x48a ... 0x52f:
			return true;
		case 0x531 ... 0x556:
			return true;
		case 0x559:
			return true;
		case 0x560 ... 0x588:
			return true;
		case 0x5d0 ... 0x5ea:
			return true;
		case 0x5ef ... 0x5f2:
			return true;
		case 0x620 ... 0x64a:
			return true;
		case 0x660 ... 0x669:
			return true;
		case 0x66e ... 0x66f:
			return true;
		case 0x671 ... 0x6d3:
			return true;
		case 0x6d5:
			return true;
		case 0x6e5 ... 0x6e6:
			return true;
		case 0x6ee ... 0x6fc:
			return true;
		case 0x6ff:
			return true;
		case 0x710:
			return true;
		case 0x712 ... 0x72f:
			return true;
		case 0x74d ... 0x7a5:
			return true;
		case 0x7b1:
			return true;
		case 0x7c0 ... 0x7ea:
			return true;
		case 0x7f4 ... 0x7f5:
			return true;
		case 0x7fa:
			return true;
		case 0x800 ... 0x815:
			return true;
		case 0x81a:
			return true;
		case 0x824:
			return true;
		case 0x828:
			return true;
		case 0x840 ... 0x858:
			return true;
		case 0x860 ... 0x86a:
			return true;
		case 0x8a0 ... 0x8b4:
			return true;
		case 0x8b6 ... 0x8c7:
			return true;
		case 0x904 ... 0x939:
			return true;
		case 0x93d:
			return true;
		case 0x950:
			return true;
		case 0x958 ... 0x961:
			return true;
		case 0x966 ... 0x96f:
			return true;
		case 0x971 ... 0x980:
			return true;
		case 0x985 ... 0x98c:
			return true;
		case 0x98f ... 0x990:
			return true;
		case 0x993 ... 0x9a8:
			return true;
		case 0x9aa ... 0x9b0:
			return true;
		case 0x9b2:
			return true;
		case 0x9b6 ... 0x9b9:
			return true;
		case 0x9bd:
			return true;
		case 0x9ce:
			return true;
		case 0x9dc ... 0x9dd:
			return true;
		case 0x9df ... 0x9e1:
			return true;
		case 0x9e6 ... 0x9f1:
			return true;
		case 0x9f4 ... 0x9f9:
			return true;
		case 0x9fc:
			return true;
		case 0xa05 ... 0xa0a:
			return true;
		case 0xa0f ... 0xa10:
			return true;
		case 0xa13 ... 0xa28:
			return true;
		case 0xa2a ... 0xa30:
			return true;
		case 0xa32 ... 0xa33:
			return true;
		case 0xa35 ... 0xa36:
			return true;
		case 0xa38 ... 0xa39:
			return true;
		case 0xa59 ... 0xa5c:
			return true;
		case 0xa5e:
			return true;
		case 0xa66 ... 0xa6f:
			return true;
		case 0xa72 ... 0xa74:
			return true;
		case 0xa85 ... 0xa8d:
			return true;
		case 0xa8f ... 0xa91:
			return true;
		case 0xa93 ... 0xaa8:
			return true;
		case 0xaaa ... 0xab0:
			return true;
		case 0xab2 ... 0xab3:
			return true;
		case 0xab5 ... 0xab9:
			return true;
		case 0xabd:
			return true;
		case 0xad0:
			return true;
		case 0xae0 ... 0xae1:
			return true;
		case 0xae6 ... 0xaef:
			return true;
		case 0xaf9:
			return true;
		case 0xb05 ... 0xb0c:
			return true;
		case 0xb0f ... 0xb10:
			return true;
		case 0xb13 ... 0xb28:
			return true;
		case 0xb2a ... 0xb30:
			return true;
		case 0xb32 ... 0xb33:
			return true;
		case 0xb35 ... 0xb39:
			return true;
		case 0xb3d:
			return true;
		case 0xb5c ... 0xb5d:
			return true;
		case 0xb5f ... 0xb61:
			return true;
		case 0xb66 ... 0xb6f:
			return true;
		case 0xb71 ... 0xb77:
			return true;
		case 0xb83:
			return true;
		case 0xb85 ... 0xb8a:
			return true;
		case 0xb8e ... 0xb90:
			return true;
		case 0xb92 ... 0xb95:
			return true;
		case 0xb99 ... 0xb9a:
			return true;
		case 0xb9c:
			return true;
		case 0xb9e ... 0xb9f:
			return true;
		case 0xba3 ... 0xba4:
			return true;
		case 0xba8 ... 0xbaa:
			return true;
		case 0xbae ... 0xbb9:
			return true;
		case 0xbd0:
			return true;
		case 0xbe6 ... 0xbf2:
			return true;
		case 0xc05 ... 0xc0c:
			return true;
		case 0xc0e ... 0xc10:
			return true;
		case 0xc12 ... 0xc28:
			return true;
		case 0xc2a ... 0xc39:
			return true;
		case 0xc3d:
			return true;
		case 0xc58 ... 0xc5a:
			return true;
		case 0xc60 ... 0xc61:
			return true;
		case 0xc66 ... 0xc6f:
			return true;
		case 0xc78 ... 0xc7e:
			return true;
		case 0xc80:
			return true;
		case 0xc85 ... 0xc8c:
			return true;
		case 0xc8e ... 0xc90:
			return true;
		case 0xc92 ... 0xca8:
			return true;
		case 0xcaa ... 0xcb3:
			return true;
		case 0xcb5 ... 0xcb9:
			return true;
		case 0xcbd:
			return true;
		case 0xcde:
			return true;
		case 0xce0 ... 0xce1:
			return true;
		case 0xce6 ... 0xcef:
			return true;
		case 0xcf1 ... 0xcf2:
			return true;
		case 0xd04 ... 0xd0c:
			return true;
		case 0xd0e ... 0xd10:
			return true;
		case 0xd12 ... 0xd3a:
			return true;
		case 0xd3d:
			return true;
		case 0xd4e:
			return true;
		case 0xd54 ... 0xd56:
			return true;
		case 0xd58 ... 0xd61:
			return true;
		case 0xd66 ... 0xd78:
			return true;
		case 0xd7a ... 0xd7f:
			return true;
		case 0xd85 ... 0xd96:
			return true;
		case 0xd9a ... 0xdb1:
			return true;
		case 0xdb3 ... 0xdbb:
			return true;
		case 0xdbd:
			return true;
		case 0xdc0 ... 0xdc6:
			return true;
		case 0xde6 ... 0xdef:
			return true;
		case 0xe01 ... 0xe30:
			return true;
		case 0xe32 ... 0xe33:
			return true;
		case 0xe40 ... 0xe46:
			return true;
		case 0xe50 ... 0xe59:
			return true;
		case 0xe81 ... 0xe82:
			return true;
		case 0xe84:
			return true;
		case 0xe86 ... 0xe8a:
			return true;
		case 0xe8c ... 0xea3:
			return true;
		case 0xea5:
			return true;
		case 0xea7 ... 0xeb0:
			return true;
		case 0xeb2 ... 0xeb3:
			return true;
		case 0xebd:
			return true;
		case 0xec0 ... 0xec4:
			return true;
		case 0xec6:
			return true;
		case 0xed0 ... 0xed9:
			return true;
		case 0xedc ... 0xedf:
			return true;
		case 0xf00:
			return true;
		case 0xf20 ... 0xf33:
			return true;
		case 0xf40 ... 0xf47:
			return true;
		case 0xf49 ... 0xf6c:
			return true;
		case 0xf88 ... 0xf8c:
			return true;
		case 0x1000 ... 0x102a:
			return true;
		case 0x103f ... 0x1049:
			return true;
		case 0x1050 ... 0x1055:
			return true;
		case 0x105a ... 0x105d:
			return true;
		case 0x1061:
			return true;
		case 0x1065 ... 0x1066:
			return true;
		case 0x106e ... 0x1070:
			return true;
		case 0x1075 ... 0x1081:
			return true;
		case 0x108e:
			return true;
		case 0x1090 ... 0x1099:
			return true;
		case 0x10a0 ... 0x10c5:
			return true;
		case 0x10c7:
			return true;
		case 0x10cd:
			return true;
		case 0x10d0 ... 0x10fa:
			return true;
		case 0x10fc ... 0x1248:
			return true;
		case 0x124a ... 0x124d:
			return true;
		case 0x1250 ... 0x1256:
			return true;
		case 0x1258:
			return true;
		case 0x125a ... 0x125d:
			return true;
		case 0x1260 ... 0x1288:
			return true;
		case 0x128a ... 0x128d:
			return true;
		case 0x1290 ... 0x12b0:
			return true;
		case 0x12b2 ... 0x12b5:
			return true;
		case 0x12b8 ... 0x12be:
			return true;
		case 0x12c0:
			return true;
		case 0x12c2 ... 0x12c5:
			return true;
		case 0x12c8 ... 0x12d6:
			return true;
		case 0x12d8 ... 0x1310:
			return true;
		case 0x1312 ... 0x1315:
			return true;
		case 0x1318 ... 0x135a:
			return true;
		case 0x1369 ... 0x137c:
			return true;
		case 0x1380 ... 0x138f:
			return true;
		case 0x13a0 ... 0x13f5:
			return true;
		case 0x13f8 ... 0x13fd:
			return true;
		case 0x1401 ... 0x166c:
			return true;
		case 0x166f ... 0x167f:
			return true;
		case 0x1681 ... 0x169a:
			return true;
		case 0x16a0 ... 0x16ea:
			return true;
		case 0x16ee ... 0x16f8:
			return true;
		case 0x1700 ... 0x170c:
			return true;
		case 0x170e ... 0x1711:
			return true;
		case 0x1720 ... 0x1731:
			return true;
		case 0x1740 ... 0x1751:
			return true;
		case 0x1760 ... 0x176c:
			return true;
		case 0x176e ... 0x1770:
			return true;
		case 0x1780 ... 0x17b3:
			return true;
		case 0x17d7:
			return true;
		case 0x17dc:
			return true;
		case 0x17e0 ... 0x17e9:
			return true;
		case 0x17f0 ... 0x17f9:
			return true;
		case 0x1810 ... 0x1819:
			return true;
		case 0x1820 ... 0x1878:
			return true;
		case 0x1880 ... 0x1884:
			return true;
		case 0x1887 ... 0x18a8:
			return true;
		case 0x18aa:
			return true;
		case 0x18b0 ... 0x18f5:
			return true;
		case 0x1900 ... 0x191e:
			return true;
		case 0x1946 ... 0x196d:
			return true;
		case 0x1970 ... 0x1974:
			return true;
		case 0x1980 ... 0x19ab:
			return true;
		case 0x19b0 ... 0x19c9:
			return true;
		case 0x19d0 ... 0x19da:
			return true;
		case 0x1a00 ... 0x1a16:
			return true;
		case 0x1a20 ... 0x1a54:
			return true;
		case 0x1a80 ... 0x1a89:
			return true;
		case 0x1a90 ... 0x1a99:
			return true;
		case 0x1aa7:
			return true;
		case 0x1b05 ... 0x1b33:
			return true;
		case 0x1b45 ... 0x1b4b:
			return true;
		case 0x1b50 ... 0x1b59:
			return true;
		case 0x1b83 ... 0x1ba0:
			return true;
		case 0x1bae ... 0x1be5:
			return true;
		case 0x1c00 ... 0x1c23:
			return true;
		case 0x1c40 ... 0x1c49:
			return true;
		case 0x1c4d ... 0x1c7d:
			return true;
		case 0x1c80 ... 0x1c88:
			return true;
		case 0x1c90 ... 0x1cba:
			return true;
		case 0x1cbd ... 0x1cbf:
			return true;
		case 0x1ce9 ... 0x1cec:
			return true;
		case 0x1cee ... 0x1cf3:
			return true;
		case 0x1cf5 ... 0x1cf6:
			return true;
		case 0x1cfa:
			return true;
		case 0x1d00 ... 0x1dbf:
			return true;
		case 0x1e00 ... 0x1f15:
			return true;
		case 0x1f18 ... 0x1f1d:
			return true;
		case 0x1f20 ... 0x1f45:
			return true;
		case 0x1f48 ... 0x1f4d:
			return true;
		case 0x1f50 ... 0x1f57:
			return true;
		case 0x1f59:
			return true;
		case 0x1f5b:
			return true;
		case 0x1f5d:
			return true;
		case 0x1f5f ... 0x1f7d:
			return true;
		case 0x1f80 ... 0x1fb4:
			return true;
		case 0x1fb6 ... 0x1fbc:
			return true;
		case 0x1fbe:
			return true;
		case 0x1fc2 ... 0x1fc4:
			return true;
		case 0x1fc6 ... 0x1fcc:
			return true;
		case 0x1fd0 ... 0x1fd3:
			return true;
		case 0x1fd6 ... 0x1fdb:
			return true;
		case 0x1fe0 ... 0x1fec:
			return true;
		case 0x1ff2 ... 0x1ff4:
			return true;
		case 0x1ff6 ... 0x1ffc:
			return true;
		case 0x2070 ... 0x2071:
			return true;
		case 0x2074 ... 0x2079:
			return true;
		case 0x207f ... 0x2089:
			return true;
		case 0x2090 ... 0x209c:
			return true;
		case 0x2102:
			return true;
		case 0x2107:
			return true;
		case 0x210a ... 0x2113:
			return true;
		case 0x2115:
			return true;
		case 0x2119 ... 0x211d:
			return true;
		case 0x2124:
			return true;
		case 0x2126:
			return true;
		case 0x2128:
			return true;
		case 0x212a ... 0x212d:
			return true;
		case 0x212f ... 0x2139:
			return true;
		case 0x213c ... 0x213f:
			return true;
		case 0x2145 ... 0x2149:
			return true;
		case 0x214e:
			return true;
		case 0x2150 ... 0x2189:
			return true;
		case 0x2460 ... 0x249b:
			return true;
		case 0x24ea ... 0x24ff:
			return true;
		case 0x2776 ... 0x2793:
			return true;
		case 0x2c00 ... 0x2c2e:
			return true;
		case 0x2c30 ... 0x2c5e:
			return true;
		case 0x2c60 ... 0x2ce4:
			return true;
		case 0x2ceb ... 0x2cee:
			return true;
		case 0x2cf2 ... 0x2cf3:
			return true;
		case 0x2cfd:
			return true;
		case 0x2d00 ... 0x2d25:
			return true;
		case 0x2d27:
			return true;
		case 0x2d2d:
			return true;
		case 0x2d30 ... 0x2d67:
			return true;
		case 0x2d6f:
			return true;
		case 0x2d80 ... 0x2d96:
			return true;
		case 0x2da0 ... 0x2da6:
			return true;
		case 0x2da8 ... 0x2dae:
			return true;
		case 0x2db0 ... 0x2db6:
			return true;
		case 0x2db8 ... 0x2dbe:
			return true;
		case 0x2dc0 ... 0x2dc6:
			return true;
		case 0x2dc8 ... 0x2dce:
			return true;
		case 0x2dd0 ... 0x2dd6:
			return true;
		case 0x2dd8 ... 0x2dde:
			return true;
		case 0x2e2f:
			return true;
		case 0x3005 ... 0x3007:
			return true;
		case 0x3021 ... 0x3029:
			return true;
		case 0x3031 ... 0x3035:
			return true;
		case 0x3038 ... 0x303c:
			return true;
		case 0x3041 ... 0x3096:
			return true;
		case 0x309d ... 0x309f:
			return true;
		case 0x30a1 ... 0x30fa:
			return true;
		case 0x30fc ... 0x30ff:
			return true;
		case 0x3105 ... 0x312f:
			return true;
		case 0x3131 ... 0x318e:
			return true;
		case 0x3192 ... 0x3195:
			return true;
		case 0x31a0 ... 0x31bf:
			return true;
		case 0x31f0 ... 0x31ff:
			return true;
		case 0x3220 ... 0x3229:
			return true;
		case 0x3248 ... 0x324f:
			return true;
		case 0x3251 ... 0x325f:
			return true;
		case 0x3280 ... 0x3289:
			return true;
		case 0x32b1 ... 0x32bf:
			return true;
		case 0x3400 ... 0x4dbf:
			return true;
		case 0x4e00 ... 0x9ffc:
			return true;
		case 0xa000 ... 0xa48c:
			return true;
		case 0xa4d0 ... 0xa4fd:
			return true;
		case 0xa500 ... 0xa60c:
			return true;
		case 0xa610 ... 0xa62b:
			return true;
		case 0xa640 ... 0xa66e:
			return true;
		case 0xa67f ... 0xa69d:
			return true;
		case 0xa6a0 ... 0xa6ef:
			return true;
		case 0xa717 ... 0xa71f:
			return true;
		case 0xa722 ... 0xa788:
			return true;
		case 0xa78b ... 0xa7bf:
			return true;
		case 0xa7c2 ... 0xa7ca:
			return true;
		case 0xa7f5 ... 0xa801:
			return true;
		case 0xa803 ... 0xa805:
			return true;
		case 0xa807 ... 0xa80a:
			return true;
		case 0xa80c ... 0xa822:
			return true;
		case 0xa830 ... 0xa835:
			return true;
		case 0xa840 ... 0xa873:
			return true;
		case 0xa882 ... 0xa8b3:
			return true;
		case 0xa8d0 ... 0xa8d9:
			return true;
		case 0xa8f2 ... 0xa8f7:
			return true;
		case 0xa8fb:
			return true;
		case 0xa8fd ... 0xa8fe:
			return true;
		case 0xa900 ... 0xa925:
			return true;
		case 0xa930 ... 0xa946:
			return true;
		case 0xa960 ... 0xa97c:
			return true;
		case 0xa984 ... 0xa9b2:
			return true;
		case 0xa9cf ... 0xa9d9:
			return true;
		case 0xa9e0 ... 0xa9e4:
			return true;
		case 0xa9e6 ... 0xa9fe:
			return true;
		case 0xaa00 ... 0xaa28:
			return true;
		case 0xaa40 ... 0xaa42:
			return true;
		case 0xaa44 ... 0xaa4b:
			return true;
		case 0xaa50 ... 0xaa59:
			return true;
		case 0xaa60 ... 0xaa76:
			return true;
		case 0xaa7a:
			return true;
		case 0xaa7e ... 0xaaaf:
			return true;
		case 0xaab1:
			return true;
		case 0xaab5 ... 0xaab6:
			return true;
		case 0xaab9 ... 0xaabd:
			return true;
		case 0xaac0:
			return true;
		case 0xaac2:
			return true;
		case 0xaadb ... 0xaadd:
			return true;
		case 0xaae0 ... 0xaaea:
			return true;
		case 0xaaf2 ... 0xaaf4:
			return true;
		case 0xab01 ... 0xab06:
			return true;
		case 0xab09 ... 0xab0e:
			return true;
		case 0xab11 ... 0xab16:
			return true;
		case 0xab20 ... 0xab26:
			return true;
		case 0xab28 ... 0xab2e:
			return true;
		case 0xab30 ... 0xab5a:
			return true;
		case 0xab5c ... 0xab69:
			return true;
		case 0xab70 ... 0xabe2:
			return true;
		case 0xabf0 ... 0xabf9:
			return true;
		case 0xac00 ... 0xd7a3:
			return true;
		case 0xd7b0 ... 0xd7c6:
			return true;
		case 0xd7cb ... 0xd7fb:
			return true;
		case 0xf900 ... 0xfa6d:
			return true;
		case 0xfa70 ... 0xfad9:
			return true;
		case 0xfb00 ... 0xfb06:
			return true;
		case 0xfb13 ... 0xfb17:
			return true;
		case 0xfb1d:
			return true;
		case 0xfb1f ... 0xfb28:
			return true;
		case 0xfb2a ... 0xfb36:
			return true;
		case 0xfb38 ... 0xfb3c:
			return true;
		case 0xfb3e:
			return true;
		case 0xfb40 ... 0xfb41:
			return true;
		case 0xfb43 ... 0xfb44:
			return true;
		case 0xfb46 ... 0xfbb1:
			return true;
		case 0xfbd3 ... 0xfd3d:
			return true;
		case 0xfd50 ... 0xfd8f:
			return true;
		case 0xfd92 ... 0xfdc7:
			return true;
		case 0xfdf0 ... 0xfdfb:
			return true;
		case 0xfe70 ... 0xfe74:
			return true;
		case 0xfe76 ... 0xfefc:
			return true;
		case 0xff10 ... 0xff19:
			return true;
		case 0xff21 ... 0xff3a:
			return true;
		case 0xff41 ... 0xff5a:
			return true;
		case 0xff66 ... 0xffbe:
			return true;
		case 0xffc2 ... 0xffc7:
			return true;
		case 0xffca ... 0xffcf:
			return true;
		case 0xffd2 ... 0xffd7:
			return true;
		case 0xffda ... 0xffdc:
			return true;
		case 0x10000 ... 0x1000b:
			return true;
		case 0x1000d ... 0x10026:
			return true;
		case 0x10028 ... 0x1003a:
			return true;
		case 0x1003c ... 0x1003d:
			return true;
		case 0x1003f ... 0x1004d:
			return true;
		case 0x10050 ... 0x1005d:
			return true;
		case 0x10080 ... 0x100fa:
			return true;
		case 0x10107 ... 0x10133:
			return true;
		case 0x10140 ... 0x10178:
			return true;
		case 0x1018a ... 0x1018b:
			return true;
		case 0x10280 ... 0x1029c:
			return true;
		case 0x102a0 ... 0x102d0:
			return true;
		case 0x102e1 ... 0x102fb:
			return true;
		case 0x10300 ... 0x10323:
			return true;
		case 0x1032d ... 0x1034a:
			return true;
		case 0x10350 ... 0x10375:
			return true;
		case 0x10380 ... 0x1039d:
			return true;
		case 0x103a0 ... 0x103c3:
			return true;
		case 0x103c8 ... 0x103cf:
			return true;
		case 0x103d1 ... 0x103d5:
			return true;
		case 0x10400 ... 0x1049d:
			return true;
		case 0x104a0 ... 0x104a9:
			return true;
		case 0x104b0 ... 0x104d3:
			return true;
		case 0x104d8 ... 0x104fb:
			return true;
		case 0x10500 ... 0x10527:
			return true;
		case 0x10530 ... 0x10563:
			return true;
		case 0x10600 ... 0x10736:
			return true;
		case 0x10740 ... 0x10755:
			return true;
		case 0x10760 ... 0x10767:
			return true;
		case 0x10800 ... 0x10805:
			return true;
		case 0x10808:
			return true;
		case 0x1080a ... 0x10835:
			return true;
		case 0x10837 ... 0x10838:
			return true;
		case 0x1083c:
			return true;
		case 0x1083f ... 0x10855:
			return true;
		case 0x10858 ... 0x10876:
			return true;
		case 0x10879 ... 0x1089e:
			return true;
		case 0x108a7 ... 0x108af:
			return true;
		case 0x108e0 ... 0x108f2:
			return true;
		case 0x108f4 ... 0x108f5:
			return true;
		case 0x108fb ... 0x1091b:
			return true;
		case 0x10920 ... 0x10939:
			return true;
		case 0x10980 ... 0x109b7:
			return true;
		case 0x109bc ... 0x109cf:
			return true;
		case 0x109d2 ... 0x10a00:
			return true;
		case 0x10a10 ... 0x10a13:
			return true;
		case 0x10a15 ... 0x10a17:
			return true;
		case 0x10a19 ... 0x10a35:
			return true;
		case 0x10a40 ... 0x10a48:
			return true;
		case 0x10a60 ... 0x10a7e:
			return true;
		case 0x10a80 ... 0x10a9f:
			return true;
		case 0x10ac0 ... 0x10ac7:
			return true;
		case 0x10ac9 ... 0x10ae4:
			return true;
		case 0x10aeb ... 0x10aef:
			return true;
		case 0x10b00 ... 0x10b35:
			return true;
		case 0x10b40 ... 0x10b55:
			return true;
		case 0x10b58 ... 0x10b72:
			return true;
		case 0x10b78 ... 0x10b91:
			return true;
		case 0x10ba9 ... 0x10baf:
			return true;
		case 0x10c00 ... 0x10c48:
			return true;
		case 0x10c80 ... 0x10cb2:
			return true;
		case 0x10cc0 ... 0x10cf2:
			return true;
		case 0x10cfa ... 0x10d23:
			return true;
		case 0x10d30 ... 0x10d39:
			return true;
		case 0x10e60 ... 0x10e7e:
			return true;
		case 0x10e80 ... 0x10ea9:
			return true;
		case 0x10eb0 ... 0x10eb1:
			return true;
		case 0x10f00 ... 0x10f27:
			return true;
		case 0x10f30 ... 0x10f45:
			return true;
		case 0x10f51 ... 0x10f54:
			return true;
		case 0x10fb0 ... 0x10fcb:
			return true;
		case 0x10fe0 ... 0x10ff6:
			return true;
		case 0x11003 ... 0x11037:
			return true;
		case 0x11052 ... 0x1106f:
			return true;
		case 0x11083 ... 0x110af:
			return true;
		case 0x110d0 ... 0x110e8:
			return true;
		case 0x110f0 ... 0x110f9:
			return true;
		case 0x11103 ... 0x11126:
			return true;
		case 0x11136 ... 0x1113f:
			return true;
		case 0x11144:
			return true;
		case 0x11147:
			return true;
		case 0x11150 ... 0x11172:
			return true;
		case 0x11176:
			return true;
		case 0x11183 ... 0x111b2:
			return true;
		case 0x111c1 ... 0x111c4:
			return true;
		case 0x111d0 ... 0x111da:
			return true;
		case 0x111dc:
			return true;
		case 0x111e1 ... 0x111f4:
			return true;
		case 0x11200 ... 0x11211:
			return true;
		case 0x11213 ... 0x1122b:
			return true;
		case 0x11280 ... 0x11286:
			return true;
		case 0x11288:
			return true;
		case 0x1128a ... 0x1128d:
			return true;
		case 0x1128f ... 0x1129d:
			return true;
		case 0x1129f ... 0x112a8:
			return true;
		case 0x112b0 ... 0x112de:
			return true;
		case 0x112f0 ... 0x112f9:
			return true;
		case 0x11305 ... 0x1130c:
			return true;
		case 0x1130f ... 0x11310:
			return true;
		case 0x11313 ... 0x11328:
			return true;
		case 0x1132a ... 0x11330:
			return true;
		case 0x11332 ... 0x11333:
			return true;
		case 0x11335 ... 0x11339:
			return true;
		case 0x1133d:
			return true;
		case 0x11350:
			return true;
		case 0x1135d ... 0x11361:
			return true;
		case 0x11400 ... 0x11434:
			return true;
		case 0x11447 ... 0x1144a:
			return true;
		case 0x11450 ... 0x11459:
			return true;
		case 0x1145f ... 0x11461:
			return true;
		case 0x11480 ... 0x114af:
			return true;
		case 0x114c4 ... 0x114c5:
			return true;
		case 0x114c7:
			return true;
		case 0x114d0 ... 0x114d9:
			return true;
		case 0x11580 ... 0x115ae:
			return true;
		case 0x115d8 ... 0x115db:
			return true;
		case 0x11600 ... 0x1162f:
			return true;
		case 0x11644:
			return true;
		case 0x11650 ... 0x11659:
			return true;
		case 0x11680 ... 0x116aa:
			return true;
		case 0x116b8:
			return true;
		case 0x116c0 ... 0x116c9:
			return true;
		case 0x11700 ... 0x1171a:
			return true;
		case 0x11730 ... 0x1173b:
			return true;
		case 0x11800 ... 0x1182b:
			return true;
		case 0x118a0 ... 0x118f2:
			return true;
		case 0x118ff ... 0x11906:
			return true;
		case 0x11909:
			return true;
		case 0x1190c ... 0x11913:
			return true;
		case 0x11915 ... 0x11916:
			return true;
		case 0x11918 ... 0x1192f:
			return true;
		case 0x1193f:
			return true;
		case 0x11941:
			return true;
		case 0x11950 ... 0x11959:
			return true;
		case 0x119a0 ... 0x119a7:
			return true;
		case 0x119aa ... 0x119d0:
			return true;
		case 0x119e1:
			return true;
		case 0x119e3:
			return true;
		case 0x11a00:
			return true;
		case 0x11a0b ... 0x11a32:
			return true;
		case 0x11a3a:
			return true;
		case 0x11a50:
			return true;
		case 0x11a5c ... 0x11a89:
			return true;
		case 0x11a9d:
			return true;
		case 0x11ac0 ... 0x11af8:
			return true;
		case 0x11c00 ... 0x11c08:
			return true;
		case 0x11c0a ... 0x11c2e:
			return true;
		case 0x11c40:
			return true;
		case 0x11c50 ... 0x11c6c:
			return true;
		case 0x11c72 ... 0x11c8f:
			return true;
		case 0x11d00 ... 0x11d06:
			return true;
		case 0x11d08 ... 0x11d09:
			return true;
		case 0x11d0b ... 0x11d30:
			return true;
		case 0x11d46:
			return true;
		case 0x11d50 ... 0x11d59:
			return true;
		case 0x11d60 ... 0x11d65:
			return true;
		case 0x11d67 ... 0x11d68:
			return true;
		case 0x11d6a ... 0x11d89:
			return true;
		case 0x11d98:
			return true;
		case 0x11da0 ... 0x11da9:
			return true;
		case 0x11ee0 ... 0x11ef2:
			return true;
		case 0x11fb0:
			return true;
		case 0x11fc0 ... 0x11fd4:
			return true;
		case 0x12000 ... 0x12399:
			return true;
		case 0x12400 ... 0x1246e:
			return true;
		case 0x12480 ... 0x12543:
			return true;
		case 0x13000 ... 0x1342e:
			return true;
		case 0x14400 ... 0x14646:
			return true;
		case 0x16800 ... 0x16a38:
			return true;
		case 0x16a40 ... 0x16a5e:
			return true;
		case 0x16a60 ... 0x16a69:
			return true;
		case 0x16ad0 ... 0x16aed:
			return true;
		case 0x16b00 ... 0x16b2f:
			return true;
		case 0x16b40 ... 0x16b43:
			return true;
		case 0x16b50 ... 0x16b59:
			return true;
		case 0x16b5b ... 0x16b61:
			return true;
		case 0x16b63 ... 0x16b77:
			return true;
		case 0x16b7d ... 0x16b8f:
			return true;
		case 0x16e40 ... 0x16e96:
			return true;
		case 0x16f00 ... 0x16f4a:
			return true;
		case 0x16f50:
			return true;
		case 0x16f93 ... 0x16f9f:
			return true;
		case 0x16fe0 ... 0x16fe1:
			return true;
		case 0x16fe3:
			return true;
		case 0x17000 ... 0x187f7:
			return true;
		case 0x18800 ... 0x18cd5:
			return true;
		case 0x18d00 ... 0x18d08:
			return true;
		case 0x1b000 ... 0x1b11e:
			return true;
		case 0x1b150 ... 0x1b152:
			return true;
		case 0x1b164 ... 0x1b167:
			return true;
		case 0x1b170 ... 0x1b2fb:
			return true;
		case 0x1bc00 ... 0x1bc6a:
			return true;
		case 0x1bc70 ... 0x1bc7c:
			return true;
		case 0x1bc80 ... 0x1bc88:
			return true;
		case 0x1bc90 ... 0x1bc99:
			return true;
		case 0x1d2e0 ... 0x1d2f3:
			return true;
		case 0x1d360 ... 0x1d378:
			return true;
		case 0x1d400 ... 0x1d454:
			return true;
		case 0x1d456 ... 0x1d49c:
			return true;
		case 0x1d49e ... 0x1d49f:
			return true;
		case 0x1d4a2:
			return true;
		case 0x1d4a5 ... 0x1d4a6:
			return true;
		case 0x1d4a9 ... 0x1d4ac:
			return true;
		case 0x1d4ae ... 0x1d4b9:
			return true;
		case 0x1d4bb:
			return true;
		case 0x1d4bd ... 0x1d4c3:
			return true;
		case 0x1d4c5 ... 0x1d505:
			return true;
		case 0x1d507 ... 0x1d50a:
			return true;
		case 0x1d50d ... 0x1d514:
			return true;
		case 0x1d516 ... 0x1d51c:
			return true;
		case 0x1d51e ... 0x1d539:
			return true;
		case 0x1d53b ... 0x1d53e:
			return true;
		case 0x1d540 ... 0x1d544:
			return true;
		case 0x1d546:
			return true;
		case 0x1d54a ... 0x1d550:
			return true;
		case 0x1d552 ... 0x1d6a5:
			return true;
		case 0x1d6a8 ... 0x1d6c0:
			return true;
		case 0x1d6c2 ... 0x1d6da:
			return true;
		case 0x1d6dc ... 0x1d6fa:
			return true;
		case 0x1d6fc ... 0x1d714:
			return true;
		case 0x1d716 ... 0x1d734:
			return true;
		case 0x1d736 ... 0x1d74e:
			return true;
		case 0x1d750 ... 0x1d76e:
			return true;
		case 0x1d770 ... 0x1d788:
			return true;
		case 0x1d78a ... 0x1d7a8:
			return true;
		case 0x1d7aa ... 0x1d7c2:
			return true;
		case 0x1d7c4 ... 0x1d7cb:
			return true;
		case 0x1d7ce ... 0x1d7ff:
			return true;
		case 0x1e100 ... 0x1e12c:
			return true;
		case 0x1e137 ... 0x1e13d:
			return true;
		case 0x1e140 ... 0x1e149:
			return true;
		case 0x1e14e:
			return true;
		case 0x1e2c0 ... 0x1e2eb:
			return true;
		case 0x1e2f0 ... 0x1e2f9:
			return true;
		case 0x1e800 ... 0x1e8c4:
			return true;
		case 0x1e8c7 ... 0x1e8cf:
			return true;
		case 0x1e900 ... 0x1e943:
			return true;
		case 0x1e94b:
			return true;
		case 0x1e950 ... 0x1e959:
			return true;
		case 0x1ec71 ... 0x1ecab:
			return true;
		case 0x1ecad ... 0x1ecaf:
			return true;
		case 0x1ecb1 ... 0x1ecb4:
			return true;
		case 0x1ed01 ... 0x1ed2d:
			return true;
		case 0x1ed2f ... 0x1ed3d:
			return true;
		case 0x1ee00 ... 0x1ee03:
			return true;
		case 0x1ee05 ... 0x1ee1f:
			return true;
		case 0x1ee21 ... 0x1ee22:
			return true;
		case 0x1ee24:
			return true;
		case 0x1ee27:
			return true;
		case 0x1ee29 ... 0x1ee32:
			return true;
		case 0x1ee34 ... 0x1ee37:
			return true;
		case 0x1ee39:
			return true;
		case 0x1ee3b:
			return true;
		case 0x1ee42:
			return true;
		case 0x1ee47:
			return true;
		case 0x1ee49:
			return true;
		case 0x1ee4b:
			return true;
		case 0x1ee4d ... 0x1ee4f:
			return true;
		case 0x1ee51 ... 0x1ee52:
			return true;
		case 0x1ee54:
			return true;
		case 0x1ee57:
			return true;
		case 0x1ee59:
			return true;
		case 0x1ee5b:
			return true;
		case 0x1ee5d:
			return true;
		case 0x1ee5f:
			return true;
		case 0x1ee61 ... 0x1ee62:
			return true;
		case 0x1ee64:
			return true;
		case 0x1ee67 ... 0x1ee6a:
			return true;
		case 0x1ee6c ... 0x1ee72:
			return true;
		case 0x1ee74 ... 0x1ee77:
			return true;
		case 0x1ee79 ... 0x1ee7c:
			return true;
		case 0x1ee7e:
			return true;
		case 0x1ee80 ... 0x1ee89:
			return true;
		case 0x1ee8b ... 0x1ee9b:
			return true;
		case 0x1eea1 ... 0x1eea3:
			return true;
		case 0x1eea5 ... 0x1eea9:
			return true;
		case 0x1eeab ... 0x1eebb:
			return true;
		case 0x1f100 ... 0x1f10c:
			return true;
		case 0x1fbf0 ... 0x1fbf9:
			return true;
		case 0x20000 ... 0x2a6dd:
			return true;
		case 0x2a700 ... 0x2b734:
			return true;
		case 0x2b740 ... 0x2b81d:
			return true;
		case 0x2b820 ... 0x2cea1:
			return true;
		case 0x2ceb0 ... 0x2ebe0:
			return true;
		case 0x2f800 ... 0x2fa1d:
			return true;
		case 0x30000 ... 0x3134a:
			return true;
	} // }}}

	return false;
}

bool
is_CZ_category(char_type code) {
	// C and Z categories (139761 codepoints) {{{
	switch(code) {
		case 0x0 ... 0x20:
			return true;
		case 0x7f ... 0xa0:
			return true;
		case 0xad:
			return true;
		case 0x600 ... 0x605:
			return true;
		case 0x61c:
			return true;
		case 0x6dd:
			return true;
		case 0x70f:
			return true;
		case 0x8e2:
			return true;
		case 0x1680:
			return true;
		case 0x180e:
			return true;
		case 0x2000 ... 0x200f:
			return true;
		case 0x2028 ... 0x202f:
			return true;
		case 0x205f ... 0x2064:
			return true;
		case 0x2066 ... 0x206f:
			return true;
		case 0x3000:
			return true;
		case 0xd800 ... 0xf8ff:
			return true;
		case 0xfeff:
			return true;
		case 0xfff9 ... 0xfffb:
			return true;
		case 0x110bd:
			return true;
		case 0x110cd:
			return true;
		case 0x13430 ... 0x13438:
			return true;
		case 0x1bca0 ... 0x1bca3:
			return true;
		case 0x1d173 ... 0x1d17a:
			return true;
		case 0xe0001:
			return true;
		case 0xe0020 ... 0xe007f:
			return true;
		case 0xf0000 ... 0xffffd:
			return true;
		case 0x100000 ... 0x10fffd:
			return true;
	} // }}}

	return false;
}

bool
is_P_category(char_type code) {
	// P category (punctuation) (798 codepoints) {{{
	switch(code) {
		case 0x21 ... 0x23:
			return true;
		case 0x25 ... 0x2a:
			return true;
		case 0x2c ... 0x2f:
			return true;
		case 0x3a ... 0x3b:
			return true;
		case 0x3f ... 0x40:
			return true;
		case 0x5b ... 0x5d:
			return true;
		case 0x5f:
			return true;
		case 0x7b:
			return true;
		case 0x7d:
			return true;
		case 0xa1:
			return true;
		case 0xa7:
			return true;
		case 0xab:
			return true;
		case 0xb6 ... 0xb7:
			return true;
		case 0xbb:
			return true;
		case 0xbf:
			return true;
		case 0x37e:
			return true;
		case 0x387:
			return true;
		case 0x55a ... 0x55f:
			return true;
		case 0x589 ... 0x58a:
			return true;
		case 0x5be:
			return true;
		case 0x5c0:
			return true;
		case 0x5c3:
			return true;
		case 0x5c6:
			return true;
		case 0x5f3 ... 0x5f4:
			return true;
		case 0x609 ... 0x60a:
			return true;
		case 0x60c ... 0x60d:
			return true;
		case 0x61b:
			return true;
		case 0x61e ... 0x61f:
			return true;
		case 0x66a ... 0x66d:
			return true;
		case 0x6d4:
			return true;
		case 0x700 ... 0x70d:
			return true;
		case 0x7f7 ... 0x7f9:
			return true;
		case 0x830 ... 0x83e:
			return true;
		case 0x85e:
			return true;
		case 0x964 ... 0x965:
			return true;
		case 0x970:
			return true;
		case 0x9fd:
			return true;
		case 0xa76:
			return true;
		case 0xaf0:
			return true;
		case 0xc77:
			return true;
		case 0xc84:
			return true;
		case 0xdf4:
			return true;
		case 0xe4f:
			return true;
		case 0xe5a ... 0xe5b:
			return true;
		case 0xf04 ... 0xf12:
			return true;
		case 0xf14:
			return true;
		case 0xf3a ... 0xf3d:
			return true;
		case 0xf85:
			return true;
		case 0xfd0 ... 0xfd4:
			return true;
		case 0xfd9 ... 0xfda:
			return true;
		case 0x104a ... 0x104f:
			return true;
		case 0x10fb:
			return true;
		case 0x1360 ... 0x1368:
			return true;
		case 0x1400:
			return true;
		case 0x166e:
			return true;
		case 0x169b ... 0x169c:
			return true;
		case 0x16eb ... 0x16ed:
			return true;
		case 0x1735 ... 0x1736:
			return true;
		case 0x17d4 ... 0x17d6:
			return true;
		case 0x17d8 ... 0x17da:
			return true;
		case 0x1800 ... 0x180a:
			return true;
		case 0x1944 ... 0x1945:
			return true;
		case 0x1a1e ... 0x1a1f:
			return true;
		case 0x1aa0 ... 0x1aa6:
			return true;
		case 0x1aa8 ... 0x1aad:
			return true;
		case 0x1b5a ... 0x1b60:
			return true;
		case 0x1bfc ... 0x1bff:
			return true;
		case 0x1c3b ... 0x1c3f:
			return true;
		case 0x1c7e ... 0x1c7f:
			return true;
		case 0x1cc0 ... 0x1cc7:
			return true;
		case 0x1cd3:
			return true;
		case 0x2010 ... 0x2027:
			return true;
		case 0x2030 ... 0x2043:
			return true;
		case 0x2045 ... 0x2051:
			return true;
		case 0x2053 ... 0x205e:
			return true;
		case 0x207d ... 0x207e:
			return true;
		case 0x208d ... 0x208e:
			return true;
		case 0x2308 ... 0x230b:
			return true;
		case 0x2329 ... 0x232a:
			return true;
		case 0x2768 ... 0x2775:
			return true;
		case 0x27c5 ... 0x27c6:
			return true;
		case 0x27e6 ... 0x27ef:
			return true;
		case 0x2983 ... 0x2998:
			return true;
		case 0x29d8 ... 0x29db:
			return true;
		case 0x29fc ... 0x29fd:
			return true;
		case 0x2cf9 ... 0x2cfc:
			return true;
		case 0x2cfe ... 0x2cff:
			return true;
		case 0x2d70:
			return true;
		case 0x2e00 ... 0x2e2e:
			return true;
		case 0x2e30 ... 0x2e4f:
			return true;
		case 0x2e52:
			return true;
		case 0x3001 ... 0x3003:
			return true;
		case 0x3008 ... 0x3011:
			return true;
		case 0x3014 ... 0x301f:
			return true;
		case 0x3030:
			return true;
		case 0x303d:
			return true;
		case 0x30a0:
			return true;
		case 0x30fb:
			return true;
		case 0xa4fe ... 0xa4ff:
			return true;
		case 0xa60d ... 0xa60f:
			return true;
		case 0xa673:
			return true;
		case 0xa67e:
			return true;
		case 0xa6f2 ... 0xa6f7:
			return true;
		case 0xa874 ... 0xa877:
			return true;
		case 0xa8ce ... 0xa8cf:
			return true;
		case 0xa8f8 ... 0xa8fa:
			return true;
		case 0xa8fc:
			return true;
		case 0xa92e ... 0xa92f:
			return true;
		case 0xa95f:
			return true;
		case 0xa9c1 ... 0xa9cd:
			return true;
		case 0xa9de ... 0xa9df:
			return true;
		case 0xaa5c ... 0xaa5f:
			return true;
		case 0xaade ... 0xaadf:
			return true;
		case 0xaaf0 ... 0xaaf1:
			return true;
		case 0xabeb:
			return true;
		case 0xfd3e ... 0xfd3f:
			return true;
		case 0xfe10 ... 0xfe19:
			return true;
		case 0xfe30 ... 0xfe52:
			return true;
		case 0xfe54 ... 0xfe61:
			return true;
		case 0xfe63:
			return true;
		case 0xfe68:
			return true;
		case 0xfe6a ... 0xfe6b:
			return true;
		case 0xff01 ... 0xff03:
			return true;
		case 0xff05 ... 0xff0a:
			return true;
		case 0xff0c ... 0xff0f:
			return true;
		case 0xff1a ... 0xff1b:
			return true;
		case 0xff1f ... 0xff20:
			return true;
		case 0xff3b ... 0xff3d:
			return true;
		case 0xff3f:
			return true;
		case 0xff5b:
			return true;
		case 0xff5d:
			return true;
		case 0xff5f ... 0xff65:
			return true;
		case 0x10100 ... 0x10102:
			return true;
		case 0x1039f:
			return true;
		case 0x103d0:
			return true;
		case 0x1056f:
			return true;
		case 0x10857:
			return true;
		case 0x1091f:
			return true;
		case 0x1093f:
			return true;
		case 0x10a50 ... 0x10a58:
			return true;
		case 0x10a7f:
			return true;
		case 0x10af0 ... 0x10af6:
			return true;
		case 0x10b39 ... 0x10b3f:
			return true;
		case 0x10b99 ... 0x10b9c:
			return true;
		case 0x10ead:
			return true;
		case 0x10f55 ... 0x10f59:
			return true;
		case 0x11047 ... 0x1104d:
			return true;
		case 0x110bb ... 0x110bc:
			return true;
		case 0x110be ... 0x110c1:
			return true;
		case 0x11140 ... 0x11143:
			return true;
		case 0x11174 ... 0x11175:
			return true;
		case 0x111c5 ... 0x111c8:
			return true;
		case 0x111cd:
			return true;
		case 0x111db:
			return true;
		case 0x111dd ... 0x111df:
			return true;
		case 0x11238 ... 0x1123d:
			return true;
		case 0x112a9:
			return true;
		case 0x1144b ... 0x1144f:
			return true;
		case 0x1145a ... 0x1145b:
			return true;
		case 0x1145d:
			return true;
		case 0x114c6:
			return true;
		case 0x115c1 ... 0x115d7:
			return true;
		case 0x11641 ... 0x11643:
			return true;
		case 0x11660 ... 0x1166c:
			return true;
		case 0x1173c ... 0x1173e:
			return true;
		case 0x1183b:
			return true;
		case 0x11944 ... 0x11946:
			return true;
		case 0x119e2:
			return true;
		case 0x11a3f ... 0x11a46:
			return true;
		case 0x11a9a ... 0x11a9c:
			return true;
		case 0x11a9e ... 0x11aa2:
			return true;
		case 0x11c41 ... 0x11c45:
			return true;
		case 0x11c70 ... 0x11c71:
			return true;
		case 0x11ef7 ... 0x11ef8:
			return true;
		case 0x11fff:
			return true;
		case 0x12470 ... 0x12474:
			return true;
		case 0x16a6e ... 0x16a6f:
			return true;
		case 0x16af5:
			return true;
		case 0x16b37 ... 0x16b3b:
			return true;
		case 0x16b44:
			return true;
		case 0x16e97 ... 0x16e9a:
			return true;
		case 0x16fe2:
			return true;
		case 0x1bc9f:
			return true;
		case 0x1da87 ... 0x1da8b:
			return true;
		case 0x1e95e ... 0x1e95f:
			return true;
	} // }}}

	return false;
}

char_type codepoint_for_mark(combining_type m) {
	static char_type map[2328] = { 0, 768, 769, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 780, 781, 782, 783, 784, 785, 786, 787, 788, 789, 790, 791, 792, 793, 794, 795, 796, 797, 798, 799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809, 810, 811, 812, 813, 814, 815, 816, 817, 818, 819, 820, 821, 822, 823, 824, 825, 826, 827, 828, 829, 830, 831, 832, 833, 834, 835, 836, 837, 838, 839, 840, 841, 842, 843, 844, 845, 846, 847, 848, 849, 850, 851, 852, 853, 854, 855, 856, 857, 858, 859, 860, 861, 862, 863, 864, 865, 866, 867, 868, 869, 870, 871, 872, 873, 874, 875, 876, 877, 878, 879, 1155, 1156, 1157, 1158, 1159, 1160, 1161, 1425, 1426, 1427, 1428, 1429, 1430, 1431, 1432, 1433, 1434, 1435, 1436, 1437, 1438, 1439, 1440, 1441, 1442, 1443, 1444, 1445, 1446, 1447, 1448, 1449, 1450, 1451, 1452, 1453, 1454, 1455, 1456, 1457, 1458, 1459, 1460, 1461, 1462, 1463, 1464, 1465, 1466, 1467, 1468, 1469, 1471, 1473, 1474, 1476, 1477, 1479, 1552, 1553, 1554, 1555, 1556, 1557, 1558, 1559, 1560, 1561, 1562, 1611, 1612, 1613, 1614, 1615, 1616, 1617, 1618, 1619, 1620, 1621, 1622, 1623, 1624, 1625, 1626, 1627, 1628, 1629, 1630, 1631, 1648, 1750, 1751, 1752, 1753, 1754, 1755, 1756, 1759, 1760, 1761, 1762, 1763, 1764, 1767, 1768, 1770, 1771, 1772, 1773, 1809, 1840, 1841, 1842, 1843, 1844, 1845, 1846, 1847, 1848, 1849, 1850, 1851, 1852, 1853, 1854, 1855, 1856, 1857, 1858, 1859, 1860, 1861, 1862, 1863, 1864, 1865, 1866, 1958, 1959, 1960, 1961, 1962, 1963, 1964, 1965, 1966, 1967, 1968, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2045, 2070, 2071, 2072, 2073, 2075, 2076, 2077, 2078, 2079, 2080, 2081, 2082, 2083, 2085, 2086, 2087, 2089, 2090, 2091, 2092, 2093, 2137, 2138, 2139, 2259, 2260, 2261, 2262, 2263, 2264, 2265, 2266, 2267, 2268, 2269, 2270, 2271, 2272, 2273, 2275, 2276, 2277, 2278, 2279, 2280, 2281, 2282, 2283, 2284, 2285, 2286, 2287, 2288, 2289, 2290, 2291, 2292, 2293, 2294, 2295, 2296, 2297, 2298, 2299, 2300, 2301, 2302, 2303, 2304, 2305, 2306, 2307, 2362, 2363, 2364, 2366, 2367, 2368, 2369, 2370, 2371, 2372, 2373, 2374, 2375, 2376, 2377, 2378, 2379, 2380, 2381, 2382, 2383, 2385, 2386, 2387, 2388, 2389, 2390, 2391, 2402, 2403, 2433, 2434, 2435, 2492, 2494, 2495, 2496, 2497, 2498, 2499, 2500, 2503, 2504, 2507, 2508, 2509, 2519, 2530, 2531, 2558, 2561, 2562, 2563, 2620, 2622, 2623, 2624, 2625, 2626, 2631, 2632, 2635, 2636, 2637, 2641, 2672, 2673, 2677, 2689, 2690, 2691, 2748, 2750, 2751, 2752, 2753, 2754, 2755, 2756, 2757, 2759, 2760, 2761, 2763, 2764, 2765, 2786, 2787, 2810, 2811, 2812, 2813, 2814, 2815, 2817, 2818, 2819, 2876, 2878, 2879, 2880, 2881, 2882, 2883, 2884, 2887, 2888, 2891, 2892, 2893, 2901, 2902, 2903, 2914, 2915, 2946, 3006, 3007, 3008, 3009, 3010, 3014, 3015, 3016, 3018, 3019, 3020, 3021, 3031, 3072, 3073, 3074, 3075, 3076, 3134, 3135, 3136, 3137, 3138, 3139, 3140, 3142, 3143, 3144, 3146, 3147, 3148, 3149, 3157, 3158, 3170, 3171, 3201, 3202, 3203, 3260, 3262, 3263, 3264, 3265, 3266, 3267, 3268, 3270, 3271, 3272, 3274, 3275, 3276, 3277, 3285, 3286, 3298, 3299, 3328, 3329, 3330, 3331, 3387, 3388, 3390, 3391, 3392, 3393, 3394, 3395, 3396, 3398, 3399, 3400, 3402, 3403, 3404, 3405, 3415, 3426, 3427, 3457, 3458, 3459, 3530, 3535, 3536, 3537, 3538, 3539, 3540, 3542, 3544, 3545, 3546, 3547, 3548, 3549, 3550, 3551, 3570, 3571, 3633, 3636, 3637, 3638, 3639, 3640, 3641, 3642, 3655, 3656, 3657, 3658, 3659, 3660, 3661, 3662, 3761, 3764, 3765, 3766, 3767, 3768, 3769, 3770, 3771, 3772, 3784, 3785, 3786, 3787, 3788, 3789, 3864, 3865, 3893, 3895, 3897, 3902, 3903, 3953, 3954, 3955, 3956, 3957, 3958, 3959, 3960, 3961, 3962, 3963, 3964, 3965, 3966, 3967, 3968, 3969, 3970, 3971, 3972, 3974, 3975, 3981, 3982, 3983, 3984, 3985, 3986, 3987, 3988, 3989, 3990, 3991, 3993, 3994, 3995, 3996, 3997, 3998, 3999, 4000, 4001, 4002, 4003, 4004, 4005, 4006, 4007, 4008, 4009, 4010, 4011, 4012, 4013, 4014, 4015, 4016, 4017, 4018, 4019, 4020, 4021, 4022, 4023, 4024, 4025, 4026, 4027, 4028, 4038, 4139, 4140, 4141, 4142, 4143, 4144, 4145, 4146, 4147, 4148, 4149, 4150, 4151, 4152, 4153, 4154, 4155, 4156, 4157, 4158, 4182, 4183, 4184, 4185, 4190, 4191, 4192, 4194, 4195, 4196, 4199, 4200, 4201, 4202, 4203, 4204, 4205, 4209, 4210, 4211, 4212, 4226, 4227, 4228, 4229, 4230, 4231, 4232, 4233, 4234, 4235, 4236, 4237, 4239, 4250, 4251, 4252, 4253, 4957, 4958, 4959, 5906, 5907, 5908, 5938, 5939, 5940, 5970, 5971, 6002, 6003, 6068, 6069, 6070, 6071, 6072, 6073, 6074, 6075, 6076, 6077, 6078, 6079, 6080, 6081, 6082, 6083, 6084, 6085, 6086, 6087, 6088, 6089, 6090, 6091, 6092, 6093, 6094, 6095, 6096, 6097, 6098, 6099, 6109, 6155, 6156, 6157, 6277, 6278, 6313, 6432, 6433, 6434, 6435, 6436, 6437, 6438, 6439, 6440, 6441, 6442, 6443, 6448, 6449, 6450, 6451, 6452, 6453, 6454, 6455, 6456, 6457, 6458, 6459, 6679, 6680, 6681, 6682, 6683, 6741, 6742, 6743, 6744, 6745, 6746, 6747, 6748, 6749, 6750, 6752, 6753, 6754, 6755, 6756, 6757, 6758, 6759, 6760, 6761, 6762, 6763, 6764, 6765, 6766, 6767, 6768, 6769, 6770, 6771, 6772, 6773, 6774, 6775, 6776, 6777, 6778, 6779, 6780, 6783, 6832, 6833, 6834, 6835, 6836, 6837, 6838, 6839, 6840, 6841, 6842, 6843, 6844, 6845, 6846, 6847, 6848, 6912, 6913, 6914, 6915, 6916, 6964, 6965, 6966, 6967, 6968, 6969, 6970, 6971, 6972, 6973, 6974, 6975, 6976, 6977, 6978, 6979, 6980, 7019, 7020, 7021, 7022, 7023, 7024, 7025, 7026, 7027, 7040, 7041, 7042, 7073, 7074, 7075, 7076, 7077, 7078, 7079, 7080, 7081, 7082, 7083, 7084, 7085, 7142, 7143, 7144, 7145, 7146, 7147, 7148, 7149, 7150, 7151, 7152, 7153, 7154, 7155, 7204, 7205, 7206, 7207, 7208, 7209, 7210, 7211, 7212, 7213, 7214, 7215, 7216, 7217, 7218, 7219, 7220, 7221, 7222, 7223, 7376, 7377, 7378, 7380, 7381, 7382, 7383, 7384, 7385, 7386, 7387, 7388, 7389, 7390, 7391, 7392, 7393, 7394, 7395, 7396, 7397, 7398, 7399, 7400, 7405, 7412, 7415, 7416, 7417, 7616, 7617, 7618, 7619, 7620, 7621, 7622, 7623, 7624, 7625, 7626, 7627, 7628, 7629, 7630, 7631, 7632, 7633, 7634, 7635, 7636, 7637, 7638, 7639, 7640, 7641, 7642, 7643, 7644, 7645, 7646, 7647, 7648, 7649, 7650, 7651, 7652, 7653, 7654, 7655, 7656, 7657, 7658, 7659, 7660, 7661, 7662, 7663, 7664, 7665, 7666, 7667, 7668, 7669, 7670, 7671, 7672, 7673, 7675, 7676, 7677, 7678, 7679, 8205, 8400, 8401, 8402, 8403, 8404, 8405, 8406, 8407, 8408, 8409, 8410, 8411, 8412, 8413, 8414, 8415, 8416, 8417, 8418, 8419, 8420, 8421, 8422, 8423, 8424, 8425, 8426, 8427, 8428, 8429, 8430, 8431, 8432, 11503, 11504, 11505, 11647, 11744, 11745, 11746, 11747, 11748, 11749, 11750, 11751, 11752, 11753, 11754, 11755, 11756, 11757, 11758, 11759, 11760, 11761, 11762, 11763, 11764, 11765, 11766, 11767, 11768, 11769, 11770, 11771, 11772, 11773, 11774, 11775, 12330, 12331, 12332, 12333, 12334, 12335, 12441, 12442, 42607, 42608, 42609, 42610, 42612, 42613, 42614, 42615, 42616, 42617, 42618, 42619, 42620, 42621, 42654, 42655, 42736, 42737, 43010, 43014, 43019, 43043, 43044, 43045, 43046, 43047, 43052, 43136, 43137, 43188, 43189, 43190, 43191, 43192, 43193, 43194, 43195, 43196, 43197, 43198, 43199, 43200, 43201, 43202, 43203, 43204, 43205, 43232, 43233, 43234, 43235, 43236, 43237, 43238, 43239, 43240, 43241, 43242, 43243, 43244, 43245, 43246, 43247, 43248, 43249, 43263, 43302, 43303, 43304, 43305, 43306, 43307, 43308, 43309, 43335, 43336, 43337, 43338, 43339, 43340, 43341, 43342, 43343, 43344, 43345, 43346, 43347, 43392, 43393, 43394, 43395, 43443, 43444, 43445, 43446, 43447, 43448, 43449, 43450, 43451, 43452, 43453, 43454, 43455, 43456, 43493, 43561, 43562, 43563, 43564, 43565, 43566, 43567, 43568, 43569, 43570, 43571, 43572, 43573, 43574, 43587, 43596, 43597, 43643, 43644, 43645, 43696, 43698, 43699, 43700, 43703, 43704, 43710, 43711, 43713, 43755, 43756, 43757, 43758, 43759, 43765, 43766, 44003, 44004, 44005, 44006, 44007, 44008, 44009, 44010, 44012, 44013, 64286, 65024, 65025, 65026, 65027, 65028, 65029, 65030, 65031, 65032, 65033, 65034, 65035, 65036, 65037, 65038, 65039, 65056, 65057, 65058, 65059, 65060, 65061, 65062, 65063, 65064, 65065, 65066, 65067, 65068, 65069, 65070, 65071, 66045, 66272, 66422, 66423, 66424, 66425, 66426, 68097, 68098, 68099, 68101, 68102, 68108, 68109, 68110, 68111, 68152, 68153, 68154, 68159, 68325, 68326, 68900, 68901, 68902, 68903, 69291, 69292, 69446, 69447, 69448, 69449, 69450, 69451, 69452, 69453, 69454, 69455, 69456, 69632, 69633, 69634, 69688, 69689, 69690, 69691, 69692, 69693, 69694, 69695, 69696, 69697, 69698, 69699, 69700, 69701, 69702, 69759, 69760, 69761, 69762, 69808, 69809, 69810, 69811, 69812, 69813, 69814, 69815, 69816, 69817, 69818, 69888, 69889, 69890, 69927, 69928, 69929, 69930, 69931, 69932, 69933, 69934, 69935, 69936, 69937, 69938, 69939, 69940, 69957, 69958, 70003, 70016, 70017, 70018, 70067, 70068, 70069, 70070, 70071, 70072, 70073, 70074, 70075, 70076, 70077, 70078, 70079, 70080, 70089, 70090, 70091, 70092, 70094, 70095, 70188, 70189, 70190, 70191, 70192, 70193, 70194, 70195, 70196, 70197, 70198, 70199, 70206, 70367, 70368, 70369, 70370, 70371, 70372, 70373, 70374, 70375, 70376, 70377, 70378, 70400, 70401, 70402, 70403, 70459, 70460, 70462, 70463, 70464, 70465, 70466, 70467, 70468, 70471, 70472, 70475, 70476, 70477, 70487, 70498, 70499, 70502, 70503, 70504, 70505, 70506, 70507, 70508, 70512, 70513, 70514, 70515, 70516, 70709, 70710, 70711, 70712, 70713, 70714, 70715, 70716, 70717, 70718, 70719, 70720, 70721, 70722, 70723, 70724, 70725, 70726, 70750, 70832, 70833, 70834, 70835, 70836, 70837, 70838, 70839, 70840, 70841, 70842, 70843, 70844, 70845, 70846, 70847, 70848, 70849, 70850, 70851, 71087, 71088, 71089, 71090, 71091, 71092, 71093, 71096, 71097, 71098, 71099, 71100, 71101, 71102, 71103, 71104, 71132, 71133, 71216, 71217, 71218, 71219, 71220, 71221, 71222, 71223, 71224, 71225, 71226, 71227, 71228, 71229, 71230, 71231, 71232, 71339, 71340, 71341, 71342, 71343, 71344, 71345, 71346, 71347, 71348, 71349, 71350, 71351, 71453, 71454, 71455, 71456, 71457, 71458, 71459, 71460, 71461, 71462, 71463, 71464, 71465, 71466, 71467, 71724, 71725, 71726, 71727, 71728, 71729, 71730, 71731, 71732, 71733, 71734, 71735, 71736, 71737, 71738, 71984, 71985, 71986, 71987, 71988, 71989, 71991, 71992, 71995, 71996, 71997, 71998, 72000, 72002, 72003, 72145, 72146, 72147, 72148, 72149, 72150, 72151, 72154, 72155, 72156, 72157, 72158, 72159, 72160, 72164, 72193, 72194, 72195, 72196, 72197, 72198, 72199, 72200, 72201, 72202, 72243, 72244, 72245, 72246, 72247, 72248, 72249, 72251, 72252, 72253, 72254, 72263, 72273, 72274, 72275, 72276, 72277, 72278, 72279, 72280, 72281, 72282, 72283, 72330, 72331, 72332, 72333, 72334, 72335, 72336, 72337, 72338, 72339, 72340, 72341, 72342, 72343, 72344, 72345, 72751, 72752, 72753, 72754, 72755, 72756, 72757, 72758, 72760, 72761, 72762, 72763, 72764, 72765, 72766, 72767, 72850, 72851, 72852, 72853, 72854, 72855, 72856, 72857, 72858, 72859, 72860, 72861, 72862, 72863, 72864, 72865, 72866, 72867, 72868, 72869, 72870, 72871, 72873, 72874, 72875, 72876, 72877, 72878, 72879, 72880, 72881, 72882, 72883, 72884, 72885, 72886, 73009, 73010, 73011, 73012, 73013, 73014, 73018, 73020, 73021, 73023, 73024, 73025, 73026, 73027, 73028, 73029, 73031, 73098, 73099, 73100, 73101, 73102, 73104, 73105, 73107, 73108, 73109, 73110, 73111, 73459, 73460, 73461, 73462, 92912, 92913, 92914, 92915, 92916, 92976, 92977, 92978, 92979, 92980, 92981, 92982, 94031, 94033, 94034, 94035, 94036, 94037, 94038, 94039, 94040, 94041, 94042, 94043, 94044, 94045, 94046, 94047, 94048, 94049, 94050, 94051, 94052, 94053, 94054, 94055, 94056, 94057, 94058, 94059, 94060, 94061, 94062, 94063, 94064, 94065, 94066, 94067, 94068, 94069, 94070, 94071, 94072, 94073, 94074, 94075, 94076, 94077, 94078, 94079, 94080, 94081, 94082, 94083, 94084, 94085, 94086, 94087, 94095, 94096, 94097, 94098, 94180, 94192, 94193, 113821, 113822, 119141, 119142, 119143, 119144, 119145, 119149, 119150, 119151, 119152, 119153, 119154, 119163, 119164, 119165, 119166, 119167, 119168, 119169, 119170, 119173, 119174, 119175, 119176, 119177, 119178, 119179, 119210, 119211, 119212, 119213, 119362, 119363, 119364, 121344, 121345, 121346, 121347, 121348, 121349, 121350, 121351, 121352, 121353, 121354, 121355, 121356, 121357, 121358, 121359, 121360, 121361, 121362, 121363, 121364, 121365, 121366, 121367, 121368, 121369, 121370, 121371, 121372, 121373, 121374, 121375, 121376, 121377, 121378, 121379, 121380, 121381, 121382, 121383, 121384, 121385, 121386, 121387, 121388, 121389, 121390, 121391, 121392, 121393, 121394, 121395, 121396, 121397, 121398, 121403, 121404, 121405, 121406, 121407, 121408, 121409, 121410, 121411, 121412, 121413, 121414, 121415, 121416, 121417, 121418, 121419, 121420, 121421, 121422, 121423, 121424, 121425, 121426, 121427, 121428, 121429, 121430, 121431, 121432, 121433, 121434, 121435, 121436, 121437, 121438, 121439, 121440, 121441, 121442, 121443, 121444, 121445, 121446, 121447, 121448, 121449, 121450, 121451, 121452, 121461, 121476, 121499, 121500, 121501, 121502, 121503, 121505, 121506, 121507, 121508, 121509, 121510, 121511, 121512, 121513, 121514, 121515, 121516, 121517, 121518, 121519, 122880, 122881, 122882, 122883, 122884, 122885, 122886, 122888, 122889, 122890, 122891, 122892, 122893, 122894, 122895, 122896, 122897, 122898, 122899, 122900, 122901, 122902, 122903, 122904, 122907, 122908, 122909, 122910, 122911, 122912, 122913, 122915, 122916, 122918, 122919, 122920, 122921, 122922, 123184, 123185, 123186, 123187, 123188, 123189, 123190, 123628, 123629, 123630, 123631, 125136, 125137, 125138, 125139, 125140, 125141, 125142, 125252, 125253, 125254, 125255, 125256, 125257, 125258, 127462, 127463, 127464, 127465, 127466, 127467, 127468, 127469, 127470, 127471, 127472, 127473, 127474, 127475, 127476, 127477, 127478, 127479, 127480, 127481, 127482, 127483, 127484, 127485, 127486, 127487, 127995, 127996, 127997, 127998, 127999, 917760, 917761, 917762, 917763, 917764, 917765, 917766, 917767, 917768, 917769, 917770, 917771, 917772, 917773, 917774, 917775, 917776, 917777, 917778, 917779, 917780, 917781, 917782, 917783, 917784, 917785, 917786, 917787, 917788, 917789, 917790, 917791, 917792, 917793, 917794, 917795, 917796, 917797, 917798, 917799, 917800, 917801, 917802, 917803, 917804, 917805, 917806, 917807, 917808, 917809, 917810, 917811, 917812, 917813, 917814, 917815, 917816, 917817, 917818, 917819, 917820, 917821, 917822, 917823, 917824, 917825, 917826, 917827, 917828, 917829, 917830, 917831, 917832, 917833, 917834, 917835, 917836, 917837, 917838, 917839, 917840, 917841, 917842, 917843, 917844, 917845, 917846, 917847, 917848, 917849, 917850, 917851, 917852, 917853, 917854, 917855, 917856, 917857, 917858, 917859, 917860, 917861, 917862, 917863, 917864, 917865, 917866, 917867, 917868, 917869, 917870, 917871, 917872, 917873, 917874, 917875, 917876, 917877, 917878, 917879, 917880, 917881, 917882, 917883, 917884, 917885, 917886, 917887, 917888, 917889, 917890, 917891, 917892, 917893, 917894, 917895, 917896, 917897, 917898, 917899, 917900, 917901, 917902, 917903, 917904, 917905, 917906, 917907, 917908, 917909, 917910, 917911, 917912, 917913, 917914, 917915, 917916, 917917, 917918, 917919, 917920, 917921, 917922, 917923, 917924, 917925, 917926, 917927, 917928, 917929, 917930, 917931, 917932, 917933, 917934, 917935, 917936, 917937, 917938, 917939, 917940, 917941, 917942, 917943, 917944, 917945, 917946, 917947, 917948, 917949, 917950, 917951, 917952, 917953, 917954, 917955, 917956, 917957, 917958, 917959, 917960, 917961, 917962, 917963, 917964, 917965, 917966, 917967, 917968, 917969, 917970, 917971, 917972, 917973, 917974, 917975, 917976, 917977, 917978, 917979, 917980, 917981, 917982, 917983, 917984, 917985, 917986, 917987, 917988, 917989, 917990, 917991, 917992, 917993, 917994, 917995, 917996, 917997, 917998, 917999 }; // {{{ mapping }}}
	if (m < arraysz(map)) return map[m];
	return 0;
}

combining_type mark_for_codepoint(char_type c) {
	switch(c) { // {{{
		case 0: return 0;
		case 768: case 769: case 770: case 771: case 772: case 773: case 774: case 775: case 776: case 777: case 778: case 779: case 780: case 781: case 782: case 783: case 784: case 785: case 786: case 787: case 788: case 789: case 790: case 791: case 792: case 793: case 794: case 795: case 796: case 797: case 798: case 799: case 800: case 801: case 802: case 803: case 804: case 805: case 806: case 807: case 808: case 809: case 810: case 811: case 812: case 813: case 814: case 815: case 816: case 817: case 818: case 819: case 820: case 821: case 822: case 823: case 824: case 825: case 826: case 827: case 828: case 829: case 830: case 831: case 832: case 833: case 834: case 835: case 836: case 837: case 838: case 839: case 840: case 841: case 842: case 843: case 844: case 845: case 846: case 847: case 848: case 849: case 850: case 851: case 852: case 853: case 854: case 855: case 856: case 857: case 858: case 859: case 860: case 861: case 862: case 863: case 864: case 865: case 866: case 867: case 868: case 869: case 870: case 871: case 872: case 873: case 874: case 875: case 876: case 877: case 878: case 879: return 1 + c - 768;
		case 1155: case 1156: case 1157: case 1158: case 1159: case 1160: case 1161: return 113 + c - 1155;
		case 1425: case 1426: case 1427: case 1428: case 1429: case 1430: case 1431: case 1432: case 1433: case 1434: case 1435: case 1436: case 1437: case 1438: case 1439: case 1440: case 1441: case 1442: case 1443: case 1444: case 1445: case 1446: case 1447: case 1448: case 1449: case 1450: case 1451: case 1452: case 1453: case 1454: case 1455: case 1456: case 1457: case 1458: case 1459: case 1460: case 1461: case 1462: case 1463: case 1464: case 1465: case 1466: case 1467: case 1468: case 1469: return 120 + c - 1425;
		case 1471: return 165;
		case 1473: case 1474: return 166 + c - 1473;
		case 1476: case 1477: return 168 + c - 1476;
		case 1479: return 170;
		case 1552: case 1553: case 1554: case 1555: case 1556: case 1557: case 1558: case 1559: case 1560: case 1561: case 1562: return 171 + c - 1552;
		case 1611: case 1612: case 1613: case 1614: case 1615: case 1616: case 1617: case 1618: case 1619: case 1620: case 1621: case 1622: case 1623: case 1624: case 1625: case 1626: case 1627: case 1628: case 1629: case 1630: case 1631: return 182 + c - 1611;
		case 1648: return 203;
		case 1750: case 1751: case 1752: case 1753: case 1754: case 1755: case 1756: return 204 + c - 1750;
		case 1759: case 1760: case 1761: case 1762: case 1763: case 1764: return 211 + c - 1759;
		case 1767: case 1768: return 217 + c - 1767;
		case 1770: case 1771: case 1772: case 1773: return 219 + c - 1770;
		case 1809: return 223;
		case 1840: case 1841: case 1842: case 1843: case 1844: case 1845: case 1846: case 1847: case 1848: case 1849: case 1850: case 1851: case 1852: case 1853: case 1854: case 1855: case 1856: case 1857: case 1858: case 1859: case 1860: case 1861: case 1862: case 1863: case 1864: case 1865: case 1866: return 224 + c - 1840;
		case 1958: case 1959: case 1960: case 1961: case 1962: case 1963: case 1964: case 1965: case 1966: case 1967: case 1968: return 251 + c - 1958;
		case 2027: case 2028: case 2029: case 2030: case 2031: case 2032: case 2033: case 2034: case 2035: return 262 + c - 2027;
		case 2045: return 271;
		case 2070: case 2071: case 2072: case 2073: return 272 + c - 2070;
		case 2075: case 2076: case 2077: case 2078: case 2079: case 2080: case 2081: case 2082: case 2083: return 276 + c - 2075;
		case 2085: case 2086: case 2087: return 285 + c - 2085;
		case 2089: case 2090: case 2091: case 2092: case 2093: return 288 + c - 2089;
		case 2137: case 2138: case 2139: return 293 + c - 2137;
		case 2259: case 2260: case 2261: case 2262: case 2263: case 2264: case 2265: case 2266: case 2267: case 2268: case 2269: case 2270: case 2271: case 2272: case 2273: return 296 + c - 2259;
		case 2275: case 2276: case 2277: case 2278: case 2279: case 2280: case 2281: case 2282: case 2283: case 2284: case 2285: case 2286: case 2287: case 2288: case 2289: case 2290: case 2291: case 2292: case 2293: case 2294: case 2295: case 2296: case 2297: case 2298: case 2299: case 2300: case 2301: case 2302: case 2303: case 2304: case 2305: case 2306: case 2307: return 311 + c - 2275;
		case 2362: case 2363: case 2364: return 344 + c - 2362;
		case 2366: case 2367: case 2368: case 2369: case 2370: case 2371: case 2372: case 2373: case 2374: case 2375: case 2376: case 2377: case 2378: case 2379: case 2380: case 2381: case 2382: case 2383: return 347 + c - 2366;
		case 2385: case 2386: case 2387: case 2388: case 2389: case 2390: case 2391: return 365 + c - 2385;
		case 2402: case 2403: return 372 + c - 2402;
		case 2433: case 2434: case 2435: return 374 + c - 2433;
		case 2492: return 377;
		case 2494: case 2495: case 2496: case 2497: case 2498: case 2499: case 2500: return 378 + c - 2494;
		case 2503: case 2504: return 385 + c - 2503;
		case 2507: case 2508: case 2509: return 387 + c - 2507;
		case 2519: return 390;
		case 2530: case 2531: return 391 + c - 2530;
		case 2558: return 393;
		case 2561: case 2562: case 2563: return 394 + c - 2561;
		case 2620: return 397;
		case 2622: case 2623: case 2624: case 2625: case 2626: return 398 + c - 2622;
		case 2631: case 2632: return 403 + c - 2631;
		case 2635: case 2636: case 2637: return 405 + c - 2635;
		case 2641: return 408;
		case 2672: case 2673: return 409 + c - 2672;
		case 2677: return 411;
		case 2689: case 2690: case 2691: return 412 + c - 2689;
		case 2748: return 415;
		case 2750: case 2751: case 2752: case 2753: case 2754: case 2755: case 2756: case 2757: return 416 + c - 2750;
		case 2759: case 2760: case 2761: return 424 + c - 2759;
		case 2763: case 2764: case 2765: return 427 + c - 2763;
		case 2786: case 2787: return 430 + c - 2786;
		case 2810: case 2811: case 2812: case 2813: case 2814: case 2815: return 432 + c - 2810;
		case 2817: case 2818: case 2819: return 438 + c - 2817;
		case 2876: return 441;
		case 2878: case 2879: case 2880: case 2881: case 2882: case 2883: case 2884: return 442 + c - 2878;
		case 2887: case 2888: return 449 + c - 2887;
		case 2891: case 2892: case 2893: return 451 + c - 2891;
		case 2901: case 2902: case 2903: return 454 + c - 2901;
		case 2914: case 2915: return 457 + c - 2914;
		case 2946: return 459;
		case 3006: case 3007: case 3008: case 3009: case 3010: return 460 + c - 3006;
		case 3014: case 3015: case 3016: return 465 + c - 3014;
		case 3018: case 3019: case 3020: case 3021: return 468 + c - 3018;
		case 3031: return 472;
		case 3072: case 3073: case 3074: case 3075: case 3076: return 473 + c - 3072;
		case 3134: case 3135: case 3136: case 3137: case 3138: case 3139: case 3140: return 478 + c - 3134;
		case 3142: case 3143: case 3144: return 485 + c - 3142;
		case 3146: case 3147: case 3148: case 3149: return 488 + c - 3146;
		case 3157: case 3158: return 492 + c - 3157;
		case 3170: case 3171: return 494 + c - 3170;
		case 3201: case 3202: case 3203: return 496 + c - 3201;
		case 3260: return 499;
		case 3262: case 3263: case 3264: case 3265: case 3266: case 3267: case 3268: return 500 + c - 3262;
		case 3270: case 3271: case 3272: return 507 + c - 3270;
		case 3274: case 3275: case 3276: case 3277: return 510 + c - 3274;
		case 3285: case 3286: return 514 + c - 3285;
		case 3298: case 3299: return 516 + c - 3298;
		case 3328: case 3329: case 3330: case 3331: return 518 + c - 3328;
		case 3387: case 3388: return 522 + c - 3387;
		case 3390: case 3391: case 3392: case 3393: case 3394: case 3395: case 3396: return 524 + c - 3390;
		case 3398: case 3399: case 3400: return 531 + c - 3398;
		case 3402: case 3403: case 3404: case 3405: return 534 + c - 3402;
		case 3415: return 538;
		case 3426: case 3427: return 539 + c - 3426;
		case 3457: case 3458: case 3459: return 541 + c - 3457;
		case 3530: return 544;
		case 3535: case 3536: case 3537: case 3538: case 3539: case 3540: return 545 + c - 3535;
		case 3542: return 551;
		case 3544: case 3545: case 3546: case 3547: case 3548: case 3549: case 3550: case 3551: return 552 + c - 3544;
		case 3570: case 3571: return 560 + c - 3570;
		case 3633: return 562;
		case 3636: case 3637: case 3638: case 3639: case 3640: case 3641: case 3642: return 563 + c - 3636;
		case 3655: case 3656: case 3657: case 3658: case 3659: case 3660: case 3661: case 3662: return 570 + c - 3655;
		case 3761: return 578;
		case 3764: case 3765: case 3766: case 3767: case 3768: case 3769: case 3770: case 3771: case 3772: return 579 + c - 3764;
		case 3784: case 3785: case 3786: case 3787: case 3788: case 3789: return 588 + c - 3784;
		case 3864: case 3865: return 594 + c - 3864;
		case 3893: return 596;
		case 3895: return 597;
		case 3897: return 598;
		case 3902: case 3903: return 599 + c - 3902;
		case 3953: case 3954: case 3955: case 3956: case 3957: case 3958: case 3959: case 3960: case 3961: case 3962: case 3963: case 3964: case 3965: case 3966: case 3967: case 3968: case 3969: case 3970: case 3971: case 3972: return 601 + c - 3953;
		case 3974: case 3975: return 621 + c - 3974;
		case 3981: case 3982: case 3983: case 3984: case 3985: case 3986: case 3987: case 3988: case 3989: case 3990: case 3991: return 623 + c - 3981;
		case 3993: case 3994: case 3995: case 3996: case 3997: case 3998: case 3999: case 4000: case 4001: case 4002: case 4003: case 4004: case 4005: case 4006: case 4007: case 4008: case 4009: case 4010: case 4011: case 4012: case 4013: case 4014: case 4015: case 4016: case 4017: case 4018: case 4019: case 4020: case 4021: case 4022: case 4023: case 4024: case 4025: case 4026: case 4027: case 4028: return 634 + c - 3993;
		case 4038: return 670;
		case 4139: case 4140: case 4141: case 4142: case 4143: case 4144: case 4145: case 4146: case 4147: case 4148: case 4149: case 4150: case 4151: case 4152: case 4153: case 4154: case 4155: case 4156: case 4157: case 4158: return 671 + c - 4139;
		case 4182: case 4183: case 4184: case 4185: return 691 + c - 4182;
		case 4190: case 4191: case 4192: return 695 + c - 4190;
		case 4194: case 4195: case 4196: return 698 + c - 4194;
		case 4199: case 4200: case 4201: case 4202: case 4203: case 4204: case 4205: return 701 + c - 4199;
		case 4209: case 4210: case 4211: case 4212: return 708 + c - 4209;
		case 4226: case 4227: case 4228: case 4229: case 4230: case 4231: case 4232: case 4233: case 4234: case 4235: case 4236: case 4237: return 712 + c - 4226;
		case 4239: return 724;
		case 4250: case 4251: case 4252: case 4253: return 725 + c - 4250;
		case 4957: case 4958: case 4959: return 729 + c - 4957;
		case 5906: case 5907: case 5908: return 732 + c - 5906;
		case 5938: case 5939: case 5940: return 735 + c - 5938;
		case 5970: case 5971: return 738 + c - 5970;
		case 6002: case 6003: return 740 + c - 6002;
		case 6068: case 6069: case 6070: case 6071: case 6072: case 6073: case 6074: case 6075: case 6076: case 6077: case 6078: case 6079: case 6080: case 6081: case 6082: case 6083: case 6084: case 6085: case 6086: case 6087: case 6088: case 6089: case 6090: case 6091: case 6092: case 6093: case 6094: case 6095: case 6096: case 6097: case 6098: case 6099: return 742 + c - 6068;
		case 6109: return 774;
		case 6155: case 6156: case 6157: return 775 + c - 6155;
		case 6277: case 6278: return 778 + c - 6277;
		case 6313: return 780;
		case 6432: case 6433: case 6434: case 6435: case 6436: case 6437: case 6438: case 6439: case 6440: case 6441: case 6442: case 6443: return 781 + c - 6432;
		case 6448: case 6449: case 6450: case 6451: case 6452: case 6453: case 6454: case 6455: case 6456: case 6457: case 6458: case 6459: return 793 + c - 6448;
		case 6679: case 6680: case 6681: case 6682: case 6683: return 805 + c - 6679;
		case 6741: case 6742: case 6743: case 6744: case 6745: case 6746: case 6747: case 6748: case 6749: case 6750: return 810 + c - 6741;
		case 6752: case 6753: case 6754: case 6755: case 6756: case 6757: case 6758: case 6759: case 6760: case 6761: case 6762: case 6763: case 6764: case 6765: case 6766: case 6767: case 6768: case 6769: case 6770: case 6771: case 6772: case 6773: case 6774: case 6775: case 6776: case 6777: case 6778: case 6779: case 6780: return 820 + c - 6752;
		case 6783: return 849;
		case 6832: case 6833: case 6834: case 6835: case 6836: case 6837: case 6838: case 6839: case 6840: case 6841: case 6842: case 6843: case 6844: case 6845: case 6846: case 6847: case 6848: return 850 + c - 6832;
		case 6912: case 6913: case 6914: case 6915: case 6916: return 867 + c - 6912;
		case 6964: case 6965: case 6966: case 6967: case 6968: case 6969: case 6970: case 6971: case 6972: case 6973: case 6974: case 6975: case 6976: case 6977: case 6978: case 6979: case 6980: return 872 + c - 6964;
		case 7019: case 7020: case 7021: case 7022: case 7023: case 7024: case 7025: case 7026: case 7027: return 889 + c - 7019;
		case 7040: case 7041: case 7042: return 898 + c - 7040;
		case 7073: case 7074: case 7075: case 7076: case 7077: case 7078: case 7079: case 7080: case 7081: case 7082: case 7083: case 7084: case 7085: return 901 + c - 7073;
		case 7142: case 7143: case 7144: case 7145: case 7146: case 7147: case 7148: case 7149: case 7150: case 7151: case 7152: case 7153: case 7154: case 7155: return 914 + c - 7142;
		case 7204: case 7205: case 7206: case 7207: case 7208: case 7209: case 7210: case 7211: case 7212: case 7213: case 7214: case 7215: case 7216: case 7217: case 7218: case 7219: case 7220: case 7221: case 7222: case 7223: return 928 + c - 7204;
		case 7376: case 7377: case 7378: return 948 + c - 7376;
		case 7380: case 7381: case 7382: case 7383: case 7384: case 7385: case 7386: case 7387: case 7388: case 7389: case 7390: case 7391: case 7392: case 7393: case 7394: case 7395: case 7396: case 7397: case 7398: case 7399: case 7400: return 951 + c - 7380;
		case 7405: return 972;
		case 7412: return 973;
		case 7415: case 7416: case 7417: return 974 + c - 7415;
		case 7616: case 7617: case 7618: case 7619: case 7620: case 7621: case 7622: case 7623: case 7624: case 7625: case 7626: case 7627: case 7628: case 7629: case 7630: case 7631: case 7632: case 7633: case 7634: case 7635: case 7636: case 7637: case 7638: case 7639: case 7640: case 7641: case 7642: case 7643: case 7644: case 7645: case 7646: case 7647: case 7648: case 7649: case 7650: case 7651: case 7652: case 7653: case 7654: case 7655: case 7656: case 7657: case 7658: case 7659: case 7660: case 7661: case 7662: case 7663: case 7664: case 7665: case 7666: case 7667: case 7668: case 7669: case 7670: case 7671: case 7672: case 7673: return 977 + c - 7616;
		case 7675: case 7676: case 7677: case 7678: case 7679: return 1035 + c - 7675;
		case 8205: return 1040;
		case 8400: case 8401: case 8402: case 8403: case 8404: case 8405: case 8406: case 8407: case 8408: case 8409: case 8410: case 8411: case 8412: case 8413: case 8414: case 8415: case 8416: case 8417: case 8418: case 8419: case 8420: case 8421: case 8422: case 8423: case 8424: case 8425: case 8426: case 8427: case 8428: case 8429: case 8430: case 8431: case 8432: return 1041 + c - 8400;
		case 11503: case 11504: case 11505: return 1074 + c - 11503;
		case 11647: return 1077;
		case 11744: case 11745: case 11746: case 11747: case 11748: case 11749: case 11750: case 11751: case 11752: case 11753: case 11754: case 11755: case 11756: case 11757: case 11758: case 11759: case 11760: case 11761: case 11762: case 11763: case 11764: case 11765: case 11766: case 11767: case 11768: case 11769: case 11770: case 11771: case 11772: case 11773: case 11774: case 11775: return 1078 + c - 11744;
		case 12330: case 12331: case 12332: case 12333: case 12334: case 12335: return 1110 + c - 12330;
		case 12441: case 12442: return 1116 + c - 12441;
		case 42607: case 42608: case 42609: case 42610: return 1118 + c - 42607;
		case 42612: case 42613: case 42614: case 42615: case 42616: case 42617: case 42618: case 42619: case 42620: case 42621: return 1122 + c - 42612;
		case 42654: case 42655: return 1132 + c - 42654;
		case 42736: case 42737: return 1134 + c - 42736;
		case 43010: return 1136;
		case 43014: return 1137;
		case 43019: return 1138;
		case 43043: case 43044: case 43045: case 43046: case 43047: return 1139 + c - 43043;
		case 43052: return 1144;
		case 43136: case 43137: return 1145 + c - 43136;
		case 43188: case 43189: case 43190: case 43191: case 43192: case 43193: case 43194: case 43195: case 43196: case 43197: case 43198: case 43199: case 43200: case 43201: case 43202: case 43203: case 43204: case 43205: return 1147 + c - 43188;
		case 43232: case 43233: case 43234: case 43235: case 43236: case 43237: case 43238: case 43239: case 43240: case 43241: case 43242: case 43243: case 43244: case 43245: case 43246: case 43247: case 43248: case 43249: return 1165 + c - 43232;
		case 43263: return 1183;
		case 43302: case 43303: case 43304: case 43305: case 43306: case 43307: case 43308: case 43309: return 1184 + c - 43302;
		case 43335: case 43336: case 43337: case 43338: case 43339: case 43340: case 43341: case 43342: case 43343: case 43344: case 43345: case 43346: case 43347: return 1192 + c - 43335;
		case 43392: case 43393: case 43394: case 43395: return 1205 + c - 43392;
		case 43443: case 43444: case 43445: case 43446: case 43447: case 43448: case 43449: case 43450: case 43451: case 43452: case 43453: case 43454: case 43455: case 43456: return 1209 + c - 43443;
		case 43493: return 1223;
		case 43561: case 43562: case 43563: case 43564: case 43565: case 43566: case 43567: case 43568: case 43569: case 43570: case 43571: case 43572: case 43573: case 43574: return 1224 + c - 43561;
		case 43587: return 1238;
		case 43596: case 43597: return 1239 + c - 43596;
		case 43643: case 43644: case 43645: return 1241 + c - 43643;
		case 43696: return 1244;
		case 43698: case 43699: case 43700: return 1245 + c - 43698;
		case 43703: case 43704: return 1248 + c - 43703;
		case 43710: case 43711: return 1250 + c - 43710;
		case 43713: return 1252;
		case 43755: case 43756: case 43757: case 43758: case 43759: return 1253 + c - 43755;
		case 43765: case 43766: return 1258 + c - 43765;
		case 44003: case 44004: case 44005: case 44006: case 44007: case 44008: case 44009: case 44010: return 1260 + c - 44003;
		case 44012: case 44013: return 1268 + c - 44012;
		case 64286: return 1270;
		case 65024: case 65025: case 65026: case 65027: case 65028: case 65029: case 65030: case 65031: case 65032: case 65033: case 65034: case 65035: case 65036: case 65037: case 65038: case 65039: return 1271 + c - 65024;
		case 65056: case 65057: case 65058: case 65059: case 65060: case 65061: case 65062: case 65063: case 65064: case 65065: case 65066: case 65067: case 65068: case 65069: case 65070: case 65071: return 1287 + c - 65056;
		case 66045: return 1303;
		case 66272: return 1304;
		case 66422: case 66423: case 66424: case 66425: case 66426: return 1305 + c - 66422;
		case 68097: case 68098: case 68099: return 1310 + c - 68097;
		case 68101: case 68102: return 1313 + c - 68101;
		case 68108: case 68109: case 68110: case 68111: return 1315 + c - 68108;
		case 68152: case 68153: case 68154: return 1319 + c - 68152;
		case 68159: return 1322;
		case 68325: case 68326: return 1323 + c - 68325;
		case 68900: case 68901: case 68902: case 68903: return 1325 + c - 68900;
		case 69291: case 69292: return 1329 + c - 69291;
		case 69446: case 69447: case 69448: case 69449: case 69450: case 69451: case 69452: case 69453: case 69454: case 69455: case 69456: return 1331 + c - 69446;
		case 69632: case 69633: case 69634: return 1342 + c - 69632;
		case 69688: case 69689: case 69690: case 69691: case 69692: case 69693: case 69694: case 69695: case 69696: case 69697: case 69698: case 69699: case 69700: case 69701: case 69702: return 1345 + c - 69688;
		case 69759: case 69760: case 69761: case 69762: return 1360 + c - 69759;
		case 69808: case 69809: case 69810: case 69811: case 69812: case 69813: case 69814: case 69815: case 69816: case 69817: case 69818: return 1364 + c - 69808;
		case 69888: case 69889: case 69890: return 1375 + c - 69888;
		case 69927: case 69928: case 69929: case 69930: case 69931: case 69932: case 69933: case 69934: case 69935: case 69936: case 69937: case 69938: case 69939: case 69940: return 1378 + c - 69927;
		case 69957: case 69958: return 1392 + c - 69957;
		case 70003: return 1394;
		case 70016: case 70017: case 70018: return 1395 + c - 70016;
		case 70067: case 70068: case 70069: case 70070: case 70071: case 70072: case 70073: case 70074: case 70075: case 70076: case 70077: case 70078: case 70079: case 70080: return 1398 + c - 70067;
		case 70089: case 70090: case 70091: case 70092: return 1412 + c - 70089;
		case 70094: case 70095: return 1416 + c - 70094;
		case 70188: case 70189: case 70190: case 70191: case 70192: case 70193: case 70194: case 70195: case 70196: case 70197: case 70198: case 70199: return 1418 + c - 70188;
		case 70206: return 1430;
		case 70367: case 70368: case 70369: case 70370: case 70371: case 70372: case 70373: case 70374: case 70375: case 70376: case 70377: case 70378: return 1431 + c - 70367;
		case 70400: case 70401: case 70402: case 70403: return 1443 + c - 70400;
		case 70459: case 70460: return 1447 + c - 70459;
		case 70462: case 70463: case 70464: case 70465: case 70466: case 70467: case 70468: return 1449 + c - 70462;
		case 70471: case 70472: return 1456 + c - 70471;
		case 70475: case 70476: case 70477: return 1458 + c - 70475;
		case 70487: return 1461;
		case 70498: case 70499: return 1462 + c - 70498;
		case 70502: case 70503: case 70504: case 70505: case 70506: case 70507: case 70508: return 1464 + c - 70502;
		case 70512: case 70513: case 70514: case 70515: case 70516: return 1471 + c - 70512;
		case 70709: case 70710: case 70711: case 70712: case 70713: case 70714: case 70715: case 70716: case 70717: case 70718: case 70719: case 70720: case 70721: case 70722: case 70723: case 70724: case 70725: case 70726: return 1476 + c - 70709;
		case 70750: return 1494;
		case 70832: case 70833: case 70834: case 70835: case 70836: case 70837: case 70838: case 70839: case 70840: case 70841: case 70842: case 70843: case 70844: case 70845: case 70846: case 70847: case 70848: case 70849: case 70850: case 70851: return 1495 + c - 70832;
		case 71087: case 71088: case 71089: case 71090: case 71091: case 71092: case 71093: return 1515 + c - 71087;
		case 71096: case 71097: case 71098: case 71099: case 71100: case 71101: case 71102: case 71103: case 71104: return 1522 + c - 71096;
		case 71132: case 71133: return 1531 + c - 71132;
		case 71216: case 71217: case 71218: case 71219: case 71220: case 71221: case 71222: case 71223: case 71224: case 71225: case 71226: case 71227: case 71228: case 71229: case 71230: case 71231: case 71232: return 1533 + c - 71216;
		case 71339: case 71340: case 71341: case 71342: case 71343: case 71344: case 71345: case 71346: case 71347: case 71348: case 71349: case 71350: case 71351: return 1550 + c - 71339;
		case 71453: case 71454: case 71455: case 71456: case 71457: case 71458: case 71459: case 71460: case 71461: case 71462: case 71463: case 71464: case 71465: case 71466: case 71467: return 1563 + c - 71453;
		case 71724: case 71725: case 71726: case 71727: case 71728: case 71729: case 71730: case 71731: case 71732: case 71733: case 71734: case 71735: case 71736: case 71737: case 71738: return 1578 + c - 71724;
		case 71984: case 71985: case 71986: case 71987: case 71988: case 71989: return 1593 + c - 71984;
		case 71991: case 71992: return 1599 + c - 71991;
		case 71995: case 71996: case 71997: case 71998: return 1601 + c - 71995;
		case 72000: return 1605;
		case 72002: case 72003: return 1606 + c - 72002;
		case 72145: case 72146: case 72147: case 72148: case 72149: case 72150: case 72151: return 1608 + c - 72145;
		case 72154: case 72155: case 72156: case 72157: case 72158: case 72159: case 72160: return 1615 + c - 72154;
		case 72164: return 1622;
		case 72193: case 72194: case 72195: case 72196: case 72197: case 72198: case 72199: case 72200: case 72201: case 72202: return 1623 + c - 72193;
		case 72243: case 72244: case 72245: case 72246: case 72247: case 72248: case 72249: return 1633 + c - 72243;
		case 72251: case 72252: case 72253: case 72254: return 1640 + c - 72251;
		case 72263: return 1644;
		case 72273: case 72274: case 72275: case 72276: case 72277: case 72278: case 72279: case 72280: case 72281: case 72282: case 72283: return 1645 + c - 72273;
		case 72330: case 72331: case 72332: case 72333: case 72334: case 72335: case 72336: case 72337: case 72338: case 72339: case 72340: case 72341: case 72342: case 72343: case 72344: case 72345: return 1656 + c - 72330;
		case 72751: case 72752: case 72753: case 72754: case 72755: case 72756: case 72757: case 72758: return 1672 + c - 72751;
		case 72760: case 72761: case 72762: case 72763: case 72764: case 72765: case 72766: case 72767: return 1680 + c - 72760;
		case 72850: case 72851: case 72852: case 72853: case 72854: case 72855: case 72856: case 72857: case 72858: case 72859: case 72860: case 72861: case 72862: case 72863: case 72864: case 72865: case 72866: case 72867: case 72868: case 72869: case 72870: case 72871: return 1688 + c - 72850;
		case 72873: case 72874: case 72875: case 72876: case 72877: case 72878: case 72879: case 72880: case 72881: case 72882: case 72883: case 72884: case 72885: case 72886: return 1710 + c - 72873;
		case 73009: case 73010: case 73011: case 73012: case 73013: case 73014: return 1724 + c - 73009;
		case 73018: return 1730;
		case 73020: case 73021: return 1731 + c - 73020;
		case 73023: case 73024: case 73025: case 73026: case 73027: case 73028: case 73029: return 1733 + c - 73023;
		case 73031: return 1740;
		case 73098: case 73099: case 73100: case 73101: case 73102: return 1741 + c - 73098;
		case 73104: case 73105: return 1746 + c - 73104;
		case 73107: case 73108: case 73109: case 73110: case 73111: return 1748 + c - 73107;
		case 73459: case 73460: case 73461: case 73462: return 1753 + c - 73459;
		case 92912: case 92913: case 92914: case 92915: case 92916: return 1757 + c - 92912;
		case 92976: case 92977: case 92978: case 92979: case 92980: case 92981: case 92982: return 1762 + c - 92976;
		case 94031: return 1769;
		case 94033: case 94034: case 94035: case 94036: case 94037: case 94038: case 94039: case 94040: case 94041: case 94042: case 94043: case 94044: case 94045: case 94046: case 94047: case 94048: case 94049: case 94050: case 94051: case 94052: case 94053: case 94054: case 94055: case 94056: case 94057: case 94058: case 94059: case 94060: case 94061: case 94062: case 94063: case 94064: case 94065: case 94066: case 94067: case 94068: case 94069: case 94070: case 94071: case 94072: case 94073: case 94074: case 94075: case 94076: case 94077: case 94078: case 94079: case 94080: case 94081: case 94082: case 94083: case 94084: case 94085: case 94086: case 94087: return 1770 + c - 94033;
		case 94095: case 94096: case 94097: case 94098: return 1825 + c - 94095;
		case 94180: return 1829;
		case 94192: case 94193: return 1830 + c - 94192;
		case 113821: case 113822: return 1832 + c - 113821;
		case 119141: case 119142: case 119143: case 119144: case 119145: return 1834 + c - 119141;
		case 119149: case 119150: case 119151: case 119152: case 119153: case 119154: return 1839 + c - 119149;
		case 119163: case 119164: case 119165: case 119166: case 119167: case 119168: case 119169: case 119170: return 1845 + c - 119163;
		case 119173: case 119174: case 119175: case 119176: case 119177: case 119178: case 119179: return 1853 + c - 119173;
		case 119210: case 119211: case 119212: case 119213: return 1860 + c - 119210;
		case 119362: case 119363: case 119364: return 1864 + c - 119362;
		case 121344: case 121345: case 121346: case 121347: case 121348: case 121349: case 121350: case 121351: case 121352: case 121353: case 121354: case 121355: case 121356: case 121357: case 121358: case 121359: case 121360: case 121361: case 121362: case 121363: case 121364: case 121365: case 121366: case 121367: case 121368: case 121369: case 121370: case 121371: case 121372: case 121373: case 121374: case 121375: case 121376: case 121377: case 121378: case 121379: case 121380: case 121381: case 121382: case 121383: case 121384: case 121385: case 121386: case 121387: case 121388: case 121389: case 121390: case 121391: case 121392: case 121393: case 121394: case 121395: case 121396: case 121397: case 121398: return 1867 + c - 121344;
		case 121403: case 121404: case 121405: case 121406: case 121407: case 121408: case 121409: case 121410: case 121411: case 121412: case 121413: case 121414: case 121415: case 121416: case 121417: case 121418: case 121419: case 121420: case 121421: case 121422: case 121423: case 121424: case 121425: case 121426: case 121427: case 121428: case 121429: case 121430: case 121431: case 121432: case 121433: case 121434: case 121435: case 121436: case 121437: case 121438: case 121439: case 121440: case 121441: case 121442: case 121443: case 121444: case 121445: case 121446: case 121447: case 121448: case 121449: case 121450: case 121451: case 121452: return 1922 + c - 121403;
		case 121461: return 1972;
		case 121476: return 1973;
		case 121499: case 121500: case 121501: case 121502: case 121503: return 1974 + c - 121499;
		case 121505: case 121506: case 121507: case 121508: case 121509: case 121510: case 121511: case 121512: case 121513: case 121514: case 121515: case 121516: case 121517: case 121518: case 121519: return 1979 + c - 121505;
		case 122880: case 122881: case 122882: case 122883: case 122884: case 122885: case 122886: return 1994 + c - 122880;
		case 122888: case 122889: case 122890: case 122891: case 122892: case 122893: case 122894: case 122895: case 122896: case 122897: case 122898: case 122899: case 122900: case 122901: case 122902: case 122903: case 122904: return 2001 + c - 122888;
		case 122907: case 122908: case 122909: case 122910: case 122911: case 122912: case 122913: return 2018 + c - 122907;
		case 122915: case 122916: return 2025 + c - 122915;
		case 122918: case 122919: case 122920: case 122921: case 122922: return 2027 + c - 122918;
		case 123184: case 123185: case 123186: case 123187: case 123188: case 123189: case 123190: return 2032 + c - 123184;
		case 123628: case 123629: case 123630: case 123631: return 2039 + c - 123628;
		case 125136: case 125137: case 125138: case 125139: case 125140: case 125141: case 125142: return 2043 + c - 125136;
		case 125252: case 125253: case 125254: case 125255: case 125256: case 125257: case 125258: return 2050 + c - 125252;
		case 127462: case 127463: case 127464: case 127465: case 127466: case 127467: case 127468: case 127469: case 127470: case 127471: case 127472: case 127473: case 127474: case 127475: case 127476: case 127477: case 127478: case 127479: case 127480: case 127481: case 127482: case 127483: case 127484: case 127485: case 127486: case 127487: return 2057 + c - 127462;
		case 127995: case 127996: case 127997: case 127998: case 127999: return 2083 + c - 127995;
		case 917760: case 917761: case 917762: case 917763: case 917764: case 917765: case 917766: case 917767: case 917768: case 917769: case 917770: case 917771: case 917772: case 917773: case 917774: case 917775: case 917776: case 917777: case 917778: case 917779: case 917780: case 917781: case 917782: case 917783: case 917784: case 917785: case 917786: case 917787: case 917788: case 917789: case 917790: case 917791: case 917792: case 917793: case 917794: case 917795: case 917796: case 917797: case 917798: case 917799: case 917800: case 917801: case 917802: case 917803: case 917804: case 917805: case 917806: case 917807: case 917808: case 917809: case 917810: case 917811: case 917812: case 917813: case 917814: case 917815: case 917816: case 917817: case 917818: case 917819: case 917820: case 917821: case 917822: case 917823: case 917824: case 917825: case 917826: case 917827: case 917828: case 917829: case 917830: case 917831: case 917832: case 917833: case 917834: case 917835: case 917836: case 917837: case 917838: case 917839: case 917840: case 917841: case 917842: case 917843: case 917844: case 917845: case 917846: case 917847: case 917848: case 917849: case 917850: case 917851: case 917852: case 917853: case 917854: case 917855: case 917856: case 917857: case 917858: case 917859: case 917860: case 917861: case 917862: case 917863: case 917864: case 917865: case 917866: case 917867: case 917868: case 917869: case 917870: case 917871: case 917872: case 917873: case 917874: case 917875: case 917876: case 917877: case 917878: case 917879: case 917880: case 917881: case 917882: case 917883: case 917884: case 917885: case 917886: case 917887: case 917888: case 917889: case 917890: case 917891: case 917892: case 917893: case 917894: case 917895: case 917896: case 917897: case 917898: case 917899: case 917900: case 917901: case 917902: case 917903: case 917904: case 917905: case 917906: case 917907: case 917908: case 917909: case 917910: case 917911: case 917912: case 917913: case 917914: case 917915: case 917916: case 917917: case 917918: case 917919: case 917920: case 917921: case 917922: case 917923: case 917924: case 917925: case 917926: case 917927: case 917928: case 917929: case 917930: case 917931: case 917932: case 917933: case 917934: case 917935: case 917936: case 917937: case 917938: case 917939: case 917940: case 917941: case 917942: case 917943: case 917944: case 917945: case 917946: case 917947: case 917948: case 917949: case 917950: case 917951: case 917952: case 917953: case 917954: case 917955: case 917956: case 917957: case 917958: case 917959: case 917960: case 917961: case 917962: case 917963: case 917964: case 917965: case 917966: case 917967: case 917968: case 917969: case 917970: case 917971: case 917972: case 917973: case 917974: case 917975: case 917976: case 917977: case 917978: case 917979: case 917980: case 917981: case 917982: case 917983: case 917984: case 917985: case 917986: case 917987: case 917988: case 917989: case 917990: case 917991: case 917992: case 917993: case 917994: case 917995: case 917996: case 917997: case 917998: case 917999: return 2088 + c - 917760;
default: return 0;
	} // }}}
}


END_ALLOW_CASE_RANGE
