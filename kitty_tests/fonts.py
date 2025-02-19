#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import array
import os
import tempfile
import unittest
from collections.abc import Iterable
from functools import lru_cache, partial
from itertools import repeat
from math import ceil

from kitty.constants import is_macos, read_kitty_resource
from kitty.fast_data_types import (
    DECAWM,
    ParsedFontFeature,
    get_fallback_font,
    set_allow_use_of_box_fonts,
    sprite_idx_to_pos,
    sprite_map_set_layout,
    sprite_map_set_limits,
    test_render_line,
    test_sprite_position_increment,
    wcwidth,
)
from kitty.fonts import family_name_to_key
from kitty.fonts.common import FontSpec, all_fonts_map, face_from_descriptor, get_font_files, get_named_style, spec_for_face
from kitty.fonts.render import coalesce_symbol_maps, create_face, render_string, setup_for_testing, shape_string
from kitty.options.types import Options

from . import BaseTest, draw_multicell


def parse_font_spec(spec):
    return FontSpec.from_setting(spec)


@lru_cache(maxsize=64)
def testing_font_data(name):
    return read_kitty_resource(name, __name__.rpartition('.')[0])


class Selection(BaseTest):

    def test_font_selection(self):
        self.set_options({'font_features': {'LiberationMono': (ParsedFontFeature('-dlig'),)}})
        opts = Options()
        fonts_map = all_fonts_map(True)
        names = set(fonts_map['family_map']) | set(fonts_map['variable_map'])
        del fonts_map

        def s(family: str, *expected: str, alternate=None) -> None:
            opts.font_family = parse_font_spec(family)
            ff = get_font_files(opts)
            actual = tuple(face_from_descriptor(ff[x]).postscript_name() for x in ('medium', 'bold', 'italic', 'bi'))  # type: ignore
            del ff
            for x in actual:
                if '/' in x:  # Old FreeType failed to generate postscript name for a variable font probably
                    return
            with self.subTest(spec=family):
                try:
                    self.ae(expected, actual)
                except AssertionError:
                    if alternate:
                        self.ae(alternate, actual)
                    else:
                        raise

        def both(family: str, *expected: str, alternate=None) -> None:
            for family in (family, f'family="{family}"'):
                s(family, *expected, alternate=alternate)

        def has(family, allow_missing_in_ci=False):
            ans = family_name_to_key(family) in names
            if self.is_ci and not allow_missing_in_ci and not ans:
                raise AssertionError(f'The family: {family} is not available')
            return ans

        def t(family, psprefix, bold='Bold', italic='Italic', bi='', reg='Regular', allow_missing_in_ci=False, alternate=None):
            if has(family, allow_missing_in_ci=allow_missing_in_ci):
                bi = bi or bold + italic
                if reg:
                    reg = '-' + reg
                both(family, f'{psprefix}{reg}', f'{psprefix}-{bold}', f'{psprefix}-{italic}', f'{psprefix}-{bi}', alternate=alternate)

        t('Source Code Pro', 'SourceCodePro', 'Semibold', 'It')
        t('sourcecodeVf', 'SourceCodeVF', 'Semibold')

        # The Arch ttf-fira-code package excludes the variable fonts for some reason
        t('fira code', 'FiraCodeRoman', 'SemiBold', 'Regular', 'SemiBold', alternate=(
            'FiraCode-Regular', 'FiraCode-SemiBold', 'FiraCode-Retina', 'FiraCode-SemiBold'))
        t('hack', 'Hack')
        # some ubuntu systems (such as the build VM) have only the regular and
        # bold faces of DejaVu Sans Mono installed.
        # t('DejaVu Sans Mono', 'DejaVuSansMono', reg='', italic='Oblique')
        t('ubuntu mono', 'UbuntuMono')
        t('liberation mono', 'LiberationMono', reg='')
        t('ibm plex mono', 'IBMPlexMono', 'SmBld', reg='')
        t('iosevka fixed', 'Iosevka-Fixed', 'Semibold', reg='', bi='Semibold-Italic', allow_missing_in_ci=True)
        t('iosevka term', 'Iosevka-Term', 'Semibold', reg='', bi='Semibold-Italic', allow_missing_in_ci=True)
        t('fantasque sans mono', 'FantasqueSansMono')
        t('jetbrains mono', 'JetBrainsMono', 'SemiBold')
        t('consolas', 'Consolas', reg='', allow_missing_in_ci=True)
        if has('cascadia code'):
            if is_macos:
                both('cascadia code', 'CascadiaCode-Regular', 'CascadiaCode-Regular_SemiBold', 'CascadiaCode-Italic', 'CascadiaCode-Italic_SemiBold-Italic')
            else:
                both('cascadia code', 'CascadiaCodeRoman-Regular', 'CascadiaCodeRoman-SemiBold', 'CascadiaCode-Italic', 'CascadiaCode-SemiBoldItalic')
        if has('cascadia mono'):
            if is_macos:
                both('cascadia mono', 'CascadiaMono-Regular', 'CascadiaMono-Regular_SemiBold', 'CascadiaMono-Italic', 'CascadiaMono-Italic_SemiBold-Italic')
            else:
                both('cascadia mono', 'CascadiaMonoRoman-Regular', 'CascadiaMonoRoman-SemiBold', 'CascadiaMono-Italic', 'CascadiaMono-SemiBoldItalic')
        if has('operator mono', allow_missing_in_ci=True):
            both('operator mono', 'OperatorMono-Medium', 'OperatorMono-Bold', 'OperatorMono-MediumItalic', 'OperatorMono-BoldItalic')

        # Test variable font selection

        if has('SourceCodeVF'):
            opts = Options()
            opts.font_family = parse_font_spec('family="SourceCodeVF" variable_name="SourceCodeUpright" style="Bold"')
            ff = get_font_files(opts)
            face = face_from_descriptor(ff['medium'])
            self.ae(get_named_style(face)['name'], 'Bold')
            face = face_from_descriptor(ff['italic'])
            self.ae(get_named_style(face)['name'], 'Bold Italic')
            face = face_from_descriptor(ff['bold'])
            self.ae(get_named_style(face)['name'], 'Black')
            face = face_from_descriptor(ff['bi'])
            self.ae(get_named_style(face)['name'], 'Black Italic')
            opts.font_family = parse_font_spec('family=SourceCodeVF variable_name=SourceCodeUpright wght=470')
            opts.italic_font = parse_font_spec('family=SourceCodeVF variable_name=SourceCodeItalic style=Black')
            ff = get_font_files(opts)
            self.assertFalse(get_named_style(ff['medium']))
            self.ae(get_named_style(ff['italic'])['name'], 'Black Italic')
        if has('cascadia code'):
            opts = Options()
            opts.font_family = parse_font_spec('family="cascadia code"')
            opts.italic_font = parse_font_spec('family="cascadia code" variable_name= style="Light Italic"')
            ff = get_font_files(opts)

            def t(x, **kw):
                if 'spec' in kw:
                    fs = FontSpec.from_setting('family="Cascadia Code" ' + kw['spec'])._replace(created_from_string='')
                else:
                    kw['family'] = 'Cascadia Code'
                    fs = FontSpec(**kw)
                face = face_from_descriptor(ff[x])
                self.ae(fs.as_setting, spec_for_face('Cascadia Code', face).as_setting)

            t('medium', variable_name='CascadiaCodeRoman', style='Regular')
            t('italic', variable_name='', style='Light Italic')

            opts = Options()
            opts.font_family = parse_font_spec('family="cascadia code" variable_name=CascadiaCodeRoman wght=455')
            opts.italic_font = parse_font_spec('family="cascadia code" variable_name= wght=405')
            opts.bold_font = parse_font_spec('family="cascadia code" variable_name=CascadiaCodeRoman wght=603')
            ff = get_font_files(opts)
            t('medium', spec='variable_name=CascadiaCodeRoman wght=455')
            t('italic', spec='variable_name= wght=405')
            t('bold', spec='variable_name=CascadiaCodeRoman wght=603')
            t('bi', spec='variable_name= wght=603')

        # Test font features
        if has('liberation mono'):
            opts = Options()
            opts.font_family = parse_font_spec('family="liberation mono"')
            ff = get_font_files(opts)
            self.ae(face_from_descriptor(ff['medium']).applied_features(), {'dlig': '-dlig'})
            self.ae(face_from_descriptor(ff['bold']).applied_features(), {})
            opts.font_family = parse_font_spec('family="liberation mono" features="dlig test=3"')
            ff = get_font_files(opts)
            self.ae(face_from_descriptor(ff['medium']).applied_features(), {'dlig': 'dlig', 'test': 'test=3'})
            self.ae(face_from_descriptor(ff['bold']).applied_features(), {'dlig': 'dlig', 'test': 'test=3'})

