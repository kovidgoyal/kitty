#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import sys

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .key_constants import patch_file

# References for these names:
# CSS:choices_for_{option.name} https://developer.mozilla.org/en-US/docs/Web/CSS/cursor
# XCursor: https://tronche.com/gui/x/xlib/appendix/b/ + Absolute chaos
# Wayland: https://wayland.app/protocols/cursor-shape-v1
# Cocoa: https://developer.apple.com/documentation/appkit/nscursor + secret apple selectors + SDL_cocoamouse.m

# kitty_names CSS_name       XCursor_names                             Wayland_name    Cocoa_name
cursors = '''\
arrow         default        default,!left_ptr                         default         arrowCursor
beam,text     text           text,!xterm,ibeam                         text            IBeamCursor
pointer,hand  pointer        pointing_hand,pointer,!hand2,hand         pointer         pointingHandCursor
help          help           help,!question_arrow,whats_this           help            help:arrowCursor
wait          wait           wait,!clock,watch                         wait            busybutclickable:arrowCursor
progress      progress       progress,half-busy,left_ptr_watch         progress        busybutclickable:arrowCursor
crosshair     crosshair      crosshair,!tcross                         crosshair       crosshairCursor
cell          cell           cell,!plus,!cross                         cell            cell:crosshairCursor
vertical-text vertical-text  vertical-text                             vertical-text   IBeamCursorForVerticalLayout
move          move           move,!fleur,pointer-move                  move            move:openHandCursor

e-resize      e-resize       e-resize,!right_side                      e_resize        resizeRightCursor
ne-resize     ne-resize      ne-resize,!top_right_corner               ne_resize       resizenortheast:_windowResizeNorthEastSouthWestCursor
nw-resize     nw-resize      nw-resize,!top_left_corner                nw_resize       resizenorthwest:_windowResizeNorthWestSouthEastCursor
n-resize      n-resize       n-resize,!top_side                        n_resize        resizeUpCursor
se-resize     se-resize      se-resize,!bottom_right_corner            se_resize       resizesoutheast:_windowResizeNorthWestSouthEastCursor
sw-resize     sw-resize      sw-resize,!bottom_left_corner             sw_resize       resizesouthwest:_windowResizeNorthEastSouthWestCursor
s-resize      s-resize       s-resize,!bottom_side                     s_resize        resizeDownCursor
w-resize      w-resize       w-resize,!left_side                       w_resize        resizeLeftCursor

ew-resize     ew-resize      ew-resize,!sb_h_double_arrow,split_h      ew_resize       resizeLeftRightCursor
ns-resize     ns-resize      ns-resize,!sb_v_double_arrow,split_v      ns_resize       resizeUpDownCursor
nesw-resize   nesw-resize    nesw-resize,size_bdiag,size-bdiag         nesw_resize     _windowResizeNorthEastSouthWestCursor
nwse-resize   nwse-resize    nwse-resize,size_fdiag,size-fdiag         nwse_resize     _windowResizeNorthWestSouthEastCursor

zoom-in       zoom-in        zoom-in,zoom_in                           zoom_in         zoomin:arrowCursor
zoom-out      zoom-out       zoom-out,zoom_out                         zoom_out        zoomout:arrowCursor

alias         alias          dnd-link                                  alias           dragLinkCursor
copy          copy           dnd-copy                                  copy            dragCopyCursor
not-allowed   not-allowed    not-allowed,forbidden,crossed_circle      not_allowed     operationNotAllowedCursor
no-drop       no-drop        no-drop,dnd-no-drop                       no_drop         operationNotAllowedCursor
grab          grab           grab,openhand,!hand1                      grab            openHandCursor
grabbing      grabbing       grabbing,closedhand,dnd-none              grabbing        closedHandCursor
'''


