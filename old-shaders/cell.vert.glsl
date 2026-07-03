#version 140



#line 0 7893001
#extension GL_ARB_explicit_attrib_location : require



#line 0 7893002
#define FG_OVERRIDE_ALGO 0
#define TEXT_NEW_GAMMA 1

#define DECORATION_SHIFT 0
#define REVERSE_SHIFT 5
#define STRIKE_SHIFT 6
#define DIM_SHIFT 7
#define BLINK_SHIFT 8
#define MARK_SHIFT 9
#define MARK_MASK 3
#define USE_SELECTION_FG
#define NUM_COLORS 256
#define COLOR_NOT_SET 0
#define COLOR_IS_SPECIAL 1
#define COLOR_IS_RGB 3
#define COLOR_IS_INDEX 2

#if 1 == 1
#define ONLY_BACKGROUND
#endif

#if 0 == 1
#define ONLY_FOREGROUND
#endif

#if FG_OVERRIDE_ALGO == 0
#define DO_FG_OVERRIDE 0
#else
#define DO_FG_OVERRIDE 1
#endif

// Linear space luminance values
const vec3 Y = vec3(0.2126, 0.7152, 0.0722);



#line 1 7893001




#line 0 7893003
// Return 0 if x < 1 otherwise 1
#define zero_or_one(x) step(1.f, x)
// condition must be zero or one. When 1 thenval is returned otherwise elseval
#define if_one_then(condition, thenval, elseval) mix(elseval, thenval, condition)
// a < b ? thenval : elseval
#define if_less_than(a, b, thenval, elseval) mix(thenval, elseval, step(b, a))

vec4 vec4_premul(vec3 rgb, float a) {
    return vec4(rgb * a, a);
}

vec4 vec4_premul(vec4 rgba) {
    return vec4(rgba.rgb * rgba.a, rgba.a);
}



#line 2 7893001



// Inputs {{{
layout(std140) uniform CellRenderData {
    float use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, highlight_fg, highlight_bg, main_cursor_fg, main_cursor_bg, url_color, url_style, inverted, extra_cursor_fg, extra_cursor_bg;

    uint columns, lines, sprites_xnum, sprites_ynum, cursor_shape, cell_width, cell_height;
    uint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
    float cursor_opacity, inactive_text_alpha, fg_override_threshold, row_offset, dim_opacity, blink_opacity;

    // must have unique entries with 0 being default_bg and unset being UINT32_MAX
    uint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
    float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
};

layout(std140) uniform ColorTable {
    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};
uniform float gamma_lut[256];
uniform uint draw_bg_bitfield;
uniform usampler2D sprite_decorations_map;

// Have to use fixed locations here as all variants of the cell program share the same VAOs
layout(location=0) in uvec3 colors;
layout(location=1) in uvec2 sprite_idx;
layout(location=2) in uint is_selected;
// }}}

const int fg_index_map[] = int[3](0, 1, 0);
const uvec2 cell_pos_map[] = uvec2[4](
    uvec2(1u, 0u),  // right, top
    uvec2(1u, 1u),  // right, bottom
    uvec2(0u, 1u),  // left, bottom
    uvec2(0u, 0u)   // left, top
);
const uint cursor_shape_map[] = uint[5](  // maps cursor shape to foreground sprite index
   0u,  // NO_CURSOR
   0u,  // BLOCK  (this is rendered as background)
   2u,  // BEAM
   3u,  // UNDERLINE
   4u   // UNFOCUSED
);


out vec3 background;
out vec4 effective_background_premul;
#ifndef ONLY_BACKGROUND
out float effective_text_alpha;
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 cursor_pos;
out vec3 strike_pos;
flat out uint underline_exclusion_pos;
out vec3 cell_foreground;
out vec4 cursor_color_premult;
out vec3 decoration_fg;
out float colored_sprite;
#endif


// Utility functions {{{
const uint BYTE_MASK = uint(0xFF);
const uint SPRITE_INDEX_MASK = uint(0x7fffffff);
const uint SPRITE_COLORED_MASK = uint(0x80000000);
const uint SPRITE_COLORED_SHIFT = 31u;
const uint BIT_MASK = 1u;
const uint DECORATION_MASK = uint(7);

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
}

