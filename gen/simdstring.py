#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Generate the amd64 archsimd implementations of the functions in
# tools/simdstring. These are identical apart from the vector width and the
# expression that compares a vector against the needles, so they are
# generated, see tools/simdstring/simd_amd64.go for the helpers they use and
# an explanation of how they work.

from collections.abc import Callable
from typing import NamedTuple

OUTPUT_PATH = 'tools/simdstring/simd_amd64_generated.go'
WIDTHS = 16, 32, 64
# The number of vectors tested per iteration of the main loop. For 16 and 32
# byte vectors this is four, for 64 byte vectors, two. Determined by
# benchmarking.
UNROLL = {16: 4, 32: 4, 64: 2}


class Op(NamedTuple):
    params: str
    args: str
    # Statements creating the vectors of needles for a vector width
    setup: Callable[[int], tuple[str, ...]]
    # Expression returning the mask of matching lanes for a vector width and
    # name of the vector variable
    mask: Callable[[int, str], str]
    # Whether the result is the first lane not in the mask
    inverted: bool = False


def broadcast(*names: str) -> Callable[[int], tuple[str, ...]]:
    def setup(w: int) -> tuple[str, ...]:
        vars = ', '.join(f'n{x}' for x in names)
        vals = ', '.join(f'archsimd.BroadcastUint8x{w}({x})' for x in names)
        return (f'{vars} := {vals}',)

    return setup


def c0_setup(w: int) -> tuple[str, ...]:
    # The 16 and 32 byte vector code uses min(x, 0x1f) == x <=> x <= 0x1f as
    # unsigned comparisons are only available with AVX512
    first = "' '" if w == 64 else "' '-1"
    return (f'c0a, c0b := archsimd.BroadcastUint8x{w}({first}), archsimd.BroadcastUint8x{w}(0x7f)',)


ops: dict[str, Op] = {
    'index_byte': Op('data []byte, b byte', 'data, b', broadcast('b'), lambda w, v: f'{v}.Equal(nb)'),
    'index_byte2': Op('data []byte, a, b byte', 'data, a, b', broadcast('a', 'b'), lambda w, v: f'{v}.Equal(na).Or({v}.Equal(nb))'),
    'index_c0': Op('data []byte', 'data', c0_setup, lambda w, v: f'c0_mask{w}({v}, c0a, c0b)'),
    'not_index_byte': Op('data []byte, b byte', 'data, b', broadcast('b'), lambda w, v: f'{v}.Equal(nb)', True),
    'not_index_byte2': Op('data []byte, a, b byte', 'data, a, b', broadcast('a', 'b'), lambda w, v: f'{v}.Equal(na).Or({v}.Equal(nb))', True),
}


def generate_function(name: str, op: Op, w: int) -> list[str]:
    lines: list[str] = []

    def a(indent: int, line: str) -> None:
        lines.append('\t' * indent + line)

    def bitmask(width: int, v: str = 'v') -> str:
        return ('^' if op.inverted else '') + op.mask(width, v) + '.ToBits()'

    a(0, f'func {name}_{w}({op.params}) int {{')
    a(1, 'if len(data) < 16 {')
    a(2, 'if len(data) == 0 {')
    a(3, 'return -1')
    a(2, '}')
    a(2, 'v, k := load_short16(data)')
    for x in op.setup(16):
        a(2, x)
    a(2, f'return short_index16({bitmask(16)}, k, len(data))')
    a(1, '}')
    a(1, 'p := unsafe.Pointer(unsafe.SliceData(data))')
    for h in (16, 32) if w == 64 else (16,):
        a(1, f'if len(data) < {2 * h} {{')
        for x in op.setup(h):
            a(2, x)
        a(2, f'v, h := load{h}(p, 0), load{h}(p, len(data)-{h})')
        a(2, f'return pair_index(uint64({bitmask(h)}), uint64({bitmask(h, "h")}), {h}, len(data))')
        a(1, '}')
    for x in op.setup(w):
        a(1, x)
    a(1, f'v := load{w}(p, 0)')
    a(1, f'if m := {bitmask(w)}; m != 0 {{')
    a(2, f'return bits.TrailingZeros{w}(m)')
    a(1, '}')
    a(1, f'last := len(data) - {w}')
    a(1, f'i := aligned_start(data, {w})')
    n = UNROLL[w]
    a(1, f'// Test {n} vectors at a time, finding the matching vector with the loop below')
    a(1, f'for ; i+{(n - 1) * w} < last; i += {n * w} {{')
    for j in range(n):
        a(2, f'v{j} := load{w}(p, i+{j * w})' if j else f'v{j} := load{w}(p, i)')
    for j in range(n):
        a(2, f'c{j} := {op.mask(w, f"v{j}")}')
    combined = 'c0' + ''.join(f'.{"And" if op.inverted else "Or"}(c{j})' for j in range(1, n))
    a(2, f'if {"^" if op.inverted else ""}{combined}.ToBits() != 0 {{')
    a(3, 'break')
    a(2, '}')
    a(1, '}')
    a(1, f'for ; i < last; i += {w} {{')
    a(2, f'v := load{w}(p, i)')
    a(2, f'if m := {bitmask(w)}; m != 0 {{')
    a(3, f'return i + bits.TrailingZeros{w}(m)')
    a(2, '}')
    a(1, '}')
    a(1, f'v = load{w}(p, last)')
    a(1, f'return found_at{w}(last, {bitmask(w)})')
    a(0, '}')
    return lines


def generate_simdstring_amd64() -> str:
    lines = [
        '//go:build goexperiment.simd && amd64',
        '',
        'package simdstring',
        '',
        'import (',
        '\t"math/bits"',
        '\t"simd/archsimd"',
        '\t"unsafe"',
        ')',
    ]
    for w in WIDTHS:
        for name, op in ops.items():
            lines.append('')
            lines.extend(generate_function(name, op, w))
    return '\n'.join(lines)
