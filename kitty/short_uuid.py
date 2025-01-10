#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import math
import string
import uuid as _uuid
from collections.abc import Sequence


def num_to_string(number: int, alphabet: Sequence[str], alphabet_len: int, pad_to_length: int | None = None) -> str:
    ans = []
    number = max(0, number)
    while number:
        number, digit = divmod(number, alphabet_len)
        ans.append(alphabet[digit])
    if pad_to_length is not None and pad_to_length > len(ans):
        ans.append(alphabet[0] * (pad_to_length - len(ans)))
    return ''.join(ans)


def string_to_num(string: str, alphabet_map: dict[str, int], alphabet_len: int) -> int:
    ans = 0
    for char in reversed(string):
        ans = ans * alphabet_len + alphabet_map[char]
    return ans


escape_code_safe_alphabet = string.ascii_letters + string.digits + string.punctuation + ' '
human_alphabet = (string.digits + string.ascii_letters)[2:]


class ShortUUID:

    def __init__(self, alphabet: str = human_alphabet):
        self.alphabet = tuple(sorted(alphabet))
        self.alphabet_len = len(self.alphabet)
        self.alphabet_map = {c: i for i, c in enumerate(self.alphabet)}
        self.uuid_pad_len = int(math.ceil(math.log(1 << 128, self.alphabet_len)))

    def uuid4(self, pad_to_length: int | None = None) -> str:
        if pad_to_length is None:
            pad_to_length = self.uuid_pad_len
        return num_to_string(_uuid.uuid4().int, self.alphabet, self.alphabet_len, pad_to_length)

    def uuid5(self, namespace: _uuid.UUID, name: str, pad_to_length: int | None = None) -> str:
        if pad_to_length is None:
            pad_to_length = self.uuid_pad_len
        return num_to_string(_uuid.uuid5(namespace, name).int, self.alphabet, self.alphabet_len, pad_to_length)

    def decode(self, encoded: str) -> _uuid.UUID:
        return _uuid.UUID(int=string_to_num(encoded, self.alphabet_map, self.alphabet_len))


_global_instance = ShortUUID()
uuid4 = _global_instance.uuid4
uuid5 = _global_instance.uuid5
decode = _global_instance.decode
_escape_code_instance: ShortUUID | None = None


def uuid4_for_escape_code() -> str:
    global _escape_code_instance
    if _escape_code_instance is None:
        _escape_code_instance = ShortUUID(escape_code_safe_alphabet)
    return _escape_code_instance.uuid4()