float one_if_equal_zero_otherwise(float a, float b) { return (1.0f - zero_or_one(abs(float(a) - float(b)))); }
// Wee need an integer variant to accommodate GPU driver bugs, see
// https://github.com/kovidgoyal/kitty/issues/9072
uint one_if_equal_zero_otherwise(int a, int b) { return (1u - uint(zero_or_one(abs(float(a) - float(b))))); }
uint one_if_equal_zero_otherwise(uint a, uint b) { return (1u - uint(zero_or_one(abs(float(a) - float(b))))); }


uint resolve_color(uint c, uint defval) {
    // Convert a cell color to an actual color based on the color table
    int t = int(c & BYTE_MASK);
    uint is_one = one_if_equal_zero_otherwise(t, 1);
    uint is_two = one_if_equal_zero_otherwise(t, 2);
    uint is_neither_one_nor_two = 1u - is_one - is_two;
    return is_one * color_table[(c >> 8) & BYTE_MASK] + is_two * (c >> 8) + is_neither_one_nor_two * defval;
}

vec3 to_color(uint c, uint defval) {
    return color_to_vec(resolve_color(c, defval));
}

vec3 resolve_dynamic_color(uint c, vec3 special_val, vec3 defval) {
    float type = float((c >> 24) & BYTE_MASK);
#define q(which, val) one_if_equal_zero_otherwise(type, float(which)) * val
    return (
        q(COLOR_IS_RGB, color_to_vec(c)) + q(COLOR_IS_INDEX, color_to_vec(color_table[c & BYTE_MASK])) +
        q(COLOR_IS_SPECIAL, special_val) + q(COLOR_NOT_SET, defval)
    );
#undef q
}

float contrast_ratio(float under_luminance, float over_luminance) {
    return clamp((max(under_luminance, over_luminance) + 0.05f) / (min(under_luminance, over_luminance) + 0.05f), 1.f, 21.f);
}

float contrast_ratio(vec3 a, vec3 b) {
    return contrast_ratio(dot(a, Y), dot(b, Y));
}

struct ColorPair {
    vec3 bg, fg;
};

float contrast_ratio(ColorPair a) { return contrast_ratio(a.bg, a.fg); }

ColorPair if_less_than_pair(float a, float b, ColorPair thenval, ColorPair elseval) {
    return ColorPair(if_less_than(a, b, thenval.bg, elseval.bg),
            if_less_than(a, b, thenval.fg, elseval.fg));
}

ColorPair if_one_then_pair(float condition, ColorPair thenval, ColorPair elseval) {
    return ColorPair(if_one_then(condition, thenval.bg, elseval.bg),
            if_one_then(condition, thenval.fg, elseval.fg));
}

ColorPair resolve_extra_cursor_colors_for_special_cursor(vec3 cell_bg, vec3 cell_fg) {
    ColorPair cell = ColorPair(cell_fg, cell_bg), base = ColorPair(color_to_vec(default_fg), color_to_vec(bg_colors0));
    float cr = contrast_ratio(cell), br = contrast_ratio(base);
    ColorPair higher_contrast_pair = if_less_than_pair(cr, br, base, cell);
    return if_less_than_pair(cr, 2.5, higher_contrast_pair, cell);
}

ColorPair resolve_extra_cursor_colors(vec3 cell_bg, vec3 cell_fg, ColorPair main_cursor) {
    ColorPair ans = ColorPair(
        resolve_dynamic_color(extra_cursor_bg, main_cursor.bg, main_cursor.bg),
        resolve_dynamic_color(extra_cursor_fg, cell_bg, main_cursor.fg)
    );
    ColorPair special = resolve_extra_cursor_colors_for_special_cursor(cell_bg, cell_fg);
    return if_one_then_pair(zero_or_one(abs(float(extra_cursor_bg & BYTE_MASK) - COLOR_IS_SPECIAL)), ans, special);
}

uvec3 to_sprite_coords(uint idx) {
    uint sprites_per_page = sprites_xnum * sprites_ynum;
    uint z = idx / sprites_per_page;
    uint num_on_last_page = idx - sprites_per_page * z;
    uint y = num_on_last_page / sprites_xnum;
    uint x = num_on_last_page - sprites_xnum * y;
    return uvec3(x, y, z);
}