def main(args: list[str]=sys.argv) -> None:
    glfw_enum = []
    css_names = []
    glfw_xc_map = {}
    glfw_xfont_map = []
    kitty_to_enum_map = {}
    enum_to_glfw_map = {}
    enum_to_css_map = {}
    glfw_cocoa_map = {}
    glfw_css_map = {}
    css_to_enum = {}
    xc_to_enum = {}
    glfw_wayland = {}
    for line in cursors.splitlines():
        line = line.strip()
        if line:
            names_, css, xc_, wayland, cocoa = line.split()
            names, xc = names_.split(','), xc_.split(',')
            base = css.replace('-', '_').upper()
            glfw_name = 'GLFW_' + base + '_CURSOR'
            enum_name = base + '_POINTER'
            enum_to_glfw_map[enum_name] = glfw_name
            enum_to_css_map[enum_name] = css
            glfw_css_map[glfw_name] = css
            css_to_enum[css] = enum_name
            css_names.append(css)
            glfw_wayland[glfw_name] = 'WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_' + wayland.replace('-', '_').upper()
            for n in names:
                kitty_to_enum_map[n] = enum_name
            glfw_enum.append(glfw_name)
            glfw_xc_map[glfw_name] = ', '.join(f'''"{x.replace('!', '')}"''' for x in xc)
            for x in xc:
                if x.startswith('!'):
                    glfw_xfont_map.append(f"case {glfw_name}: return set_cursor_from_font(cursor, {'XC_' + x[1:]});")
                    break
            else:
                items = tuple('"' + x.replace('!', '') + '"' for x in xc)
                glfw_xfont_map.append(f'case {glfw_name}: return try_cursor_names(cursor, {len(items)}, {", ".join(items)});')
            for x in xc:
                x = x.lstrip('!')
                xc_to_enum[x] = enum_name
            parts = cocoa.split(':', 1)
            if len(parts) == 1:
                if parts[0].startswith('_'):
                    glfw_cocoa_map[glfw_name] = f'U({glfw_name}, {parts[0]});'
                else:
                    glfw_cocoa_map[glfw_name] = f'C({glfw_name}, {parts[0]});'
            else:
                glfw_cocoa_map[glfw_name] = f'S({glfw_name}, {parts[0]}, {parts[1]});'

    for x, v in xc_to_enum.items():
        if x not in css_to_enum:
            css_to_enum[x] = v

    glfw_enum.append('GLFW_INVALID_CURSOR')
    patch_file('glfw/glfw3.h', 'mouse cursor shapes', '\n'.join(f'    {x},' for x in glfw_enum))
    patch_file('glfw/wl_window.c', 'glfw to wayland mapping', '\n'.join(f'        C({g}, {x});' for g, x in glfw_wayland.items()))
    patch_file('glfw/wl_window.c', 'glfw to xc mapping', '\n'.join(f'        C({g}, {x});' for g, x in glfw_xc_map.items()))
    patch_file('glfw/x11_window.c', 'glfw to xc mapping', '\n'.join(f'        {x}' for x in glfw_xfont_map))
    patch_file('kitty/data-types.h', 'mouse shapes', '\n'.join(f'    {x},' for x in enum_to_glfw_map))
    patch_file(
        'kitty/options/utils.py', 'pointer shape names', '\n'.join(f'    {x!r},' for x in kitty_to_enum_map),
        start_marker='# ', end_marker='',
    )
    patch_file('kitty/options/to-c.h', 'pointer shapes', '\n'.join(
        f'    else if (strcmp(name, "{k}") == 0) return {v};' for k, v in kitty_to_enum_map.items()))
    patch_file('kitty/glfw.c', 'enum to glfw', '\n'.join(
        f'        case {k}: set_glfw_mouse_cursor(w, {v}); break;' for k, v in enum_to_glfw_map.items()))
    patch_file('kitty/glfw.c', 'name to glfw', '\n'.join(
        f'    if (strcmp(name, "{k}") == 0) return {enum_to_glfw_map[v]};' for k, v in kitty_to_enum_map.items()))
    patch_file('kitty/glfw.c', 'glfw to css', '\n'.join(
        f'        case {g}: return "{c}";' for g, c in glfw_css_map.items()
    ))
    patch_file('kitty/screen.c', 'enum to css', '\n'.join(
        f'        case {e}: ans = "{c}"; break;' for e, c in enum_to_css_map.items()))
    patch_file('kitty/screen.c', 'css to enum', '\n'.join(
        f'        else if (strcmp("{c}", css_name) == 0) s = {e};' for c, e in css_to_enum.items()))
    patch_file('glfw/cocoa_window.m', 'glfw to cocoa', '\n'.join(f'        {x}' for x in glfw_cocoa_map.values()))
    patch_file('docs/pointer-shapes.rst', 'list of shape css names', '\n'.join(
        f'#. {x}' if x else '' for x in [''] + sorted(css_names) + ['']), start_marker='.. ', end_marker='')
    patch_file('tools/tui/loop/mouse.go', 'pointer shape enum', '\n'.join(
        f'\t{x} PointerShape = {i}' for i, x in enumerate(enum_to_glfw_map)), start_marker='// ', end_marker='')
    patch_file('tools/tui/loop/mouse.go', 'pointer shape tostring', '\n'.join(
        f'''\tcase {x}: return "{x.lower().rpartition('_')[0].replace('_', '-')}"''' for x in enum_to_glfw_map), start_marker='// ', end_marker='')
    patch_file('tools/cmd/mouse_demo/main.go', 'all pointer shapes', '\n'.join(
        f'\tloop.{x},' for x in enum_to_glfw_map), start_marker='// ', end_marker='')

    subprocess.check_call(['glfw/glfw.py'])


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'cursors'])
