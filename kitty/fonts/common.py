#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Dict, Union

from kitty.constants import is_macos

from . import VariableData

if TYPE_CHECKING:
    from kitty.fast_data_types import CoreTextFont, CTFace, FontConfigPattern
    from kitty.fast_data_types import Face as FT_Face

    Descriptor = Union[FontConfigPattern, CoreTextFont]
    def Face(descriptor: Descriptor) -> Union[FT_Face, CTFace]:
        pass
else:
    Descriptor = object
    if is_macos:
        from kitty.fast_data_types import CTFace as Face
    else:
        from kitty.fast_data_types import Face


cache_for_variable_data_by_path: Dict[str, VariableData] = {}


def get_variable_data_for_descriptor(d: Descriptor) -> VariableData:
    if not d['path']:
        return Face(descriptor=d).get_variable_data()
    ans = cache_for_variable_data_by_path.get(d['path'])
    if ans is None:
        ans = cache_for_variable_data_by_path[d['path']] = Face(descriptor=d).get_variable_data()
    return ans