vec3 to_sprite_pos(uvec2 pos, uint idx) {
    uvec3 c = to_sprite_coords(idx);
    vec2 s_xpos = vec2(c.x, float(c.x) + 1.0f) * (1.0f / float(sprites_xnum));
    vec2 s_ypos = vec2(c.y, float(c.y) + 1.0f) * (1.0f / float(sprites_ynum));
    uint texture_height_px = (cell_height + 1u) * sprites_ynum;
    float row_height = 1.0f / float(texture_height_px);
    s_ypos[1] -= row_height;  // skip the decorations_exclude row
    return vec3(s_xpos[pos.x], s_ypos[pos.y], c.z);
}

uint to_underline_exclusion_pos() {
    uvec3 c = to_sprite_coords(sprite_idx[0]);
    uint cell_top_px = c.y * (cell_height + 1u);
    return cell_top_px + cell_height;
}

uint read_sprite_decorations_idx() {
    int idx = int(sprite_idx[0] & SPRITE_INDEX_MASK);
    ivec2 sz = textureSize(sprite_decorations_map, 0);
    int y = idx / sz[0];
    int x = idx - y * sz[0];
    return texelFetch(sprite_decorations_map, ivec2(x, y), 0).r;
}

uvec2 get_decorations_indices(uint in_url /* [0, 1] */, uint text_attrs) {
    uint decorations_idx = read_sprite_decorations_idx();
    // decorations_idx == 0 means no decorations, for example, for a blank line
    // when drawing fractionally scaled text
    uint has_decorations = uint(zero_or_one(float(decorations_idx)));
    uint strike_style = ((text_attrs >> STRIKE_SHIFT) & BIT_MASK); // 0 or 1
    uint strike_idx = decorations_idx * strike_style;
    uint underline_style = ((text_attrs >> DECORATION_SHIFT) & DECORATION_MASK);
    underline_style = in_url * url_style + (1u - in_url) * underline_style; // [0, 5]
    uint has_underline = uint(step(0.5f, float(underline_style)));  // [0, 1]
    return has_decorations * uvec2(strike_idx, has_underline * (decorations_idx + underline_style));
}

uint is_cursor(uint x, uint y) {
    uint clamped_x = clamp(x, cursor_x1, cursor_x2);
    uint clamped_y = clamp(y, cursor_y1, cursor_y2);
    return one_if_equal_zero_otherwise(x, clamped_x) * one_if_equal_zero_otherwise(y, clamped_y);
}
// }}}

struct CellData {
    float has_cursor, has_block_cursor;
    uvec2 pos;
    uint cursor_fg_sprite_idx;
    ColorPair cursor;
} cell_data;

CellData set_vertex_position(vec3 cell_fg, vec3 cell_bg) {
    uint instance_id = uint(gl_InstanceID);
    float dx = 2.0 / float(columns);
    float dy = 2.0 / float(lines);
    /* The current cell being rendered */
    uint row = instance_id / columns;
    uint column = instance_id - row * columns;
    /* The position of this vertex, at a corner of the cell  */
    float left = -1.0 + column * dx;
    float top = 1.0 - (float(row) + row_offset) * dy;
    uvec2 pos = cell_pos_map[gl_VertexID];
    gl_Position = vec4(vec2(left, left + dx)[pos.x], vec2(top, top - dy)[pos.y], 0, 1);
    // The character sprite being rendered
#ifndef ONLY_BACKGROUND
    sprite_pos = to_sprite_pos(pos, sprite_idx[0] & SPRITE_INDEX_MASK);
    colored_sprite = float((sprite_idx[0] & SPRITE_COLORED_MASK) >> SPRITE_COLORED_SHIFT);
#endif
    // Cursor shape and colors
    float has_main_cursor = float(is_cursor(column, row));
    float multicursor_shape = float((is_selected >> 2) & 3u);
    float multicursor_uses_main_cursor_shape = float((is_selected >> 4) & BIT_MASK);
    multicursor_shape = if_one_then(multicursor_uses_main_cursor_shape, cursor_shape, multicursor_shape);
    float final_cursor_shape = if_one_then(has_main_cursor, cursor_shape, multicursor_shape);
    float has_cursor = zero_or_one(final_cursor_shape);
    float is_block_cursor = has_cursor * one_if_equal_zero_otherwise(final_cursor_shape, 1.0);
    ColorPair main_cursor = ColorPair(color_to_vec(main_cursor_bg), color_to_vec(main_cursor_fg));
    ColorPair extra_cursor = resolve_extra_cursor_colors(cell_bg, cell_fg, main_cursor);
    ColorPair cursor = if_one_then_pair(has_main_cursor, main_cursor, extra_cursor);
    return CellData(has_cursor, is_block_cursor, pos, cursor_shape_map[int(final_cursor_shape)], cursor);
}

