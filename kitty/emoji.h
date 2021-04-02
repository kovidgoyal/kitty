// unicode data, built from the unicode standard on: 2021-04-02
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
	return false;
}
static inline bool
is_symbol(char_type code) {
	switch(code) {
		case 0x24:
			return true;
		case 0x2b:
			return true;
		case 0x3c ... 0x3e:
			return true;
		case 0x5e:
			return true;
		case 0x60:
			return true;
		case 0x7c:
			return true;
		case 0x7e:
			return true;
		case 0xa2 ... 0xa6:
			return true;
		case 0xa8 ... 0xa9:
			return true;
		case 0xac:
			return true;
		case 0xae ... 0xb1:
			return true;
		case 0xb4:
			return true;
		case 0xb8:
			return true;
		case 0xd7:
			return true;
		case 0xf7:
			return true;
		case 0x2c2 ... 0x2c5:
			return true;
		case 0x2d2 ... 0x2df:
			return true;
		case 0x2e5 ... 0x2eb:
			return true;
		case 0x2ed:
			return true;
		case 0x2ef ... 0x2ff:
			return true;
		case 0x375:
			return true;
		case 0x384 ... 0x385:
			return true;
		case 0x3f6:
			return true;
		case 0x482:
			return true;
		case 0x58d ... 0x58f:
			return true;
		case 0x606 ... 0x608:
			return true;
		case 0x60b:
			return true;
		case 0x60e ... 0x60f:
			return true;
		case 0x6de:
			return true;
		case 0x6e9:
			return true;
		case 0x6fd ... 0x6fe:
			return true;
		case 0x7f6:
			return true;
		case 0x7fe ... 0x7ff:
			return true;
		case 0x9f2 ... 0x9f3:
			return true;
		case 0x9fa ... 0x9fb:
			return true;
		case 0xaf1:
			return true;
		case 0xb70:
			return true;
		case 0xbf3 ... 0xbfa:
			return true;
		case 0xc7f:
			return true;
		case 0xd4f:
			return true;
		case 0xd79:
			return true;
		case 0xe3f:
			return true;
		case 0xf01 ... 0xf03:
			return true;
		case 0xf13:
			return true;
		case 0xf15 ... 0xf17:
			return true;
		case 0xf1a ... 0xf1f:
			return true;
		case 0xf34:
			return true;
		case 0xf36:
			return true;
		case 0xf38:
			return true;
		case 0xfbe ... 0xfc5:
			return true;
		case 0xfc7 ... 0xfcc:
			return true;
		case 0xfce ... 0xfcf:
			return true;
		case 0xfd5 ... 0xfd8:
			return true;
		case 0x109e ... 0x109f:
			return true;
		case 0x1390 ... 0x1399:
			return true;
		case 0x166d:
			return true;
		case 0x17db:
			return true;
		case 0x1940:
			return true;
		case 0x19de ... 0x19ff:
			return true;
		case 0x1b61 ... 0x1b6a:
			return true;
		case 0x1b74 ... 0x1b7c:
			return true;
		case 0x1fbd:
			return true;
		case 0x1fbf ... 0x1fc1:
			return true;
		case 0x1fcd ... 0x1fcf:
			return true;
		case 0x1fdd ... 0x1fdf:
			return true;
		case 0x1fed ... 0x1fef:
			return true;
		case 0x1ffd ... 0x1ffe:
			return true;
		case 0x2044:
			return true;
		case 0x2052:
			return true;
		case 0x207a ... 0x207c:
			return true;
		case 0x208a ... 0x208c:
			return true;
		case 0x20a0 ... 0x20bf:
			return true;
		case 0x2100 ... 0x2101:
			return true;
		case 0x2103 ... 0x2106:
			return true;
		case 0x2108 ... 0x2109:
			return true;
		case 0x2114:
			return true;
		case 0x2116 ... 0x2118:
			return true;
		case 0x211e ... 0x2123:
			return true;
		case 0x2125:
			return true;
		case 0x2127:
			return true;
		case 0x2129:
			return true;
		case 0x212e:
			return true;
		case 0x213a ... 0x213b:
			return true;
		case 0x2140 ... 0x2144:
			return true;
		case 0x214a ... 0x214d:
			return true;
		case 0x214f:
			return true;
		case 0x218a ... 0x218b:
			return true;
		case 0x2190 ... 0x2307:
			return true;
		case 0x230c ... 0x2328:
			return true;
		case 0x232b ... 0x2426:
			return true;
		case 0x2440 ... 0x244a:
			return true;
		case 0x249c ... 0x24e9:
			return true;
		case 0x2500 ... 0x2767:
			return true;
		case 0x2794 ... 0x27c4:
			return true;
		case 0x27c7 ... 0x27e5:
			return true;
		case 0x27f0 ... 0x2982:
			return true;
		case 0x2999 ... 0x29d7:
			return true;
		case 0x29dc ... 0x29fb:
			return true;
		case 0x29fe ... 0x2b73:
			return true;
		case 0x2b76 ... 0x2b95:
			return true;
		case 0x2b97 ... 0x2bff:
			return true;
		case 0x2ce5 ... 0x2cea:
			return true;
		case 0x2e50 ... 0x2e51:
			return true;
		case 0x2e80 ... 0x2e99:
			return true;
		case 0x2e9b ... 0x2ef3:
			return true;
		case 0x2f00 ... 0x2fd5:
			return true;
		case 0x2ff0 ... 0x2ffb:
			return true;
		case 0x3004:
			return true;
		case 0x3012 ... 0x3013:
			return true;
		case 0x3020:
			return true;
		case 0x3036 ... 0x3037:
			return true;
		case 0x303e ... 0x303f:
			return true;
		case 0x309b ... 0x309c:
			return true;
		case 0x3190 ... 0x3191:
			return true;
		case 0x3196 ... 0x319f:
			return true;
		case 0x31c0 ... 0x31e3:
			return true;
		case 0x3200 ... 0x321e:
			return true;
		case 0x322a ... 0x3247:
			return true;
		case 0x3250:
			return true;
		case 0x3260 ... 0x327f:
			return true;
		case 0x328a ... 0x32b0:
			return true;
		case 0x32c0 ... 0x33ff:
			return true;
		case 0x4dc0 ... 0x4dff:
			return true;
		case 0xa490 ... 0xa4c6:
			return true;
		case 0xa700 ... 0xa716:
			return true;
		case 0xa720 ... 0xa721:
			return true;
		case 0xa789 ... 0xa78a:
			return true;
		case 0xa828 ... 0xa82b:
			return true;
		case 0xa836 ... 0xa839:
			return true;
		case 0xaa77 ... 0xaa79:
			return true;
		case 0xab5b:
			return true;
		case 0xab6a ... 0xab6b:
			return true;
		case 0xfb29:
			return true;
		case 0xfbb2 ... 0xfbc1:
			return true;
		case 0xfdfc ... 0xfdfd:
			return true;
		case 0xfe62:
			return true;
		case 0xfe64 ... 0xfe66:
			return true;
		case 0xfe69:
			return true;
		case 0xff04:
			return true;
		case 0xff0b:
			return true;
		case 0xff1c ... 0xff1e:
			return true;
		case 0xff3e:
			return true;
		case 0xff40:
			return true;
		case 0xff5c:
			return true;
		case 0xff5e:
			return true;
		case 0xffe0 ... 0xffe6:
			return true;
		case 0xffe8 ... 0xffee:
			return true;
		case 0xfffc ... 0xfffd:
			return true;
		case 0x10137 ... 0x1013f:
			return true;
		case 0x10179 ... 0x10189:
			return true;
		case 0x1018c ... 0x1018e:
			return true;
		case 0x10190 ... 0x1019c:
			return true;
		case 0x101a0:
			return true;
		case 0x101d0 ... 0x101fc:
			return true;
		case 0x10877 ... 0x10878:
			return true;
		case 0x10ac8:
			return true;
		case 0x1173f:
			return true;
		case 0x11fd5 ... 0x11ff1:
			return true;
		case 0x16b3c ... 0x16b3f:
			return true;
		case 0x16b45:
			return true;
		case 0x1bc9c:
			return true;
		case 0x1d000 ... 0x1d0f5:
			return true;
		case 0x1d100 ... 0x1d126:
			return true;
		case 0x1d129 ... 0x1d164:
			return true;
		case 0x1d16a ... 0x1d16c:
			return true;
		case 0x1d183 ... 0x1d184:
			return true;
		case 0x1d18c ... 0x1d1a9:
			return true;
		case 0x1d1ae ... 0x1d1e8:
			return true;
		case 0x1d200 ... 0x1d241:
			return true;
		case 0x1d245:
			return true;
		case 0x1d300 ... 0x1d356:
			return true;
		case 0x1d6c1:
			return true;
		case 0x1d6db:
			return true;
		case 0x1d6fb:
			return true;
		case 0x1d715:
			return true;
		case 0x1d735:
			return true;
		case 0x1d74f:
			return true;
		case 0x1d76f:
			return true;
		case 0x1d789:
			return true;
		case 0x1d7a9:
			return true;
		case 0x1d7c3:
			return true;
		case 0x1d800 ... 0x1d9ff:
			return true;
		case 0x1da37 ... 0x1da3a:
			return true;
		case 0x1da6d ... 0x1da74:
			return true;
		case 0x1da76 ... 0x1da83:
			return true;
		case 0x1da85 ... 0x1da86:
			return true;
		case 0x1e14f:
			return true;
		case 0x1e2ff:
			return true;
		case 0x1ecac:
			return true;
		case 0x1ecb0:
			return true;
		case 0x1ed2e:
			return true;
		case 0x1eef0 ... 0x1eef1:
			return true;
		case 0x1f000 ... 0x1f02b:
			return true;
		case 0x1f030 ... 0x1f093:
			return true;
		case 0x1f0a0 ... 0x1f0ae:
			return true;
		case 0x1f0b1 ... 0x1f0bf:
			return true;
		case 0x1f0c1 ... 0x1f0cf:
			return true;
		case 0x1f0d1 ... 0x1f0f5:
			return true;
		case 0x1f10d ... 0x1f1ad:
			return true;
		case 0x1f1e6 ... 0x1f202:
			return true;
		case 0x1f210 ... 0x1f23b:
			return true;
		case 0x1f240 ... 0x1f248:
			return true;
		case 0x1f250 ... 0x1f251:
			return true;
		case 0x1f260 ... 0x1f265:
			return true;
		case 0x1f300 ... 0x1f6d7:
			return true;
		case 0x1f6e0 ... 0x1f6ec:
			return true;
		case 0x1f6f0 ... 0x1f6fc:
			return true;
		case 0x1f700 ... 0x1f773:
			return true;
		case 0x1f780 ... 0x1f7d8:
			return true;
		case 0x1f7e0 ... 0x1f7eb:
			return true;
		case 0x1f800 ... 0x1f80b:
			return true;
		case 0x1f810 ... 0x1f847:
			return true;
		case 0x1f850 ... 0x1f859:
			return true;
		case 0x1f860 ... 0x1f887:
			return true;
		case 0x1f890 ... 0x1f8ad:
			return true;
		case 0x1f8b0 ... 0x1f8b1:
			return true;
		case 0x1f900 ... 0x1f978:
			return true;
		case 0x1f97a ... 0x1f9cb:
			return true;
		case 0x1f9cd ... 0x1fa53:
			return true;
		case 0x1fa60 ... 0x1fa6d:
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
		case 0x1fb00 ... 0x1fb92:
			return true;
		case 0x1fb94 ... 0x1fbca:
			return true;
		default: return false;
	}
	return false;
}

END_ALLOW_CASE_RANGE
