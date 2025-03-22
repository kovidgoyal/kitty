#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import NamedTuple


class BitField(NamedTuple):
     name: str
     bits: int


def typename_for_bitsize(bits: int) -> str:
     if bits <= 8:
        return 'uint8'
     if bits <= 16:
        return 'uint16'
     if bits <= 32:
        return 'uint32'
     return 'uint64'


def make_bitfield(dest: str, typename: str, *fields_: str, add_package: bool = True) -> tuple[str, str]:
    output_path = os.path.join(dest, f'{typename.lower()}_generated.go')
    ans = [f'package {os.path.basename(dest)}', '']
    a = ans.append
    if not add_package:
        del ans[0]

    def fieldify(spec: str) -> BitField:
        name, num = spec.partition(' ')[::2]
        return BitField(name, int(num))

    fields = tuple(map(fieldify, fields_))
    total_size = sum(x.bits for x in fields)
    if total_size > 64:
        raise ValueError(f'Total size of bit fields: {total_size} for {typename} is larger than 64 bits')
    a(f'// Total number of bits used: {total_size}')
    itype = typename_for_bitsize(total_size)
    a(f'type {typename} {itype}')
    a('')
    shift = 0
    for bf in reversed(fields):
        tn = typename_for_bitsize(bf.bits)
        mask = '0b' + '1' * bf.bits
        a(f'func (s {typename}) {bf.name.capitalize()}() {tn} {{')  # }}
        if shift:
            a(f'    return {tn}((s >> {shift}) & {mask})')
        else:
            a(f'    return {tn}(s & {mask})')
        a('}')
        a('')
        a(f'func (s *{typename}) Set_{bf.name}(val {tn}) {{')  # }}
        if shift:
            a(f'    *s &^= {mask} << {shift}')
            a(f'    *s |= {typename}(val&{mask}) << {shift}')
        else:
            a(f'    *s &^= {mask}')
            a(f'    *s |= {typename}(val & {mask})')
        a('}')
        a('')
        shift += bf.bits

    return output_path, '\n'.join(ans)