float background_opacity_for(uint bg, uint colorval, float opacity_if_matched) {  // opacity_if_matched if bg == colorval else 1
    float not_matched = step(1.f, abs(float(colorval - bg)));  // not_matched = 0 if bg == colorval else 1
    return not_matched + opacity_if_matched * (1.f - not_matched);
}

float calc_background_opacity(uint bg) {
    return (
        background_opacity_for(bg, bg_colors0, bg_opacities0) *
        background_opacity_for(bg, bg_colors1, bg_opacities1) *
        background_opacity_for(bg, bg_colors2, bg_opacities2) *
        background_opacity_for(bg, bg_colors3, bg_opacities3) *
        background_opacity_for(bg, bg_colors4, bg_opacities4) *
        background_opacity_for(bg, bg_colors5, bg_opacities5) *
        background_opacity_for(bg, bg_colors6, bg_opacities6) *
        background_opacity_for(bg, bg_colors7, bg_opacities7)
    );
}

// Overriding of foreground colors for contrast requirements {{{
#if DO_FG_OVERRIDE == 1 && !defined(ONLY_BACKGROUND)
#define OVERRIDE_FG_COLORS



#line 0 7893004
/*
HSLUV-GLSL v4.2
HSLUV is a human-friendly alternative to HSL. ( http://www.hsluv.org )
GLSL port by William Malo ( https://github.com/williammalo )
Put this code in your fragment shader.
*/

// stripped down and optimized (branchless) version

float divide(float num, float denom) {
    return num / (abs(denom) + 1e-15) * sign(denom);
}

vec3 divide(vec3 num, vec3 denom) {
    return num / (abs(denom) + 1e-15) * sign(denom);
}

vec3 hsluv_intersectLineLine(vec3 line1x, vec3 line1y, vec3 line2x, vec3 line2y) {
    return (line1y - line2y) / (line2x - line1x);
}

vec3 hsluv_distanceFromPole(vec3 pointx,vec3 pointy) {
    return sqrt(pointx*pointx + pointy*pointy);
}

vec3 hsluv_lengthOfRayUntilIntersect(float theta, vec3 x, vec3 y) {
    vec3 len = divide(y, sin(theta) - x * cos(theta));
    len = mix(len, vec3(1000.0), step(len, vec3(0.0)));
    return len;
}

float hsluv_maxSafeChromaForL(float L){
    mat3 m2 = mat3(
         3.2409699419045214  ,-0.96924363628087983 , 0.055630079696993609,
        -1.5373831775700935  , 1.8759675015077207  ,-0.20397695888897657 ,
        -0.49861076029300328 , 0.041555057407175613, 1.0569715142428786
    );
    float sub0 = L + 16.0;
    float sub1 = sub0 * sub0 * sub0 * .000000641;
    float sub2 = mix(L / 903.2962962962963, sub1, step(0.0088564516790356308, sub1));

    vec3 top1   = (284517.0 * m2[0] - 94839.0  * m2[2]) * sub2;
    vec3 bottom = (632260.0 * m2[2] - 126452.0 * m2[1]) * sub2;
    vec3 top2   = (838422.0 * m2[2] + 769860.0 * m2[1] + 731718.0 * m2[0]) * L * sub2;

    vec3 bounds0x = top1 / bottom;
    vec3 bounds0y = top2 / bottom;

    vec3 bounds1x =              top1 / (bottom+126452.0);
    vec3 bounds1y = (top2-769860.0*L) / (bottom+126452.0);

    vec3 xs0 = hsluv_intersectLineLine(bounds0x, bounds0y, -1.0/bounds0x, vec3(0.0) );
    vec3 xs1 = hsluv_intersectLineLine(bounds1x, bounds1y, -1.0/bounds1x, vec3(0.0) );

    vec3 lengths0 = hsluv_distanceFromPole( xs0, bounds0y + xs0 * bounds0x );
    vec3 lengths1 = hsluv_distanceFromPole( xs1, bounds1y + xs1 * bounds1x );

    return  min(lengths0.r,
            min(lengths1.r,
            min(lengths0.g,
            min(lengths1.g,
            min(lengths0.b,
                lengths1.b)))));
}

