// unicode data, built from the unicode standard on: 2018-04-24
// see gen-wcwidth.py
#include "data-types.h"

START_ALLOW_CASE_RANGE

#include "unicode-data.h"
bool
is_combining_char(char_type code) {
	// M category (marks) (2177 codepoints) {{{
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
		case 0x8d4 ... 0x8e1:
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
		case 0xb56 ... 0xb57:
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
		case 0xc00 ... 0xc03:
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
		case 0xd82 ... 0xd83:
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
		case 0xeb4 ... 0xeb9:
			return true;
		case 0xebb ... 0xebc:
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
		case 0x1ab0 ... 0x1abe:
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
		case 0x1cf2 ... 0x1cf4:
			return true;
		case 0x1cf7 ... 0x1cf9:
			return true;
		case 0x1dc0 ... 0x1df9:
			return true;
		case 0x1dfb ... 0x1dff:
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
		case 0xa880 ... 0xa881:
			return true;
		case 0xa8b4 ... 0xa8c5:
			return true;
		case 0xa8e0 ... 0xa8f1:
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
		case 0x11173:
			return true;
		case 0x11180 ... 0x11182:
			return true;
		case 0x111b3 ... 0x111c0:
			return true;
		case 0x111ca ... 0x111cc:
			return true;
		case 0x1122c ... 0x11237:
			return true;
		case 0x1123e:
			return true;
		case 0x112df ... 0x112ea:
			return true;
		case 0x11300 ... 0x11303:
			return true;
		case 0x1133c:
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
		case 0x16af0 ... 0x16af4:
			return true;
		case 0x16b30 ... 0x16b36:
			return true;
		case 0x16f51 ... 0x16f7e:
			return true;
		case 0x16f8f ... 0x16f92:
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
		case 0x1e8d0 ... 0x1e8d6:
			return true;
		case 0x1e944 ... 0x1e94a:
			return true;
		case 0xe0100 ... 0xe01ef:
			return true;
	} // }}}

	return false;
}

bool
is_ignored_char(char_type code) {
	// Control characters (Cc Cf Cs) (2264 codepoints) {{{
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
		case 0x200b ... 0x200f:
			return true;
		case 0x202a ... 0x202e:
			return true;
		case 0x2060 ... 0x2064:
			return true;
		case 0x2066 ... 0x206f:
			return true;
		case 0xd800 ... 0xdfff:
			return true;
		case 0xfeff:
			return true;
		case 0xfff9 ... 0xfffb:
			return true;
		case 0x110bd:
			return true;
		case 0x1bca0 ... 0x1bca3:
			return true;
		case 0x1d173 ... 0x1d17a:
			return true;
		case 0xe0001:
			return true;
		case 0xe0020 ... 0xe007f:
			return true;
	} // }}}

	return false;
}

bool
is_word_char(char_type code) {
	// L and N categories (126595 codepoints) {{{
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
		case 0x561 ... 0x587:
			return true;
		case 0x5d0 ... 0x5ea:
			return true;
		case 0x5f0 ... 0x5f2:
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
		case 0x8b6 ... 0x8bd:
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
		case 0xd05 ... 0xd0c:
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
		case 0xe87 ... 0xe88:
			return true;
		case 0xe8a:
			return true;
		case 0xe8d:
			return true;
		case 0xe94 ... 0xe97:
			return true;
		case 0xe99 ... 0xe9f:
			return true;
		case 0xea1 ... 0xea3:
			return true;
		case 0xea5:
			return true;
		case 0xea7:
			return true;
		case 0xeaa ... 0xeab:
			return true;
		case 0xead ... 0xeb0:
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
		case 0x1820 ... 0x1877:
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
		case 0x1ce9 ... 0x1cec:
			return true;
		case 0x1cee ... 0x1cf1:
			return true;
		case 0x1cf5 ... 0x1cf6:
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
		case 0x3105 ... 0x312e:
			return true;
		case 0x3131 ... 0x318e:
			return true;
		case 0x3192 ... 0x3195:
			return true;
		case 0x31a0 ... 0x31ba:
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
		case 0x3400 ... 0x4db5:
			return true;
		case 0x4e00 ... 0x9fea:
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
		case 0xa78b ... 0xa7ae:
			return true;
		case 0xa7b0 ... 0xa7b7:
			return true;
		case 0xa7f7 ... 0xa801:
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
		case 0xa8fd:
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
		case 0xab5c ... 0xab65:
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
		case 0x10a19 ... 0x10a33:
			return true;
		case 0x10a40 ... 0x10a47:
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
		case 0x10cfa ... 0x10cff:
			return true;
		case 0x10e60 ... 0x10e7e:
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
		case 0x116c0 ... 0x116c9:
			return true;
		case 0x11700 ... 0x11719:
			return true;
		case 0x11730 ... 0x1173b:
			return true;
		case 0x118a0 ... 0x118f2:
			return true;
		case 0x118ff:
			return true;
		case 0x11a00:
			return true;
		case 0x11a0b ... 0x11a32:
			return true;
		case 0x11a3a:
			return true;
		case 0x11a50:
			return true;
		case 0x11a5c ... 0x11a83:
			return true;
		case 0x11a86 ... 0x11a89:
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
		case 0x16f00 ... 0x16f44:
			return true;
		case 0x16f50:
			return true;
		case 0x16f93 ... 0x16f9f:
			return true;
		case 0x16fe0 ... 0x16fe1:
			return true;
		case 0x17000 ... 0x187ec:
			return true;
		case 0x18800 ... 0x18af2:
			return true;
		case 0x1b000 ... 0x1b11e:
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
		case 0x1d360 ... 0x1d371:
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
		case 0x1e800 ... 0x1e8c4:
			return true;
		case 0x1e8c7 ... 0x1e8cf:
			return true;
		case 0x1e900 ... 0x1e943:
			return true;
		case 0x1e950 ... 0x1e959:
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
		case 0x20000 ... 0x2a6d6:
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
	} // }}}

	return false;
}