def block_helpers(s, sprites, cell_width, cell_height):
    block_size = cell_width * cell_height * 4

    def full_block():
        return b'\xff' * block_size

    def empty_block():
        return b'\0' * block_size

    def half_block(first=b'\xff', second=b'\0', swap=False):
        frac = 0.5
        height = ceil(frac * cell_height)
        rest = cell_height - height
        if swap:
            height, rest = rest, height
            first, second = second, first
        return (first * (height * cell_width * 4)) + (second * rest * cell_width * 4)

    def quarter_block():
        frac = 0.5
        height = ceil(frac * cell_height)
        width = ceil(frac * cell_width)
        ans = array.array('I', b'\0' * block_size)
        for y in range(height):
            pos = cell_width * y
            for x in range(width):
                ans[pos + x] = 0xffffffff
        return ans.tobytes()

    def upper_half_block():
        return half_block()

    def lower_half_block():
        return half_block(swap=True)

    def block_as_str(a):
        pixels = array.array('I', a)
        def row(y):
            pos = y * cell_width
            return ' '.join(f'{int(pixels[pos + x] != 0)}' for x in range(cell_width))
        return '\n'.join(row(y) for y in range(cell_height))

    def assert_blocks(a, b, msg=''):
        if a != b:
            msg = msg or 'block not equal'
            if len(a) != len(b):
                assert_blocks.__msg = msg + f' block lengths not equal: {len(a)/4} != {len(b)/4}'
            else:
                assert_blocks.__msg = msg + '\n' + block_as_str(a) + '\n\n' + block_as_str(b)
            del a, b
            raise AssertionError(assert_blocks.__msg)

    def multiline_render(text, scale=1, width=1, **kw):
        s.reset()
        draw_multicell(s, text, scale=scale, width=width, **kw)
        ans = []
        for y in range(scale):
            line = s.line(y)
            test_render_line(line)
            for x in range(width * scale):
                ans.append(sprites[sprite_idx_to_pos(line.sprite_at(x), setup_for_testing.xnum, setup_for_testing.ynum)])
        return ans

    def block_test(*expected, **kw):
        mr = multiline_render(kw.pop('text', '█'), **kw)
        try:
            z = zip(expected, mr, strict=True)
        except TypeError:
            z = zip(expected, mr)
        for i, (expected, actual) in enumerate(z):
            assert_blocks(expected(), actual, f'Block {i} is not equal')


    return full_block, empty_block, upper_half_block, lower_half_block, quarter_block, block_as_str, block_test