float hsluv_maxChromaForLH(float L, float H) {

    float hrad = radians(H);

    mat3 m2 = mat3(
         3.2409699419045214  ,-0.96924363628087983 , 0.055630079696993609,
        -1.5373831775700935  , 1.8759675015077207  ,-0.20397695888897657 ,
        -0.49861076029300328 , 0.041555057407175613, 1.0569715142428786
    );
    float sub1 = pow(L + 16.0, 3.0) / 1560896.0;
    float sub2 = mix(L / 903.2962962962963, sub1, step(0.0088564516790356308, sub1));

    vec3 top1   = (284517.0 * m2[0] - 94839.0  * m2[2]) * sub2;
    vec3 bottom = (632260.0 * m2[2] - 126452.0 * m2[1]) * sub2;
    vec3 top2   = (838422.0 * m2[2] + 769860.0 * m2[1] + 731718.0 * m2[0]) * L * sub2;

    vec3 bound0x = top1 / bottom;
    vec3 bound0y = top2 / bottom;

    vec3 bound1x =              top1 / (bottom+126452.0);
    vec3 bound1y = (top2-769860.0*L) / (bottom+126452.0);

    vec3 lengths0 = hsluv_lengthOfRayUntilIntersect(hrad, bound0x, bound0y );
    vec3 lengths1 = hsluv_lengthOfRayUntilIntersect(hrad, bound1x, bound1y );

    return  min(lengths0.r,
            min(lengths1.r,
            min(lengths0.g,
            min(lengths1.g,
            min(lengths0.b,
                lengths1.b)))));
}