bool
is_CZ_category(char_type code) {
	// C and Z categories (139751 codepoints) {{{
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
	// P category (punctuation) (770 codepoints) {{{
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
		case 0xaf0:
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
		case 0x166d ... 0x166e:
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
		case 0x2e30 ... 0x2e49:
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
		case 0x111c5 ... 0x111c9:
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
		case 0x1145b:
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
	static char_type map[2178] = { 0, 768, 769, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 780, 781, 782, 783, 784, 785, 786, 787, 788, 789, 790, 791, 792, 793, 794, 795, 796, 797, 798, 799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809, 810, 811, 812, 813, 814, 815, 816, 817, 818, 819, 820, 821, 822, 823, 824, 825, 826, 827, 828, 829, 830, 831, 832, 833, 834, 835, 836, 837, 838, 839, 840, 841, 842, 843, 844, 845, 846, 847, 848, 849, 850, 851, 852, 853, 854, 855, 856, 857, 858, 859, 860, 861, 862, 863, 864, 865, 866, 867, 868, 869, 870, 871, 872, 873, 874, 875, 876, 877, 878, 879, 1155, 1156, 1157, 1158, 1159, 1160, 1161, 1425, 1426, 1427, 1428, 1429, 1430, 1431, 1432, 1433, 1434, 1435, 1436, 1437, 1438, 1439, 1440, 1441, 1442, 1443, 1444, 1445, 1446, 1447, 1448, 1449, 1450, 1451, 1452, 1453, 1454, 1455, 1456, 1457, 1458, 1459, 1460, 1461, 1462, 1463, 1464, 1465, 1466, 1467, 1468, 1469, 1471, 1473, 1474, 1476, 1477, 1479, 1552, 1553, 1554, 1555, 1556, 1557, 1558, 1559, 1560, 1561, 1562, 1611, 1612, 1613, 1614, 1615, 1616, 1617, 1618, 1619, 1620, 1621, 1622, 1623, 1624, 1625, 1626, 1627, 1628, 1629, 1630, 1631, 1648, 1750, 1751, 1752, 1753, 1754, 1755, 1756, 1759, 1760, 1761, 1762, 1763, 1764, 1767, 1768, 1770, 1771, 1772, 1773, 1809, 1840, 1841, 1842, 1843, 1844, 1845, 1846, 1847, 1848, 1849, 1850, 1851, 1852, 1853, 1854, 1855, 1856, 1857, 1858, 1859, 1860, 1861, 1862, 1863, 1864, 1865, 1866, 1958, 1959, 1960, 1961, 1962, 1963, 1964, 1965, 1966, 1967, 1968, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2070, 2071, 2072, 2073, 2075, 2076, 2077, 2078, 2079, 2080, 2081, 2082, 2083, 2085, 2086, 2087, 2089, 2090, 2091, 2092, 2093, 2137, 2138, 2139, 2260, 2261, 2262, 2263, 2264, 2265, 2266, 2267, 2268, 2269, 2270, 2271, 2272, 2273, 2275, 2276, 2277, 2278, 2279, 2280, 2281, 2282, 2283, 2284, 2285, 2286, 2287, 2288, 2289, 2290, 2291, 2292, 2293, 2294, 2295, 2296, 2297, 2298, 2299, 2300, 2301, 2302, 2303, 2304, 2305, 2306, 2307, 2362, 2363, 2364, 2366, 2367, 2368, 2369, 2370, 2371, 2372, 2373, 2374, 2375, 2376, 2377, 2378, 2379, 2380, 2381, 2382, 2383, 2385, 2386, 2387, 2388, 2389, 2390, 2391, 2402, 2403, 2433, 2434, 2435, 2492, 2494, 2495, 2496, 2497, 2498, 2499, 2500, 2503, 2504, 2507, 2508, 2509, 2519, 2530, 2531, 2561, 2562, 2563, 2620, 2622, 2623, 2624, 2625, 2626, 2631, 2632, 2635, 2636, 2637, 2641, 2672, 2673, 2677, 2689, 2690, 2691, 2748, 2750, 2751, 2752, 2753, 2754, 2755, 2756, 2757, 2759, 2760, 2761, 2763, 2764, 2765, 2786, 2787, 2810, 2811, 2812, 2813, 2814, 2815, 2817, 2818, 2819, 2876, 2878, 2879, 2880, 2881, 2882, 2883, 2884, 2887, 2888, 2891, 2892, 2893, 2902, 2903, 2914, 2915, 2946, 3006, 3007, 3008, 3009, 3010, 3014, 3015, 3016, 3018, 3019, 3020, 3021, 3031, 3072, 3073, 3074, 3075, 3134, 3135, 3136, 3137, 3138, 3139, 3140, 3142, 3143, 3144, 3146, 3147, 3148, 3149, 3157, 3158, 3170, 3171, 3201, 3202, 3203, 3260, 3262, 3263, 3264, 3265, 3266, 3267, 3268, 3270, 3271, 3272, 3274, 3275, 3276, 3277, 3285, 3286, 3298, 3299, 3328, 3329, 3330, 3331, 3387, 3388, 3390, 3391, 3392, 3393, 3394, 3395, 3396, 3398, 3399, 3400, 3402, 3403, 3404, 3405, 3415, 3426, 3427, 3458, 3459, 3530, 3535, 3536, 3537, 3538, 3539, 3540, 3542, 3544, 3545, 3546, 3547, 3548, 3549, 3550, 3551, 3570, 3571, 3633, 3636, 3637, 3638, 3639, 3640, 3641, 3642, 3655, 3656, 3657, 3658, 3659, 3660, 3661, 3662, 3761, 3764, 3765, 3766, 3767, 3768, 3769, 3771, 3772, 3784, 3785, 3786, 3787, 3788, 3789, 3864, 3865, 3893, 3895, 3897, 3902, 3903, 3953, 3954, 3955, 3956, 3957, 3958, 3959, 3960, 3961, 3962, 3963, 3964, 3965, 3966, 3967, 3968, 3969, 3970, 3971, 3972, 3974, 3975, 3981, 3982, 3983, 3984, 3985, 3986, 3987, 3988, 3989, 3990, 3991, 3993, 3994, 3995, 3996, 3997, 3998, 3999, 4000, 4001, 4002, 4003, 4004, 4005, 4006, 4007, 4008, 4009, 4010, 4011, 4012, 4013, 4014, 4015, 4016, 4017, 4018, 4019, 4020, 4021, 4022, 4023, 4024, 4025, 4026, 4027, 4028, 4038, 4139, 4140, 4141, 4142, 4143, 4144, 4145, 4146, 4147, 4148, 4149, 4150, 4151, 4152, 4153, 4154, 4155, 4156, 4157, 4158, 4182, 4183, 4184, 4185, 4190, 4191, 4192, 4194, 4195, 4196, 4199, 4200, 4201, 4202, 4203, 4204, 4205, 4209, 4210, 4211, 4212, 4226, 4227, 4228, 4229, 4230, 4231, 4232, 4233, 4234, 4235, 4236, 4237, 4239, 4250, 4251, 4252, 4253, 4957, 4958, 4959, 5906, 5907, 5908, 5938, 5939, 5940, 5970, 5971, 6002, 6003, 6068, 6069, 6070, 6071, 6072, 6073, 6074, 6075, 6076, 6077, 6078, 6079, 6080, 6081, 6082, 6083, 6084, 6085, 6086, 6087, 6088, 6089, 6090, 6091, 6092, 6093, 6094, 6095, 6096, 6097, 6098, 6099, 6109, 6155, 6156, 6157, 6277, 6278, 6313, 6432, 6433, 6434, 6435, 6436, 6437, 6438, 6439, 6440, 6441, 6442, 6443, 6448, 6449, 6450, 6451, 6452, 6453, 6454, 6455, 6456, 6457, 6458, 6459, 6679, 6680, 6681, 6682, 6683, 6741, 6742, 6743, 6744, 6745, 6746, 6747, 6748, 6749, 6750, 6752, 6753, 6754, 6755, 6756, 6757, 6758, 6759, 6760, 6761, 6762, 6763, 6764, 6765, 6766, 6767, 6768, 6769, 6770, 6771, 6772, 6773, 6774, 6775, 6776, 6777, 6778, 6779, 6780, 6783, 6832, 6833, 6834, 6835, 6836, 6837, 6838, 6839, 6840, 6841, 6842, 6843, 6844, 6845, 6846, 6912, 6913, 6914, 6915, 6916, 6964, 6965, 6966, 6967, 6968, 6969, 6970, 6971, 6972, 6973, 6974, 6975, 6976, 6977, 6978, 6979, 6980, 7019, 7020, 7021, 7022, 7023, 7024, 7025, 7026, 7027, 7040, 7041, 7042, 7073, 7074, 7075, 7076, 7077, 7078, 7079, 7080, 7081, 7082, 7083, 7084, 7085, 7142, 7143, 7144, 7145, 7146, 7147, 7148, 7149, 7150, 7151, 7152, 7153, 7154, 7155, 7204, 7205, 7206, 7207, 7208, 7209, 7210, 7211, 7212, 7213, 7214, 7215, 7216, 7217, 7218, 7219, 7220, 7221, 7222, 7223, 7376, 7377, 7378, 7380, 7381, 7382, 7383, 7384, 7385, 7386, 7387, 7388, 7389, 7390, 7391, 7392, 7393, 7394, 7395, 7396, 7397, 7398, 7399, 7400, 7405, 7410, 7411, 7412, 7415, 7416, 7417, 7616, 7617, 7618, 7619, 7620, 7621, 7622, 7623, 7624, 7625, 7626, 7627, 7628, 7629, 7630, 7631, 7632, 7633, 7634, 7635, 7636, 7637, 7638, 7639, 7640, 7641, 7642, 7643, 7644, 7645, 7646, 7647, 7648, 7649, 7650, 7651, 7652, 7653, 7654, 7655, 7656, 7657, 7658, 7659, 7660, 7661, 7662, 7663, 7664, 7665, 7666, 7667, 7668, 7669, 7670, 7671, 7672, 7673, 7675, 7676, 7677, 7678, 7679, 8400, 8401, 8402, 8403, 8404, 8405, 8406, 8407, 8408, 8409, 8410, 8411, 8412, 8413, 8414, 8415, 8416, 8417, 8418, 8419, 8420, 8421, 8422, 8423, 8424, 8425, 8426, 8427, 8428, 8429, 8430, 8431, 8432, 11503, 11504, 11505, 11647, 11744, 11745, 11746, 11747, 11748, 11749, 11750, 11751, 11752, 11753, 11754, 11755, 11756, 11757, 11758, 11759, 11760, 11761, 11762, 11763, 11764, 11765, 11766, 11767, 11768, 11769, 11770, 11771, 11772, 11773, 11774, 11775, 12330, 12331, 12332, 12333, 12334, 12335, 12441, 12442, 42607, 42608, 42609, 42610, 42612, 42613, 42614, 42615, 42616, 42617, 42618, 42619, 42620, 42621, 42654, 42655, 42736, 42737, 43010, 43014, 43019, 43043, 43044, 43045, 43046, 43047, 43136, 43137, 43188, 43189, 43190, 43191, 43192, 43193, 43194, 43195, 43196, 43197, 43198, 43199, 43200, 43201, 43202, 43203, 43204, 43205, 43232, 43233, 43234, 43235, 43236, 43237, 43238, 43239, 43240, 43241, 43242, 43243, 43244, 43245, 43246, 43247, 43248, 43249, 43302, 43303, 43304, 43305, 43306, 43307, 43308, 43309, 43335, 43336, 43337, 43338, 43339, 43340, 43341, 43342, 43343, 43344, 43345, 43346, 43347, 43392, 43393, 43394, 43395, 43443, 43444, 43445, 43446, 43447, 43448, 43449, 43450, 43451, 43452, 43453, 43454, 43455, 43456, 43493, 43561, 43562, 43563, 43564, 43565, 43566, 43567, 43568, 43569, 43570, 43571, 43572, 43573, 43574, 43587, 43596, 43597, 43643, 43644, 43645, 43696, 43698, 43699, 43700, 43703, 43704, 43710, 43711, 43713, 43755, 43756, 43757, 43758, 43759, 43765, 43766, 44003, 44004, 44005, 44006, 44007, 44008, 44009, 44010, 44012, 44013, 64286, 65024, 65025, 65026, 65027, 65028, 65029, 65030, 65031, 65032, 65033, 65034, 65035, 65036, 65037, 65038, 65039, 65056, 65057, 65058, 65059, 65060, 65061, 65062, 65063, 65064, 65065, 65066, 65067, 65068, 65069, 65070, 65071, 66045, 66272, 66422, 66423, 66424, 66425, 66426, 68097, 68098, 68099, 68101, 68102, 68108, 68109, 68110, 68111, 68152, 68153, 68154, 68159, 68325, 68326, 69632, 69633, 69634, 69688, 69689, 69690, 69691, 69692, 69693, 69694, 69695, 69696, 69697, 69698, 69699, 69700, 69701, 69702, 69759, 69760, 69761, 69762, 69808, 69809, 69810, 69811, 69812, 69813, 69814, 69815, 69816, 69817, 69818, 69888, 69889, 69890, 69927, 69928, 69929, 69930, 69931, 69932, 69933, 69934, 69935, 69936, 69937, 69938, 69939, 69940, 70003, 70016, 70017, 70018, 70067, 70068, 70069, 70070, 70071, 70072, 70073, 70074, 70075, 70076, 70077, 70078, 70079, 70080, 70090, 70091, 70092, 70188, 70189, 70190, 70191, 70192, 70193, 70194, 70195, 70196, 70197, 70198, 70199, 70206, 70367, 70368, 70369, 70370, 70371, 70372, 70373, 70374, 70375, 70376, 70377, 70378, 70400, 70401, 70402, 70403, 70460, 70462, 70463, 70464, 70465, 70466, 70467, 70468, 70471, 70472, 70475, 70476, 70477, 70487, 70498, 70499, 70502, 70503, 70504, 70505, 70506, 70507, 70508, 70512, 70513, 70514, 70515, 70516, 70709, 70710, 70711, 70712, 70713, 70714, 70715, 70716, 70717, 70718, 70719, 70720, 70721, 70722, 70723, 70724, 70725, 70726, 70832, 70833, 70834, 70835, 70836, 70837, 70838, 70839, 70840, 70841, 70842, 70843, 70844, 70845, 70846, 70847, 70848, 70849, 70850, 70851, 71087, 71088, 71089, 71090, 71091, 71092, 71093, 71096, 71097, 71098, 71099, 71100, 71101, 71102, 71103, 71104, 71132, 71133, 71216, 71217, 71218, 71219, 71220, 71221, 71222, 71223, 71224, 71225, 71226, 71227, 71228, 71229, 71230, 71231, 71232, 71339, 71340, 71341, 71342, 71343, 71344, 71345, 71346, 71347, 71348, 71349, 71350, 71351, 71453, 71454, 71455, 71456, 71457, 71458, 71459, 71460, 71461, 71462, 71463, 71464, 71465, 71466, 71467, 72193, 72194, 72195, 72196, 72197, 72198, 72199, 72200, 72201, 72202, 72243, 72244, 72245, 72246, 72247, 72248, 72249, 72251, 72252, 72253, 72254, 72263, 72273, 72274, 72275, 72276, 72277, 72278, 72279, 72280, 72281, 72282, 72283, 72330, 72331, 72332, 72333, 72334, 72335, 72336, 72337, 72338, 72339, 72340, 72341, 72342, 72343, 72344, 72345, 72751, 72752, 72753, 72754, 72755, 72756, 72757, 72758, 72760, 72761, 72762, 72763, 72764, 72765, 72766, 72767, 72850, 72851, 72852, 72853, 72854, 72855, 72856, 72857, 72858, 72859, 72860, 72861, 72862, 72863, 72864, 72865, 72866, 72867, 72868, 72869, 72870, 72871, 72873, 72874, 72875, 72876, 72877, 72878, 72879, 72880, 72881, 72882, 72883, 72884, 72885, 72886, 73009, 73010, 73011, 73012, 73013, 73014, 73018, 73020, 73021, 73023, 73024, 73025, 73026, 73027, 73028, 73029, 73031, 92912, 92913, 92914, 92915, 92916, 92976, 92977, 92978, 92979, 92980, 92981, 92982, 94033, 94034, 94035, 94036, 94037, 94038, 94039, 94040, 94041, 94042, 94043, 94044, 94045, 94046, 94047, 94048, 94049, 94050, 94051, 94052, 94053, 94054, 94055, 94056, 94057, 94058, 94059, 94060, 94061, 94062, 94063, 94064, 94065, 94066, 94067, 94068, 94069, 94070, 94071, 94072, 94073, 94074, 94075, 94076, 94077, 94078, 94095, 94096, 94097, 94098, 113821, 113822, 119141, 119142, 119143, 119144, 119145, 119149, 119150, 119151, 119152, 119153, 119154, 119163, 119164, 119165, 119166, 119167, 119168, 119169, 119170, 119173, 119174, 119175, 119176, 119177, 119178, 119179, 119210, 119211, 119212, 119213, 119362, 119363, 119364, 121344, 121345, 121346, 121347, 121348, 121349, 121350, 121351, 121352, 121353, 121354, 121355, 121356, 121357, 121358, 121359, 121360, 121361, 121362, 121363, 121364, 121365, 121366, 121367, 121368, 121369, 121370, 121371, 121372, 121373, 121374, 121375, 121376, 121377, 121378, 121379, 121380, 121381, 121382, 121383, 121384, 121385, 121386, 121387, 121388, 121389, 121390, 121391, 121392, 121393, 121394, 121395, 121396, 121397, 121398, 121403, 121404, 121405, 121406, 121407, 121408, 121409, 121410, 121411, 121412, 121413, 121414, 121415, 121416, 121417, 121418, 121419, 121420, 121421, 121422, 121423, 121424, 121425, 121426, 121427, 121428, 121429, 121430, 121431, 121432, 121433, 121434, 121435, 121436, 121437, 121438, 121439, 121440, 121441, 121442, 121443, 121444, 121445, 121446, 121447, 121448, 121449, 121450, 121451, 121452, 121461, 121476, 121499, 121500, 121501, 121502, 121503, 121505, 121506, 121507, 121508, 121509, 121510, 121511, 121512, 121513, 121514, 121515, 121516, 121517, 121518, 121519, 122880, 122881, 122882, 122883, 122884, 122885, 122886, 122888, 122889, 122890, 122891, 122892, 122893, 122894, 122895, 122896, 122897, 122898, 122899, 122900, 122901, 122902, 122903, 122904, 122907, 122908, 122909, 122910, 122911, 122912, 122913, 122915, 122916, 122918, 122919, 122920, 122921, 122922, 125136, 125137, 125138, 125139, 125140, 125141, 125142, 125252, 125253, 125254, 125255, 125256, 125257, 125258, 917760, 917761, 917762, 917763, 917764, 917765, 917766, 917767, 917768, 917769, 917770, 917771, 917772, 917773, 917774, 917775, 917776, 917777, 917778, 917779, 917780, 917781, 917782, 917783, 917784, 917785, 917786, 917787, 917788, 917789, 917790, 917791, 917792, 917793, 917794, 917795, 917796, 917797, 917798, 917799, 917800, 917801, 917802, 917803, 917804, 917805, 917806, 917807, 917808, 917809, 917810, 917811, 917812, 917813, 917814, 917815, 917816, 917817, 917818, 917819, 917820, 917821, 917822, 917823, 917824, 917825, 917826, 917827, 917828, 917829, 917830, 917831, 917832, 917833, 917834, 917835, 917836, 917837, 917838, 917839, 917840, 917841, 917842, 917843, 917844, 917845, 917846, 917847, 917848, 917849, 917850, 917851, 917852, 917853, 917854, 917855, 917856, 917857, 917858, 917859, 917860, 917861, 917862, 917863, 917864, 917865, 917866, 917867, 917868, 917869, 917870, 917871, 917872, 917873, 917874, 917875, 917876, 917877, 917878, 917879, 917880, 917881, 917882, 917883, 917884, 917885, 917886, 917887, 917888, 917889, 917890, 917891, 917892, 917893, 917894, 917895, 917896, 917897, 917898, 917899, 917900, 917901, 917902, 917903, 917904, 917905, 917906, 917907, 917908, 917909, 917910, 917911, 917912, 917913, 917914, 917915, 917916, 917917, 917918, 917919, 917920, 917921, 917922, 917923, 917924, 917925, 917926, 917927, 917928, 917929, 917930, 917931, 917932, 917933, 917934, 917935, 917936, 917937, 917938, 917939, 917940, 917941, 917942, 917943, 917944, 917945, 917946, 917947, 917948, 917949, 917950, 917951, 917952, 917953, 917954, 917955, 917956, 917957, 917958, 917959, 917960, 917961, 917962, 917963, 917964, 917965, 917966, 917967, 917968, 917969, 917970, 917971, 917972, 917973, 917974, 917975, 917976, 917977, 917978, 917979, 917980, 917981, 917982, 917983, 917984, 917985, 917986, 917987, 917988, 917989, 917990, 917991, 917992, 917993, 917994, 917995, 917996, 917997, 917998, 917999 }; // {{{ mapping }}}
	if (m < arraysz(map)) return map[m];
	return 0;
}

