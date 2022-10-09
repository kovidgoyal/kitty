// unicode data, built from the unicode standard on: 2022-09-30
// see gen-wcwidth.py
#include "data-types.h"

START_ALLOW_CASE_RANGE

#include "unicode-data.h"
bool
is_combining_char(char_type code) {
	// Combining and default ignored characters (6424 codepoints) {{{
	if (LIKELY(code < 173)) return false;
	switch(code) {
		case 0xad:
			return true;
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
		case 0x600 ... 0x605:
			return true;
		case 0x610 ... 0x61a:
			return true;
		case 0x61c:
			return true;
		case 0x64b ... 0x65f:
			return true;
		case 0x670:
			return true;
		case 0x6d6 ... 0x6dd:
			return true;
		case 0x6df ... 0x6e4:
			return true;
		case 0x6e7 ... 0x6e8:
			return true;
		case 0x6ea ... 0x6ed:
			return true;
		case 0x70f:
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
		case 0x890 ... 0x891:
			return true;
		case 0x898 ... 0x89f:
			return true;
		case 0x8ca ... 0x903:
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
		case 0xc3c:
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
		case 0xcf3:
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
		case 0xec8 ... 0xece:
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
		case 0x115f ... 0x1160:
			return true;
		case 0x135d ... 0x135f:
			return true;
		case 0x1712 ... 0x1715:
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
		case 0x180b ... 0x180f:
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
		case 0x1ab0 ... 0x1ace:
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
		case 0x1dc0 ... 0x1dff:
			return true;
		case 0x200b ... 0x200f:
			return true;
		case 0x202a ... 0x202e:
			return true;
		case 0x2060 ... 0x206f:
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
		case 0x3164:
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
		case 0xfeff:
			return true;
		case 0xffa0:
			return true;
		case 0xfff0 ... 0xfffb:
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
		case 0x10efd ... 0x10eff:
			return true;
		case 0x10f46 ... 0x10f50:
			return true;
		case 0x10f82 ... 0x10f85:
			return true;
		case 0x11000 ... 0x11002:
			return true;
		case 0x11038 ... 0x11046:
			return true;
		case 0x11070:
			return true;
		case 0x11073 ... 0x11074:
			return true;
		case 0x1107f ... 0x11082:
			return true;
		case 0x110b0 ... 0x110ba:
			return true;
		case 0x110bd:
			return true;
		case 0x110c2:
			return true;
		case 0x110cd:
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
		case 0x11241:
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
		case 0x11f00 ... 0x11f01:
			return true;
		case 0x11f03:
			return true;
		case 0x11f34 ... 0x11f3a:
			return true;
		case 0x11f3e ... 0x11f42:
			return true;
		case 0x13430 ... 0x13440:
			return true;
		case 0x13447 ... 0x13455:
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
		case 0x1bca0 ... 0x1bca3:
			return true;
		case 0x1cf00 ... 0x1cf2d:
			return true;
		case 0x1cf30 ... 0x1cf46:
			return true;
		case 0x1d165 ... 0x1d169:
			return true;
		case 0x1d16d ... 0x1d182:
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
		case 0x1e08f:
			return true;
		case 0x1e130 ... 0x1e136:
			return true;
		case 0x1e2ae:
			return true;
		case 0x1e2ec ... 0x1e2ef:
			return true;
		case 0x1e4ec ... 0x1e4ef:
			return true;
		case 0x1e8d0 ... 0x1e8d6:
			return true;
		case 0x1e944 ... 0x1e94a:
			return true;
		case 0x1f1e6 ... 0x1f1ff:
			return true;
		case 0x1f3fb ... 0x1f3ff:
			return true;
		case 0xe0000 ... 0xe0fff:
			return true;
	} // }}}

	return false;
}