vec3 hsluv_fromLinear(vec3 c) {
    return mix(c * 12.92, 1.055 * pow(max(c, vec3(0)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

vec3 hsluv_toLinear(vec3 c) {
    return mix(c / 12.92, pow(max((c + 0.055) / (1.0 + 0.055), vec3(0)), vec3(2.4)), step(0.04045, c));
}

float hsluv_yToL(float Y){
    return mix(Y * 903.2962962962963, 116.0 * pow(max(Y, 0), 1.0 / 3.0) - 16.0, step(0.0088564516790356308, Y));
}

float hsluv_lToY(float L) {
    return mix(L / 903.2962962962963, pow((max(L, 0) + 16.0) / 116.0, 3.0), step(8.0, L));
}

vec3 xyzToRgb(vec3 tuple) {
    const mat3 m = mat3(
        3.2409699419045214  ,-1.5373831775700935 ,-0.49861076029300328 ,
       -0.96924363628087983 , 1.8759675015077207 , 0.041555057407175613,
        0.055630079696993609,-0.20397695888897657, 1.0569715142428786  );
    return hsluv_fromLinear(tuple*m);
}

vec3 rgbToXyz(vec3 tuple) {
    const mat3 m = mat3(
        0.41239079926595948 , 0.35758433938387796, 0.18048078840183429 ,
        0.21263900587151036 , 0.71516867876775593, 0.072192315360733715,
        0.019330818715591851, 0.11919477979462599, 0.95053215224966058
    );
    return hsluv_toLinear(tuple) * m;
}

vec3 xyzToLuv(vec3 tuple){
    float X = tuple.x;
    float Y = tuple.y;
    float Z = tuple.z;

    float L = hsluv_yToL(Y);
    float div = 1. / max(dot(tuple, vec3(1, 15, 3)), 1e-15);

    return vec3(
        1.,
        (52. * (X*div) - 2.57179),
        (117.* (Y*div) - 6.08816)
    ) * L;
}


vec3 luvToXyz(vec3 tuple) {
    float L = tuple.x;

    float U = divide(tuple.y, 13.0 * L) + 0.19783000664283681;
    float V = divide(tuple.z, 13.0 * L) + 0.468319994938791;

    float Y = hsluv_lToY(L);
    float X = 2.25 * U * Y / V;
    float Z = (3./V - 5.)*Y - (X/3.);

    return vec3(X, Y, Z);
}

vec3 luvToLch(vec3 tuple) {
    float L = tuple.x;
    float U = tuple.y;
    float V = tuple.z;

    float C = length(tuple.yz);
    float H = degrees(atan(V,U));
    H += 360.0 * step(H, 0.0);

    return vec3(L, C, H);
}

vec3 lchToLuv(vec3 tuple) {
    float hrad = radians(tuple.b);
    return vec3(
        tuple.r,
        cos(hrad) * tuple.g,
        sin(hrad) * tuple.g
    );
}

vec3 hsluvToLch(vec3 tuple) {
    tuple.g *= hsluv_maxChromaForLH(tuple.b, tuple.r) * .01;
    return tuple.bgr;
}

vec3 lchToHsluv(vec3 tuple) {
    tuple.g = divide(tuple.g, hsluv_maxChromaForLH(tuple.r, tuple.b) * .01);
    return tuple.bgr;
}

vec3 lchToRgb(vec3 tuple) {
    return xyzToRgb(luvToXyz(lchToLuv(tuple)));
}

vec3 rgbToLch(vec3 tuple) {
    return luvToLch(xyzToLuv(rgbToXyz(tuple)));
}

vec3 hsluvToRgb(vec3 tuple) {
    return lchToRgb(hsluvToLch(tuple));
}

vec3 rgbToHsluv(vec3 tuple) {
    return lchToHsluv(rgbToLch(tuple));
}

vec3 luvToRgb(vec3 tuple){
    return xyzToRgb(luvToXyz(tuple));
}



#line 263 7893001

#if (FG_OVERRIDE_ALGO == 1)
vec3 fg_override(float under_luminance, float over_lumininace, vec3 under, vec3 over) {
    // If the difference in luminance is too small,
    // force the foreground color to be black or white.
    float diff_luminance = abs(under_luminance - over_lumininace);
	float override_level = (1.f - colored_sprite) * step(diff_luminance, fg_override_threshold);
	float original_level = 1.f - override_level;
	return original_level * over + override_level * vec3(step(under_luminance, 0.5f));
}

#else

vec3 fg_override(float under_luminance, float over_luminance, vec3 under, vec3 over) {
    float ratio = contrast_ratio(under_luminance, over_luminance);
    vec3 diff = abs(under - over);
    vec3 over_hsluv = rgbToHsluv(over);
    const float min_contrast_ratio = fg_override_threshold;
    float target_lum_a = clamp((under_luminance + 0.05f) * min_contrast_ratio - 0.05f, 0.f, 1.f);
    float target_lum_b = clamp((under_luminance + 0.05f) / min_contrast_ratio - 0.05f, 0.f, 1.f);
    vec3 result_a = clamp(hsluvToRgb(vec3(over_hsluv.x, over_hsluv.y, target_lum_a * 100.f)), 0.f, 1.f);
    vec3 result_b = clamp(hsluvToRgb(vec3(over_hsluv.x, over_hsluv.y, target_lum_b * 100.f)), 0.f, 1.f);
    float result_a_ratio = contrast_ratio(under_luminance, dot(result_a, Y));
    float result_b_ratio = contrast_ratio(under_luminance, dot(result_b, Y));
    vec3 result = mix(result_a, result_b, step(result_a_ratio, result_b_ratio));
    return mix(result, over, max(step(diff.r + diff.g + diff.b, 0.001f), step(min_contrast_ratio, ratio)));
}
#endif

vec3 override_foreground_color(vec3 over, vec3 under) {
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    return fg_override(under_luminance, over_lumininace, under, over);
}
#endif
// }}}

void main() {


    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, bg_colors0);
    uint text_attrs = sprite_idx[1];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & BIT_MASK);
    uint is_inverted = is_reversed + inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark - 1] + (BIT_MASK - has_mark) * bg_as_uint;
    float cell_has_default_bg = 1.f - step(1.f, abs(float(bg_as_uint - bg_colors0))); // 1 if has default bg else 0
    vec3 bg = color_to_vec(bg_as_uint);
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + mark] + (1u - has_mark) * fg_as_uint;
    vec3 foreground = color_to_vec(fg_as_uint);
    CellData cell_data = set_vertex_position(foreground, bg);
    // }}}

    // Foreground {{{
#ifndef ONLY_BACKGROUND // background does not depend on foreground
    float has_dim = float((text_attrs >> DIM_SHIFT) & BIT_MASK), has_blink = float((text_attrs >> BLINK_SHIFT) & BIT_MASK);
    effective_text_alpha = inactive_text_alpha * if_one_then(has_dim, dim_opacity, 1.0) * if_one_then(
            has_blink, blink_opacity, 1.0);
    float in_url = float((is_selected >> 1) & BIT_MASK);
    decoration_fg = if_one_then(in_url, color_to_vec(url_color), to_color(colors[2], fg_as_uint));
    // Selection
    vec3 selection_color = if_one_then(use_cell_bg_for_selection_fg, bg, color_to_vec(highlight_fg));
    selection_color = if_one_then(use_cell_fg_for_selection_fg, foreground, selection_color);
    foreground = if_one_then(float(is_selected & BIT_MASK), selection_color, foreground);
    decoration_fg = if_one_then(float(is_selected & BIT_MASK), selection_color, decoration_fg);
    // Underline and strike through (rendered via sprites)
    uvec2 decs = get_decorations_indices(uint(in_url), text_attrs);
    strike_pos = to_sprite_pos(cell_data.pos, decs[0]);
    underline_pos = to_sprite_pos(cell_data.pos, decs[1]);
    underline_exclusion_pos = to_underline_exclusion_pos();

    // Cursor
    cursor_color_premult = vec4(cell_data.cursor.bg * cursor_opacity, cursor_opacity);
    vec3 final_cursor_text_color = mix(foreground, cell_data.cursor.fg, cursor_opacity);
    foreground = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, foreground);
    decoration_fg = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, decoration_fg);
    cursor_pos = to_sprite_pos(cell_data.pos, cell_data.cursor_fg_sprite_idx * uint(cell_data.has_cursor));
