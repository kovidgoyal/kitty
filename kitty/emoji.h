#pragma once
#include "data-types.h"

START_ALLOW_CASE_RANGE
static inline bool is_emoji(uint32_t code) {
	switch(code) {
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
		case 0x2660:
			return true;
		case 0x2663:
			return true;
		case 0x2665 ... 0x2666:
			return true;
		case 0x2668:
			return true;
		case 0x267b:
			return true;
		case 0x267f:
			return true;
		case 0x2692 ... 0x2697:
			return true;
		case 0x2699:
			return true;
		case 0x269b ... 0x269c:
			return true;
		case 0x26a0 ... 0x26a1:
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
		case 0x1f6e0 ... 0x1f6e5:
			return true;
		case 0x1f6e9:
			return true;
		case 0x1f6eb ... 0x1f6ec:
			return true;
		case 0x1f6f0:
			return true;
		case 0x1f6f3 ... 0x1f6f8:
			return true;
		case 0x1f910 ... 0x1f93a:
			return true;
		case 0x1f93c ... 0x1f93e:
			return true;
		case 0x1f940 ... 0x1f945:
			return true;
		case 0x1f947 ... 0x1f94c:
			return true;
		case 0x1f950 ... 0x1f96b:
			return true;
		case 0x1f980 ... 0x1f997:
			return true;
		case 0x1f9c0:
			return true;
		case 0x1f9d0 ... 0x1f9e6:
			return true;
		default: return false;
	}
	return false; 
}
static inline bool is_emoji_modifier(uint32_t code) {
	switch(code) {
		case 0x1f3fb ... 0x1f3ff:
			return true;
		default: return false;
	}
	return false; 
}
END_ALLOW_CASE_RANGE