class FontBaseTest(BaseTest):

    font_size = 16.0
    dpi = 72.
    font_name = 'FiraCode-Medium.otf'

    def path_for_font(self, name):
        if name not in self.font_path_cache:
            with open(os.path.join(self.tdir, name), 'wb') as f:
                self.font_path_cache[name] = f.name
                f.write(testing_font_data(name))
        return self.font_path_cache[name]

    def setUp(self):
        super().setUp()
        self.font_path_cache = {}
        self.tdir = tempfile.mkdtemp()
        self.addCleanup(self.rmtree_ignoring_errors, self.tdir)
        path = self.path_for_font(self.font_name) if self.font_name else ''
        tc = setup_for_testing(size=self.font_size, dpi=self.dpi, main_face_path=path)
        self.sprites, self.cell_width, self.cell_height = tc.__enter__()
        self.addCleanup(tc.__exit__)
        self.assertEqual([k[0] for k in self.sprites], list(range(11)))

    def tearDown(self):
        del self.sprites, self.cell_width, self.cell_height
        self.font_path_cache = {}
        super().tearDown()



class Rendering(FontBaseTest):

    def test_sprite_map(self):
        sprite_map_set_limits(10, 3)
        sprite_map_set_layout(5, 4)  # 4 because of underline_exclusion row
        self.ae(test_sprite_position_increment(), (0, 0, 0))
        self.ae(test_sprite_position_increment(), (1, 0, 0))
        self.ae(test_sprite_position_increment(), (0, 1, 0))
        self.ae(test_sprite_position_increment(), (1, 1, 0))
        self.ae(test_sprite_position_increment(), (0, 0, 1))
        self.ae(test_sprite_position_increment(), (1, 0, 1))
        self.ae(test_sprite_position_increment(), (0, 1, 1))
        self.ae(test_sprite_position_increment(), (1, 1, 1))
        self.ae(test_sprite_position_increment(), (0, 0, 2))
        self.ae(test_sprite_position_increment(), (1, 0, 2))

    def test_box_drawing(self):
        s = self.create_screen(cols=len(box_chars) + 1, lines=1, scrollback=0)
        prerendered = len(self.sprites)
        s.draw(''.join(box_chars))
        line = s.line(0)
        test_render_line(line)
        self.assertEqual(len(self.sprites) - prerendered, len(box_chars))

    def test_scaled_box_drawing(self):
        self.scaled_drawing_test()

    def test_scaled_font_drawing(self):
        set_allow_use_of_box_fonts(False)
        try:
            self.scaled_drawing_test()
        finally:
            set_allow_use_of_box_fonts(True)

    def scaled_drawing_test(self):
        s = self.create_screen(cols=8, lines=8, scrollback=0)
        full_block, empty_block, upper_half_block, lower_half_block, quarter_block, block_as_str, block_test = block_helpers(
                s, self.sprites, self.cell_width, self.cell_height)
        block_test(full_block)
        block_test(full_block, full_block, full_block, full_block, scale=2)
        block_test(full_block, empty_block, empty_block, empty_block, scale=2, subscale_n=1, subscale_d=2)
        block_test(empty_block, full_block, empty_block, empty_block, scale=2, subscale_n=1, subscale_d=2, horizontal_align=1)
        block_test(full_block, full_block, empty_block, empty_block, scale=2, subscale_n=1, subscale_d=2, text='██')
        block_test(empty_block, empty_block, full_block, empty_block, scale=2, subscale_n=1, subscale_d=2, vertical_align=1)
        block_test(quarter_block, scale=1, subscale_n=1, subscale_d=2)
        block_test(upper_half_block, scale=1, subscale_n=1, subscale_d=2, text='██')
        block_test(lower_half_block, scale=1, subscale_n=1, subscale_d=2, text='██', vertical_align=1)

    def test_font_rendering(self):
        render_string('ab\u0347\u0305你好|\U0001F601|\U0001F64f|\U0001F63a|')
        text = 'He\u0347\u0305llo\u0341, w\u0302or\u0306l\u0354d!'
        # macOS has no fonts capable of rendering combining chars
        if is_macos:
            text = text.encode('ascii', 'ignore').decode('ascii')
        cells = render_string(text)[-1]
        self.ae(len(cells), len(text.encode('ascii', 'ignore')))
        text = '你好,世界'
        sz = sum(map(lambda x: wcwidth(ord(x)), text))
        cells = render_string(text)[-1]
        self.ae(len(cells), sz)

    @unittest.skipIf(is_macos, 'COLRv1 is only supported on Linux')
    def test_rendering_colrv1(self):
        f = create_face(self.path_for_font('twemoji_smiley-cff2_colr_1.otf'))
        f.set_size(64, 96, 96)
        for char in '😁😇😈':
            _, w, h = f.render_codepoint(ord(char))
            self.assertGreater(w, 64)
            self.assertGreater(h, 64)

    def test_shaping(self):

        def ss(text, font=None):
            path = self.path_for_font(font) if font else None
            return shape_string(text, path=path)

        def groups(text, font=None):
            return [x[:2] for x in ss(text, font)]

        for font in ('FiraCode-Medium.otf', 'CascadiaCode-Regular.otf', 'iosevka-regular.ttf'):
            g = partial(groups, font=font)
            self.ae(g('abcd'), [(1, 1) for i in range(4)])
            self.ae(g('A===B!=C'), [(1, 1), (3, 3), (1, 1), (2, 2), (1, 1)])
            self.ae(g('A=>>B!=C'), [(1, 1), (3, 3), (1, 1), (2, 2), (1, 1)])
            if 'iosevka' in font:
                self.ae(g('--->'), [(4, 4)])
                self.ae(g('-' * 12 + '>'), [(13, 13)])
                self.ae(g('<~~~'), [(4, 4)])
                self.ae(g('a<~~~b'), [(1, 1), (4, 4), (1, 1)])
            else:
                self.ae(g('----'), [(4, 4)])
                self.ae(g('F--a--'), [(1, 1), (2, 2), (1, 1), (2, 2)])
                self.ae(g('===--<>=='), [(3, 3), (2, 2), (2, 2), (2, 2)])
                self.ae(g('==!=<>==<><><>'), [(4, 4), (2, 2), (2, 2), (2, 2), (2, 2), (2, 2)])
                self.ae(g('-' * 18), [(18, 18)])
            self.ae(g('a>\u2060<b'), [(1, 1), (1, 2), (1, 1), (1, 1)])
        colon_glyph = ss('9:30', font='FiraCode-Medium.otf')[1][2]
        self.assertNotEqual(colon_glyph, ss(':', font='FiraCode-Medium.otf')[0][2])
        self.ae(colon_glyph, 1031)
        self.ae(groups('9:30', font='FiraCode-Medium.otf'), [(1, 1), (1, 1), (1, 1), (1, 1)])

        self.ae(groups('|\U0001F601|\U0001F64f|\U0001F63a|'), [(1, 1), (2, 1), (1, 1), (2, 1), (1, 1), (2, 1), (1, 1)])
        self.ae(groups('He\u0347\u0305llo\u0337,', font='LiberationMono-Regular.ttf'),
                [(1, 1), (1, 3), (1, 1), (1, 1), (1, 2), (1, 1)])

        self.ae(groups('i\u0332\u0308', font='LiberationMono-Regular.ttf'), [(1, 2)])
        self.ae(groups('u\u0332 u\u0332\u0301', font='LiberationMono-Regular.ttf'), [(1, 2), (1, 1), (1, 2)])

    def test_emoji_presentation(self):
        s = self.create_screen()
        s.draw('\u2716\u2716\ufe0f')
        self.ae((s.cursor.x, s.cursor.y), (3, 0))
        s.draw('\u2716\u2716')
        self.ae((s.cursor.x, s.cursor.y), (5, 0))
        s.draw('\ufe0f')
        self.ae((s.cursor.x, s.cursor.y), (2, 1))
        self.ae(str(s.line(0)), '\u2716\u2716\ufe0f\u2716')
        self.ae(str(s.line(1)), '\u2716\ufe0f')
        s.draw('\u2716' * 3)
        self.ae((s.cursor.x, s.cursor.y), (5, 1))
        self.ae(str(s.line(1)), '\u2716\ufe0f\u2716\u2716\u2716')
        self.ae((s.cursor.x, s.cursor.y), (5, 1))
        s.reset_mode(DECAWM)
        s.draw('\ufe0f')
        s.set_mode(DECAWM)
        self.ae((s.cursor.x, s.cursor.y), (5, 1))
        self.ae(str(s.line(1)), '\u2716\ufe0f\u2716\u2716\ufe0f')
        s.cursor.y = s.lines - 1
        s.draw('\u2716' * s.columns)
        self.ae((s.cursor.x, s.cursor.y), (5, 4))
        s.draw('\ufe0f')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))
        self.ae(str(s.line(s.cursor.y)), '\u2716\ufe0f')

    @unittest.skipUnless(is_macos, 'Only macOS has a Last Resort font')
    def test_fallback_font_not_last_resort(self):
        # Ensure that the LastResort font is not reported as a fallback font on
        # macOS. See https://github.com/kovidgoyal/kitty/issues/799
        with self.assertRaises(ValueError, msg='No fallback font found'):
            get_fallback_font('\U0010FFFF', False, False)

    def test_coalesce_symbol_maps(self):
        q = {(2, 3): 'a', (4, 6): 'b', (5, 5): 'b', (7, 7): 'b', (9, 9): 'b', (1, 1): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 3): 'a', (4, 7): 'b', (9, 9): 'b'})
        q = {(1, 4): 'a', (2, 3): 'b'}
        self.ae(coalesce_symbol_maps(q), {(1, 1): 'a', (2, 3): 'b', (4, 4): 'a'})
        q = {(2, 3): 'b', (1, 4): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 4): 'a'})
        q = {(1, 4): 'a', (2, 5): 'b'}
        self.ae(coalesce_symbol_maps(q), {(1, 1): 'a', (2, 5): 'b'})
        q = {(2, 5): 'b', (1, 4): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 4): 'a', (5, 5): 'b'})
        q = {(1, 4): 'a', (2, 5): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 5): 'a'})
        q = {(1, 4): 'a', (4, 5): 'b'}
        self.ae(coalesce_symbol_maps(q), {(1, 3): 'a', (4, 5): 'b'})
        q = {(4, 5): 'b', (1, 4): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 4): 'a', (5, 5): 'b'})
        q = {(0, 30): 'a', (10, 10): 'b', (11, 11): 'b', (2, 2): 'c', (1, 1): 'c'}
        self.ae(coalesce_symbol_maps(q), {
            (0, 0): 'a', (1, 2): 'c', (3, 9): 'a', (10, 11): 'b', (12, 30): 'a'})

