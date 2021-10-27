from typing import List, Optional, Tuple

from .collect import Segment


def split_with_highlights(
    line: str, truncate_points: List[int], fg_highlights: List[Segment],
    bg_highlight: Optional[Segment]
) -> List[str]:
    pass


def changed_center(left_prefix: str, right_postfix: str) -> Tuple[int, int]:
    pass