bool
is_ignored_char(char_type code) {
	// Control characters and non-characters (2179 codepoints) {{{
	if (LIKELY(0x20 <= code && code <= 0x7e)) return false;
	switch(code) {
		case 0x0 ... 0x1f:
			return true;
		case 0x7f ... 0x9f:
			return true;
		case 0xd800 ... 0xdfff:
			return true;
		case 0xfdd0 ... 0xfdef:
			return true;
		case 0xfffe ... 0xffff:
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
is_non_rendered_char(char_type code) {
	// Other_Default_Ignorable_Code_Point and soft hyphen (6075 codepoints) {{{
	if (LIKELY(0x20 <= code && code <= 0x7e)) return false;
	switch(code) {
		case 0x0 ... 0x1f:
			return true;
		case 0x7f ... 0x9f:
			return true;
		case 0xad:
			return true;
		case 0x34f:
			return true;
		case 0x600 ... 0x605:
			return true;
		case 0x61c:
			return true;
		case 0x6dd:
			return true;
		case 0x70f:
			return true;
		case 0x890 ... 0x891:
			return true;
		case 0x8e2:
			return true;
		case 0x115f ... 0x1160:
			return true;
		case 0x17b4 ... 0x17b5:
			return true;
		case 0x180e:
			return true;
		case 0x200b ... 0x200f:
			return true;
		case 0x202a ... 0x202e:
			return true;
		case 0x2060 ... 0x206f:
			return true;
		case 0x3164:
			return true;
		case 0xd800 ... 0xdfff:
			return true;
		case 0xfe00 ... 0xfe0f:
			return true;
		case 0xfeff:
			return true;
		case 0xffa0:
			return true;
		case 0xfff0 ... 0xfffb:
			return true;
		case 0x110bd:
			return true;
		case 0x110cd:
			return true;
		case 0x13430 ... 0x1343f:
			return true;
		case 0x1bca0 ... 0x1bca3:
			return true;
		case 0x1d173 ... 0x1d17a:
			return true;
		case 0xe0000 ... 0xe00ff:
			return true;
		case 0xe01f0 ... 0xe0fff:
			return true;
	} // }}}

	return false;
}

bool
is_word_char(char_type code) {
	// L and N categories (137935 codepoints) {{{
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
		case 0x870 ... 0x887:
			return true;
		case 0x889 ... 0x88e:
			return true;
		case 0x8a0 ... 0x8c9:
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
		case 0xc5d:
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
		case 0xcdd ... 0xcde:
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
		case 0x1700 ... 0x1711:
			return true;
		case 0x171f ... 0x1731:
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
		case 0x1b45 ... 0x1b4c:
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
		case 0x2c00 ... 0x2ce4:
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
		case 0x4e00 ... 0xa48c:
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
		case 0xa78b ... 0xa7ca:
			return true;
		case 0xa7d0 ... 0xa7d1:
			return true;
		case 0xa7d3:
			return true;
		case 0xa7d5 ... 0xa7d9:
			return true;
		case 0xa7f2 ... 0xa801:
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
		case 0x10570 ... 0x1057a:
			return true;
		case 0x1057c ... 0x1058a:
			return true;
		case 0x1058c ... 0x10592:
			return true;
		case 0x10594 ... 0x10595:
			return true;
		case 0x10597 ... 0x105a1:
			return true;
		case 0x105a3 ... 0x105b1:
			return true;
		case 0x105b3 ... 0x105b9:
			return true;
		case 0x105bb ... 0x105bc:
			return true;
		case 0x10600 ... 0x10736:
			return true;
		case 0x10740 ... 0x10755:
			return true;
		case 0x10760 ... 0x10767:
			return true;
		case 0x10780 ... 0x10785:
			return true;
		case 0x10787 ... 0x107b0:
			return true;
		case 0x107b2 ... 0x107ba:
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
		case 0x10f70 ... 0x10f81:
			return true;
		case 0x10fb0 ... 0x10fcb:
			return true;
		case 0x10fe0 ... 0x10ff6:
			return true;
		case 0x11003 ... 0x11037:
			return true;
		case 0x11052 ... 0x1106f:
			return true;
		case 0x11071 ... 0x11072:
			return true;
		case 0x11075:
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
		case 0x1123f ... 0x11240:
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
		case 0x11740 ... 0x11746:
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
		case 0x11ab0 ... 0x11af8:
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
		case 0x11f02:
			return true;
		case 0x11f04 ... 0x11f10:
			return true;
		case 0x11f12 ... 0x11f33:
			return true;
		case 0x11f50 ... 0x11f59:
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
		case 0x12f90 ... 0x12ff0:
			return true;
		case 0x13000 ... 0x1342f:
			return true;
		case 0x13441 ... 0x13446:
			return true;
		case 0x14400 ... 0x14646:
			return true;
		case 0x16800 ... 0x16a38:
			return true;
		case 0x16a40 ... 0x16a5e:
			return true;
		case 0x16a60 ... 0x16a69:
			return true;
		case 0x16a70 ... 0x16abe:
			return true;
		case 0x16ac0 ... 0x16ac9:
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
		case 0x1aff0 ... 0x1aff3:
			return true;
		case 0x1aff5 ... 0x1affb:
			return true;
		case 0x1affd ... 0x1affe:
			return true;
		case 0x1b000 ... 0x1b122:
			return true;
		case 0x1b132:
			return true;
		case 0x1b150 ... 0x1b152:
			return true;
		case 0x1b155:
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
		case 0x1d2c0 ... 0x1d2d3:
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
		case 0x1df00 ... 0x1df1e:
			return true;
		case 0x1df25 ... 0x1df2a:
			return true;
		case 0x1e030 ... 0x1e06d:
			return true;
		case 0x1e100 ... 0x1e12c:
			return true;
		case 0x1e137 ... 0x1e13d:
			return true;
		case 0x1e140 ... 0x1e149:
			return true;
		case 0x1e14e:
			return true;
		case 0x1e290 ... 0x1e2ad:
			return true;
		case 0x1e2c0 ... 0x1e2eb:
			return true;
		case 0x1e2f0 ... 0x1e2f9:
			return true;
		case 0x1e4d0 ... 0x1e4eb:
			return true;
		case 0x1e4f0 ... 0x1e4f9:
			return true;
		case 0x1e7e0 ... 0x1e7e6:
			return true;
		case 0x1e7e8 ... 0x1e7eb:
			return true;
		case 0x1e7ed ... 0x1e7ee:
			return true;
		case 0x1e7f0 ... 0x1e7fe:
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
		case 0x20000 ... 0x2a6df:
			return true;
		case 0x2a700 ... 0x2b739:
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
		case 0x31350 ... 0x323af:
			return true;
	} // }}}

	return false;
}

bool
is_CZ_category(char_type code) {
	// C and Z categories (139770 codepoints) {{{
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
		case 0x890 ... 0x891:
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
		case 0x13430 ... 0x1343f:
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
	// P category (punctuation) (842 codepoints) {{{
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
		case 0x61d ... 0x61f:
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
		case 0x1b7d ... 0x1b7e:
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
		case 0x2e52 ... 0x2e5d:
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
		case 0x10f86 ... 0x10f89:
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
		case 0x116b9:
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
		case 0x11b00 ... 0x11b09:
			return true;
		case 0x11c41 ... 0x11c45:
			return true;
		case 0x11c70 ... 0x11c71:
			return true;
		case 0x11ef7 ... 0x11ef8:
			return true;
		case 0x11f43 ... 0x11f4f:
			return true;
		case 0x11fff:
			return true;
		case 0x12470 ... 0x12474:
			return true;
		case 0x12ff1 ... 0x12ff2:
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
	static char_type map[6425] = { 0, 173, 768, 769, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 780, 781, 782, 783, 784, 785, 786, 787, 788, 789, 790, 791, 792, 793, 794, 795, 796, 797, 798, 799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809, 810, 811, 812, 813, 814, 815, 816, 817, 818, 819, 820, 821, 822, 823, 824, 825, 826, 827, 828, 829, 830, 831, 832, 833, 834, 835, 836, 837, 838, 839, 840, 841, 842, 843, 844, 845, 846, 847, 848, 849, 850, 851, 852, 853, 854, 855, 856, 857, 858, 859, 860, 861, 862, 863, 864, 865, 866, 867, 868, 869, 870, 871, 872, 873, 874, 875, 876, 877, 878, 879, 1155, 1156, 1157, 1158, 1159, 1160, 1161, 1425, 1426, 1427, 1428, 1429, 1430, 1431, 1432, 1433, 1434, 1435, 1436, 1437, 1438, 1439, 1440, 1441, 1442, 1443, 1444, 1445, 1446, 1447, 1448, 1449, 1450, 1451, 1452, 1453, 1454, 1455, 1456, 1457, 1458, 1459, 1460, 1461, 1462, 1463, 1464, 1465, 1466, 1467, 1468, 1469, 1471, 1473, 1474, 1476, 1477, 1479, 1536, 1537, 1538, 1539, 1540, 1541, 1552, 1553, 1554, 1555, 1556, 1557, 1558, 1559, 1560, 1561, 1562, 1564, 1611, 1612, 1613, 1614, 1615, 1616, 1617, 1618, 1619, 1620, 1621, 1622, 1623, 1624, 1625, 1626, 1627, 1628, 1629, 1630, 1631, 1648, 1750, 1751, 1752, 1753, 1754, 1755, 1756, 1757, 1759, 1760, 1761, 1762, 1763, 1764, 1767, 1768, 1770, 1771, 1772, 1773, 1807, 1809, 1840, 1841, 1842, 1843, 1844, 1845, 1846, 1847, 1848, 1849, 1850, 1851, 1852, 1853, 1854, 1855, 1856, 1857, 1858, 1859, 1860, 1861, 1862, 1863, 1864, 1865, 1866, 1958, 1959, 1960, 1961, 1962, 1963, 1964, 1965, 1966, 1967, 1968, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2045, 2070, 2071, 2072, 2073, 2075, 2076, 2077, 2078, 2079, 2080, 2081, 2082, 2083, 2085, 2086, 2087, 2089, 2090, 2091, 2092, 2093, 2137, 2138, 2139, 2192, 2193, 2200, 2201, 2202, 2203, 2204, 2205, 2206, 2207, 2250, 2251, 2252, 2253, 2254, 2255, 2256, 2257, 2258, 2259, 2260, 2261, 2262, 2263, 2264, 2265, 2266, 2267, 2268, 2269, 2270, 2271, 2272, 2273, 2274, 2275, 2276, 2277, 2278, 2279, 2280, 2281, 2282, 2283, 2284, 2285, 2286, 2287, 2288, 2289, 2290, 2291, 2292, 2293, 2294, 2295, 2296, 2297, 2298, 2299, 2300, 2301, 2302, 2303, 2304, 2305, 2306, 2307, 2362, 2363, 2364, 2366, 2367, 2368, 2369, 2370, 2371, 2372, 2373, 2374, 2375, 2376, 2377, 2378, 2379, 2380, 2381, 2382, 2383, 2385, 2386, 2387, 2388, 2389, 2390, 2391, 2402, 2403, 2433, 2434, 2435, 2492, 2494, 2495, 2496, 2497, 2498, 2499, 2500, 2503, 2504, 2507, 2508, 2509, 2519, 2530, 2531, 2558, 2561, 2562, 2563, 2620, 2622, 2623, 2624, 2625, 2626, 2631, 2632, 2635, 2636, 2637, 2641, 2672, 2673, 2677, 2689, 2690, 2691, 2748, 2750, 2751, 2752, 2753, 2754, 2755, 2756, 2757, 2759, 2760, 2761, 2763, 2764, 2765, 2786, 2787, 2810, 2811, 2812, 2813, 2814, 2815, 2817, 2818, 2819, 2876, 2878, 2879, 2880, 2881, 2882, 2883, 2884, 2887, 2888, 2891, 2892, 2893, 2901, 2902, 2903, 2914, 2915, 2946, 3006, 3007, 3008, 3009, 3010, 3014, 3015, 3016, 3018, 3019, 3020, 3021, 3031, 3072, 3073, 3074, 3075, 3076, 3132, 3134, 3135, 3136, 3137, 3138, 3139, 3140, 3142, 3143, 3144, 3146, 3147, 3148, 3149, 3157, 3158, 3170, 3171, 3201, 3202, 3203, 3260, 3262, 3263, 3264, 3265, 3266, 3267, 3268, 3270, 3271, 3272, 3274, 3275, 3276, 3277, 3285, 3286, 3298, 3299, 3315, 3328, 3329, 3330, 3331, 3387, 3388, 3390, 3391, 3392, 3393, 3394, 3395, 3396, 3398, 3399, 3400, 3402, 3403, 3404, 3405, 3415, 3426, 3427, 3457, 3458, 3459, 3530, 3535, 3536, 3537, 3538, 3539, 3540, 3542, 3544, 3545, 3546, 3547, 3548, 3549, 3550, 3551, 3570, 3571, 3633, 3636, 3637, 3638, 3639, 3640, 3641, 3642, 3655, 3656, 3657, 3658, 3659, 3660, 3661, 3662, 3761, 3764, 3765, 3766, 3767, 3768, 3769, 3770, 3771, 3772, 3784, 3785, 3786, 3787, 3788, 3789, 3790, 3864, 3865, 3893, 3895, 3897, 3902, 3903, 3953, 3954, 3955, 3956, 3957, 3958, 3959, 3960, 3961, 3962, 3963, 3964, 3965, 3966, 3967, 3968, 3969, 3970, 3971, 3972, 3974, 3975, 3981, 3982, 3983, 3984, 3985, 3986, 3987, 3988, 3989, 3990, 3991, 3993, 3994, 3995, 3996, 3997, 3998, 3999, 4000, 4001, 4002, 4003, 4004, 4005, 4006, 4007, 4008, 4009, 4010, 4011, 4012, 4013, 4014, 4015, 4016, 4017, 4018, 4019, 4020, 4021, 4022, 4023, 4024, 4025, 4026, 4027, 4028, 4038, 4139, 4140, 4141, 4142, 4143, 4144, 4145, 4146, 4147, 4148, 4149, 4150, 4151, 4152, 4153, 4154, 4155, 4156, 4157, 4158, 4182, 4183, 4184, 4185, 4190, 4191, 4192, 4194, 4195, 4196, 4199, 4200, 4201, 4202, 4203, 4204, 4205, 4209, 4210, 4211, 4212, 4226, 4227, 4228, 4229, 4230, 4231, 4232, 4233, 4234, 4235, 4236, 4237, 4239, 4250, 4251, 4252, 4253, 4447, 4448, 4957, 4958, 4959, 5906, 5907, 5908, 5909, 5938, 5939, 5940, 5970, 5971, 6002, 6003, 6068, 6069, 6070, 6071, 6072, 6073, 6074, 6075, 6076, 6077, 6078, 6079, 6080, 6081, 6082, 6083, 6084, 6085, 6086, 6087, 6088, 6089, 6090, 6091, 6092, 6093, 6094, 6095, 6096, 6097, 6098, 6099, 6109, 6155, 6156, 6157, 6158, 6159, 6277, 6278, 6313, 6432, 6433, 6434, 6435, 6436, 6437, 6438, 6439, 6440, 6441, 6442, 6443, 6448, 6449, 6450, 6451, 6452, 6453, 6454, 6455, 6456, 6457, 6458, 6459, 6679, 6680, 6681, 6682, 6683, 6741, 6742, 6743, 6744, 6745, 6746, 6747, 6748, 6749, 6750, 6752, 6753, 6754, 6755, 6756, 6757, 6758, 6759, 6760, 6761, 6762, 6763, 6764, 6765, 6766, 6767, 6768, 6769, 6770, 6771, 6772, 6773, 6774, 6775, 6776, 6777, 6778, 6779, 6780, 6783, 6832, 6833, 6834, 6835, 6836, 6837, 6838, 6839, 6840, 6841, 6842, 6843, 6844, 6845, 6846, 6847, 6848, 6849, 6850, 6851, 6852, 6853, 6854, 6855, 6856, 6857, 6858, 6859, 6860, 6861, 6862, 6912, 6913, 6914, 6915, 6916, 6964, 6965, 6966, 6967, 6968, 6969, 6970, 6971, 6972, 6973, 6974, 6975, 6976, 6977, 6978, 6979, 6980, 7019, 7020, 7021, 7022, 7023, 7024, 7025, 7026, 7027, 7040, 7041, 7042, 7073, 7074, 7075, 7076, 7077, 7078, 7079, 7080, 7081, 7082, 7083, 7084, 7085, 7142, 7143, 7144, 7145, 7146, 7147, 7148, 7149, 7150, 7151, 7152, 7153, 7154, 7155, 7204, 7205, 7206, 7207, 7208, 7209, 7210, 7211, 7212, 7213, 7214, 7215, 7216, 7217, 7218, 7219, 7220, 7221, 7222, 7223, 7376, 7377, 7378, 7380, 7381, 7382, 7383, 7384, 7385, 7386, 7387, 7388, 7389, 7390, 7391, 7392, 7393, 7394, 7395, 7396, 7397, 7398, 7399, 7400, 7405, 7412, 7415, 7416, 7417, 7616, 7617, 7618, 7619, 7620, 7621, 7622, 7623, 7624, 7625, 7626, 7627, 7628, 7629, 7630, 7631, 7632, 7633, 7634, 7635, 7636, 7637, 7638, 7639, 7640, 7641, 7642, 7643, 7644, 7645, 7646, 7647, 7648, 7649, 7650, 7651, 7652, 7653, 7654, 7655, 7656, 7657, 7658, 7659, 7660, 7661, 7662, 7663, 7664, 7665, 7666, 7667, 7668, 7669, 7670, 7671, 7672, 7673, 7674, 7675, 7676, 7677, 7678, 7679, 8203, 8204, 8205, 8206, 8207, 8234, 8235, 8236, 8237, 8238, 8288, 8289, 8290, 8291, 8292, 8293, 8294, 8295, 8296, 8297, 8298, 8299, 8300, 8301, 8302, 8303, 8400, 8401, 8402, 8403, 8404, 8405, 8406, 8407, 8408, 8409, 8410, 8411, 8412, 8413, 8414, 8415, 8416, 8417, 8418, 8419, 8420, 8421, 8422, 8423, 8424, 8425, 8426, 8427, 8428, 8429, 8430, 8431, 8432, 11503, 11504, 11505, 11647, 11744, 11745, 11746, 11747, 11748, 11749, 11750, 11751, 11752, 11753, 11754, 11755, 11756, 11757, 11758, 11759, 11760, 11761, 11762, 11763, 11764, 11765, 11766, 11767, 11768, 11769, 11770, 11771, 11772, 11773, 11774, 11775, 12330, 12331, 12332, 12333, 12334, 12335, 12441, 12442, 12644, 42607, 42608, 42609, 42610, 42612, 42613, 42614, 42615, 42616, 42617, 42618, 42619, 42620, 42621, 42654, 42655, 42736, 42737, 43010, 43014, 43019, 43043, 43044, 43045, 43046, 43047, 43052, 43136, 43137, 43188, 43189, 43190, 43191, 43192, 43193, 43194, 43195, 43196, 43197, 43198, 43199, 43200, 43201, 43202, 43203, 43204, 43205, 43232, 43233, 43234, 43235, 43236, 43237, 43238, 43239, 43240, 43241, 43242, 43243, 43244, 43245, 43246, 43247, 43248, 43249, 43263, 43302, 43303, 43304, 43305, 43306, 43307, 43308, 43309, 43335, 43336, 43337, 43338, 43339, 43340, 43341, 43342, 43343, 43344, 43345, 43346, 43347, 43392, 43393, 43394, 43395, 43443, 43444, 43445, 43446, 43447, 43448, 43449, 43450, 43451, 43452, 43453, 43454, 43455, 43456, 43493, 43561, 43562, 43563, 43564, 43565, 43566, 43567, 43568, 43569, 43570, 43571, 43572, 43573, 43574, 43587, 43596, 43597, 43643, 43644, 43645, 43696, 43698, 43699, 43700, 43703, 43704, 43710, 43711, 43713, 43755, 43756, 43757, 43758, 43759, 43765, 43766, 44003, 44004, 44005, 44006, 44007, 44008, 44009, 44010, 44012, 44013, 64286, 65024, 65025, 65026, 65027, 65028, 65029, 65030, 65031, 65032, 65033, 65034, 65035, 65036, 65037, 65038, 65039, 65056, 65057, 65058, 65059, 65060, 65061, 65062, 65063, 65064, 65065, 65066, 65067, 65068, 65069, 65070, 65071, 65279, 65440, 65520, 65521, 65522, 65523, 65524, 65525, 65526, 65527, 65528, 65529, 65530, 65531, 66045, 66272, 66422, 66423, 66424, 66425, 66426, 68097, 68098, 68099, 68101, 68102, 68108, 68109, 68110, 68111, 68152, 68153, 68154, 68159, 68325, 68326, 68900, 68901, 68902, 68903, 69291, 69292, 69373, 69374, 69375, 69446, 69447, 69448, 69449, 69450, 69451, 69452, 69453, 69454, 69455, 69456, 69506, 69507, 69508, 69509, 69632, 69633, 69634, 69688, 69689, 69690, 69691, 69692, 69693, 69694, 69695, 69696, 69697, 69698, 69699, 69700, 69701, 69702, 69744, 69747, 69748, 69759, 69760, 69761, 69762, 69808, 69809, 69810, 69811, 69812, 69813, 69814, 69815, 69816, 69817, 69818, 69821, 69826, 69837, 69888, 69889, 69890, 69927, 69928, 69929, 69930, 69931, 69932, 69933, 69934, 69935, 69936, 69937, 69938, 69939, 69940, 69957, 69958, 70003, 70016, 70017, 70018, 70067, 70068, 70069, 70070, 70071, 70072, 70073, 70074, 70075, 70076, 70077, 70078, 70079, 70080, 70089, 70090, 70091, 70092, 70094, 70095, 70188, 70189, 70190, 70191, 70192, 70193, 70194, 70195, 70196, 70197, 70198, 70199, 70206, 70209, 70367, 70368, 70369, 70370, 70371, 70372, 70373, 70374, 70375, 70376, 70377, 70378, 70400, 70401, 70402, 70403, 70459, 70460, 70462, 70463, 70464, 70465, 70466, 70467, 70468, 70471, 70472, 70475, 70476, 70477, 70487, 70498, 70499, 70502, 70503, 70504, 70505, 70506, 70507, 70508, 70512, 70513, 70514, 70515, 70516, 70709, 70710, 70711, 70712, 70713, 70714, 70715, 70716, 70717, 70718, 70719, 70720, 70721, 70722, 70723, 70724, 70725, 70726, 70750, 70832, 70833, 70834, 70835, 70836, 70837, 70838, 70839, 70840, 70841, 70842, 70843, 70844, 70845, 70846, 70847, 70848, 70849, 70850, 70851, 71087, 71088, 71089, 71090, 71091, 71092, 71093, 71096, 71097, 71098, 71099, 71100, 71101, 71102, 71103, 71104, 71132, 71133, 71216, 71217, 71218, 71219, 71220, 71221, 71222, 71223, 71224, 71225, 71226, 71227, 71228, 71229, 71230, 71231, 71232, 71339, 71340, 71341, 71342, 71343, 71344, 71345, 71346, 71347, 71348, 71349, 71350, 71351, 71453, 71454, 71455, 71456, 71457, 71458, 71459, 71460, 71461, 71462, 71463, 71464, 71465, 71466, 71467, 71724, 71725, 71726, 71727, 71728, 71729, 71730, 71731, 71732, 71733, 71734, 71735, 71736, 71737, 71738, 71984, 71985, 71986, 71987, 71988, 71989, 71991, 71992, 71995, 71996, 71997, 71998, 72000, 72002, 72003, 72145, 72146, 72147, 72148, 72149, 72150, 72151, 72154, 72155, 72156, 72157, 72158, 72159, 72160, 72164, 72193, 72194, 72195, 72196, 72197, 72198, 72199, 72200, 72201, 72202, 72243, 72244, 72245, 72246, 72247, 72248, 72249, 72251, 72252, 72253, 72254, 72263, 72273, 72274, 72275, 72276, 72277, 72278, 72279, 72280, 72281, 72282, 72283, 72330, 72331, 72332, 72333, 72334, 72335, 72336, 72337, 72338, 72339, 72340, 72341, 72342, 72343, 72344, 72345, 72751, 72752, 72753, 72754, 72755, 72756, 72757, 72758, 72760, 72761, 72762, 72763, 72764, 72765, 72766, 72767, 72850, 72851, 72852, 72853, 72854, 72855, 72856, 72857, 72858, 72859, 72860, 72861, 72862, 72863, 72864, 72865, 72866, 72867, 72868, 72869, 72870, 72871, 72873, 72874, 72875, 72876, 72877, 72878, 72879, 72880, 72881, 72882, 72883, 72884, 72885, 72886, 73009, 73010, 73011, 73012, 73013, 73014, 73018, 73020, 73021, 73023, 73024, 73025, 73026, 73027, 73028, 73029, 73031, 73098, 73099, 73100, 73101, 73102, 73104, 73105, 73107, 73108, 73109, 73110, 73111, 73459, 73460, 73461, 73462, 73472, 73473, 73475, 73524, 73525, 73526, 73527, 73528, 73529, 73530, 73534, 73535, 73536, 73537, 73538, 78896, 78897, 78898, 78899, 78900, 78901, 78902, 78903, 78904, 78905, 78906, 78907, 78908, 78909, 78910, 78911, 78912, 78919, 78920, 78921, 78922, 78923, 78924, 78925, 78926, 78927, 78928, 78929, 78930, 78931, 78932, 78933, 92912, 92913, 92914, 92915, 92916, 92976, 92977, 92978, 92979, 92980, 92981, 92982, 94031, 94033, 94034, 94035, 94036, 94037, 94038, 94039, 94040, 94041, 94042, 94043, 94044, 94045, 94046, 94047, 94048, 94049, 94050, 94051, 94052, 94053, 94054, 94055, 94056, 94057, 94058, 94059, 94060, 94061, 94062, 94063, 94064, 94065, 94066, 94067, 94068, 94069, 94070, 94071, 94072, 94073, 94074, 94075, 94076, 94077, 94078, 94079, 94080, 94081, 94082, 94083, 94084, 94085, 94086, 94087, 94095, 94096, 94097, 94098, 94180, 94192, 94193, 113821, 113822, 113824, 113825, 113826, 113827, 118528, 118529, 118530, 118531, 118532, 118533, 118534, 118535, 118536, 118537, 118538, 118539, 118540, 118541, 118542, 118543, 118544, 118545, 118546, 118547, 118548, 118549, 118550, 118551, 118552, 118553, 118554, 118555, 118556, 118557, 118558, 118559, 118560, 118561, 118562, 118563, 118564, 118565, 118566, 118567, 118568, 118569, 118570, 118571, 118572, 118573, 118576, 118577, 118578, 118579, 118580, 118581, 118582, 118583, 118584, 118585, 118586, 118587, 118588, 118589, 118590, 118591, 118592, 118593, 118594, 118595, 118596, 118597, 118598, 119141, 119142, 119143, 119144, 119145, 119149, 119150, 119151, 119152, 119153, 119154, 119155, 119156, 119157, 119158, 119159, 119160, 119161, 119162, 119163, 119164, 119165, 119166, 119167, 119168, 119169, 119170, 119173, 119174, 119175, 119176, 119177, 119178, 119179, 119210, 119211, 119212, 119213, 119362, 119363, 119364, 121344, 121345, 121346, 121347, 121348, 121349, 121350, 121351, 121352, 121353, 121354, 121355, 121356, 121357, 121358, 121359, 121360, 121361, 121362, 121363, 121364, 121365, 121366, 121367, 121368, 121369, 121370, 121371, 121372, 121373, 121374, 121375, 121376, 121377, 121378, 121379, 121380, 121381, 121382, 121383, 121384, 121385, 121386, 121387, 121388, 121389, 121390, 121391, 121392, 121393, 121394, 121395, 121396, 121397, 121398, 121403, 121404, 121405, 121406, 121407, 121408, 121409, 121410, 121411, 121412, 121413, 121414, 121415, 121416, 121417, 121418, 121419, 121420, 121421, 121422, 121423, 121424, 121425, 121426, 121427, 121428, 121429, 121430, 121431, 121432, 121433, 121434, 121435, 121436, 121437, 121438, 121439, 121440, 121441, 121442, 121443, 121444, 121445, 121446, 121447, 121448, 121449, 121450, 121451, 121452, 121461, 121476, 121499, 121500, 121501, 121502, 121503, 121505, 121506, 121507, 121508, 121509, 121510, 121511, 121512, 121513, 121514, 121515, 121516, 121517, 121518, 121519, 122880, 122881, 122882, 122883, 122884, 122885, 122886, 122888, 122889, 122890, 122891, 122892, 122893, 122894, 122895, 122896, 122897, 122898, 122899, 122900, 122901, 122902, 122903, 122904, 122907, 122908, 122909, 122910, 122911, 122912, 122913, 122915, 122916, 122918, 122919, 122920, 122921, 122922, 123023, 123184, 123185, 123186, 123187, 123188, 123189, 123190, 123566, 123628, 123629, 123630, 123631, 124140, 124141, 124142, 124143, 125136, 125137, 125138, 125139, 125140, 125141, 125142, 125252, 125253, 125254, 125255, 125256, 125257, 125258, 127462, 127463, 127464, 127465, 127466, 127467, 127468, 127469, 127470, 127471, 127472, 127473, 127474, 127475, 127476, 127477, 127478, 127479, 127480, 127481, 127482, 127483, 127484, 127485, 127486, 127487, 127995, 127996, 127997, 127998, 127999, 917504, 917505, 917506, 917507, 917508, 917509, 917510, 917511, 917512, 917513, 917514, 917515, 917516, 917517, 917518, 917519, 917520, 917521, 917522, 917523, 917524, 917525, 917526, 917527, 917528, 917529, 917530, 917531, 917532, 917533, 917534, 917535, 917536, 917537, 917538, 917539, 917540, 917541, 917542, 917543, 917544, 917545, 917546, 917547, 917548, 917549, 917550, 917551, 917552, 917553, 917554, 917555, 917556, 917557, 917558, 917559, 917560, 917561, 917562, 917563, 917564, 917565, 917566, 917567, 917568, 917569, 917570, 917571, 917572, 917573, 917574, 917575, 917576, 917577, 917578, 917579, 917580, 917581, 917582, 917583, 917584, 917585, 917586, 917587, 917588, 917589, 917590, 917591, 917592, 917593, 917594, 917595, 917596, 917597, 917598, 917599, 917600, 917601, 917602, 917603, 917604, 917605, 917606, 917607, 917608, 917609, 917610, 917611, 917612, 917613, 917614, 917615, 917616, 917617, 917618, 917619, 917620, 917621, 917622, 917623, 917624, 917625, 917626, 917627, 917628, 917629, 917630, 917631, 917632, 917633, 917634, 917635, 917636, 917637, 917638, 917639, 917640, 917641, 917642, 917643, 917644, 917645, 917646, 917647, 917648, 917649, 917650, 917651, 917652, 917653, 917654, 917655, 917656, 917657, 917658, 917659, 917660, 917661, 917662, 917663, 917664, 917665, 917666, 917667, 917668, 917669, 917670, 917671, 917672, 917673, 917674, 917675, 917676, 917677, 917678, 917679, 917680, 917681, 917682, 917683, 917684, 917685, 917686, 917687, 917688, 917689, 917690, 917691, 917692, 917693, 917694, 917695, 917696, 917697, 917698, 917699, 917700, 917701, 917702, 917703, 917704, 917705, 917706, 917707, 917708, 917709, 917710, 917711, 917712, 917713, 917714, 917715, 917716, 917717, 917718, 917719, 917720, 917721, 917722, 917723, 917724, 917725, 917726, 917727, 917728, 917729, 917730, 917731, 917732, 917733, 917734, 917735, 917736, 917737, 917738, 917739, 917740, 917741, 917742, 917743, 917744, 917745, 917746, 917747, 917748, 917749, 917750, 917751, 917752, 917753, 917754, 917755, 917756, 917757, 917758, 917759, 917760, 917761, 917762, 917763, 917764, 917765, 917766, 917767, 917768, 917769, 917770, 917771, 917772, 917773, 917774, 917775, 917776, 917777, 917778, 917779, 917780, 917781, 917782, 917783, 917784, 917785, 917786, 917787, 917788, 917789, 917790, 917791, 917792, 917793, 917794, 917795, 917796, 917797, 917798, 917799, 917800, 917801, 917802, 917803, 917804, 917805, 917806, 917807, 917808, 917809, 917810, 917811, 917812, 917813, 917814, 917815, 917816, 917817, 917818, 917819, 917820, 917821, 917822, 917823, 917824, 917825, 917826, 917827, 917828, 917829, 917830, 917831, 917832, 917833, 917834, 917835, 917836, 917837, 917838, 917839, 917840, 917841, 917842, 917843, 917844, 917845, 917846, 917847, 917848, 917849, 917850, 917851, 917852, 917853, 917854, 917855, 917856, 917857, 917858, 917859, 917860, 917861, 917862, 917863, 917864, 917865, 917866, 917867, 917868, 917869, 917870, 917871, 917872, 917873, 917874, 917875, 917876, 917877, 917878, 917879, 917880, 917881, 917882, 917883, 917884, 917885, 917886, 917887, 917888, 917889, 917890, 917891, 917892, 917893, 917894, 917895, 917896, 917897, 917898, 917899, 917900, 917901, 917902, 917903, 917904, 917905, 917906, 917907, 917908, 917909, 917910, 917911, 917912, 917913, 917914, 917915, 917916, 917917, 917918, 917919, 917920, 917921, 917922, 917923, 917924, 917925, 917926, 917927, 917928, 917929, 917930, 917931, 917932, 917933, 917934, 917935, 917936, 917937, 917938, 917939, 917940, 917941, 917942, 917943, 917944, 917945, 917946, 917947, 917948, 917949, 917950, 917951, 917952, 917953, 917954, 917955, 917956, 917957, 917958, 917959, 917960, 917961, 917962, 917963, 917964, 917965, 917966, 917967, 917968, 917969, 917970, 917971, 917972, 917973, 917974, 917975, 917976, 917977, 917978, 917979, 917980, 917981, 917982, 917983, 917984, 917985, 917986, 917987, 917988, 917989, 917990, 917991, 917992, 917993, 917994, 917995, 917996, 917997, 917998, 917999, 918000, 918001, 918002, 918003, 918004, 918005, 918006, 918007, 918008, 918009, 918010, 918011, 918012, 918013, 918014, 918015, 918016, 918017, 918018, 918019, 918020, 918021, 918022, 918023, 918024, 918025, 918026, 918027, 918028, 918029, 918030, 918031, 918032, 918033, 918034, 918035, 918036, 918037, 918038, 918039, 918040, 918041, 918042, 918043, 918044, 918045, 918046, 918047, 918048, 918049, 918050, 918051, 918052, 918053, 918054, 918055, 918056, 918057, 918058, 918059, 918060, 918061, 918062, 918063, 918064, 918065, 918066, 918067, 918068, 918069, 918070, 918071, 918072, 918073, 918074, 918075, 918076, 918077, 918078, 918079, 918080, 918081, 918082, 918083, 918084, 918085, 918086, 918087, 918088, 918089, 918090, 918091, 918092, 918093, 918094, 918095, 918096, 918097, 918098, 918099, 918100, 918101, 918102, 918103, 918104, 918105, 918106, 918107, 918108, 918109, 918110, 918111, 918112, 918113, 918114, 918115, 918116, 918117, 918118, 918119, 918120, 918121, 918122, 918123, 918124, 918125, 918126, 918127, 918128, 918129, 918130, 918131, 918132, 918133, 918134, 918135, 918136, 918137, 918138, 918139, 918140, 918141, 918142, 918143, 918144, 918145, 918146, 918147, 918148, 918149, 918150, 918151, 918152, 918153, 918154, 918155, 918156, 918157, 918158, 918159, 918160, 918161, 918162, 918163, 918164, 918165, 918166, 918167, 918168, 918169, 918170, 918171, 918172, 918173, 918174, 918175, 918176, 918177, 918178, 918179, 918180, 918181, 918182, 918183, 918184, 918185, 918186, 918187, 918188, 918189, 918190, 918191, 918192, 918193, 918194, 918195, 918196, 918197, 918198, 918199, 918200, 918201, 918202, 918203, 918204, 918205, 918206, 918207, 918208, 918209, 918210, 918211, 918212, 918213, 918214, 918215, 918216, 918217, 918218, 918219, 918220, 918221, 918222, 918223, 918224, 918225, 918226, 918227, 918228, 918229, 918230, 918231, 918232, 918233, 918234, 918235, 918236, 918237, 918238, 918239, 918240, 918241, 918242, 918243, 918244, 918245, 918246, 918247, 918248, 918249, 918250, 918251, 918252, 918253, 918254, 918255, 918256, 918257, 918258, 918259, 918260, 918261, 918262, 918263, 918264, 918265, 918266, 918267, 918268, 918269, 918270, 918271, 918272, 918273, 918274, 918275, 918276, 918277, 918278, 918279, 918280, 918281, 918282, 918283, 918284, 918285, 918286, 918287, 918288, 918289, 918290, 918291, 918292, 918293, 918294, 918295, 918296, 918297, 918298, 918299, 918300, 918301, 918302, 918303, 918304, 918305, 918306, 918307, 918308, 918309, 918310, 918311, 918312, 918313, 918314, 918315, 918316, 918317, 918318, 918319, 918320, 918321, 918322, 918323, 918324, 918325, 918326, 918327, 918328, 918329, 918330, 918331, 918332, 918333, 918334, 918335, 918336, 918337, 918338, 918339, 918340, 918341, 918342, 918343, 918344, 918345, 918346, 918347, 918348, 918349, 918350, 918351, 918352, 918353, 918354, 918355, 918356, 918357, 918358, 918359, 918360, 918361, 918362, 918363, 918364, 918365, 918366, 918367, 918368, 918369, 918370, 918371, 918372, 918373, 918374, 918375, 918376, 918377, 918378, 918379, 918380, 918381, 918382, 918383, 918384, 918385, 918386, 918387, 918388, 918389, 918390, 918391, 918392, 918393, 918394, 918395, 918396, 918397, 918398, 918399, 918400, 918401, 918402, 918403, 918404, 918405, 918406, 918407, 918408, 918409, 918410, 918411, 918412, 918413, 918414, 918415, 918416, 918417, 918418, 918419, 918420, 918421, 918422, 918423, 918424, 918425, 918426, 918427, 918428, 918429, 918430, 918431, 918432, 918433, 918434, 918435, 918436, 918437, 918438, 918439, 918440, 918441, 918442, 918443, 918444, 918445, 918446, 918447, 918448, 918449, 918450, 918451, 918452, 918453, 918454, 918455, 918456, 918457, 918458, 918459, 918460, 918461, 918462, 918463, 918464, 918465, 918466, 918467, 918468, 918469, 918470, 918471, 918472, 918473, 918474, 918475, 918476, 918477, 918478, 918479, 918480, 918481, 918482, 918483, 918484, 918485, 918486, 918487, 918488, 918489, 918490, 918491, 918492, 918493, 918494, 918495, 918496, 918497, 918498, 918499, 918500, 918501, 918502, 918503, 918504, 918505, 918506, 918507, 918508, 918509, 918510, 918511, 918512, 918513, 918514, 918515, 918516, 918517, 918518, 918519, 918520, 918521, 918522, 918523, 918524, 918525, 918526, 918527, 918528, 918529, 918530, 918531, 918532, 918533, 918534, 918535, 918536, 918537, 918538, 918539, 918540, 918541, 918542, 918543, 918544, 918545, 918546, 918547, 918548, 918549, 918550, 918551, 918552, 918553, 918554, 918555, 918556, 918557, 918558, 918559, 918560, 918561, 918562, 918563, 918564, 918565, 918566, 918567, 918568, 918569, 918570, 918571, 918572, 918573, 918574, 918575, 918576, 918577, 918578, 918579, 918580, 918581, 918582, 918583, 918584, 918585, 918586, 918587, 918588, 918589, 918590, 918591, 918592, 918593, 918594, 918595, 918596, 918597, 918598, 918599, 918600, 918601, 918602, 918603, 918604, 918605, 918606, 918607, 918608, 918609, 918610, 918611, 918612, 918613, 918614, 918615, 918616, 918617, 918618, 918619, 918620, 918621, 918622, 918623, 918624, 918625, 918626, 918627, 918628, 918629, 918630, 918631, 918632, 918633, 918634, 918635, 918636, 918637, 918638, 918639, 918640, 918641, 918642, 918643, 918644, 918645, 918646, 918647, 918648, 918649, 918650, 918651, 918652, 918653, 918654, 918655, 918656, 918657, 918658, 918659, 918660, 918661, 918662, 918663, 918664, 918665, 918666, 918667, 918668, 918669, 918670, 918671, 918672, 918673, 918674, 918675, 918676, 918677, 918678, 918679, 918680, 918681, 918682, 918683, 918684, 918685, 918686, 918687, 918688, 918689, 918690, 918691, 918692, 918693, 918694, 918695, 918696, 918697, 918698, 918699, 918700, 918701, 918702, 918703, 918704, 918705, 918706, 918707, 918708, 918709, 918710, 918711, 918712, 918713, 918714, 918715, 918716, 918717, 918718, 918719, 918720, 918721, 918722, 918723, 918724, 918725, 918726, 918727, 918728, 918729, 918730, 918731, 918732, 918733, 918734, 918735, 918736, 918737, 918738, 918739, 918740, 918741, 918742, 918743, 918744, 918745, 918746, 918747, 918748, 918749, 918750, 918751, 918752, 918753, 918754, 918755, 918756, 918757, 918758, 918759, 918760, 918761, 918762, 918763, 918764, 918765, 918766, 918767, 918768, 918769, 918770, 918771, 918772, 918773, 918774, 918775, 918776, 918777, 918778, 918779, 918780, 918781, 918782, 918783, 918784, 918785, 918786, 918787, 918788, 918789, 918790, 918791, 918792, 918793, 918794, 918795, 918796, 918797, 918798, 918799, 918800, 918801, 918802, 918803, 918804, 918805, 918806, 918807, 918808, 918809, 918810, 918811, 918812, 918813, 918814, 918815, 918816, 918817, 918818, 918819, 918820, 918821, 918822, 918823, 918824, 918825, 918826, 918827, 918828, 918829, 918830, 918831, 918832, 918833, 918834, 918835, 918836, 918837, 918838, 918839, 918840, 918841, 918842, 918843, 918844, 918845, 918846, 918847, 918848, 918849, 918850, 918851, 918852, 918853, 918854, 918855, 918856, 918857, 918858, 918859, 918860, 918861, 918862, 918863, 918864, 918865, 918866, 918867, 918868, 918869, 918870, 918871, 918872, 918873, 918874, 918875, 918876, 918877, 918878, 918879, 918880, 918881, 918882, 918883, 918884, 918885, 918886, 918887, 918888, 918889, 918890, 918891, 918892, 918893, 918894, 918895, 918896, 918897, 918898, 918899, 918900, 918901, 918902, 918903, 918904, 918905, 918906, 918907, 918908, 918909, 918910, 918911, 918912, 918913, 918914, 918915, 918916, 918917, 918918, 918919, 918920, 918921, 918922, 918923, 918924, 918925, 918926, 918927, 918928, 918929, 918930, 918931, 918932, 918933, 918934, 918935, 918936, 918937, 918938, 918939, 918940, 918941, 918942, 918943, 918944, 918945, 918946, 918947, 918948, 918949, 918950, 918951, 918952, 918953, 918954, 918955, 918956, 918957, 918958, 918959, 918960, 918961, 918962, 918963, 918964, 918965, 918966, 918967, 918968, 918969, 918970, 918971, 918972, 918973, 918974, 918975, 918976, 918977, 918978, 918979, 918980, 918981, 918982, 918983, 918984, 918985, 918986, 918987, 918988, 918989, 918990, 918991, 918992, 918993, 918994, 918995, 918996, 918997, 918998, 918999, 919000, 919001, 919002, 919003, 919004, 919005, 919006, 919007, 919008, 919009, 919010, 919011, 919012, 919013, 919014, 919015, 919016, 919017, 919018, 919019, 919020, 919021, 919022, 919023, 919024, 919025, 919026, 919027, 919028, 919029, 919030, 919031, 919032, 919033, 919034, 919035, 919036, 919037, 919038, 919039, 919040, 919041, 919042, 919043, 919044, 919045, 919046, 919047, 919048, 919049, 919050, 919051, 919052, 919053, 919054, 919055, 919056, 919057, 919058, 919059, 919060, 919061, 919062, 919063, 919064, 919065, 919066, 919067, 919068, 919069, 919070, 919071, 919072, 919073, 919074, 919075, 919076, 919077, 919078, 919079, 919080, 919081, 919082, 919083, 919084, 919085, 919086, 919087, 919088, 919089, 919090, 919091, 919092, 919093, 919094, 919095, 919096, 919097, 919098, 919099, 919100, 919101, 919102, 919103, 919104, 919105, 919106, 919107, 919108, 919109, 919110, 919111, 919112, 919113, 919114, 919115, 919116, 919117, 919118, 919119, 919120, 919121, 919122, 919123, 919124, 919125, 919126, 919127, 919128, 919129, 919130, 919131, 919132, 919133, 919134, 919135, 919136, 919137, 919138, 919139, 919140, 919141, 919142, 919143, 919144, 919145, 919146, 919147, 919148, 919149, 919150, 919151, 919152, 919153, 919154, 919155, 919156, 919157, 919158, 919159, 919160, 919161, 919162, 919163, 919164, 919165, 919166, 919167, 919168, 919169, 919170, 919171, 919172, 919173, 919174, 919175, 919176, 919177, 919178, 919179, 919180, 919181, 919182, 919183, 919184, 919185, 919186, 919187, 919188, 919189, 919190, 919191, 919192, 919193, 919194, 919195, 919196, 919197, 919198, 919199, 919200, 919201, 919202, 919203, 919204, 919205, 919206, 919207, 919208, 919209, 919210, 919211, 919212, 919213, 919214, 919215, 919216, 919217, 919218, 919219, 919220, 919221, 919222, 919223, 919224, 919225, 919226, 919227, 919228, 919229, 919230, 919231, 919232, 919233, 919234, 919235, 919236, 919237, 919238, 919239, 919240, 919241, 919242, 919243, 919244, 919245, 919246, 919247, 919248, 919249, 919250, 919251, 919252, 919253, 919254, 919255, 919256, 919257, 919258, 919259, 919260, 919261, 919262, 919263, 919264, 919265, 919266, 919267, 919268, 919269, 919270, 919271, 919272, 919273, 919274, 919275, 919276, 919277, 919278, 919279, 919280, 919281, 919282, 919283, 919284, 919285, 919286, 919287, 919288, 919289, 919290, 919291, 919292, 919293, 919294, 919295, 919296, 919297, 919298, 919299, 919300, 919301, 919302, 919303, 919304, 919305, 919306, 919307, 919308, 919309, 919310, 919311, 919312, 919313, 919314, 919315, 919316, 919317, 919318, 919319, 919320, 919321, 919322, 919323, 919324, 919325, 919326, 919327, 919328, 919329, 919330, 919331, 919332, 919333, 919334, 919335, 919336, 919337, 919338, 919339, 919340, 919341, 919342, 919343, 919344, 919345, 919346, 919347, 919348, 919349, 919350, 919351, 919352, 919353, 919354, 919355, 919356, 919357, 919358, 919359, 919360, 919361, 919362, 919363, 919364, 919365, 919366, 919367, 919368, 919369, 919370, 919371, 919372, 919373, 919374, 919375, 919376, 919377, 919378, 919379, 919380, 919381, 919382, 919383, 919384, 919385, 919386, 919387, 919388, 919389, 919390, 919391, 919392, 919393, 919394, 919395, 919396, 919397, 919398, 919399, 919400, 919401, 919402, 919403, 919404, 919405, 919406, 919407, 919408, 919409, 919410, 919411, 919412, 919413, 919414, 919415, 919416, 919417, 919418, 919419, 919420, 919421, 919422, 919423, 919424, 919425, 919426, 919427, 919428, 919429, 919430, 919431, 919432, 919433, 919434, 919435, 919436, 919437, 919438, 919439, 919440, 919441, 919442, 919443, 919444, 919445, 919446, 919447, 919448, 919449, 919450, 919451, 919452, 919453, 919454, 919455, 919456, 919457, 919458, 919459, 919460, 919461, 919462, 919463, 919464, 919465, 919466, 919467, 919468, 919469, 919470, 919471, 919472, 919473, 919474, 919475, 919476, 919477, 919478, 919479, 919480, 919481, 919482, 919483, 919484, 919485, 919486, 919487, 919488, 919489, 919490, 919491, 919492, 919493, 919494, 919495, 919496, 919497, 919498, 919499, 919500, 919501, 919502, 919503, 919504, 919505, 919506, 919507, 919508, 919509, 919510, 919511, 919512, 919513, 919514, 919515, 919516, 919517, 919518, 919519, 919520, 919521, 919522, 919523, 919524, 919525, 919526, 919527, 919528, 919529, 919530, 919531, 919532, 919533, 919534, 919535, 919536, 919537, 919538, 919539, 919540, 919541, 919542, 919543, 919544, 919545, 919546, 919547, 919548, 919549, 919550, 919551, 919552, 919553, 919554, 919555, 919556, 919557, 919558, 919559, 919560, 919561, 919562, 919563, 919564, 919565, 919566, 919567, 919568, 919569, 919570, 919571, 919572, 919573, 919574, 919575, 919576, 919577, 919578, 919579, 919580, 919581, 919582, 919583, 919584, 919585, 919586, 919587, 919588, 919589, 919590, 919591, 919592, 919593, 919594, 919595, 919596, 919597, 919598, 919599, 919600, 919601, 919602, 919603, 919604, 919605, 919606, 919607, 919608, 919609, 919610, 919611, 919612, 919613, 919614, 919615, 919616, 919617, 919618, 919619, 919620, 919621, 919622, 919623, 919624, 919625, 919626, 919627, 919628, 919629, 919630, 919631, 919632, 919633, 919634, 919635, 919636, 919637, 919638, 919639, 919640, 919641, 919642, 919643, 919644, 919645, 919646, 919647, 919648, 919649, 919650, 919651, 919652, 919653, 919654, 919655, 919656, 919657, 919658, 919659, 919660, 919661, 919662, 919663, 919664, 919665, 919666, 919667, 919668, 919669, 919670, 919671, 919672, 919673, 919674, 919675, 919676, 919677, 919678, 919679, 919680, 919681, 919682, 919683, 919684, 919685, 919686, 919687, 919688, 919689, 919690, 919691, 919692, 919693, 919694, 919695, 919696, 919697, 919698, 919699, 919700, 919701, 919702, 919703, 919704, 919705, 919706, 919707, 919708, 919709, 919710, 919711, 919712, 919713, 919714, 919715, 919716, 919717, 919718, 919719, 919720, 919721, 919722, 919723, 919724, 919725, 919726, 919727, 919728, 919729, 919730, 919731, 919732, 919733, 919734, 919735, 919736, 919737, 919738, 919739, 919740, 919741, 919742, 919743, 919744, 919745, 919746, 919747, 919748, 919749, 919750, 919751, 919752, 919753, 919754, 919755, 919756, 919757, 919758, 919759, 919760, 919761, 919762, 919763, 919764, 919765, 919766, 919767, 919768, 919769, 919770, 919771, 919772, 919773, 919774, 919775, 919776, 919777, 919778, 919779, 919780, 919781, 919782, 919783, 919784, 919785, 919786, 919787, 919788, 919789, 919790, 919791, 919792, 919793, 919794, 919795, 919796, 919797, 919798, 919799, 919800, 919801, 919802, 919803, 919804, 919805, 919806, 919807, 919808, 919809, 919810, 919811, 919812, 919813, 919814, 919815, 919816, 919817, 919818, 919819, 919820, 919821, 919822, 919823, 919824, 919825, 919826, 919827, 919828, 919829, 919830, 919831, 919832, 919833, 919834, 919835, 919836, 919837, 919838, 919839, 919840, 919841, 919842, 919843, 919844, 919845, 919846, 919847, 919848, 919849, 919850, 919851, 919852, 919853, 919854, 919855, 919856, 919857, 919858, 919859, 919860, 919861, 919862, 919863, 919864, 919865, 919866, 919867, 919868, 919869, 919870, 919871, 919872, 919873, 919874, 919875, 919876, 919877, 919878, 919879, 919880, 919881, 919882, 919883, 919884, 919885, 919886, 919887, 919888, 919889, 919890, 919891, 919892, 919893, 919894, 919895, 919896, 919897, 919898, 919899, 919900, 919901, 919902, 919903, 919904, 919905, 919906, 919907, 919908, 919909, 919910, 919911, 919912, 919913, 919914, 919915, 919916, 919917, 919918, 919919, 919920, 919921, 919922, 919923, 919924, 919925, 919926, 919927, 919928, 919929, 919930, 919931, 919932, 919933, 919934, 919935, 919936, 919937, 919938, 919939, 919940, 919941, 919942, 919943, 919944, 919945, 919946, 919947, 919948, 919949, 919950, 919951, 919952, 919953, 919954, 919955, 919956, 919957, 919958, 919959, 919960, 919961, 919962, 919963, 919964, 919965, 919966, 919967, 919968, 919969, 919970, 919971, 919972, 919973, 919974, 919975, 919976, 919977, 919978, 919979, 919980, 919981, 919982, 919983, 919984, 919985, 919986, 919987, 919988, 919989, 919990, 919991, 919992, 919993, 919994, 919995, 919996, 919997, 919998, 919999, 920000, 920001, 920002, 920003, 920004, 920005, 920006, 920007, 920008, 920009, 920010, 920011, 920012, 920013, 920014, 920015, 920016, 920017, 920018, 920019, 920020, 920021, 920022, 920023, 920024, 920025, 920026, 920027, 920028, 920029, 920030, 920031, 920032, 920033, 920034, 920035, 920036, 920037, 920038, 920039, 920040, 920041, 920042, 920043, 920044, 920045, 920046, 920047, 920048, 920049, 920050, 920051, 920052, 920053, 920054, 920055, 920056, 920057, 920058, 920059, 920060, 920061, 920062, 920063, 920064, 920065, 920066, 920067, 920068, 920069, 920070, 920071, 920072, 920073, 920074, 920075, 920076, 920077, 920078, 920079, 920080, 920081, 920082, 920083, 920084, 920085, 920086, 920087, 920088, 920089, 920090, 920091, 920092, 920093, 920094, 920095, 920096, 920097, 920098, 920099, 920100, 920101, 920102, 920103, 920104, 920105, 920106, 920107, 920108, 920109, 920110, 920111, 920112, 920113, 920114, 920115, 920116, 920117, 920118, 920119, 920120, 920121, 920122, 920123, 920124, 920125, 920126, 920127, 920128, 920129, 920130, 920131, 920132, 920133, 920134, 920135, 920136, 920137, 920138, 920139, 920140, 920141, 920142, 920143, 920144, 920145, 920146, 920147, 920148, 920149, 920150, 920151, 920152, 920153, 920154, 920155, 920156, 920157, 920158, 920159, 920160, 920161, 920162, 920163, 920164, 920165, 920166, 920167, 920168, 920169, 920170, 920171, 920172, 920173, 920174, 920175, 920176, 920177, 920178, 920179, 920180, 920181, 920182, 920183, 920184, 920185, 920186, 920187, 920188, 920189, 920190, 920191, 920192, 920193, 920194, 920195, 920196, 920197, 920198, 920199, 920200, 920201, 920202, 920203, 920204, 920205, 920206, 920207, 920208, 920209, 920210, 920211, 920212, 920213, 920214, 920215, 920216, 920217, 920218, 920219, 920220, 920221, 920222, 920223, 920224, 920225, 920226, 920227, 920228, 920229, 920230, 920231, 920232, 920233, 920234, 920235, 920236, 920237, 920238, 920239, 920240, 920241, 920242, 920243, 920244, 920245, 920246, 920247, 920248, 920249, 920250, 920251, 920252, 920253, 920254, 920255, 920256, 920257, 920258, 920259, 920260, 920261, 920262, 920263, 920264, 920265, 920266, 920267, 920268, 920269, 920270, 920271, 920272, 920273, 920274, 920275, 920276, 920277, 920278, 920279, 920280, 920281, 920282, 920283, 920284, 920285, 920286, 920287, 920288, 920289, 920290, 920291, 920292, 920293, 920294, 920295, 920296, 920297, 920298, 920299, 920300, 920301, 920302, 920303, 920304, 920305, 920306, 920307, 920308, 920309, 920310, 920311, 920312, 920313, 920314, 920315, 920316, 920317, 920318, 920319, 920320, 920321, 920322, 920323, 920324, 920325, 920326, 920327, 920328, 920329, 920330, 920331, 920332, 920333, 920334, 920335, 920336, 920337, 920338, 920339, 920340, 920341, 920342, 920343, 920344, 920345, 920346, 920347, 920348, 920349, 920350, 920351, 920352, 920353, 920354, 920355, 920356, 920357, 920358, 920359, 920360, 920361, 920362, 920363, 920364, 920365, 920366, 920367, 920368, 920369, 920370, 920371, 920372, 920373, 920374, 920375, 920376, 920377, 920378, 920379, 920380, 920381, 920382, 920383, 920384, 920385, 920386, 920387, 920388, 920389, 920390, 920391, 920392, 920393, 920394, 920395, 920396, 920397, 920398, 920399, 920400, 920401, 920402, 920403, 920404, 920405, 920406, 920407, 920408, 920409, 920410, 920411, 920412, 920413, 920414, 920415, 920416, 920417, 920418, 920419, 920420, 920421, 920422, 920423, 920424, 920425, 920426, 920427, 920428, 920429, 920430, 920431, 920432, 920433, 920434, 920435, 920436, 920437, 920438, 920439, 920440, 920441, 920442, 920443, 920444, 920445, 920446, 920447, 920448, 920449, 920450, 920451, 920452, 920453, 920454, 920455, 920456, 920457, 920458, 920459, 920460, 920461, 920462, 920463, 920464, 920465, 920466, 920467, 920468, 920469, 920470, 920471, 920472, 920473, 920474, 920475, 920476, 920477, 920478, 920479, 920480, 920481, 920482, 920483, 920484, 920485, 920486, 920487, 920488, 920489, 920490, 920491, 920492, 920493, 920494, 920495, 920496, 920497, 920498, 920499, 920500, 920501, 920502, 920503, 920504, 920505, 920506, 920507, 920508, 920509, 920510, 920511, 920512, 920513, 920514, 920515, 920516, 920517, 920518, 920519, 920520, 920521, 920522, 920523, 920524, 920525, 920526, 920527, 920528, 920529, 920530, 920531, 920532, 920533, 920534, 920535, 920536, 920537, 920538, 920539, 920540, 920541, 920542, 920543, 920544, 920545, 920546, 920547, 920548, 920549, 920550, 920551, 920552, 920553, 920554, 920555, 920556, 920557, 920558, 920559, 920560, 920561, 920562, 920563, 920564, 920565, 920566, 920567, 920568, 920569, 920570, 920571, 920572, 920573, 920574, 920575, 920576, 920577, 920578, 920579, 920580, 920581, 920582, 920583, 920584, 920585, 920586, 920587, 920588, 920589, 920590, 920591, 920592, 920593, 920594, 920595, 920596, 920597, 920598, 920599, 920600, 920601, 920602, 920603, 920604, 920605, 920606, 920607, 920608, 920609, 920610, 920611, 920612, 920613, 920614, 920615, 920616, 920617, 920618, 920619, 920620, 920621, 920622, 920623, 920624, 920625, 920626, 920627, 920628, 920629, 920630, 920631, 920632, 920633, 920634, 920635, 920636, 920637, 920638, 920639, 920640, 920641, 920642, 920643, 920644, 920645, 920646, 920647, 920648, 920649, 920650, 920651, 920652, 920653, 920654, 920655, 920656, 920657, 920658, 920659, 920660, 920661, 920662, 920663, 920664, 920665, 920666, 920667, 920668, 920669, 920670, 920671, 920672, 920673, 920674, 920675, 920676, 920677, 920678, 920679, 920680, 920681, 920682, 920683, 920684, 920685, 920686, 920687, 920688, 920689, 920690, 920691, 920692, 920693, 920694, 920695, 920696, 920697, 920698, 920699, 920700, 920701, 920702, 920703, 920704, 920705, 920706, 920707, 920708, 920709, 920710, 920711, 920712, 920713, 920714, 920715, 920716, 920717, 920718, 920719, 920720, 920721, 920722, 920723, 920724, 920725, 920726, 920727, 920728, 920729, 920730, 920731, 920732, 920733, 920734, 920735, 920736, 920737, 920738, 920739, 920740, 920741, 920742, 920743, 920744, 920745, 920746, 920747, 920748, 920749, 920750, 920751, 920752, 920753, 920754, 920755, 920756, 920757, 920758, 920759, 920760, 920761, 920762, 920763, 920764, 920765, 920766, 920767, 920768, 920769, 920770, 920771, 920772, 920773, 920774, 920775, 920776, 920777, 920778, 920779, 920780, 920781, 920782, 920783, 920784, 920785, 920786, 920787, 920788, 920789, 920790, 920791, 920792, 920793, 920794, 920795, 920796, 920797, 920798, 920799, 920800, 920801, 920802, 920803, 920804, 920805, 920806, 920807, 920808, 920809, 920810, 920811, 920812, 920813, 920814, 920815, 920816, 920817, 920818, 920819, 920820, 920821, 920822, 920823, 920824, 920825, 920826, 920827, 920828, 920829, 920830, 920831, 920832, 920833, 920834, 920835, 920836, 920837, 920838, 920839, 920840, 920841, 920842, 920843, 920844, 920845, 920846, 920847, 920848, 920849, 920850, 920851, 920852, 920853, 920854, 920855, 920856, 920857, 920858, 920859, 920860, 920861, 920862, 920863, 920864, 920865, 920866, 920867, 920868, 920869, 920870, 920871, 920872, 920873, 920874, 920875, 920876, 920877, 920878, 920879, 920880, 920881, 920882, 920883, 920884, 920885, 920886, 920887, 920888, 920889, 920890, 920891, 920892, 920893, 920894, 920895, 920896, 920897, 920898, 920899, 920900, 920901, 920902, 920903, 920904, 920905, 920906, 920907, 920908, 920909, 920910, 920911, 920912, 920913, 920914, 920915, 920916, 920917, 920918, 920919, 920920, 920921, 920922, 920923, 920924, 920925, 920926, 920927, 920928, 920929, 920930, 920931, 920932, 920933, 920934, 920935, 920936, 920937, 920938, 920939, 920940, 920941, 920942, 920943, 920944, 920945, 920946, 920947, 920948, 920949, 920950, 920951, 920952, 920953, 920954, 920955, 920956, 920957, 920958, 920959, 920960, 920961, 920962, 920963, 920964, 920965, 920966, 920967, 920968, 920969, 920970, 920971, 920972, 920973, 920974, 920975, 920976, 920977, 920978, 920979, 920980, 920981, 920982, 920983, 920984, 920985, 920986, 920987, 920988, 920989, 920990, 920991, 920992, 920993, 920994, 920995, 920996, 920997, 920998, 920999, 921000, 921001, 921002, 921003, 921004, 921005, 921006, 921007, 921008, 921009, 921010, 921011, 921012, 921013, 921014, 921015, 921016, 921017, 921018, 921019, 921020, 921021, 921022, 921023, 921024, 921025, 921026, 921027, 921028, 921029, 921030, 921031, 921032, 921033, 921034, 921035, 921036, 921037, 921038, 921039, 921040, 921041, 921042, 921043, 921044, 921045, 921046, 921047, 921048, 921049, 921050, 921051, 921052, 921053, 921054, 921055, 921056, 921057, 921058, 921059, 921060, 921061, 921062, 921063, 921064, 921065, 921066, 921067, 921068, 921069, 921070, 921071, 921072, 921073, 921074, 921075, 921076, 921077, 921078, 921079, 921080, 921081, 921082, 921083, 921084, 921085, 921086, 921087, 921088, 921089, 921090, 921091, 921092, 921093, 921094, 921095, 921096, 921097, 921098, 921099, 921100, 921101, 921102, 921103, 921104, 921105, 921106, 921107, 921108, 921109, 921110, 921111, 921112, 921113, 921114, 921115, 921116, 921117, 921118, 921119, 921120, 921121, 921122, 921123, 921124, 921125, 921126, 921127, 921128, 921129, 921130, 921131, 921132, 921133, 921134, 921135, 921136, 921137, 921138, 921139, 921140, 921141, 921142, 921143, 921144, 921145, 921146, 921147, 921148, 921149, 921150, 921151, 921152, 921153, 921154, 921155, 921156, 921157, 921158, 921159, 921160, 921161, 921162, 921163, 921164, 921165, 921166, 921167, 921168, 921169, 921170, 921171, 921172, 921173, 921174, 921175, 921176, 921177, 921178, 921179, 921180, 921181, 921182, 921183, 921184, 921185, 921186, 921187, 921188, 921189, 921190, 921191, 921192, 921193, 921194, 921195, 921196, 921197, 921198, 921199, 921200, 921201, 921202, 921203, 921204, 921205, 921206, 921207, 921208, 921209, 921210, 921211, 921212, 921213, 921214, 921215, 921216, 921217, 921218, 921219, 921220, 921221, 921222, 921223, 921224, 921225, 921226, 921227, 921228, 921229, 921230, 921231, 921232, 921233, 921234, 921235, 921236, 921237, 921238, 921239, 921240, 921241, 921242, 921243, 921244, 921245, 921246, 921247, 921248, 921249, 921250, 921251, 921252, 921253, 921254, 921255, 921256, 921257, 921258, 921259, 921260, 921261, 921262, 921263, 921264, 921265, 921266, 921267, 921268, 921269, 921270, 921271, 921272, 921273, 921274, 921275, 921276, 921277, 921278, 921279, 921280, 921281, 921282, 921283, 921284, 921285, 921286, 921287, 921288, 921289, 921290, 921291, 921292, 921293, 921294, 921295, 921296, 921297, 921298, 921299, 921300, 921301, 921302, 921303, 921304, 921305, 921306, 921307, 921308, 921309, 921310, 921311, 921312, 921313, 921314, 921315, 921316, 921317, 921318, 921319, 921320, 921321, 921322, 921323, 921324, 921325, 921326, 921327, 921328, 921329, 921330, 921331, 921332, 921333, 921334, 921335, 921336, 921337, 921338, 921339, 921340, 921341, 921342, 921343, 921344, 921345, 921346, 921347, 921348, 921349, 921350, 921351, 921352, 921353, 921354, 921355, 921356, 921357, 921358, 921359, 921360, 921361, 921362, 921363, 921364, 921365, 921366, 921367, 921368, 921369, 921370, 921371, 921372, 921373, 921374, 921375, 921376, 921377, 921378, 921379, 921380, 921381, 921382, 921383, 921384, 921385, 921386, 921387, 921388, 921389, 921390, 921391, 921392, 921393, 921394, 921395, 921396, 921397, 921398, 921399, 921400, 921401, 921402, 921403, 921404, 921405, 921406, 921407, 921408, 921409, 921410, 921411, 921412, 921413, 921414, 921415, 921416, 921417, 921418, 921419, 921420, 921421, 921422, 921423, 921424, 921425, 921426, 921427, 921428, 921429, 921430, 921431, 921432, 921433, 921434, 921435, 921436, 921437, 921438, 921439, 921440, 921441, 921442, 921443, 921444, 921445, 921446, 921447, 921448, 921449, 921450, 921451, 921452, 921453, 921454, 921455, 921456, 921457, 921458, 921459, 921460, 921461, 921462, 921463, 921464, 921465, 921466, 921467, 921468, 921469, 921470, 921471, 921472, 921473, 921474, 921475, 921476, 921477, 921478, 921479, 921480, 921481, 921482, 921483, 921484, 921485, 921486, 921487, 921488, 921489, 921490, 921491, 921492, 921493, 921494, 921495, 921496, 921497, 921498, 921499, 921500, 921501, 921502, 921503, 921504, 921505, 921506, 921507, 921508, 921509, 921510, 921511, 921512, 921513, 921514, 921515, 921516, 921517, 921518, 921519, 921520, 921521, 921522, 921523, 921524, 921525, 921526, 921527, 921528, 921529, 921530, 921531, 921532, 921533, 921534, 921535, 921536, 921537, 921538, 921539, 921540, 921541, 921542, 921543, 921544, 921545, 921546, 921547, 921548, 921549, 921550, 921551, 921552, 921553, 921554, 921555, 921556, 921557, 921558, 921559, 921560, 921561, 921562, 921563, 921564, 921565, 921566, 921567, 921568, 921569, 921570, 921571, 921572, 921573, 921574, 921575, 921576, 921577, 921578, 921579, 921580, 921581, 921582, 921583, 921584, 921585, 921586, 921587, 921588, 921589, 921590, 921591, 921592, 921593, 921594, 921595, 921596, 921597, 921598, 921599 }; // {{{ mapping }}}
	if (m < arraysz(map)) return map[m];
	return 0;
}

combining_type mark_for_codepoint(char_type c) {
	switch(c) { // {{{
		case 0: return 0;
		case 173: return 1;
		case 768: case 769: case 770: case 771: case 772: case 773: case 774: case 775: case 776: case 777: case 778: case 779: case 780: case 781: case 782: case 783: case 784: case 785: case 786: case 787: case 788: case 789: case 790: case 791: case 792: case 793: case 794: case 795: case 796: case 797: case 798: case 799: case 800: case 801: case 802: case 803: case 804: case 805: case 806: case 807: case 808: case 809: case 810: case 811: case 812: case 813: case 814: case 815: case 816: case 817: case 818: case 819: case 820: case 821: case 822: case 823: case 824: case 825: case 826: case 827: case 828: case 829: case 830: case 831: case 832: case 833: case 834: case 835: case 836: case 837: case 838: case 839: case 840: case 841: case 842: case 843: case 844: case 845: case 846: case 847: case 848: case 849: case 850: case 851: case 852: case 853: case 854: case 855: case 856: case 857: case 858: case 859: case 860: case 861: case 862: case 863: case 864: case 865: case 866: case 867: case 868: case 869: case 870: case 871: case 872: case 873: case 874: case 875: case 876: case 877: case 878: case 879: return 2 + c - 768;
		case 1155: case 1156: case 1157: case 1158: case 1159: case 1160: case 1161: return 114 + c - 1155;
		case 1425: case 1426: case 1427: case 1428: case 1429: case 1430: case 1431: case 1432: case 1433: case 1434: case 1435: case 1436: case 1437: case 1438: case 1439: case 1440: case 1441: case 1442: case 1443: case 1444: case 1445: case 1446: case 1447: case 1448: case 1449: case 1450: case 1451: case 1452: case 1453: case 1454: case 1455: case 1456: case 1457: case 1458: case 1459: case 1460: case 1461: case 1462: case 1463: case 1464: case 1465: case 1466: case 1467: case 1468: case 1469: return 121 + c - 1425;
		case 1471: return 166;
		case 1473: case 1474: return 167 + c - 1473;
		case 1476: case 1477: return 169 + c - 1476;
		case 1479: return 171;
		case 1536: case 1537: case 1538: case 1539: case 1540: case 1541: return 172 + c - 1536;
		case 1552: case 1553: case 1554: case 1555: case 1556: case 1557: case 1558: case 1559: case 1560: case 1561: case 1562: return 178 + c - 1552;
		case 1564: return 189;
		case 1611: case 1612: case 1613: case 1614: case 1615: case 1616: case 1617: case 1618: case 1619: case 1620: case 1621: case 1622: case 1623: case 1624: case 1625: case 1626: case 1627: case 1628: case 1629: case 1630: case 1631: return 190 + c - 1611;
		case 1648: return 211;
		case 1750: case 1751: case 1752: case 1753: case 1754: case 1755: case 1756: case 1757: return 212 + c - 1750;
		case 1759: case 1760: case 1761: case 1762: case 1763: case 1764: return 220 + c - 1759;
		case 1767: case 1768: return 226 + c - 1767;
		case 1770: case 1771: case 1772: case 1773: return 228 + c - 1770;
		case 1807: return 232;
		case 1809: return 233;
		case 1840: case 1841: case 1842: case 1843: case 1844: case 1845: case 1846: case 1847: case 1848: case 1849: case 1850: case 1851: case 1852: case 1853: case 1854: case 1855: case 1856: case 1857: case 1858: case 1859: case 1860: case 1861: case 1862: case 1863: case 1864: case 1865: case 1866: return 234 + c - 1840;
		case 1958: case 1959: case 1960: case 1961: case 1962: case 1963: case 1964: case 1965: case 1966: case 1967: case 1968: return 261 + c - 1958;
		case 2027: case 2028: case 2029: case 2030: case 2031: case 2032: case 2033: case 2034: case 2035: return 272 + c - 2027;
		case 2045: return 281;
		case 2070: case 2071: case 2072: case 2073: return 282 + c - 2070;
		case 2075: case 2076: case 2077: case 2078: case 2079: case 2080: case 2081: case 2082: case 2083: return 286 + c - 2075;
		case 2085: case 2086: case 2087: return 295 + c - 2085;
		case 2089: case 2090: case 2091: case 2092: case 2093: return 298 + c - 2089;
		case 2137: case 2138: case 2139: return 303 + c - 2137;
		case 2192: case 2193: return 306 + c - 2192;
		case 2200: case 2201: case 2202: case 2203: case 2204: case 2205: case 2206: case 2207: return 308 + c - 2200;
		case 2250: case 2251: case 2252: case 2253: case 2254: case 2255: case 2256: case 2257: case 2258: case 2259: case 2260: case 2261: case 2262: case 2263: case 2264: case 2265: case 2266: case 2267: case 2268: case 2269: case 2270: case 2271: case 2272: case 2273: case 2274: case 2275: case 2276: case 2277: case 2278: case 2279: case 2280: case 2281: case 2282: case 2283: case 2284: case 2285: case 2286: case 2287: case 2288: case 2289: case 2290: case 2291: case 2292: case 2293: case 2294: case 2295: case 2296: case 2297: case 2298: case 2299: case 2300: case 2301: case 2302: case 2303: case 2304: case 2305: case 2306: case 2307: return 316 + c - 2250;
		case 2362: case 2363: case 2364: return 374 + c - 2362;
		case 2366: case 2367: case 2368: case 2369: case 2370: case 2371: case 2372: case 2373: case 2374: case 2375: case 2376: case 2377: case 2378: case 2379: case 2380: case 2381: case 2382: case 2383: return 377 + c - 2366;
		case 2385: case 2386: case 2387: case 2388: case 2389: case 2390: case 2391: return 395 + c - 2385;
		case 2402: case 2403: return 402 + c - 2402;
		case 2433: case 2434: case 2435: return 404 + c - 2433;
		case 2492: return 407;
		case 2494: case 2495: case 2496: case 2497: case 2498: case 2499: case 2500: return 408 + c - 2494;
		case 2503: case 2504: return 415 + c - 2503;
		case 2507: case 2508: case 2509: return 417 + c - 2507;
		case 2519: return 420;
		case 2530: case 2531: return 421 + c - 2530;
		case 2558: return 423;
		case 2561: case 2562: case 2563: return 424 + c - 2561;
		case 2620: return 427;
		case 2622: case 2623: case 2624: case 2625: case 2626: return 428 + c - 2622;
		case 2631: case 2632: return 433 + c - 2631;
		case 2635: case 2636: case 2637: return 435 + c - 2635;
		case 2641: return 438;
		case 2672: case 2673: return 439 + c - 2672;
		case 2677: return 441;
		case 2689: case 2690: case 2691: return 442 + c - 2689;
		case 2748: return 445;
		case 2750: case 2751: case 2752: case 2753: case 2754: case 2755: case 2756: case 2757: return 446 + c - 2750;
		case 2759: case 2760: case 2761: return 454 + c - 2759;
		case 2763: case 2764: case 2765: return 457 + c - 2763;
		case 2786: case 2787: return 460 + c - 2786;
		case 2810: case 2811: case 2812: case 2813: case 2814: case 2815: return 462 + c - 2810;
		case 2817: case 2818: case 2819: return 468 + c - 2817;
		case 2876: return 471;
		case 2878: case 2879: case 2880: case 2881: case 2882: case 2883: case 2884: return 472 + c - 2878;
		case 2887: case 2888: return 479 + c - 2887;
		case 2891: case 2892: case 2893: return 481 + c - 2891;
		case 2901: case 2902: case 2903: return 484 + c - 2901;
		case 2914: case 2915: return 487 + c - 2914;
		case 2946: return 489;
		case 3006: case 3007: case 3008: case 3009: case 3010: return 490 + c - 3006;
		case 3014: case 3015: case 3016: return 495 + c - 3014;
		case 3018: case 3019: case 3020: case 3021: return 498 + c - 3018;
		case 3031: return 502;
		case 3072: case 3073: case 3074: case 3075: case 3076: return 503 + c - 3072;
		case 3132: return 508;
		case 3134: case 3135: case 3136: case 3137: case 3138: case 3139: case 3140: return 509 + c - 3134;
		case 3142: case 3143: case 3144: return 516 + c - 3142;
		case 3146: case 3147: case 3148: case 3149: return 519 + c - 3146;
		case 3157: case 3158: return 523 + c - 3157;
		case 3170: case 3171: return 525 + c - 3170;
		case 3201: case 3202: case 3203: return 527 + c - 3201;
		case 3260: return 530;
		case 3262: case 3263: case 3264: case 3265: case 3266: case 3267: case 3268: return 531 + c - 3262;
		case 3270: case 3271: case 3272: return 538 + c - 3270;
		case 3274: case 3275: case 3276: case 3277: return 541 + c - 3274;
		case 3285: case 3286: return 545 + c - 3285;
		case 3298: case 3299: return 547 + c - 3298;
		case 3315: return 549;
		case 3328: case 3329: case 3330: case 3331: return 550 + c - 3328;
		case 3387: case 3388: return 554 + c - 3387;
		case 3390: case 3391: case 3392: case 3393: case 3394: case 3395: case 3396: return 556 + c - 3390;
		case 3398: case 3399: case 3400: return 563 + c - 3398;
		case 3402: case 3403: case 3404: case 3405: return 566 + c - 3402;
		case 3415: return 570;
		case 3426: case 3427: return 571 + c - 3426;
		case 3457: case 3458: case 3459: return 573 + c - 3457;
		case 3530: return 576;
		case 3535: case 3536: case 3537: case 3538: case 3539: case 3540: return 577 + c - 3535;
		case 3542: return 583;
		case 3544: case 3545: case 3546: case 3547: case 3548: case 3549: case 3550: case 3551: return 584 + c - 3544;
		case 3570: case 3571: return 592 + c - 3570;
		case 3633: return 594;
		case 3636: case 3637: case 3638: case 3639: case 3640: case 3641: case 3642: return 595 + c - 3636;
		case 3655: case 3656: case 3657: case 3658: case 3659: case 3660: case 3661: case 3662: return 602 + c - 3655;
		case 3761: return 610;
		case 3764: case 3765: case 3766: case 3767: case 3768: case 3769: case 3770: case 3771: case 3772: return 611 + c - 3764;
		case 3784: case 3785: case 3786: case 3787: case 3788: case 3789: case 3790: return 620 + c - 3784;
		case 3864: case 3865: return 627 + c - 3864;
		case 3893: return 629;
		case 3895: return 630;
		case 3897: return 631;
		case 3902: case 3903: return 632 + c - 3902;
		case 3953: case 3954: case 3955: case 3956: case 3957: case 3958: case 3959: case 3960: case 3961: case 3962: case 3963: case 3964: case 3965: case 3966: case 3967: case 3968: case 3969: case 3970: case 3971: case 3972: return 634 + c - 3953;
		case 3974: case 3975: return 654 + c - 3974;
		case 3981: case 3982: case 3983: case 3984: case 3985: case 3986: case 3987: case 3988: case 3989: case 3990: case 3991: return 656 + c - 3981;
		case 3993: case 3994: case 3995: case 3996: case 3997: case 3998: case 3999: case 4000: case 4001: case 4002: case 4003: case 4004: case 4005: case 4006: case 4007: case 4008: case 4009: case 4010: case 4011: case 4012: case 4013: case 4014: case 4015: case 4016: case 4017: case 4018: case 4019: case 4020: case 4021: case 4022: case 4023: case 4024: case 4025: case 4026: case 4027: case 4028: return 667 + c - 3993;
		case 4038: return 703;
		case 4139: case 4140: case 4141: case 4142: case 4143: case 4144: case 4145: case 4146: case 4147: case 4148: case 4149: case 4150: case 4151: case 4152: case 4153: case 4154: case 4155: case 4156: case 4157: case 4158: return 704 + c - 4139;
		case 4182: case 4183: case 4184: case 4185: return 724 + c - 4182;
		case 4190: case 4191: case 4192: return 728 + c - 4190;
		case 4194: case 4195: case 4196: return 731 + c - 4194;
		case 4199: case 4200: case 4201: case 4202: case 4203: case 4204: case 4205: return 734 + c - 4199;
		case 4209: case 4210: case 4211: case 4212: return 741 + c - 4209;
		case 4226: case 4227: case 4228: case 4229: case 4230: case 4231: case 4232: case 4233: case 4234: case 4235: case 4236: case 4237: return 745 + c - 4226;
		case 4239: return 757;
		case 4250: case 4251: case 4252: case 4253: return 758 + c - 4250;
		case 4447: case 4448: return 762 + c - 4447;
		case 4957: case 4958: case 4959: return 764 + c - 4957;
		case 5906: case 5907: case 5908: case 5909: return 767 + c - 5906;
		case 5938: case 5939: case 5940: return 771 + c - 5938;
		case 5970: case 5971: return 774 + c - 5970;
		case 6002: case 6003: return 776 + c - 6002;
		case 6068: case 6069: case 6070: case 6071: case 6072: case 6073: case 6074: case 6075: case 6076: case 6077: case 6078: case 6079: case 6080: case 6081: case 6082: case 6083: case 6084: case 6085: case 6086: case 6087: case 6088: case 6089: case 6090: case 6091: case 6092: case 6093: case 6094: case 6095: case 6096: case 6097: case 6098: case 6099: return 778 + c - 6068;
		case 6109: return 810;
		case 6155: case 6156: case 6157: case 6158: case 6159: return 811 + c - 6155;
		case 6277: case 6278: return 816 + c - 6277;
		case 6313: return 818;
		case 6432: case 6433: case 6434: case 6435: case 6436: case 6437: case 6438: case 6439: case 6440: case 6441: case 6442: case 6443: return 819 + c - 6432;
		case 6448: case 6449: case 6450: case 6451: case 6452: case 6453: case 6454: case 6455: case 6456: case 6457: case 6458: case 6459: return 831 + c - 6448;
		case 6679: case 6680: case 6681: case 6682: case 6683: return 843 + c - 6679;
		case 6741: case 6742: case 6743: case 6744: case 6745: case 6746: case 6747: case 6748: case 6749: case 6750: return 848 + c - 6741;
		case 6752: case 6753: case 6754: case 6755: case 6756: case 6757: case 6758: case 6759: case 6760: case 6761: case 6762: case 6763: case 6764: case 6765: case 6766: case 6767: case 6768: case 6769: case 6770: case 6771: case 6772: case 6773: case 6774: case 6775: case 6776: case 6777: case 6778: case 6779: case 6780: return 858 + c - 6752;
		case 6783: return 887;
		case 6832: case 6833: case 6834: case 6835: case 6836: case 6837: case 6838: case 6839: case 6840: case 6841: case 6842: case 6843: case 6844: case 6845: case 6846: case 6847: case 6848: case 6849: case 6850: case 6851: case 6852: case 6853: case 6854: case 6855: case 6856: case 6857: case 6858: case 6859: case 6860: case 6861: case 6862: return 888 + c - 6832;
		case 6912: case 6913: case 6914: case 6915: case 6916: return 919 + c - 6912;
		case 6964: case 6965: case 6966: case 6967: case 6968: case 6969: case 6970: case 6971: case 6972: case 6973: case 6974: case 6975: case 6976: case 6977: case 6978: case 6979: case 6980: return 924 + c - 6964;
		case 7019: case 7020: case 7021: case 7022: case 7023: case 7024: case 7025: case 7026: case 7027: return 941 + c - 7019;
		case 7040: case 7041: case 7042: return 950 + c - 7040;
		case 7073: case 7074: case 7075: case 7076: case 7077: case 7078: case 7079: case 7080: case 7081: case 7082: case 7083: case 7084: case 7085: return 953 + c - 7073;
		case 7142: case 7143: case 7144: case 7145: case 7146: case 7147: case 7148: case 7149: case 7150: case 7151: case 7152: case 7153: case 7154: case 7155: return 966 + c - 7142;
		case 7204: case 7205: case 7206: case 7207: case 7208: case 7209: case 7210: case 7211: case 7212: case 7213: case 7214: case 7215: case 7216: case 7217: case 7218: case 7219: case 7220: case 7221: case 7222: case 7223: return 980 + c - 7204;
		case 7376: case 7377: case 7378: return 1000 + c - 7376;
		case 7380: case 7381: case 7382: case 7383: case 7384: case 7385: case 7386: case 7387: case 7388: case 7389: case 7390: case 7391: case 7392: case 7393: case 7394: case 7395: case 7396: case 7397: case 7398: case 7399: case 7400: return 1003 + c - 7380;
		case 7405: return 1024;
		case 7412: return 1025;
		case 7415: case 7416: case 7417: return 1026 + c - 7415;
		case 7616: case 7617: case 7618: case 7619: case 7620: case 7621: case 7622: case 7623: case 7624: case 7625: case 7626: case 7627: case 7628: case 7629: case 7630: case 7631: case 7632: case 7633: case 7634: case 7635: case 7636: case 7637: case 7638: case 7639: case 7640: case 7641: case 7642: case 7643: case 7644: case 7645: case 7646: case 7647: case 7648: case 7649: case 7650: case 7651: case 7652: case 7653: case 7654: case 7655: case 7656: case 7657: case 7658: case 7659: case 7660: case 7661: case 7662: case 7663: case 7664: case 7665: case 7666: case 7667: case 7668: case 7669: case 7670: case 7671: case 7672: case 7673: case 7674: case 7675: case 7676: case 7677: case 7678: case 7679: return 1029 + c - 7616;
		case 8203: case 8204: case 8205: case 8206: case 8207: return 1093 + c - 8203;
		case 8234: case 8235: case 8236: case 8237: case 8238: return 1098 + c - 8234;
		case 8288: case 8289: case 8290: case 8291: case 8292: case 8293: case 8294: case 8295: case 8296: case 8297: case 8298: case 8299: case 8300: case 8301: case 8302: case 8303: return 1103 + c - 8288;
		case 8400: case 8401: case 8402: case 8403: case 8404: case 8405: case 8406: case 8407: case 8408: case 8409: case 8410: case 8411: case 8412: case 8413: case 8414: case 8415: case 8416: case 8417: case 8418: case 8419: case 8420: case 8421: case 8422: case 8423: case 8424: case 8425: case 8426: case 8427: case 8428: case 8429: case 8430: case 8431: case 8432: return 1119 + c - 8400;
		case 11503: case 11504: case 11505: return 1152 + c - 11503;
		case 11647: return 1155;
		case 11744: case 11745: case 11746: case 11747: case 11748: case 11749: case 11750: case 11751: case 11752: case 11753: case 11754: case 11755: case 11756: case 11757: case 11758: case 11759: case 11760: case 11761: case 11762: case 11763: case 11764: case 11765: case 11766: case 11767: case 11768: case 11769: case 11770: case 11771: case 11772: case 11773: case 11774: case 11775: return 1156 + c - 11744;
		case 12330: case 12331: case 12332: case 12333: case 12334: case 12335: return 1188 + c - 12330;
		case 12441: case 12442: return 1194 + c - 12441;
		case 12644: return 1196;
		case 42607: case 42608: case 42609: case 42610: return 1197 + c - 42607;
		case 42612: case 42613: case 42614: case 42615: case 42616: case 42617: case 42618: case 42619: case 42620: case 42621: return 1201 + c - 42612;
		case 42654: case 42655: return 1211 + c - 42654;
		case 42736: case 42737: return 1213 + c - 42736;
		case 43010: return 1215;
		case 43014: return 1216;
		case 43019: return 1217;
		case 43043: case 43044: case 43045: case 43046: case 43047: return 1218 + c - 43043;
		case 43052: return 1223;
		case 43136: case 43137: return 1224 + c - 43136;
		case 43188: case 43189: case 43190: case 43191: case 43192: case 43193: case 43194: case 43195: case 43196: case 43197: case 43198: case 43199: case 43200: case 43201: case 43202: case 43203: case 43204: case 43205: return 1226 + c - 43188;
		case 43232: case 43233: case 43234: case 43235: case 43236: case 43237: case 43238: case 43239: case 43240: case 43241: case 43242: case 43243: case 43244: case 43245: case 43246: case 43247: case 43248: case 43249: return 1244 + c - 43232;
		case 43263: return 1262;
		case 43302: case 43303: case 43304: case 43305: case 43306: case 43307: case 43308: case 43309: return 1263 + c - 43302;
		case 43335: case 43336: case 43337: case 43338: case 43339: case 43340: case 43341: case 43342: case 43343: case 43344: case 43345: case 43346: case 43347: return 1271 + c - 43335;
		case 43392: case 43393: case 43394: case 43395: return 1284 + c - 43392;
		case 43443: case 43444: case 43445: case 43446: case 43447: case 43448: case 43449: case 43450: case 43451: case 43452: case 43453: case 43454: case 43455: case 43456: return 1288 + c - 43443;
		case 43493: return 1302;
		case 43561: case 43562: case 43563: case 43564: case 43565: case 43566: case 43567: case 43568: case 43569: case 43570: case 43571: case 43572: case 43573: case 43574: return 1303 + c - 43561;
		case 43587: return 1317;
		case 43596: case 43597: return 1318 + c - 43596;
		case 43643: case 43644: case 43645: return 1320 + c - 43643;
		case 43696: return 1323;
		case 43698: case 43699: case 43700: return 1324 + c - 43698;
		case 43703: case 43704: return 1327 + c - 43703;
		case 43710: case 43711: return 1329 + c - 43710;
		case 43713: return 1331;
		case 43755: case 43756: case 43757: case 43758: case 43759: return 1332 + c - 43755;
		case 43765: case 43766: return 1337 + c - 43765;
		case 44003: case 44004: case 44005: case 44006: case 44007: case 44008: case 44009: case 44010: return 1339 + c - 44003;
		case 44012: case 44013: return 1347 + c - 44012;
		case 64286: return 1349;
		case 65024: case 65025: case 65026: case 65027: case 65028: case 65029: case 65030: case 65031: case 65032: case 65033: case 65034: case 65035: case 65036: case 65037: case 65038: case 65039: return 1350 + c - 65024;
		case 65056: case 65057: case 65058: case 65059: case 65060: case 65061: case 65062: case 65063: case 65064: case 65065: case 65066: case 65067: case 65068: case 65069: case 65070: case 65071: return 1366 + c - 65056;
		case 65279: return 1382;
		case 65440: return 1383;
		case 65520: case 65521: case 65522: case 65523: case 65524: case 65525: case 65526: case 65527: case 65528: case 65529: case 65530: case 65531: return 1384 + c - 65520;
		case 66045: return 1396;
		case 66272: return 1397;
		case 66422: case 66423: case 66424: case 66425: case 66426: return 1398 + c - 66422;
		case 68097: case 68098: case 68099: return 1403 + c - 68097;
		case 68101: case 68102: return 1406 + c - 68101;
		case 68108: case 68109: case 68110: case 68111: return 1408 + c - 68108;
		case 68152: case 68153: case 68154: return 1412 + c - 68152;
		case 68159: return 1415;
		case 68325: case 68326: return 1416 + c - 68325;
		case 68900: case 68901: case 68902: case 68903: return 1418 + c - 68900;
		case 69291: case 69292: return 1422 + c - 69291;
		case 69373: case 69374: case 69375: return 1424 + c - 69373;
		case 69446: case 69447: case 69448: case 69449: case 69450: case 69451: case 69452: case 69453: case 69454: case 69455: case 69456: return 1427 + c - 69446;
		case 69506: case 69507: case 69508: case 69509: return 1438 + c - 69506;
		case 69632: case 69633: case 69634: return 1442 + c - 69632;
		case 69688: case 69689: case 69690: case 69691: case 69692: case 69693: case 69694: case 69695: case 69696: case 69697: case 69698: case 69699: case 69700: case 69701: case 69702: return 1445 + c - 69688;
		case 69744: return 1460;
		case 69747: case 69748: return 1461 + c - 69747;
		case 69759: case 69760: case 69761: case 69762: return 1463 + c - 69759;
		case 69808: case 69809: case 69810: case 69811: case 69812: case 69813: case 69814: case 69815: case 69816: case 69817: case 69818: return 1467 + c - 69808;
		case 69821: return 1478;
		case 69826: return 1479;
		case 69837: return 1480;
		case 69888: case 69889: case 69890: return 1481 + c - 69888;
		case 69927: case 69928: case 69929: case 69930: case 69931: case 69932: case 69933: case 69934: case 69935: case 69936: case 69937: case 69938: case 69939: case 69940: return 1484 + c - 69927;
		case 69957: case 69958: return 1498 + c - 69957;
		case 70003: return 1500;
		case 70016: case 70017: case 70018: return 1501 + c - 70016;
		case 70067: case 70068: case 70069: case 70070: case 70071: case 70072: case 70073: case 70074: case 70075: case 70076: case 70077: case 70078: case 70079: case 70080: return 1504 + c - 70067;
		case 70089: case 70090: case 70091: case 70092: return 1518 + c - 70089;
		case 70094: case 70095: return 1522 + c - 70094;
		case 70188: case 70189: case 70190: case 70191: case 70192: case 70193: case 70194: case 70195: case 70196: case 70197: case 70198: case 70199: return 1524 + c - 70188;
		case 70206: return 1536;
		case 70209: return 1537;
		case 70367: case 70368: case 70369: case 70370: case 70371: case 70372: case 70373: case 70374: case 70375: case 70376: case 70377: case 70378: return 1538 + c - 70367;
		case 70400: case 70401: case 70402: case 70403: return 1550 + c - 70400;
		case 70459: case 70460: return 1554 + c - 70459;
		case 70462: case 70463: case 70464: case 70465: case 70466: case 70467: case 70468: return 1556 + c - 70462;
		case 70471: case 70472: return 1563 + c - 70471;
		case 70475: case 70476: case 70477: return 1565 + c - 70475;
		case 70487: return 1568;
		case 70498: case 70499: return 1569 + c - 70498;
		case 70502: case 70503: case 70504: case 70505: case 70506: case 70507: case 70508: return 1571 + c - 70502;
		case 70512: case 70513: case 70514: case 70515: case 70516: return 1578 + c - 70512;
		case 70709: case 70710: case 70711: case 70712: case 70713: case 70714: case 70715: case 70716: case 70717: case 70718: case 70719: case 70720: case 70721: case 70722: case 70723: case 70724: case 70725: case 70726: return 1583 + c - 70709;
		case 70750: return 1601;
		case 70832: case 70833: case 70834: case 70835: case 70836: case 70837: case 70838: case 70839: case 70840: case 70841: case 70842: case 70843: case 70844: case 70845: case 70846: case 70847: case 70848: case 70849: case 70850: case 70851: return 1602 + c - 70832;
		case 71087: case 71088: case 71089: case 71090: case 71091: case 71092: case 71093: return 1622 + c - 71087;
		case 71096: case 71097: case 71098: case 71099: case 71100: case 71101: case 71102: case 71103: case 71104: return 1629 + c - 71096;
		case 71132: case 71133: return 1638 + c - 71132;
		case 71216: case 71217: case 71218: case 71219: case 71220: case 71221: case 71222: case 71223: case 71224: case 71225: case 71226: case 71227: case 71228: case 71229: case 71230: case 71231: case 71232: return 1640 + c - 71216;
		case 71339: case 71340: case 71341: case 71342: case 71343: case 71344: case 71345: case 71346: case 71347: case 71348: case 71349: case 71350: case 71351: return 1657 + c - 71339;
		case 71453: case 71454: case 71455: case 71456: case 71457: case 71458: case 71459: case 71460: case 71461: case 71462: case 71463: case 71464: case 71465: case 71466: case 71467: return 1670 + c - 71453;
		case 71724: case 71725: case 71726: case 71727: case 71728: case 71729: case 71730: case 71731: case 71732: case 71733: case 71734: case 71735: case 71736: case 71737: case 71738: return 1685 + c - 71724;
		case 71984: case 71985: case 71986: case 71987: case 71988: case 71989: return 1700 + c - 71984;
		case 71991: case 71992: return 1706 + c - 71991;
		case 71995: case 71996: case 71997: case 71998: return 1708 + c - 71995;
		case 72000: return 1712;
		case 72002: case 72003: return 1713 + c - 72002;
		case 72145: case 72146: case 72147: case 72148: case 72149: case 72150: case 72151: return 1715 + c - 72145;
		case 72154: case 72155: case 72156: case 72157: case 72158: case 72159: case 72160: return 1722 + c - 72154;
		case 72164: return 1729;
		case 72193: case 72194: case 72195: case 72196: case 72197: case 72198: case 72199: case 72200: case 72201: case 72202: return 1730 + c - 72193;
		case 72243: case 72244: case 72245: case 72246: case 72247: case 72248: case 72249: return 1740 + c - 72243;
		case 72251: case 72252: case 72253: case 72254: return 1747 + c - 72251;
		case 72263: return 1751;
		case 72273: case 72274: case 72275: case 72276: case 72277: case 72278: case 72279: case 72280: case 72281: case 72282: case 72283: return 1752 + c - 72273;
		case 72330: case 72331: case 72332: case 72333: case 72334: case 72335: case 72336: case 72337: case 72338: case 72339: case 72340: case 72341: case 72342: case 72343: case 72344: case 72345: return 1763 + c - 72330;
		case 72751: case 72752: case 72753: case 72754: case 72755: case 72756: case 72757: case 72758: return 1779 + c - 72751;
		case 72760: case 72761: case 72762: case 72763: case 72764: case 72765: case 72766: case 72767: return 1787 + c - 72760;
		case 72850: case 72851: case 72852: case 72853: case 72854: case 72855: case 72856: case 72857: case 72858: case 72859: case 72860: case 72861: case 72862: case 72863: case 72864: case 72865: case 72866: case 72867: case 72868: case 72869: case 72870: case 72871: return 1795 + c - 72850;
		case 72873: case 72874: case 72875: case 72876: case 72877: case 72878: case 72879: case 72880: case 72881: case 72882: case 72883: case 72884: case 72885: case 72886: return 1817 + c - 72873;
		case 73009: case 73010: case 73011: case 73012: case 73013: case 73014: return 1831 + c - 73009;
		case 73018: return 1837;
		case 73020: case 73021: return 1838 + c - 73020;
		case 73023: case 73024: case 73025: case 73026: case 73027: case 73028: case 73029: return 1840 + c - 73023;
		case 73031: return 1847;
		case 73098: case 73099: case 73100: case 73101: case 73102: return 1848 + c - 73098;
		case 73104: case 73105: return 1853 + c - 73104;
		case 73107: case 73108: case 73109: case 73110: case 73111: return 1855 + c - 73107;
		case 73459: case 73460: case 73461: case 73462: return 1860 + c - 73459;
		case 73472: case 73473: return 1864 + c - 73472;
		case 73475: return 1866;
		case 73524: case 73525: case 73526: case 73527: case 73528: case 73529: case 73530: return 1867 + c - 73524;
		case 73534: case 73535: case 73536: case 73537: case 73538: return 1874 + c - 73534;
		case 78896: case 78897: case 78898: case 78899: case 78900: case 78901: case 78902: case 78903: case 78904: case 78905: case 78906: case 78907: case 78908: case 78909: case 78910: case 78911: case 78912: return 1879 + c - 78896;
		case 78919: case 78920: case 78921: case 78922: case 78923: case 78924: case 78925: case 78926: case 78927: case 78928: case 78929: case 78930: case 78931: case 78932: case 78933: return 1896 + c - 78919;
		case 92912: case 92913: case 92914: case 92915: case 92916: return 1911 + c - 92912;
		case 92976: case 92977: case 92978: case 92979: case 92980: case 92981: case 92982: return 1916 + c - 92976;
		case 94031: return 1923;
		case 94033: case 94034: case 94035: case 94036: case 94037: case 94038: case 94039: case 94040: case 94041: case 94042: case 94043: case 94044: case 94045: case 94046: case 94047: case 94048: case 94049: case 94050: case 94051: case 94052: case 94053: case 94054: case 94055: case 94056: case 94057: case 94058: case 94059: case 94060: case 94061: case 94062: case 94063: case 94064: case 94065: case 94066: case 94067: case 94068: case 94069: case 94070: case 94071: case 94072: case 94073: case 94074: case 94075: case 94076: case 94077: case 94078: case 94079: case 94080: case 94081: case 94082: case 94083: case 94084: case 94085: case 94086: case 94087: return 1924 + c - 94033;
		case 94095: case 94096: case 94097: case 94098: return 1979 + c - 94095;
		case 94180: return 1983;
		case 94192: case 94193: return 1984 + c - 94192;
		case 113821: case 113822: return 1986 + c - 113821;
		case 113824: case 113825: case 113826: case 113827: return 1988 + c - 113824;
		case 118528: case 118529: case 118530: case 118531: case 118532: case 118533: case 118534: case 118535: case 118536: case 118537: case 118538: case 118539: case 118540: case 118541: case 118542: case 118543: case 118544: case 118545: case 118546: case 118547: case 118548: case 118549: case 118550: case 118551: case 118552: case 118553: case 118554: case 118555: case 118556: case 118557: case 118558: case 118559: case 118560: case 118561: case 118562: case 118563: case 118564: case 118565: case 118566: case 118567: case 118568: case 118569: case 118570: case 118571: case 118572: case 118573: return 1992 + c - 118528;
		case 118576: case 118577: case 118578: case 118579: case 118580: case 118581: case 118582: case 118583: case 118584: case 118585: case 118586: case 118587: case 118588: case 118589: case 118590: case 118591: case 118592: case 118593: case 118594: case 118595: case 118596: case 118597: case 118598: return 2038 + c - 118576;
		case 119141: case 119142: case 119143: case 119144: case 119145: return 2061 + c - 119141;
		case 119149: case 119150: case 119151: case 119152: case 119153: case 119154: case 119155: case 119156: case 119157: case 119158: case 119159: case 119160: case 119161: case 119162: case 119163: case 119164: case 119165: case 119166: case 119167: case 119168: case 119169: case 119170: return 2066 + c - 119149;
		case 119173: case 119174: case 119175: case 119176: case 119177: case 119178: case 119179: return 2088 + c - 119173;
		case 119210: case 119211: case 119212: case 119213: return 2095 + c - 119210;
		case 119362: case 119363: case 119364: return 2099 + c - 119362;
		case 121344: case 121345: case 121346: case 121347: case 121348: case 121349: case 121350: case 121351: case 121352: case 121353: case 121354: case 121355: case 121356: case 121357: case 121358: case 121359: case 121360: case 121361: case 121362: case 121363: case 121364: case 121365: case 121366: case 121367: case 121368: case 121369: case 121370: case 121371: case 121372: case 121373: case 121374: case 121375: case 121376: case 121377: case 121378: case 121379: case 121380: case 121381: case 121382: case 121383: case 121384: case 121385: case 121386: case 121387: case 121388: case 121389: case 121390: case 121391: case 121392: case 121393: case 121394: case 121395: case 121396: case 121397: case 121398: return 2102 + c - 121344;
		case 121403: case 121404: case 121405: case 121406: case 121407: case 121408: case 121409: case 121410: case 121411: case 121412: case 121413: case 121414: case 121415: case 121416: case 121417: case 121418: case 121419: case 121420: case 121421: case 121422: case 121423: case 121424: case 121425: case 121426: case 121427: case 121428: case 121429: case 121430: case 121431: case 121432: case 121433: case 121434: case 121435: case 121436: case 121437: case 121438: case 121439: case 121440: case 121441: case 121442: case 121443: case 121444: case 121445: case 121446: case 121447: case 121448: case 121449: case 121450: case 121451: case 121452: return 2157 + c - 121403;
		case 121461: return 2207;
		case 121476: return 2208;
		case 121499: case 121500: case 121501: case 121502: case 121503: return 2209 + c - 121499;
		case 121505: case 121506: case 121507: case 121508: case 121509: case 121510: case 121511: case 121512: case 121513: case 121514: case 121515: case 121516: case 121517: case 121518: case 121519: return 2214 + c - 121505;
		case 122880: case 122881: case 122882: case 122883: case 122884: case 122885: case 122886: return 2229 + c - 122880;
		case 122888: case 122889: case 122890: case 122891: case 122892: case 122893: case 122894: case 122895: case 122896: case 122897: case 122898: case 122899: case 122900: case 122901: case 122902: case 122903: case 122904: return 2236 + c - 122888;
		case 122907: case 122908: case 122909: case 122910: case 122911: case 122912: case 122913: return 2253 + c - 122907;
		case 122915: case 122916: return 2260 + c - 122915;
		case 122918: case 122919: case 122920: case 122921: case 122922: return 2262 + c - 122918;
		case 123023: return 2267;
		case 123184: case 123185: case 123186: case 123187: case 123188: case 123189: case 123190: return 2268 + c - 123184;
		case 123566: return 2275;
		case 123628: case 123629: case 123630: case 123631: return 2276 + c - 123628;
		case 124140: case 124141: case 124142: case 124143: return 2280 + c - 124140;
		case 125136: case 125137: case 125138: case 125139: case 125140: case 125141: case 125142: return 2284 + c - 125136;
		case 125252: case 125253: case 125254: case 125255: case 125256: case 125257: case 125258: return 2291 + c - 125252;
		case 127462: case 127463: case 127464: case 127465: case 127466: case 127467: case 127468: case 127469: case 127470: case 127471: case 127472: case 127473: case 127474: case 127475: case 127476: case 127477: case 127478: case 127479: case 127480: case 127481: case 127482: case 127483: case 127484: case 127485: case 127486: case 127487: return 2298 + c - 127462;
		case 127995: case 127996: case 127997: case 127998: case 127999: return 2324 + c - 127995;
		case 917504: case 917505: case 917506: case 917507: case 917508: case 917509: case 917510: case 917511: case 917512: case 917513: case 917514: case 917515: case 917516: case 917517: case 917518: case 917519: case 917520: case 917521: case 917522: case 917523: case 917524: case 917525: case 917526: case 917527: case 917528: case 917529: case 917530: case 917531: case 917532: case 917533: case 917534: case 917535: case 917536: case 917537: case 917538: case 917539: case 917540: case 917541: case 917542: case 917543: case 917544: case 917545: case 917546: case 917547: case 917548: case 917549: case 917550: case 917551: case 917552: case 917553: case 917554: case 917555: case 917556: case 917557: case 917558: case 917559: case 917560: case 917561: case 917562: case 917563: case 917564: case 917565: case 917566: case 917567: case 917568: case 917569: case 917570: case 917571: case 917572: case 917573: case 917574: case 917575: case 917576: case 917577: case 917578: case 917579: case 917580: case 917581: case 917582: case 917583: case 917584: case 917585: case 917586: case 917587: case 917588: case 917589: case 917590: case 917591: case 917592: case 917593: case 917594: case 917595: case 917596: case 917597: case 917598: case 917599: case 917600: case 917601: case 917602: case 917603: case 917604: case 917605: case 917606: case 917607: case 917608: case 917609: case 917610: case 917611: case 917612: case 917613: case 917614: case 917615: case 917616: case 917617: case 917618: case 917619: case 917620: case 917621: case 917622: case 917623: case 917624: case 917625: case 917626: case 917627: case 917628: case 917629: case 917630: case 917631: case 917632: case 917633: case 917634: case 917635: case 917636: case 917637: case 917638: case 917639: case 917640: case 917641: case 917642: case 917643: case 917644: case 917645: case 917646: case 917647: case 917648: case 917649: case 917650: case 917651: case 917652: case 917653: case 917654: case 917655: case 917656: case 917657: case 917658: case 917659: case 917660: case 917661: case 917662: case 917663: case 917664: case 917665: case 917666: case 917667: case 917668: case 917669: case 917670: case 917671: case 917672: case 917673: case 917674: case 917675: case 917676: case 917677: case 917678: case 917679: case 917680: case 917681: case 917682: case 917683: case 917684: case 917685: case 917686: case 917687: case 917688: case 917689: case 917690: case 917691: case 917692: case 917693: case 917694: case 917695: case 917696: case 917697: case 917698: case 917699: case 917700: case 917701: case 917702: case 917703: case 917704: case 917705: case 917706: case 917707: case 917708: case 917709: case 917710: case 917711: case 917712: case 917713: case 917714: case 917715: case 917716: case 917717: case 917718: case 917719: case 917720: case 917721: case 917722: case 917723: case 917724: case 917725: case 917726: case 917727: case 917728: case 917729: case 917730: case 917731: case 917732: case 917733: case 917734: case 917735: case 917736: case 917737: case 917738: case 917739: case 917740: case 917741: case 917742: case 917743: case 917744: case 917745: case 917746: case 917747: case 917748: case 917749: case 917750: case 917751: case 917752: case 917753: case 917754: case 917755: case 917756: case 917757: case 917758: case 917759: case 917760: case 917761: case 917762: case 917763: case 917764: case 917765: case 917766: case 917767: case 917768: case 917769: case 917770: case 917771: case 917772: case 917773: case 917774: case 917775: case 917776: case 917777: case 917778: case 917779: case 917780: case 917781: case 917782: case 917783: case 917784: case 917785: case 917786: case 917787: case 917788: case 917789: case 917790: case 917791: case 917792: case 917793: case 917794: case 917795: case 917796: case 917797: case 917798: case 917799: case 917800: case 917801: case 917802: case 917803: case 917804: case 917805: case 917806: case 917807: case 917808: case 917809: case 917810: case 917811: case 917812: case 917813: case 917814: case 917815: case 917816: case 917817: case 917818: case 917819: case 917820: case 917821: case 917822: case 917823: case 917824: case 917825: case 917826: case 917827: case 917828: case 917829: case 917830: case 917831: case 917832: case 917833: case 917834: case 917835: case 917836: case 917837: case 917838: case 917839: case 917840: case 917841: case 917842: case 917843: case 917844: case 917845: case 917846: case 917847: case 917848: case 917849: case 917850: case 917851: case 917852: case 917853: case 917854: case 917855: case 917856: case 917857: case 917858: case 917859: case 917860: case 917861: case 917862: case 917863: case 917864: case 917865: case 917866: case 917867: case 917868: case 917869: case 917870: case 917871: case 917872: case 917873: case 917874: case 917875: case 917876: case 917877: case 917878: case 917879: case 917880: case 917881: case 917882: case 917883: case 917884: case 917885: case 917886: case 917887: case 917888: case 917889: case 917890: case 917891: case 917892: case 917893: case 917894: case 917895: case 917896: case 917897: case 917898: case 917899: case 917900: case 917901: case 917902: case 917903: case 917904: case 917905: case 917906: case 917907: case 917908: case 917909: case 917910: case 917911: case 917912: case 917913: case 917914: case 917915: case 917916: case 917917: case 917918: case 917919: case 917920: case 917921: case 917922: case 917923: case 917924: case 917925: case 917926: case 917927: case 917928: case 917929: case 917930: case 917931: case 917932: case 917933: case 917934: case 917935: case 917936: case 917937: case 917938: case 917939: case 917940: case 917941: case 917942: case 917943: case 917944: case 917945: case 917946: case 917947: case 917948: case 917949: case 917950: case 917951: case 917952: case 917953: case 917954: case 917955: case 917956: case 917957: case 917958: case 917959: case 917960: case 917961: case 917962: case 917963: case 917964: case 917965: case 917966: case 917967: case 917968: case 917969: case 917970: case 917971: case 917972: case 917973: case 917974: case 917975: case 917976: case 917977: case 917978: case 917979: case 917980: case 917981: case 917982: case 917983: case 917984: case 917985: case 917986: case 917987: case 917988: case 917989: case 917990: case 917991: case 917992: case 917993: case 917994: case 917995: case 917996: case 917997: case 917998: case 917999: case 918000: case 918001: case 918002: case 918003: case 918004: case 918005: case 918006: case 918007: case 918008: case 918009: case 918010: case 918011: case 918012: case 918013: case 918014: case 918015: case 918016: case 918017: case 918018: case 918019: case 918020: case 918021: case 918022: case 918023: case 918024: case 918025: case 918026: case 918027: case 918028: case 918029: case 918030: case 918031: case 918032: case 918033: case 918034: case 918035: case 918036: case 918037: case 918038: case 918039: case 918040: case 918041: case 918042: case 918043: case 918044: case 918045: case 918046: case 918047: case 918048: case 918049: case 918050: case 918051: case 918052: case 918053: case 918054: case 918055: case 918056: case 918057: case 918058: case 918059: case 918060: case 918061: case 918062: case 918063: case 918064: case 918065: case 918066: case 918067: case 918068: case 918069: case 918070: case 918071: case 918072: case 918073: case 918074: case 918075: case 918076: case 918077: case 918078: case 918079: case 918080: case 918081: case 918082: case 918083: case 918084: case 918085: case 918086: case 918087: case 918088: case 918089: case 918090: case 918091: case 918092: case 918093: case 918094: case 918095: case 918096: case 918097: case 918098: case 918099: case 918100: case 918101: case 918102: case 918103: case 918104: case 918105: case 918106: case 918107: case 918108: case 918109: case 918110: case 918111: case 918112: case 918113: case 918114: case 918115: case 918116: case 918117: case 918118: case 918119: case 918120: case 918121: case 918122: case 918123: case 918124: case 918125: case 918126: case 918127: case 918128: case 918129: case 918130: case 918131: case 918132: case 918133: case 918134: case 918135: case 918136: case 918137: case 918138: case 918139: case 918140: case 918141: case 918142: case 918143: case 918144: case 918145: case 918146: case 918147: case 918148: case 918149: case 918150: case 918151: case 918152: case 918153: case 918154: case 918155: case 918156: case 918157: case 918158: case 918159: case 918160: case 918161: case 918162: case 918163: case 918164: case 918165: case 918166: case 918167: case 918168: case 918169: case 918170: case 918171: case 918172: case 918173: case 918174: case 918175: case 918176: case 918177: case 918178: case 918179: case 918180: case 918181: case 918182: case 918183: case 918184: case 918185: case 918186: case 918187: case 918188: case 918189: case 918190: case 918191: case 918192: case 918193: case 918194: case 918195: case 918196: case 918197: case 918198: case 918199: case 918200: case 918201: case 918202: case 918203: case 918204: case 918205: case 918206: case 918207: case 918208: case 918209: case 918210: case 918211: case 918212: case 918213: case 918214: case 918215: case 918216: case 918217: case 918218: case 918219: case 918220: case 918221: case 918222: case 918223: case 918224: case 918225: case 918226: case 918227: case 918228: case 918229: case 918230: case 918231: case 918232: case 918233: case 918234: case 918235: case 918236: case 918237: case 918238: case 918239: case 918240: case 918241: case 918242: case 918243: case 918244: case 918245: case 918246: case 918247: case 918248: case 918249: case 918250: case 918251: case 918252: case 918253: case 918254: case 918255: case 918256: case 918257: case 918258: case 918259: case 918260: case 918261: case 918262: case 918263: case 918264: case 918265: case 918266: case 918267: case 918268: case 918269: case 918270: case 918271: case 918272: case 918273: case 918274: case 918275: case 918276: case 918277: case 918278: case 918279: case 918280: case 918281: case 918282: case 918283: case 918284: case 918285: case 918286: case 918287: case 918288: case 918289: case 918290: case 918291: case 918292: case 918293: case 918294: case 918295: case 918296: case 918297: case 918298: case 918299: case 918300: case 918301: case 918302: case 918303: case 918304: case 918305: case 918306: case 918307: case 918308: case 918309: case 918310: case 918311: case 918312: case 918313: case 918314: case 918315: case 918316: case 918317: case 918318: case 918319: case 918320: case 918321: case 918322: case 918323: case 918324: case 918325: case 918326: case 918327: case 918328: case 918329: case 918330: case 918331: case 918332: case 918333: case 918334: case 918335: case 918336: case 918337: case 918338: case 918339: case 918340: case 918341: case 918342: case 918343: case 918344: case 918345: case 918346: case 918347: case 918348: case 918349: case 918350: case 918351: case 918352: case 918353: case 918354: case 918355: case 918356: case 918357: case 918358: case 918359: case 918360: case 918361: case 918362: case 918363: case 918364: case 918365: case 918366: case 918367: case 918368: case 918369: case 918370: case 918371: case 918372: case 918373: case 918374: case 918375: case 918376: case 918377: case 918378: case 918379: case 918380: case 918381: case 918382: case 918383: case 918384: case 918385: case 918386: case 918387: case 918388: case 918389: case 918390: case 918391: case 918392: case 918393: case 918394: case 918395: case 918396: case 918397: case 918398: case 918399: case 918400: case 918401: case 918402: case 918403: case 918404: case 918405: case 918406: case 918407: case 918408: case 918409: case 918410: case 918411: case 918412: case 918413: case 918414: case 918415: case 918416: case 918417: case 918418: case 918419: case 918420: case 918421: case 918422: case 918423: case 918424: case 918425: case 918426: case 918427: case 918428: case 918429: case 918430: case 918431: case 918432: case 918433: case 918434: case 918435: case 918436: case 918437: case 918438: case 918439: case 918440: case 918441: case 918442: case 918443: case 918444: case 918445: case 918446: case 918447: case 918448: case 918449: case 918450: case 918451: case 918452: case 918453: case 918454: case 918455: case 918456: case 918457: case 918458: case 918459: case 918460: case 918461: case 918462: case 918463: case 918464: case 918465: case 918466: case 918467: case 918468: case 918469: case 918470: case 918471: case 918472: case 918473: case 918474: case 918475: case 918476: case 918477: case 918478: case 918479: case 918480: case 918481: case 918482: case 918483: case 918484: case 918485: case 918486: case 918487: case 918488: case 918489: case 918490: case 918491: case 918492: case 918493: case 918494: case 918495: case 918496: case 918497: case 918498: case 918499: case 918500: case 918501: case 918502: case 918503: case 918504: case 918505: case 918506: case 918507: case 918508: case 918509: case 918510: case 918511: case 918512: case 918513: case 918514: case 918515: case 918516: case 918517: case 918518: case 918519: case 918520: case 918521: case 918522: case 918523: case 918524: case 918525: case 918526: case 918527: case 918528: case 918529: case 918530: case 918531: case 918532: case 918533: case 918534: case 918535: case 918536: case 918537: case 918538: case 918539: case 918540: case 918541: case 918542: case 918543: case 918544: case 918545: case 918546: case 918547: case 918548: case 918549: case 918550: case 918551: case 918552: case 918553: case 918554: case 918555: case 918556: case 918557: case 918558: case 918559: case 918560: case 918561: case 918562: case 918563: case 918564: case 918565: case 918566: case 918567: case 918568: case 918569: case 918570: case 918571: case 918572: case 918573: case 918574: case 918575: case 918576: case 918577: case 918578: case 918579: case 918580: case 918581: case 918582: case 918583: case 918584: case 918585: case 918586: case 918587: case 918588: case 918589: case 918590: case 918591: case 918592: case 918593: case 918594: case 918595: case 918596: case 918597: case 918598: case 918599: case 918600: case 918601: case 918602: case 918603: case 918604: case 918605: case 918606: case 918607: case 918608: case 918609: case 918610: case 918611: case 918612: case 918613: case 918614: case 918615: case 918616: case 918617: case 918618: case 918619: case 918620: case 918621: case 918622: case 918623: case 918624: case 918625: case 918626: case 918627: case 918628: case 918629: case 918630: case 918631: case 918632: case 918633: case 918634: case 918635: case 918636: case 918637: case 918638: case 918639: case 918640: case 918641: case 918642: case 918643: case 918644: case 918645: case 918646: case 918647: case 918648: case 918649: case 918650: case 918651: case 918652: case 918653: case 918654: case 918655: case 918656: case 918657: case 918658: case 918659: case 918660: case 918661: case 918662: case 918663: case 918664: case 918665: case 918666: case 918667: case 918668: case 918669: case 918670: case 918671: case 918672: case 918673: case 918674: case 918675: case 918676: case 918677: case 918678: case 918679: case 918680: case 918681: case 918682: case 918683: case 918684: case 918685: case 918686: case 918687: case 918688: case 918689: case 918690: case 918691: case 918692: case 918693: case 918694: case 918695: case 918696: case 918697: case 918698: case 918699: case 918700: case 918701: case 918702: case 918703: case 918704: case 918705: case 918706: case 918707: case 918708: case 918709: case 918710: case 918711: case 918712: case 918713: case 918714: case 918715: case 918716: case 918717: case 918718: case 918719: case 918720: case 918721: case 918722: case 918723: case 918724: case 918725: case 918726: case 918727: case 918728: case 918729: case 918730: case 918731: case 918732: case 918733: case 918734: case 918735: case 918736: case 918737: case 918738: case 918739: case 918740: case 918741: case 918742: case 918743: case 918744: case 918745: case 918746: case 918747: case 918748: case 918749: case 918750: case 918751: case 918752: case 918753: case 918754: case 918755: case 918756: case 918757: case 918758: case 918759: case 918760: case 918761: case 918762: case 918763: case 918764: case 918765: case 918766: case 918767: case 918768: case 918769: case 918770: case 918771: case 918772: case 918773: case 918774: case 918775: case 918776: case 918777: case 918778: case 918779: case 918780: case 918781: case 918782: case 918783: case 918784: case 918785: case 918786: case 918787: case 918788: case 918789: case 918790: case 918791: case 918792: case 918793: case 918794: case 918795: case 918796: case 918797: case 918798: case 918799: case 918800: case 918801: case 918802: case 918803: case 918804: case 918805: case 918806: case 918807: case 918808: case 918809: case 918810: case 918811: case 918812: case 918813: case 918814: case 918815: case 918816: case 918817: case 918818: case 918819: case 918820: case 918821: case 918822: case 918823: case 918824: case 918825: case 918826: case 918827: case 918828: case 918829: case 918830: case 918831: case 918832: case 918833: case 918834: case 918835: case 918836: case 918837: case 918838: case 918839: case 918840: case 918841: case 918842: case 918843: case 918844: case 918845: case 918846: case 918847: case 918848: case 918849: case 918850: case 918851: case 918852: case 918853: case 918854: case 918855: case 918856: case 918857: case 918858: case 918859: case 918860: case 918861: case 918862: case 918863: case 918864: case 918865: case 918866: case 918867: case 918868: case 918869: case 918870: case 918871: case 918872: case 918873: case 918874: case 918875: case 918876: case 918877: case 918878: case 918879: case 918880: case 918881: case 918882: case 918883: case 918884: case 918885: case 918886: case 918887: case 918888: case 918889: case 918890: case 918891: case 918892: case 918893: case 918894: case 918895: case 918896: case 918897: case 918898: case 918899: case 918900: case 918901: case 918902: case 918903: case 918904: case 918905: case 918906: case 918907: case 918908: case 918909: case 918910: case 918911: case 918912: case 918913: case 918914: case 918915: case 918916: case 918917: case 918918: case 918919: case 918920: case 918921: case 918922: case 918923: case 918924: case 918925: case 918926: case 918927: case 918928: case 918929: case 918930: case 918931: case 918932: case 918933: case 918934: case 918935: case 918936: case 918937: case 918938: case 918939: case 918940: case 918941: case 918942: case 918943: case 918944: case 918945: case 918946: case 918947: case 918948: case 918949: case 918950: case 918951: case 918952: case 918953: case 918954: case 918955: case 918956: case 918957: case 918958: case 918959: case 918960: case 918961: case 918962: case 918963: case 918964: case 918965: case 918966: case 918967: case 918968: case 918969: case 918970: case 918971: case 918972: case 918973: case 918974: case 918975: case 918976: case 918977: case 918978: case 918979: case 918980: case 918981: case 918982: case 918983: case 918984: case 918985: case 918986: case 918987: case 918988: case 918989: case 918990: case 918991: case 918992: case 918993: case 918994: case 918995: case 918996: case 918997: case 918998: case 918999: case 919000: case 919001: case 919002: case 919003: case 919004: case 919005: case 919006: case 919007: case 919008: case 919009: case 919010: case 919011: case 919012: case 919013: case 919014: case 919015: case 919016: case 919017: case 919018: case 919019: case 919020: case 919021: case 919022: case 919023: case 919024: case 919025: case 919026: case 919027: case 919028: case 919029: case 919030: case 919031: case 919032: case 919033: case 919034: case 919035: case 919036: case 919037: case 919038: case 919039: case 919040: case 919041: case 919042: case 919043: case 919044: case 919045: case 919046: case 919047: case 919048: case 919049: case 919050: case 919051: case 919052: case 919053: case 919054: case 919055: case 919056: case 919057: case 919058: case 919059: case 919060: case 919061: case 919062: case 919063: case 919064: case 919065: case 919066: case 919067: case 919068: case 919069: case 919070: case 919071: case 919072: case 919073: case 919074: case 919075: case 919076: case 919077: case 919078: case 919079: case 919080: case 919081: case 919082: case 919083: case 919084: case 919085: case 919086: case 919087: case 919088: case 919089: case 919090: case 919091: case 919092: case 919093: case 919094: case 919095: case 919096: case 919097: case 919098: case 919099: case 919100: case 919101: case 919102: case 919103: case 919104: case 919105: case 919106: case 919107: case 919108: case 919109: case 919110: case 919111: case 919112: case 919113: case 919114: case 919115: case 919116: case 919117: case 919118: case 919119: case 919120: case 919121: case 919122: case 919123: case 919124: case 919125: case 919126: case 919127: case 919128: case 919129: case 919130: case 919131: case 919132: case 919133: case 919134: case 919135: case 919136: case 919137: case 919138: case 919139: case 919140: case 919141: case 919142: case 919143: case 919144: case 919145: case 919146: case 919147: case 919148: case 919149: case 919150: case 919151: case 919152: case 919153: case 919154: case 919155: case 919156: case 919157: case 919158: case 919159: case 919160: case 919161: case 919162: case 919163: case 919164: case 919165: case 919166: case 919167: case 919168: case 919169: case 919170: case 919171: case 919172: case 919173: case 919174: case 919175: case 919176: case 919177: case 919178: case 919179: case 919180: case 919181: case 919182: case 919183: case 919184: case 919185: case 919186: case 919187: case 919188: case 919189: case 919190: case 919191: case 919192: case 919193: case 919194: case 919195: case 919196: case 919197: case 919198: case 919199: case 919200: case 919201: case 919202: case 919203: case 919204: case 919205: case 919206: case 919207: case 919208: case 919209: case 919210: case 919211: case 919212: case 919213: case 919214: case 919215: case 919216: case 919217: case 919218: case 919219: case 919220: case 919221: case 919222: case 919223: case 919224: case 919225: case 919226: case 919227: case 919228: case 919229: case 919230: case 919231: case 919232: case 919233: case 919234: case 919235: case 919236: case 919237: case 919238: case 919239: case 919240: case 919241: case 919242: case 919243: case 919244: case 919245: case 919246: case 919247: case 919248: case 919249: case 919250: case 919251: case 919252: case 919253: case 919254: case 919255: case 919256: case 919257: case 919258: case 919259: case 919260: case 919261: case 919262: case 919263: case 919264: case 919265: case 919266: case 919267: case 919268: case 919269: case 919270: case 919271: case 919272: case 919273: case 919274: case 919275: case 919276: case 919277: case 919278: case 919279: case 919280: case 919281: case 919282: case 919283: case 919284: case 919285: case 919286: case 919287: case 919288: case 919289: case 919290: case 919291: case 919292: case 919293: case 919294: case 919295: case 919296: case 919297: case 919298: case 919299: case 919300: case 919301: case 919302: case 919303: case 919304: case 919305: case 919306: case 919307: case 919308: case 919309: case 919310: case 919311: case 919312: case 919313: case 919314: case 919315: case 919316: case 919317: case 919318: case 919319: case 919320: case 919321: case 919322: case 919323: case 919324: case 919325: case 919326: case 919327: case 919328: case 919329: case 919330: case 919331: case 919332: case 919333: case 919334: case 919335: case 919336: case 919337: case 919338: case 919339: case 919340: case 919341: case 919342: case 919343: case 919344: case 919345: case 919346: case 919347: case 919348: case 919349: case 919350: case 919351: case 919352: case 919353: case 919354: case 919355: case 919356: case 919357: case 919358: case 919359: case 919360: case 919361: case 919362: case 919363: case 919364: case 919365: case 919366: case 919367: case 919368: case 919369: case 919370: case 919371: case 919372: case 919373: case 919374: case 919375: case 919376: case 919377: case 919378: case 919379: case 919380: case 919381: case 919382: case 919383: case 919384: case 919385: case 919386: case 919387: case 919388: case 919389: case 919390: case 919391: case 919392: case 919393: case 919394: case 919395: case 919396: case 919397: case 919398: case 919399: case 919400: case 919401: case 919402: case 919403: case 919404: case 919405: case 919406: case 919407: case 919408: case 919409: case 919410: case 919411: case 919412: case 919413: case 919414: case 919415: case 919416: case 919417: case 919418: case 919419: case 919420: case 919421: case 919422: case 919423: case 919424: case 919425: case 919426: case 919427: case 919428: case 919429: case 919430: case 919431: case 919432: case 919433: case 919434: case 919435: case 919436: case 919437: case 919438: case 919439: case 919440: case 919441: case 919442: case 919443: case 919444: case 919445: case 919446: case 919447: case 919448: case 919449: case 919450: case 919451: case 919452: case 919453: case 919454: case 919455: case 919456: case 919457: case 919458: case 919459: case 919460: case 919461: case 919462: case 919463: case 919464: case 919465: case 919466: case 919467: case 919468: case 919469: case 919470: case 919471: case 919472: case 919473: case 919474: case 919475: case 919476: case 919477: case 919478: case 919479: case 919480: case 919481: case 919482: case 919483: case 919484: case 919485: case 919486: case 919487: case 919488: case 919489: case 919490: case 919491: case 919492: case 919493: case 919494: case 919495: case 919496: case 919497: case 919498: case 919499: case 919500: case 919501: case 919502: case 919503: case 919504: case 919505: case 919506: case 919507: case 919508: case 919509: case 919510: case 919511: case 919512: case 919513: case 919514: case 919515: case 919516: case 919517: case 919518: case 919519: case 919520: case 919521: case 919522: case 919523: case 919524: case 919525: case 919526: case 919527: case 919528: case 919529: case 919530: case 919531: case 919532: case 919533: case 919534: case 919535: case 919536: case 919537: case 919538: case 919539: case 919540: case 919541: case 919542: case 919543: case 919544: case 919545: case 919546: case 919547: case 919548: case 919549: case 919550: case 919551: case 919552: case 919553: case 919554: case 919555: case 919556: case 919557: case 919558: case 919559: case 919560: case 919561: case 919562: case 919563: case 919564: case 919565: case 919566: case 919567: case 919568: case 919569: case 919570: case 919571: case 919572: case 919573: case 919574: case 919575: case 919576: case 919577: case 919578: case 919579: case 919580: case 919581: case 919582: case 919583: case 919584: case 919585: case 919586: case 919587: case 919588: case 919589: case 919590: case 919591: case 919592: case 919593: case 919594: case 919595: case 919596: case 919597: case 919598: case 919599: case 919600: case 919601: case 919602: case 919603: case 919604: case 919605: case 919606: case 919607: case 919608: case 919609: case 919610: case 919611: case 919612: case 919613: case 919614: case 919615: case 919616: case 919617: case 919618: case 919619: case 919620: case 919621: case 919622: case 919623: case 919624: case 919625: case 919626: case 919627: case 919628: case 919629: case 919630: case 919631: case 919632: case 919633: case 919634: case 919635: case 919636: case 919637: case 919638: case 919639: case 919640: case 919641: case 919642: case 919643: case 919644: case 919645: case 919646: case 919647: case 919648: case 919649: case 919650: case 919651: case 919652: case 919653: case 919654: case 919655: case 919656: case 919657: case 919658: case 919659: case 919660: case 919661: case 919662: case 919663: case 919664: case 919665: case 919666: case 919667: case 919668: case 919669: case 919670: case 919671: case 919672: case 919673: case 919674: case 919675: case 919676: case 919677: case 919678: case 919679: case 919680: case 919681: case 919682: case 919683: case 919684: case 919685: case 919686: case 919687: case 919688: case 919689: case 919690: case 919691: case 919692: case 919693: case 919694: case 919695: case 919696: case 919697: case 919698: case 919699: case 919700: case 919701: case 919702: case 919703: case 919704: case 919705: case 919706: case 919707: case 919708: case 919709: case 919710: case 919711: case 919712: case 919713: case 919714: case 919715: case 919716: case 919717: case 919718: case 919719: case 919720: case 919721: case 919722: case 919723: case 919724: case 919725: case 919726: case 919727: case 919728: case 919729: case 919730: case 919731: case 919732: case 919733: case 919734: case 919735: case 919736: case 919737: case 919738: case 919739: case 919740: case 919741: case 919742: case 919743: case 919744: case 919745: case 919746: case 919747: case 919748: case 919749: case 919750: case 919751: case 919752: case 919753: case 919754: case 919755: case 919756: case 919757: case 919758: case 919759: case 919760: case 919761: case 919762: case 919763: case 919764: case 919765: case 919766: case 919767: case 919768: case 919769: case 919770: case 919771: case 919772: case 919773: case 919774: case 919775: case 919776: case 919777: case 919778: case 919779: case 919780: case 919781: case 919782: case 919783: case 919784: case 919785: case 919786: case 919787: case 919788: case 919789: case 919790: case 919791: case 919792: case 919793: case 919794: case 919795: case 919796: case 919797: case 919798: case 919799: case 919800: case 919801: case 919802: case 919803: case 919804: case 919805: case 919806: case 919807: case 919808: case 919809: case 919810: case 919811: case 919812: case 919813: case 919814: case 919815: case 919816: case 919817: case 919818: case 919819: case 919820: case 919821: case 919822: case 919823: case 919824: case 919825: case 919826: case 919827: case 919828: case 919829: case 919830: case 919831: case 919832: case 919833: case 919834: case 919835: case 919836: case 919837: case 919838: case 919839: case 919840: case 919841: case 919842: case 919843: case 919844: case 919845: case 919846: case 919847: case 919848: case 919849: case 919850: case 919851: case 919852: case 919853: case 919854: case 919855: case 919856: case 919857: case 919858: case 919859: case 919860: case 919861: case 919862: case 919863: case 919864: case 919865: case 919866: case 919867: case 919868: case 919869: case 919870: case 919871: case 919872: case 919873: case 919874: case 919875: case 919876: case 919877: case 919878: case 919879: case 919880: case 919881: case 919882: case 919883: case 919884: case 919885: case 919886: case 919887: case 919888: case 919889: case 919890: case 919891: case 919892: case 919893: case 919894: case 919895: case 919896: case 919897: case 919898: case 919899: case 919900: case 919901: case 919902: case 919903: case 919904: case 919905: case 919906: case 919907: case 919908: case 919909: case 919910: case 919911: case 919912: case 919913: case 919914: case 919915: case 919916: case 919917: case 919918: case 919919: case 919920: case 919921: case 919922: case 919923: case 919924: case 919925: case 919926: case 919927: case 919928: case 919929: case 919930: case 919931: case 919932: case 919933: case 919934: case 919935: case 919936: case 919937: case 919938: case 919939: case 919940: case 919941: case 919942: case 919943: case 919944: case 919945: case 919946: case 919947: case 919948: case 919949: case 919950: case 919951: case 919952: case 919953: case 919954: case 919955: case 919956: case 919957: case 919958: case 919959: case 919960: case 919961: case 919962: case 919963: case 919964: case 919965: case 919966: case 919967: case 919968: case 919969: case 919970: case 919971: case 919972: case 919973: case 919974: case 919975: case 919976: case 919977: case 919978: case 919979: case 919980: case 919981: case 919982: case 919983: case 919984: case 919985: case 919986: case 919987: case 919988: case 919989: case 919990: case 919991: case 919992: case 919993: case 919994: case 919995: case 919996: case 919997: case 919998: case 919999: case 920000: case 920001: case 920002: case 920003: case 920004: case 920005: case 920006: case 920007: case 920008: case 920009: case 920010: case 920011: case 920012: case 920013: case 920014: case 920015: case 920016: case 920017: case 920018: case 920019: case 920020: case 920021: case 920022: case 920023: case 920024: case 920025: case 920026: case 920027: case 920028: case 920029: case 920030: case 920031: case 920032: case 920033: case 920034: case 920035: case 920036: case 920037: case 920038: case 920039: case 920040: case 920041: case 920042: case 920043: case 920044: case 920045: case 920046: case 920047: case 920048: case 920049: case 920050: case 920051: case 920052: case 920053: case 920054: case 920055: case 920056: case 920057: case 920058: case 920059: case 920060: case 920061: case 920062: case 920063: case 920064: case 920065: case 920066: case 920067: case 920068: case 920069: case 920070: case 920071: case 920072: case 920073: case 920074: case 920075: case 920076: case 920077: case 920078: case 920079: case 920080: case 920081: case 920082: case 920083: case 920084: case 920085: case 920086: case 920087: case 920088: case 920089: case 920090: case 920091: case 920092: case 920093: case 920094: case 920095: case 920096: case 920097: case 920098: case 920099: case 920100: case 920101: case 920102: case 920103: case 920104: case 920105: case 920106: case 920107: case 920108: case 920109: case 920110: case 920111: case 920112: case 920113: case 920114: case 920115: case 920116: case 920117: case 920118: case 920119: case 920120: case 920121: case 920122: case 920123: case 920124: case 920125: case 920126: case 920127: case 920128: case 920129: case 920130: case 920131: case 920132: case 920133: case 920134: case 920135: case 920136: case 920137: case 920138: case 920139: case 920140: case 920141: case 920142: case 920143: case 920144: case 920145: case 920146: case 920147: case 920148: case 920149: case 920150: case 920151: case 920152: case 920153: case 920154: case 920155: case 920156: case 920157: case 920158: case 920159: case 920160: case 920161: case 920162: case 920163: case 920164: case 920165: case 920166: case 920167: case 920168: case 920169: case 920170: case 920171: case 920172: case 920173: case 920174: case 920175: case 920176: case 920177: case 920178: case 920179: case 920180: case 920181: case 920182: case 920183: case 920184: case 920185: case 920186: case 920187: case 920188: case 920189: case 920190: case 920191: case 920192: case 920193: case 920194: case 920195: case 920196: case 920197: case 920198: case 920199: case 920200: case 920201: case 920202: case 920203: case 920204: case 920205: case 920206: case 920207: case 920208: case 920209: case 920210: case 920211: case 920212: case 920213: case 920214: case 920215: case 920216: case 920217: case 920218: case 920219: case 920220: case 920221: case 920222: case 920223: case 920224: case 920225: case 920226: case 920227: case 920228: case 920229: case 920230: case 920231: case 920232: case 920233: case 920234: case 920235: case 920236: case 920237: case 920238: case 920239: case 920240: case 920241: case 920242: case 920243: case 920244: case 920245: case 920246: case 920247: case 920248: case 920249: case 920250: case 920251: case 920252: case 920253: case 920254: case 920255: case 920256: case 920257: case 920258: case 920259: case 920260: case 920261: case 920262: case 920263: case 920264: case 920265: case 920266: case 920267: case 920268: case 920269: case 920270: case 920271: case 920272: case 920273: case 920274: case 920275: case 920276: case 920277: case 920278: case 920279: case 920280: case 920281: case 920282: case 920283: case 920284: case 920285: case 920286: case 920287: case 920288: case 920289: case 920290: case 920291: case 920292: case 920293: case 920294: case 920295: case 920296: case 920297: case 920298: case 920299: case 920300: case 920301: case 920302: case 920303: case 920304: case 920305: case 920306: case 920307: case 920308: case 920309: case 920310: case 920311: case 920312: case 920313: case 920314: case 920315: case 920316: case 920317: case 920318: case 920319: case 920320: case 920321: case 920322: case 920323: case 920324: case 920325: case 920326: case 920327: case 920328: case 920329: case 920330: case 920331: case 920332: case 920333: case 920334: case 920335: case 920336: case 920337: case 920338: case 920339: case 920340: case 920341: case 920342: case 920343: case 920344: case 920345: case 920346: case 920347: case 920348: case 920349: case 920350: case 920351: case 920352: case 920353: case 920354: case 920355: case 920356: case 920357: case 920358: case 920359: case 920360: case 920361: case 920362: case 920363: case 920364: case 920365: case 920366: case 920367: case 920368: case 920369: case 920370: case 920371: case 920372: case 920373: case 920374: case 920375: case 920376: case 920377: case 920378: case 920379: case 920380: case 920381: case 920382: case 920383: case 920384: case 920385: case 920386: case 920387: case 920388: case 920389: case 920390: case 920391: case 920392: case 920393: case 920394: case 920395: case 920396: case 920397: case 920398: case 920399: case 920400: case 920401: case 920402: case 920403: case 920404: case 920405: case 920406: case 920407: case 920408: case 920409: case 920410: case 920411: case 920412: case 920413: case 920414: case 920415: case 920416: case 920417: case 920418: case 920419: case 920420: case 920421: case 920422: case 920423: case 920424: case 920425: case 920426: case 920427: case 920428: case 920429: case 920430: case 920431: case 920432: case 920433: case 920434: case 920435: case 920436: case 920437: case 920438: case 920439: case 920440: case 920441: case 920442: case 920443: case 920444: case 920445: case 920446: case 920447: case 920448: case 920449: case 920450: case 920451: case 920452: case 920453: case 920454: case 920455: case 920456: case 920457: case 920458: case 920459: case 920460: case 920461: case 920462: case 920463: case 920464: case 920465: case 920466: case 920467: case 920468: case 920469: case 920470: case 920471: case 920472: case 920473: case 920474: case 920475: case 920476: case 920477: case 920478: case 920479: case 920480: case 920481: case 920482: case 920483: case 920484: case 920485: case 920486: case 920487: case 920488: case 920489: case 920490: case 920491: case 920492: case 920493: case 920494: case 920495: case 920496: case 920497: case 920498: case 920499: case 920500: case 920501: case 920502: case 920503: case 920504: case 920505: case 920506: case 920507: case 920508: case 920509: case 920510: case 920511: case 920512: case 920513: case 920514: case 920515: case 920516: case 920517: case 920518: case 920519: case 920520: case 920521: case 920522: case 920523: case 920524: case 920525: case 920526: case 920527: case 920528: case 920529: case 920530: case 920531: case 920532: case 920533: case 920534: case 920535: case 920536: case 920537: case 920538: case 920539: case 920540: case 920541: case 920542: case 920543: case 920544: case 920545: case 920546: case 920547: case 920548: case 920549: case 920550: case 920551: case 920552: case 920553: case 920554: case 920555: case 920556: case 920557: case 920558: case 920559: case 920560: case 920561: case 920562: case 920563: case 920564: case 920565: case 920566: case 920567: case 920568: case 920569: case 920570: case 920571: case 920572: case 920573: case 920574: case 920575: case 920576: case 920577: case 920578: case 920579: case 920580: case 920581: case 920582: case 920583: case 920584: case 920585: case 920586: case 920587: case 920588: case 920589: case 920590: case 920591: case 920592: case 920593: case 920594: case 920595: case 920596: case 920597: case 920598: case 920599: case 920600: case 920601: case 920602: case 920603: case 920604: case 920605: case 920606: case 920607: case 920608: case 920609: case 920610: case 920611: case 920612: case 920613: case 920614: case 920615: case 920616: case 920617: case 920618: case 920619: case 920620: case 920621: case 920622: case 920623: case 920624: case 920625: case 920626: case 920627: case 920628: case 920629: case 920630: case 920631: case 920632: case 920633: case 920634: case 920635: case 920636: case 920637: case 920638: case 920639: case 920640: case 920641: case 920642: case 920643: case 920644: case 920645: case 920646: case 920647: case 920648: case 920649: case 920650: case 920651: case 920652: case 920653: case 920654: case 920655: case 920656: case 920657: case 920658: case 920659: case 920660: case 920661: case 920662: case 920663: case 920664: case 920665: case 920666: case 920667: case 920668: case 920669: case 920670: case 920671: case 920672: case 920673: case 920674: case 920675: case 920676: case 920677: case 920678: case 920679: case 920680: case 920681: case 920682: case 920683: case 920684: case 920685: case 920686: case 920687: case 920688: case 920689: case 920690: case 920691: case 920692: case 920693: case 920694: case 920695: case 920696: case 920697: case 920698: case 920699: case 920700: case 920701: case 920702: case 920703: case 920704: case 920705: case 920706: case 920707: case 920708: case 920709: case 920710: case 920711: case 920712: case 920713: case 920714: case 920715: case 920716: case 920717: case 920718: case 920719: case 920720: case 920721: case 920722: case 920723: case 920724: case 920725: case 920726: case 920727: case 920728: case 920729: case 920730: case 920731: case 920732: case 920733: case 920734: case 920735: case 920736: case 920737: case 920738: case 920739: case 920740: case 920741: case 920742: case 920743: case 920744: case 920745: case 920746: case 920747: case 920748: case 920749: case 920750: case 920751: case 920752: case 920753: case 920754: case 920755: case 920756: case 920757: case 920758: case 920759: case 920760: case 920761: case 920762: case 920763: case 920764: case 920765: case 920766: case 920767: case 920768: case 920769: case 920770: case 920771: case 920772: case 920773: case 920774: case 920775: case 920776: case 920777: case 920778: case 920779: case 920780: case 920781: case 920782: case 920783: case 920784: case 920785: case 920786: case 920787: case 920788: case 920789: case 920790: case 920791: case 920792: case 920793: case 920794: case 920795: case 920796: case 920797: case 920798: case 920799: case 920800: case 920801: case 920802: case 920803: case 920804: case 920805: case 920806: case 920807: case 920808: case 920809: case 920810: case 920811: case 920812: case 920813: case 920814: case 920815: case 920816: case 920817: case 920818: case 920819: case 920820: case 920821: case 920822: case 920823: case 920824: case 920825: case 920826: case 920827: case 920828: case 920829: case 920830: case 920831: case 920832: case 920833: case 920834: case 920835: case 920836: case 920837: case 920838: case 920839: case 920840: case 920841: case 920842: case 920843: case 920844: case 920845: case 920846: case 920847: case 920848: case 920849: case 920850: case 920851: case 920852: case 920853: case 920854: case 920855: case 920856: case 920857: case 920858: case 920859: case 920860: case 920861: case 920862: case 920863: case 920864: case 920865: case 920866: case 920867: case 920868: case 920869: case 920870: case 920871: case 920872: case 920873: case 920874: case 920875: case 920876: case 920877: case 920878: case 920879: case 920880: case 920881: case 920882: case 920883: case 920884: case 920885: case 920886: case 920887: case 920888: case 920889: case 920890: case 920891: case 920892: case 920893: case 920894: case 920895: case 920896: case 920897: case 920898: case 920899: case 920900: case 920901: case 920902: case 920903: case 920904: case 920905: case 920906: case 920907: case 920908: case 920909: case 920910: case 920911: case 920912: case 920913: case 920914: case 920915: case 920916: case 920917: case 920918: case 920919: case 920920: case 920921: case 920922: case 920923: case 920924: case 920925: case 920926: case 920927: case 920928: case 920929: case 920930: case 920931: case 920932: case 920933: case 920934: case 920935: case 920936: case 920937: case 920938: case 920939: case 920940: case 920941: case 920942: case 920943: case 920944: case 920945: case 920946: case 920947: case 920948: case 920949: case 920950: case 920951: case 920952: case 920953: case 920954: case 920955: case 920956: case 920957: case 920958: case 920959: case 920960: case 920961: case 920962: case 920963: case 920964: case 920965: case 920966: case 920967: case 920968: case 920969: case 920970: case 920971: case 920972: case 920973: case 920974: case 920975: case 920976: case 920977: case 920978: case 920979: case 920980: case 920981: case 920982: case 920983: case 920984: case 920985: case 920986: case 920987: case 920988: case 920989: case 920990: case 920991: case 920992: case 920993: case 920994: case 920995: case 920996: case 920997: case 920998: case 920999: case 921000: case 921001: case 921002: case 921003: case 921004: case 921005: case 921006: case 921007: case 921008: case 921009: case 921010: case 921011: case 921012: case 921013: case 921014: case 921015: case 921016: case 921017: case 921018: case 921019: case 921020: case 921021: case 921022: case 921023: case 921024: case 921025: case 921026: case 921027: case 921028: case 921029: case 921030: case 921031: case 921032: case 921033: case 921034: case 921035: case 921036: case 921037: case 921038: case 921039: case 921040: case 921041: case 921042: case 921043: case 921044: case 921045: case 921046: case 921047: case 921048: case 921049: case 921050: case 921051: case 921052: case 921053: case 921054: case 921055: case 921056: case 921057: case 921058: case 921059: case 921060: case 921061: case 921062: case 921063: case 921064: case 921065: case 921066: case 921067: case 921068: case 921069: case 921070: case 921071: case 921072: case 921073: case 921074: case 921075: case 921076: case 921077: case 921078: case 921079: case 921080: case 921081: case 921082: case 921083: case 921084: case 921085: case 921086: case 921087: case 921088: case 921089: case 921090: case 921091: case 921092: case 921093: case 921094: case 921095: case 921096: case 921097: case 921098: case 921099: case 921100: case 921101: case 921102: case 921103: case 921104: case 921105: case 921106: case 921107: case 921108: case 921109: case 921110: case 921111: case 921112: case 921113: case 921114: case 921115: case 921116: case 921117: case 921118: case 921119: case 921120: case 921121: case 921122: case 921123: case 921124: case 921125: case 921126: case 921127: case 921128: case 921129: case 921130: case 921131: case 921132: case 921133: case 921134: case 921135: case 921136: case 921137: case 921138: case 921139: case 921140: case 921141: case 921142: case 921143: case 921144: case 921145: case 921146: case 921147: case 921148: case 921149: case 921150: case 921151: case 921152: case 921153: case 921154: case 921155: case 921156: case 921157: case 921158: case 921159: case 921160: case 921161: case 921162: case 921163: case 921164: case 921165: case 921166: case 921167: case 921168: case 921169: case 921170: case 921171: case 921172: case 921173: case 921174: case 921175: case 921176: case 921177: case 921178: case 921179: case 921180: case 921181: case 921182: case 921183: case 921184: case 921185: case 921186: case 921187: case 921188: case 921189: case 921190: case 921191: case 921192: case 921193: case 921194: case 921195: case 921196: case 921197: case 921198: case 921199: case 921200: case 921201: case 921202: case 921203: case 921204: case 921205: case 921206: case 921207: case 921208: case 921209: case 921210: case 921211: case 921212: case 921213: case 921214: case 921215: case 921216: case 921217: case 921218: case 921219: case 921220: case 921221: case 921222: case 921223: case 921224: case 921225: case 921226: case 921227: case 921228: case 921229: case 921230: case 921231: case 921232: case 921233: case 921234: case 921235: case 921236: case 921237: case 921238: case 921239: case 921240: case 921241: case 921242: case 921243: case 921244: case 921245: case 921246: case 921247: case 921248: case 921249: case 921250: case 921251: case 921252: case 921253: case 921254: case 921255: case 921256: case 921257: case 921258: case 921259: case 921260: case 921261: case 921262: case 921263: case 921264: case 921265: case 921266: case 921267: case 921268: case 921269: case 921270: case 921271: case 921272: case 921273: case 921274: case 921275: case 921276: case 921277: case 921278: case 921279: case 921280: case 921281: case 921282: case 921283: case 921284: case 921285: case 921286: case 921287: case 921288: case 921289: case 921290: case 921291: case 921292: case 921293: case 921294: case 921295: case 921296: case 921297: case 921298: case 921299: case 921300: case 921301: case 921302: case 921303: case 921304: case 921305: case 921306: case 921307: case 921308: case 921309: case 921310: case 921311: case 921312: case 921313: case 921314: case 921315: case 921316: case 921317: case 921318: case 921319: case 921320: case 921321: case 921322: case 921323: case 921324: case 921325: case 921326: case 921327: case 921328: case 921329: case 921330: case 921331: case 921332: case 921333: case 921334: case 921335: case 921336: case 921337: case 921338: case 921339: case 921340: case 921341: case 921342: case 921343: case 921344: case 921345: case 921346: case 921347: case 921348: case 921349: case 921350: case 921351: case 921352: case 921353: case 921354: case 921355: case 921356: case 921357: case 921358: case 921359: case 921360: case 921361: case 921362: case 921363: case 921364: case 921365: case 921366: case 921367: case 921368: case 921369: case 921370: case 921371: case 921372: case 921373: case 921374: case 921375: case 921376: case 921377: case 921378: case 921379: case 921380: case 921381: case 921382: case 921383: case 921384: case 921385: case 921386: case 921387: case 921388: case 921389: case 921390: case 921391: case 921392: case 921393: case 921394: case 921395: case 921396: case 921397: case 921398: case 921399: case 921400: case 921401: case 921402: case 921403: case 921404: case 921405: case 921406: case 921407: case 921408: case 921409: case 921410: case 921411: case 921412: case 921413: case 921414: case 921415: case 921416: case 921417: case 921418: case 921419: case 921420: case 921421: case 921422: case 921423: case 921424: case 921425: case 921426: case 921427: case 921428: case 921429: case 921430: case 921431: case 921432: case 921433: case 921434: case 921435: case 921436: case 921437: case 921438: case 921439: case 921440: case 921441: case 921442: case 921443: case 921444: case 921445: case 921446: case 921447: case 921448: case 921449: case 921450: case 921451: case 921452: case 921453: case 921454: case 921455: case 921456: case 921457: case 921458: case 921459: case 921460: case 921461: case 921462: case 921463: case 921464: case 921465: case 921466: case 921467: case 921468: case 921469: case 921470: case 921471: case 921472: case 921473: case 921474: case 921475: case 921476: case 921477: case 921478: case 921479: case 921480: case 921481: case 921482: case 921483: case 921484: case 921485: case 921486: case 921487: case 921488: case 921489: case 921490: case 921491: case 921492: case 921493: case 921494: case 921495: case 921496: case 921497: case 921498: case 921499: case 921500: case 921501: case 921502: case 921503: case 921504: case 921505: case 921506: case 921507: case 921508: case 921509: case 921510: case 921511: case 921512: case 921513: case 921514: case 921515: case 921516: case 921517: case 921518: case 921519: case 921520: case 921521: case 921522: case 921523: case 921524: case 921525: case 921526: case 921527: case 921528: case 921529: case 921530: case 921531: case 921532: case 921533: case 921534: case 921535: case 921536: case 921537: case 921538: case 921539: case 921540: case 921541: case 921542: case 921543: case 921544: case 921545: case 921546: case 921547: case 921548: case 921549: case 921550: case 921551: case 921552: case 921553: case 921554: case 921555: case 921556: case 921557: case 921558: case 921559: case 921560: case 921561: case 921562: case 921563: case 921564: case 921565: case 921566: case 921567: case 921568: case 921569: case 921570: case 921571: case 921572: case 921573: case 921574: case 921575: case 921576: case 921577: case 921578: case 921579: case 921580: case 921581: case 921582: case 921583: case 921584: case 921585: case 921586: case 921587: case 921588: case 921589: case 921590: case 921591: case 921592: case 921593: case 921594: case 921595: case 921596: case 921597: case 921598: case 921599: return 2329 + c - 917504;
default: return 0;
	} // }}}
}


END_ALLOW_CASE_RANGE