def test_chars(chars: str = '╌', sz: int = 128) -> None:
    # kitty +runpy "from kitty.fonts.box_drawing import test_chars; test_chars('XXX')"
    from kitty.fast_data_types import concat_cells, render_box_char, set_send_sprite_to_gpu
    from kitty.fonts.render import display_bitmap, setup_for_testing
    if not chars:
        import sys
        chars = sys.argv[-1]

    def as_ord(x: str) -> int:
        if x.lower().startswith('u+'):
            return int(x[2:], 16)
        return ord(x)

    if '...' in chars:
        start, end = chars.partition('...')[::2]
        chars = ''.join(map(chr, range(as_ord(start), as_ord(end)+1)))

    with setup_for_testing('monospace', sz) as (_, width, height):
        try:
            for ch in chars:
                nb = render_box_char(as_ord(ch), width, height)
                rgb_data = concat_cells(width, height, False, (nb,))
                display_bitmap(rgb_data, width, height)
                print()
        finally:
            set_send_sprite_to_gpu(None)


def test_drawing(sz: int = 48, family: str = 'monospace', start: int = 0x2500, num_rows: int = 10, num_cols: int = 16) -> None:
    from kitty.fast_data_types import concat_cells, render_box_char, set_send_sprite_to_gpu

    from .render import display_bitmap, setup_for_testing

    with setup_for_testing(family, sz) as (_, width, height):
        space = bytearray(width * height)

        def join_cells(cells: Iterable[bytes]) -> bytes:
            cells = tuple(bytes(x) for x in cells)
            return concat_cells(width, height, False, cells)

        def render_chr(ch: str) -> bytearray:
            if ch in box_chars:
                return bytearray(render_box_char(ord(ch), width, height))
            return space

        pos = start
        rows = []
        space_row = join_cells(repeat(space, 32))

        try:
            for r in range(num_rows):
                row = []
                for i in range(num_cols):
                    row.append(render_chr(chr(pos)))
                    row.append(space)
                    pos += 1
                rows.append(join_cells(row))
                rows.append(space_row)
            rgb_data = b''.join(rows)
            width *= 32
            height *= len(rows)
            assert len(rgb_data) == width * height * 4, f'{len(rgb_data)} != {width * height * 4}'
            display_bitmap(rgb_data, width, height)
        finally:
            set_send_sprite_to_gpu(None)

