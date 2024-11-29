#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile
import unittest
from functools import partial
from math import ceil

from kitty.constants import is_macos, read_kitty_resource
from kitty.fast_data_types import (
    DECAWM,
    ParsedFontFeature,
    get_fallback_font,
    sprite_map_set_layout,
    sprite_map_set_limits,
    test_render_line,
    test_sprite_position_for,
    wcwidth,
)
from kitty.fonts import family_name_to_key
from kitty.fonts.box_drawing import box_chars
from kitty.fonts.common import FontSpec, all_fonts_map, face_from_descriptor, get_font_files, get_named_style, spec_for_face
from kitty.fonts.render import coalesce_symbol_maps, render_string, setup_for_testing, shape_string
from kitty.options.types import Options

from . import BaseTest, draw_multicell


def parse_font_spec(spec):
    return FontSpec.from_setting(spec)


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


class Rendering(BaseTest):

    def setUp(self):
        super().setUp()
        self.test_ctx = setup_for_testing()
        self.test_ctx.__enter__()
        self.sprites, self.cell_width, self.cell_height = self.test_ctx.__enter__()
        try:
            self.assertEqual([k[0] for k in self.sprites], [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        except Exception:
            self.test_ctx.__exit__()
            del self.test_ctx
            raise
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        self.test_ctx.__exit__()
        del self.sprites, self.cell_width, self.cell_height, self.test_ctx
        self.rmtree_ignoring_errors(self.tdir)
        super().tearDown()

    def test_sprite_map(self):
        sprite_map_set_limits(10, 2)
        sprite_map_set_layout(5, 5)
        self.ae(test_sprite_position_for(0), (0, 0, 0))
        self.ae(test_sprite_position_for(1), (1, 0, 0))
        self.ae(test_sprite_position_for(2), (0, 1, 0))
        self.ae(test_sprite_position_for(3), (1, 1, 0))
        self.ae(test_sprite_position_for(4), (0, 0, 1))
        self.ae(test_sprite_position_for(5), (1, 0, 1))
        self.ae(test_sprite_position_for(6), (0, 1, 1))
        self.ae(test_sprite_position_for(7), (1, 1, 1))
        self.ae(test_sprite_position_for(0, 1), (0, 0, 2))
        self.ae(test_sprite_position_for(0, 2), (1, 0, 2))

    def test_box_drawing(self):
        prerendered = len(self.sprites)
        s = self.create_screen(cols=len(box_chars) + 1, lines=1, scrollback=0)
        s.draw(''.join(box_chars))
        line = s.line(0)
        test_render_line(line)
        self.assertEqual(len(self.sprites) - prerendered, len(box_chars))

    def test_scaled_box_drawing(self):
        block_size = self.cell_width * self.cell_height * 4

        def full_block(subscale):
            return b'\xff' * block_size

        def empty_block(subscale):
            return b'\0' * block_size

        def half_block(subscale, first=b'\xff', second=b'\0'):
            frac = 1 / (subscale + 1)
            height = ceil(frac * self.cell_height)
            rest = self.cell_height - height
            return (first * (rest * self.cell_width * 4)) + (second * height * self.cell_width * 4)

        def upper_half_block(subscale):
            return half_block(subscale)

        def lower_half_block(subscale):
            return half_block(subscale, b'\0', b'\xff')

        s = self.create_screen(cols=8, lines=8, scrollback=0)

        def block_test(a=empty_block, b=empty_block, c=empty_block, d=empty_block, scale=2, subscale=1, vertical_align=0):
            s.reset()
            before = len(self.sprites)
            draw_multicell(s, '█', scale=scale, subscale=subscale, vertical_align=vertical_align)
            test_render_line(s.line(0))
            self.ae(len(self.sprites), before + 2)
            test_render_line(s.line(1))
            self.ae(len(self.sprites), before + 4)
            blocks = tuple(self.sprites)[before:]
            for i, (expected, actual) in enumerate(zip((a(subscale), b(subscale), c(subscale), d(subscale)), blocks)):
                self.ae(self.sprites[actual], expected, f'The {i} block differs')

        block_test(full_block, full_block, full_block, full_block, subscale=0)
        block_test(a=full_block)
        block_test(c=full_block, vertical_align=1)
        block_test(a=lower_half_block, c=upper_half_block, vertical_align=2)

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

    def test_shaping(self):

        font_path_cache = {}

        def path_for_font(name):
            if name not in font_path_cache:
                with open(os.path.join(self.tdir, name), 'wb') as f:
                    font_path_cache[name] = f.name
                    data = read_kitty_resource(name, __name__.rpartition('.')[0])
                    f.write(data)
            return font_path_cache[name]

        def ss(text, font=None):
            path = path_for_font(font) if font else None
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