#endif
    // }}}

    // Background {{{
    float bg_alpha = calc_background_opacity(bg_as_uint);
    // we use max so that opacity of the block cursor cell background goes from bg_alpha to 1
    float effective_cursor_opacity = max(cursor_opacity, bg_alpha);
    // is_special_cell is either 0 or 1
    float is_special_cell = cell_data.has_block_cursor + float(is_selected & BIT_MASK);
    is_special_cell += float(is_reversed);  // reverse video cells should be opaque as well
    is_special_cell = zero_or_one(is_special_cell);
    cell_has_default_bg = if_one_then(is_special_cell, 0., cell_has_default_bg);

    // special cells must always be fully opaque, otherwise leave bg_alpha untouched
    bg_alpha = if_one_then(is_special_cell, 1.f, bg_alpha);
    // Selection and cursor
    bg_alpha = if_one_then(cell_data.has_block_cursor, effective_cursor_opacity, bg_alpha);
    bg = if_one_then(float(is_selected & BIT_MASK), if_one_then(use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(highlight_bg)), bg);
    vec3 background_rgb = if_one_then(cell_data.has_block_cursor, mix(bg, cell_data.cursor.bg, cursor_opacity), bg);
    background = background_rgb;
    // }}}

#if !defined(ONLY_BACKGROUND) && defined(OVERRIDE_FG_COLORS)
    decoration_fg = override_foreground_color(decoration_fg, background_rgb);
    foreground = override_foreground_color(foreground, background_rgb);
#endif

#if !defined(ONLY_FOREGROUND)
    vec4 bgpremul = vec4_premul(background_rgb, bg_alpha);
    // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
    float cell_has_non_default_bg = 1.f - cell_has_default_bg;
    uint draw_bg_mask = uint(2.f * cell_has_non_default_bg + cell_has_default_bg); // 1 if has default bg else 2
    float draw_bg = step(0.5, float(draw_bg_bitfield & draw_bg_mask));
    bgpremul *= draw_bg;
    effective_background_premul = bgpremul;
#endif

#ifndef ONLY_BACKGROUND
    cell_foreground = foreground;
#endif
}