box_chars = {  # {{{
'─',
 '━',
 '│',
 '┃',
 '┄',
 '┅',
 '┆',
 '┇',
 '┈',
 '┉',
 '┊',
 '┋',
 '┌',
 '┍',
 '┎',
 '┏',
 '┐',
 '┑',
 '┒',
 '┓',
 '└',
 '┕',
 '┖',
 '┗',
 '┘',
 '┙',
 '┚',
 '┛',
 '├',
 '┝',
 '┞',
 '┟',
 '┠',
 '┡',
 '┢',
 '┣',
 '┤',
 '┥',
 '┦',
 '┧',
 '┨',
 '┩',
 '┪',
 '┫',
 '┬',
 '┭',
 '┮',
 '┯',
 '┰',
 '┱',
 '┲',
 '┳',
 '┴',
 '┵',
 '┶',
 '┷',
 '┸',
 '┹',
 '┺',
 '┻',
 '┼',
 '┽',
 '┾',
 '┿',
 '╀',
 '╁',
 '╂',
 '╃',
 '╄',
 '╅',
 '╆',
 '╇',
 '╈',
 '╉',
 '╊',
 '╋',
 '╌',
 '╍',
 '╎',
 '╏',
 '═',
 '║',
 '╒',
 '╓',
 '╔',
 '╕',
 '╖',
 '╗',
 '╘',
 '╙',
 '╚',
 '╛',
 '╜',
 '╝',
 '╞',
 '╟',
 '╠',
 '╡',
 '╢',
 '╣',
 '╤',
 '╥',
 '╦',
 '╧',
 '╨',
 '╩',
 '╪',
 '╫',
 '╬',
 '╭',
 '╮',
 '╯',
 '╰',
 '╱',
 '╲',
 '╳',
 '╴',
 '╵',
 '╶',
 '╷',
 '╸',
 '╹',
 '╺',
 '╻',
 '╼',
 '╽',
 '╾',
 '╿',
 '▀',
 '▁',
 '▂',
 '▃',
 '▄',
 '▅',
 '▆',
 '▇',
 '█',
 '▉',
 '▊',
 '▋',
 '▌',
 '▍',
 '▎',
 '▏',
 '▐',
 '░',
 '▒',
 '▓',
 '▔',
 '▕',
 '▖',
 '▗',
 '▘',
 '▙',
 '▚',
 '▛',
 '▜',
 '▝',
 '▞',
 '▟',
 '◉',
 '○',
 '●',
 '◖',
 '◗',
 '◜',
 '◝',
 '◞',
 '◟',
 '◠',
 '◡',
 '◢',
 '◣',
 '◤',
 '◥',
 '⠀',
 '⠁',
 '⠂',
 '⠃',
 '⠄',
 '⠅',
 '⠆',
 '⠇',
 '⠈',
 '⠉',
 '⠊',
 '⠋',
 '⠌',
 '⠍',
 '⠎',
 '⠏',
 '⠐',
 '⠑',
 '⠒',
 '⠓',
 '⠔',
 '⠕',
 '⠖',
 '⠗',
 '⠘',
 '⠙',
 '⠚',
 '⠛',
 '⠜',
 '⠝',
 '⠞',
 '⠟',
 '⠠',
 '⠡',
 '⠢',
 '⠣',
 '⠤',
 '⠥',
 '⠦',
 '⠧',
 '⠨',
 '⠩',
 '⠪',
 '⠫',
 '⠬',
 '⠭',
 '⠮',
 '⠯',
 '⠰',
 '⠱',
 '⠲',
 '⠳',
 '⠴',
 '⠵',
 '⠶',
 '⠷',
 '⠸',
 '⠹',
 '⠺',
 '⠻',
 '⠼',
 '⠽',
 '⠾',
 '⠿',
 '⡀',
 '⡁',
 '⡂',
 '⡃',
 '⡄',
 '⡅',
 '⡆',
 '⡇',
 '⡈',
 '⡉',
 '⡊',
 '⡋',
 '⡌',
 '⡍',
 '⡎',
 '⡏',
 '⡐',
 '⡑',
 '⡒',
 '⡓',
 '⡔',
 '⡕',
 '⡖',
 '⡗',
 '⡘',
 '⡙',
 '⡚',
 '⡛',
 '⡜',
 '⡝',
 '⡞',
 '⡟',
 '⡠',
 '⡡',
 '⡢',
 '⡣',
 '⡤',
 '⡥',
 '⡦',
 '⡧',
 '⡨',
 '⡩',
 '⡪',
 '⡫',
 '⡬',
 '⡭',
 '⡮',
 '⡯',
 '⡰',
 '⡱',
 '⡲',
 '⡳',
 '⡴',
 '⡵',
 '⡶',
 '⡷',
 '⡸',
 '⡹',
 '⡺',
 '⡻',
 '⡼',
 '⡽',
 '⡾',
 '⡿',
 '⢀',
 '⢁',
 '⢂',
 '⢃',
 '⢄',
 '⢅',
 '⢆',
 '⢇',
 '⢈',
 '⢉',
 '⢊',
 '⢋',
 '⢌',
 '⢍',
 '⢎',
 '⢏',
 '⢐',
 '⢑',
 '⢒',
 '⢓',
 '⢔',
 '⢕',
 '⢖',
 '⢗',
 '⢘',
 '⢙',
 '⢚',
 '⢛',
 '⢜',
 '⢝',
 '⢞',
 '⢟',
 '⢠',
 '⢡',
 '⢢',
 '⢣',
 '⢤',
 '⢥',
 '⢦',
 '⢧',
 '⢨',
 '⢩',
 '⢪',
 '⢫',
 '⢬',
 '⢭',
 '⢮',
 '⢯',
 '⢰',
 '⢱',
 '⢲',
 '⢳',
 '⢴',
 '⢵',
 '⢶',
 '⢷',
 '⢸',
 '⢹',
 '⢺',
 '⢻',
 '⢼',
 '⢽',
 '⢾',
 '⢿',
 '⣀',
 '⣁',
 '⣂',
 '⣃',
 '⣄',
 '⣅',
 '⣆',
 '⣇',
 '⣈',
 '⣉',
 '⣊',
 '⣋',
 '⣌',
 '⣍',
 '⣎',
 '⣏',
 '⣐',
 '⣑',
 '⣒',
 '⣓',
 '⣔',
 '⣕',
 '⣖',
 '⣗',
 '⣘',
 '⣙',
 '⣚',
 '⣛',
 '⣜',
 '⣝',
 '⣞',
 '⣟',
 '⣠',
 '⣡',
 '⣢',
 '⣣',
 '⣤',
 '⣥',
 '⣦',
 '⣧',
 '⣨',
 '⣩',
 '⣪',
 '⣫',
 '⣬',
 '⣭',
 '⣮',
 '⣯',
 '⣰',
 '⣱',
 '⣲',
 '⣳',
 '⣴',
 '⣵',
 '⣶',
 '⣷',
 '⣸',
 '⣹',
 '⣺',
 '⣻',
 '⣼',
 '⣽',
 '⣾',
 '⣿',
 '\ue0b0',
 '\ue0b1',
 '\ue0b2',
 '\ue0b3',
 '\ue0b4',
 '\ue0b5',
 '\ue0b6',
 '\ue0b7',
 '\ue0b8',
 '\ue0b9',
 '\ue0ba',
 '\ue0bb',
 '\ue0bc',
 '\ue0bd',
 '\ue0be',
 '\ue0bf',
 '\ue0d6',
 '\ue0d7',
 '\uee00',
 '\uee01',
 '\uee02',
 '\uee03',
 '\uee04',
 '\uee05',
 '\uee06',
 '\uee07',
 '\uee08',
 '\uee09',
 '\uee0a',
 '\uee0b',
 '\uf5d0',
 '\uf5d1',
 '\uf5d2',
 '\uf5d3',
 '\uf5d4',
 '\uf5d5',
 '\uf5d6',
 '\uf5d7',
 '\uf5d8',
 '\uf5d9',
 '\uf5da',
 '\uf5db',
 '\uf5dc',
 '\uf5dd',
 '\uf5de',
 '\uf5df',
 '\uf5e0',
 '\uf5e1',
 '\uf5e2',
 '\uf5e3',
 '\uf5e4',
 '\uf5e5',
 '\uf5e6',
 '\uf5e7',
 '\uf5e8',
 '\uf5e9',
 '\uf5ea',
 '\uf5eb',
 '\uf5ec',
 '\uf5ed',
 '\uf5ee',
 '\uf5ef',
 '\uf5f0',
 '\uf5f1',
 '\uf5f2',
 '\uf5f3',
 '\uf5f4',
 '\uf5f5',
 '\uf5f6',
 '\uf5f7',
 '\uf5f8',
 '\uf5f9',
 '\uf5fa',
 '\uf5fb',
 '\uf5fc',
 '\uf5fd',
 '\uf5fe',
 '\uf5ff',
 '\uf600',
 '\uf601',
 '\uf602',
 '\uf603',
 '\uf604',
 '\uf605',
 '\uf606',
 '\uf607',
 '\uf608',
 '\uf609',
 '\uf60a',
 '\uf60b',
 '\uf60c',
 '\uf60d',
 '🬀',
 '🬁',
 '🬂',
 '🬃',
 '🬄',
 '🬅',
 '🬆',
 '🬇',
 '🬈',
 '🬉',
 '🬊',
 '🬋',
 '🬌',
 '🬍',
 '🬎',
 '🬏',
 '🬐',
 '🬑',
 '🬒',
 '🬓',
 '🬔',
 '🬕',
 '🬖',
 '🬗',
 '🬘',
 '🬙',
 '🬚',
 '🬛',
 '🬜',
 '🬝',
 '🬞',
 '🬟',
 '🬠',
 '🬡',
 '🬢',
 '🬣',
 '🬤',
 '🬥',
 '🬦',
 '🬧',
 '🬨',
 '🬩',
 '🬪',
 '🬫',
 '🬬',
 '🬭',
 '🬮',
 '🬯',
 '🬰',
 '🬱',
 '🬲',
 '🬳',
 '🬴',
 '🬵',
 '🬶',
 '🬷',
 '🬸',
 '🬹',
 '🬺',
 '🬻',
 '🬼',
 '🬽',
 '🬾',
 '🬿',
 '🭀',
 '🭁',
 '🭂',
 '🭃',
 '🭄',
 '🭅',
 '🭆',
 '🭇',
 '🭈',
 '🭉',
 '🭊',
 '🭋',
 '🭌',
 '🭍',
 '🭎',
 '🭏',
 '🭐',
 '🭑',
 '🭒',
 '🭓',
 '🭔',
 '🭕',
 '🭖',
 '🭗',
 '🭘',
 '🭙',
 '🭚',
 '🭛',
 '🭜',
 '🭝',
 '🭞',
 '🭟',
 '🭠',
 '🭡',
 '🭢',
 '🭣',
 '🭤',
 '🭥',
 '🭦',
 '🭧',
 '🭨',
 '🭩',
 '🭪',
 '🭫',
 '🭬',
 '🭭',
 '🭮',
 '🭯',
 '🭰',
 '🭱',
 '🭲',
 '🭳',
 '🭴',
 '🭵',
 '🭶',
 '🭷',
 '🭸',
 '🭹',
 '🭺',
 '🭻',
 '🭼',
 '🭽',
 '🭾',
 '🭿',
 '🮀',
 '🮁',
 '🮂',
 '🮃',
 '🮄',
 '🮅',
 '🮆',
 '🮇',
 '🮈',
 '🮉',
 '🮊',
 '🮋',
 '🮌',
 '🮍',
 '🮎',
 '🮏',
 '🮐',
 '🮑',
 '🮒',
 '\U0001fb93',
 '🮔',
 '🮕',
 '🮖',
 '🮗',
 '🮘',
 '🮙',
 '🮚',
 '🮛',
 '🮜',
 '🮝',
 '🮞',
 '🮟',
 '🮠',
 '🮡',
 '🮢',
 '🮣',
 '🮤',
 '🮥',
 '🮦',
 '🮧',
 '🮨',
 '🮩',
 '🮪',
 '🮫',
 '🮬',
 '🮭',
 '🮮',
 '\U0001fbe6', '\U0001fbe7',
 }  # }}}
for ch in range(0x1cd00, 0x1cde5+1):  # octants
    box_chars.add(chr(ch))