combining_type mark_for_codepoint(char_type c) {
	switch(c) { // {{{
		case 0: return 0;
		case 768 ... 879: return 1 + c - 768;
		case 1155 ... 1161: return 113 + c - 1155;
		case 1425 ... 1469: return 120 + c - 1425;
		case 1471: return 165;
		case 1473 ... 1474: return 166 + c - 1473;
		case 1476 ... 1477: return 168 + c - 1476;
		case 1479: return 170;
		case 1552 ... 1562: return 171 + c - 1552;
		case 1611 ... 1631: return 182 + c - 1611;
		case 1648: return 203;
		case 1750 ... 1756: return 204 + c - 1750;
		case 1759 ... 1764: return 211 + c - 1759;
		case 1767 ... 1768: return 217 + c - 1767;
		case 1770 ... 1773: return 219 + c - 1770;
		case 1809: return 223;
		case 1840 ... 1866: return 224 + c - 1840;
		case 1958 ... 1968: return 251 + c - 1958;
		case 2027 ... 2035: return 262 + c - 2027;
		case 2070 ... 2073: return 271 + c - 2070;
		case 2075 ... 2083: return 275 + c - 2075;
		case 2085 ... 2087: return 284 + c - 2085;
		case 2089 ... 2093: return 287 + c - 2089;
		case 2137 ... 2139: return 292 + c - 2137;
		case 2260 ... 2273: return 295 + c - 2260;
		case 2275 ... 2307: return 309 + c - 2275;
		case 2362 ... 2364: return 342 + c - 2362;
		case 2366 ... 2383: return 345 + c - 2366;
		case 2385 ... 2391: return 363 + c - 2385;
		case 2402 ... 2403: return 370 + c - 2402;
		case 2433 ... 2435: return 372 + c - 2433;
		case 2492: return 375;
		case 2494 ... 2500: return 376 + c - 2494;
		case 2503 ... 2504: return 383 + c - 2503;
		case 2507 ... 2509: return 385 + c - 2507;
		case 2519: return 388;
		case 2530 ... 2531: return 389 + c - 2530;
		case 2561 ... 2563: return 391 + c - 2561;
		case 2620: return 394;
		case 2622 ... 2626: return 395 + c - 2622;
		case 2631 ... 2632: return 400 + c - 2631;
		case 2635 ... 2637: return 402 + c - 2635;
		case 2641: return 405;
		case 2672 ... 2673: return 406 + c - 2672;
		case 2677: return 408;
		case 2689 ... 2691: return 409 + c - 2689;
		case 2748: return 412;
		case 2750 ... 2757: return 413 + c - 2750;
		case 2759 ... 2761: return 421 + c - 2759;
		case 2763 ... 2765: return 424 + c - 2763;
		case 2786 ... 2787: return 427 + c - 2786;
		case 2810 ... 2815: return 429 + c - 2810;
		case 2817 ... 2819: return 435 + c - 2817;
		case 2876: return 438;
		case 2878 ... 2884: return 439 + c - 2878;
		case 2887 ... 2888: return 446 + c - 2887;
		case 2891 ... 2893: return 448 + c - 2891;
		case 2902 ... 2903: return 451 + c - 2902;
		case 2914 ... 2915: return 453 + c - 2914;
		case 2946: return 455;
		case 3006 ... 3010: return 456 + c - 3006;
		case 3014 ... 3016: return 461 + c - 3014;
		case 3018 ... 3021: return 464 + c - 3018;
		case 3031: return 468;
		case 3072 ... 3075: return 469 + c - 3072;
		case 3134 ... 3140: return 473 + c - 3134;
		case 3142 ... 3144: return 480 + c - 3142;
		case 3146 ... 3149: return 483 + c - 3146;
		case 3157 ... 3158: return 487 + c - 3157;
		case 3170 ... 3171: return 489 + c - 3170;
		case 3201 ... 3203: return 491 + c - 3201;
		case 3260: return 494;
		case 3262 ... 3268: return 495 + c - 3262;
		case 3270 ... 3272: return 502 + c - 3270;
		case 3274 ... 3277: return 505 + c - 3274;
		case 3285 ... 3286: return 509 + c - 3285;
		case 3298 ... 3299: return 511 + c - 3298;
		case 3328 ... 3331: return 513 + c - 3328;
		case 3387 ... 3388: return 517 + c - 3387;
		case 3390 ... 3396: return 519 + c - 3390;
		case 3398 ... 3400: return 526 + c - 3398;
		case 3402 ... 3405: return 529 + c - 3402;
		case 3415: return 533;
		case 3426 ... 3427: return 534 + c - 3426;
		case 3458 ... 3459: return 536 + c - 3458;
		case 3530: return 538;
		case 3535 ... 3540: return 539 + c - 3535;
		case 3542: return 545;
		case 3544 ... 3551: return 546 + c - 3544;
		case 3570 ... 3571: return 554 + c - 3570;
		case 3633: return 556;
		case 3636 ... 3642: return 557 + c - 3636;
		case 3655 ... 3662: return 564 + c - 3655;
		case 3761: return 572;
		case 3764 ... 3769: return 573 + c - 3764;
		case 3771 ... 3772: return 579 + c - 3771;
		case 3784 ... 3789: return 581 + c - 3784;
		case 3864 ... 3865: return 587 + c - 3864;
		case 3893: return 589;
		case 3895: return 590;
		case 3897: return 591;
		case 3902 ... 3903: return 592 + c - 3902;
		case 3953 ... 3972: return 594 + c - 3953;
		case 3974 ... 3975: return 614 + c - 3974;
		case 3981 ... 3991: return 616 + c - 3981;
		case 3993 ... 4028: return 627 + c - 3993;
		case 4038: return 663;
		case 4139 ... 4158: return 664 + c - 4139;
		case 4182 ... 4185: return 684 + c - 4182;
		case 4190 ... 4192: return 688 + c - 4190;
		case 4194 ... 4196: return 691 + c - 4194;
		case 4199 ... 4205: return 694 + c - 4199;
		case 4209 ... 4212: return 701 + c - 4209;
		case 4226 ... 4237: return 705 + c - 4226;
		case 4239: return 717;
		case 4250 ... 4253: return 718 + c - 4250;
		case 4957 ... 4959: return 722 + c - 4957;
		case 5906 ... 5908: return 725 + c - 5906;
		case 5938 ... 5940: return 728 + c - 5938;
		case 5970 ... 5971: return 731 + c - 5970;
		case 6002 ... 6003: return 733 + c - 6002;
		case 6068 ... 6099: return 735 + c - 6068;
		case 6109: return 767;
		case 6155 ... 6157: return 768 + c - 6155;
		case 6277 ... 6278: return 771 + c - 6277;
		case 6313: return 773;
		case 6432 ... 6443: return 774 + c - 6432;
		case 6448 ... 6459: return 786 + c - 6448;
		case 6679 ... 6683: return 798 + c - 6679;
		case 6741 ... 6750: return 803 + c - 6741;
		case 6752 ... 6780: return 813 + c - 6752;
		case 6783: return 842;
		case 6832 ... 6846: return 843 + c - 6832;
		case 6912 ... 6916: return 858 + c - 6912;
		case 6964 ... 6980: return 863 + c - 6964;
		case 7019 ... 7027: return 880 + c - 7019;
		case 7040 ... 7042: return 889 + c - 7040;
		case 7073 ... 7085: return 892 + c - 7073;
		case 7142 ... 7155: return 905 + c - 7142;
		case 7204 ... 7223: return 919 + c - 7204;
		case 7376 ... 7378: return 939 + c - 7376;
		case 7380 ... 7400: return 942 + c - 7380;
		case 7405: return 963;
		case 7410 ... 7412: return 964 + c - 7410;
		case 7415 ... 7417: return 967 + c - 7415;
		case 7616 ... 7673: return 970 + c - 7616;
		case 7675 ... 7679: return 1028 + c - 7675;
		case 8400 ... 8432: return 1033 + c - 8400;
		case 11503 ... 11505: return 1066 + c - 11503;
		case 11647: return 1069;
		case 11744 ... 11775: return 1070 + c - 11744;
		case 12330 ... 12335: return 1102 + c - 12330;
		case 12441 ... 12442: return 1108 + c - 12441;
		case 42607 ... 42610: return 1110 + c - 42607;
		case 42612 ... 42621: return 1114 + c - 42612;
		case 42654 ... 42655: return 1124 + c - 42654;
		case 42736 ... 42737: return 1126 + c - 42736;
		case 43010: return 1128;
		case 43014: return 1129;
		case 43019: return 1130;
		case 43043 ... 43047: return 1131 + c - 43043;
		case 43136 ... 43137: return 1136 + c - 43136;
		case 43188 ... 43205: return 1138 + c - 43188;
		case 43232 ... 43249: return 1156 + c - 43232;
		case 43302 ... 43309: return 1174 + c - 43302;
		case 43335 ... 43347: return 1182 + c - 43335;
		case 43392 ... 43395: return 1195 + c - 43392;
		case 43443 ... 43456: return 1199 + c - 43443;
		case 43493: return 1213;
		case 43561 ... 43574: return 1214 + c - 43561;
		case 43587: return 1228;
		case 43596 ... 43597: return 1229 + c - 43596;
		case 43643 ... 43645: return 1231 + c - 43643;
		case 43696: return 1234;
		case 43698 ... 43700: return 1235 + c - 43698;
		case 43703 ... 43704: return 1238 + c - 43703;
		case 43710 ... 43711: return 1240 + c - 43710;
		case 43713: return 1242;
		case 43755 ... 43759: return 1243 + c - 43755;
		case 43765 ... 43766: return 1248 + c - 43765;
		case 44003 ... 44010: return 1250 + c - 44003;
		case 44012 ... 44013: return 1258 + c - 44012;
		case 64286: return 1260;
		case 65024 ... 65039: return 1261 + c - 65024;
		case 65056 ... 65071: return 1277 + c - 65056;
		case 66045: return 1293;
		case 66272: return 1294;
		case 66422 ... 66426: return 1295 + c - 66422;
		case 68097 ... 68099: return 1300 + c - 68097;
		case 68101 ... 68102: return 1303 + c - 68101;
		case 68108 ... 68111: return 1305 + c - 68108;
		case 68152 ... 68154: return 1309 + c - 68152;
		case 68159: return 1312;
		case 68325 ... 68326: return 1313 + c - 68325;
		case 69632 ... 69634: return 1315 + c - 69632;
		case 69688 ... 69702: return 1318 + c - 69688;
		case 69759 ... 69762: return 1333 + c - 69759;
		case 69808 ... 69818: return 1337 + c - 69808;
		case 69888 ... 69890: return 1348 + c - 69888;
		case 69927 ... 69940: return 1351 + c - 69927;
		case 70003: return 1365;
		case 70016 ... 70018: return 1366 + c - 70016;
		case 70067 ... 70080: return 1369 + c - 70067;
		case 70090 ... 70092: return 1383 + c - 70090;
		case 70188 ... 70199: return 1386 + c - 70188;
		case 70206: return 1398;
		case 70367 ... 70378: return 1399 + c - 70367;
		case 70400 ... 70403: return 1411 + c - 70400;
		case 70460: return 1415;
		case 70462 ... 70468: return 1416 + c - 70462;
		case 70471 ... 70472: return 1423 + c - 70471;
		case 70475 ... 70477: return 1425 + c - 70475;
		case 70487: return 1428;
		case 70498 ... 70499: return 1429 + c - 70498;
		case 70502 ... 70508: return 1431 + c - 70502;
		case 70512 ... 70516: return 1438 + c - 70512;
		case 70709 ... 70726: return 1443 + c - 70709;
		case 70832 ... 70851: return 1461 + c - 70832;
		case 71087 ... 71093: return 1481 + c - 71087;
		case 71096 ... 71104: return 1488 + c - 71096;
		case 71132 ... 71133: return 1497 + c - 71132;
		case 71216 ... 71232: return 1499 + c - 71216;
		case 71339 ... 71351: return 1516 + c - 71339;
		case 71453 ... 71467: return 1529 + c - 71453;
		case 72193 ... 72202: return 1544 + c - 72193;
		case 72243 ... 72249: return 1554 + c - 72243;
		case 72251 ... 72254: return 1561 + c - 72251;
		case 72263: return 1565;
		case 72273 ... 72283: return 1566 + c - 72273;
		case 72330 ... 72345: return 1577 + c - 72330;
		case 72751 ... 72758: return 1593 + c - 72751;
		case 72760 ... 72767: return 1601 + c - 72760;
		case 72850 ... 72871: return 1609 + c - 72850;
		case 72873 ... 72886: return 1631 + c - 72873;
		case 73009 ... 73014: return 1645 + c - 73009;
		case 73018: return 1651;
		case 73020 ... 73021: return 1652 + c - 73020;
		case 73023 ... 73029: return 1654 + c - 73023;
		case 73031: return 1661;
		case 92912 ... 92916: return 1662 + c - 92912;
		case 92976 ... 92982: return 1667 + c - 92976;
		case 94033 ... 94078: return 1674 + c - 94033;
		case 94095 ... 94098: return 1720 + c - 94095;
		case 113821 ... 113822: return 1724 + c - 113821;
		case 119141 ... 119145: return 1726 + c - 119141;
		case 119149 ... 119154: return 1731 + c - 119149;
		case 119163 ... 119170: return 1737 + c - 119163;
		case 119173 ... 119179: return 1745 + c - 119173;
		case 119210 ... 119213: return 1752 + c - 119210;
		case 119362 ... 119364: return 1756 + c - 119362;
		case 121344 ... 121398: return 1759 + c - 121344;
		case 121403 ... 121452: return 1814 + c - 121403;
		case 121461: return 1864;
		case 121476: return 1865;
		case 121499 ... 121503: return 1866 + c - 121499;
		case 121505 ... 121519: return 1871 + c - 121505;
		case 122880 ... 122886: return 1886 + c - 122880;
		case 122888 ... 122904: return 1893 + c - 122888;
		case 122907 ... 122913: return 1910 + c - 122907;
		case 122915 ... 122916: return 1917 + c - 122915;
		case 122918 ... 122922: return 1919 + c - 122918;
		case 125136 ... 125142: return 1924 + c - 125136;
		case 125252 ... 125258: return 1931 + c - 125252;
		case 917760 ... 917999: return 1938 + c - 917760;
default: return 0;
	} // }}}
}


END_ALLOW_CASE_RANGE
