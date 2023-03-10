
from typing import Callable, List, Optional, Tuple

from .collect import Segment

def splitlines_like_git(raw: bytes, callback: Callable[[memoryview], None]) -> None: ...

def split_with_highlights(
    line: str, truncate_points: List[int], fg_highlights: List[Segment],
    bg_highlight: Optional[Segment]
) -> List[str]:
    pass


def changed_center(left_prefix: str, right_postfix: str) -> Tuple[int, int]:
    pass
