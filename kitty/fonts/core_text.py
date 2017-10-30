#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
from collections import namedtuple

from kitty.fast_data_types import CTFace as Face, coretext_all_fonts
from kitty.utils import safe_print

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


def create_font_map(all_fonts):
    ans = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
    for x in all_fonts:
        f = (x['family'] or '').lower()
        s = (x['style'] or '').lower()
        ps = (x['postscript_name'] or '').lower()
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(f + ' ' + s, []).append(x)
    return ans


def all_fonts_map():
    ans = getattr(all_fonts_map, 'ans', None)
    if ans is None:
        ans = all_fonts_map.ans = create_font_map(coretext_all_fonts())
    return ans


def find_best_match(family, bold, italic):
    q = re.sub(r'\s+', ' ', family.lower())
    font_map = all_fonts_map()

    def score(candidate):
        style_match = 1 if candidate['bold'] == bold and candidate[
            'italic'
        ] == italic else 0
        monospace_match = 1 if candidate['monospace'] else 0
        return style_match, monospace_match

    # First look for an exact match
    for selector in ('ps_map', 'full_map'):
        candidates = font_map[selector].get(q)
        if candidates:
            candidates.sort(key=score)
            return candidates[-1]

    # Let CoreText choose the font if the family exists, otherwise
    # fallback to Menlo
    if q not in font_map['family_map']:
        safe_print(
            'The font {} was not found, falling back to Menlo'.format(family),
            file=sys.stderr
        )
        family = 'Menlo'
    return {
        'monospace': True,
        'bold': bold,
        'italic': italic,
        'family': family
    }


def resolve_family(f, main_family, bold, italic):
    if (bold or italic) and f == 'auto':
        f = main_family
    if f.lower() == 'monospace':
        f = 'Menlo'
    return f


FaceDescription = namedtuple(
    'FaceDescription', 'resolved_family family bold italic'
)


def face_description(family, main_family, bold=False, italic=False):
    return FaceDescription(
        resolve_family(family, main_family, bold, italic), family, bold, italic
    )


def get_face(family, font_size, dpi, bold=False, italic=False):
    descriptor = find_best_match(family, bold, italic)
    return Face(descriptor, font_size, dpi)


def get_font_files(opts):
    ans = {}
    for (bold, italic), attr in attr_map.items():
        face = face_description(
            getattr(opts, attr), opts.font_family, bold, italic
        )
        key = {(False, False): 'medium',
               (True, False): 'bold',
               (False, True): 'italic',
               (True, True): 'bi'}[(bold, italic)]
        ans[key] = face
        if key == 'medium':
            save_medium_face.family = face.resolved_family
    return ans


def face_from_font(font, pt_sz, xdpi, ydpi):
    return get_face(font.resolved_family, pt_sz, (xdpi + ydpi) / 2, bold=font.bold, italic=font.italic)


def save_medium_face(face, family):
    save_medium_face.face = face


def font_for_text(text, current_font_family, pt_sz, xdpi, ydpi, bold=False, italic=False):
    save_medium_face.face.face_for_text(text, bold, italic)


def font_for_family(family):
    return face_description(family, save_medium_face.family)


def test_font_matching(
    name='Menlo', bold=False, italic=False, dpi=72.0, font_size=11.0
):
    all_fonts = create_font_map(coretext_all_fonts())
    face = get_face(all_fonts, name, 'Menlo', font_size, dpi, bold, italic)
    return face


def test_family_matching(name='Menlo', dpi=72.0, font_size=11.0):
    all_fonts = create_font_map(coretext_all_fonts())
    for bold in (False, True):
        for italic in (False, True):
            face = get_face(
                all_fonts, name, 'Menlo', font_size, dpi, bold, italic
            )
            print(bold, italic, face)
