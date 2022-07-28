#version GLSL_VERSION
#define {WHICH_PROGRAM}
#define NOT_TRANSPARENT
#define DECORATION_SHIFT {DECORATION_SHIFT}
#define REVERSE_SHIFT {REVERSE_SHIFT}
#define STRIKE_SHIFT {STRIKE_SHIFT}
#define DIM_SHIFT {DIM_SHIFT}
#define MARK_SHIFT {MARK_SHIFT}
#define MARK_MASK {MARK_MASK}
#define USE_SELECTION_FG
#define NUM_COLORS 256

// Inputs {{{
layout(std140) uniform CellRenderData {
    float xstart, ystart, dx, dy, sprite_dx, sprite_dy, background_opacity, use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, default_bg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

    uint xnum, ynum, cursor_fg_sprite_idx;
    float cursor_x, cursor_y, cursor_w;

    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};
#ifdef BACKGROUND
uniform uint draw_bg_bitfield;
#endif

// Have to use fixed locations here as all variants of the cell program share the same VAO
layout(location=0) in uvec3 colors;
layout(location=1) in uvec4 sprite_coords;
layout(location=2) in uint is_selected;


const int fg_index_map[] = int[3](0, 1, 0);
const uvec2 cell_pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);
// }}}


#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL)
#define NEEDS_BACKROUND
#endif

#if defined(SIMPLE) || defined(FOREGROUND)
#define NEEDS_FOREGROUND
#endif

#ifdef NEEDS_BACKROUND
out vec3 background;
out float draw_bg;
#if defined(TRANSPARENT) || defined(SPECIAL)
out float bg_alpha;
#endif
#endif

#ifdef NEEDS_FOREGROUND
uniform float inactive_text_alpha;
uniform float dim_opacity;
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 cursor_pos;
out vec4 cursor_color_vec;
out vec3 strike_pos;
out vec3 foreground;
out vec3 decoration_fg;
out float colored_sprite;
out float effective_text_alpha;
#endif


// Utility functions {{{
const uint BYTE_MASK = uint(0xFF);
const uint Z_MASK = uint(0xFFF);
const uint COLOR_MASK = uint(0x4000);
const uint ZERO = uint(0);
const uint ONE = uint(1);
const uint TWO = uint(2);
const uint STRIKE_SPRITE_INDEX = uint({STRIKE_SPRITE_INDEX});
const uint DECORATION_MASK = uint({DECORATION_MASK});

// TODO: Move to a texture, configurable?
// Generated using build-srgb-lut
const float srgb_lut[256] = float[](
0.00000000000000000000, 0.00030352698354883752, 0.00060705396709767503, 0.00091058095064651249, 0.00121410793419535006, 0.00151763491774418741, 0.00182116190129302498, 0.00212468888484186255, 0.00242821586839070012, 0.00273174285193953726, 0.00303526983548837483, 0.00334653576389916082, 0.00367650732404743589, 0.00402471701849630662, 0.00439144203741029335, 0.00477695348069372919,
0.00518151670233838596, 0.00560539162420272286, 0.00604883302285705391, 0.00651209079259447519, 0.00699541018726538687, 0.00749903204322617534, 0.00802319298538499426, 0.00856812561806930689, 0.00913405870222078718, 0.00972121732023784914, 0.01032982302962693645, 0.01096009400648824579, 0.01161224517974388491, 0.01228648835691587178, 0.01298303234217301240, 0.01370208304728968637,
0.01444384359609254473, 0.01520851442291270943, 0.01599629336550963121, 0.01680737575288738378, 0.01764195448838407759, 0.01850022012837969701, 0.01938236095693572289, 0.02028856305665240056, 0.02121901037600355464, 0.02217388479338738144, 0.02315336617811040998, 0.02415763244850475597, 0.02518685962736163034, 0.02624122189484989764, 0.02732089163907489363, 0.02842603950442079350,
0.02955683443780880021, 0.03071344373299363453, 0.03189603307301153157, 0.03310476657088505525, 0.03433980680868217034, 0.03560131487502034286, 0.03688945040110003931, 0.03820437159534650212, 0.03954623527673283706, 0.04091519690685319066, 0.04231141062080967519, 0.04373502925697346500, 0.04518620438567554076, 0.04666508633688009472, 0.04817182422688941895, 0.04970656598412723226,
0.05126945837404323775, 0.05286064702318024611, 0.05448027644244236856, 0.05612849004960009103, 0.05780543019106722941, 0.05951123816298119901, 0.06124605423161760820, 0.06301001765316767422, 0.06480326669290577268, 0.06662593864377289177, 0.06847816984440016630, 0.07036009569659587570, 0.07227185068231747889, 0.07421356838014962765, 0.07618538148130785115, 0.07818742180518632734,
0.08021982031446832362, 0.08228270712981479440, 0.08437621154414881586, 0.08650046203654976340, 0.08865558628577294153, 0.09084171118340768347, 0.09305896284668745133, 0.09530746663096470450, 0.09758734714186245718, 0.09989872824711389099, 0.10224173308810131922, 0.10461648409110418934, 0.10702310297826761465, 0.10946171077829933149, 0.11193242783690560138, 0.11443537382697373250,
0.11697066775851083786, 0.11953842798834561634, 0.12213877222960187185, 0.12477181756095048759, 0.12743768043564743242, 0.13013647669036429444, 0.13286832155381797516, 0.13563332965520566442, 0.13843161503245182686, 0.14126329114027164069, 0.14412847085805777225, 0.14702726649759498279, 0.14995978981060856250, 0.15292615199615017252, 0.15592646370782739518, 0.15896083506088040660,
0.16202937563911098962, 0.16513219450166760627, 0.16826940018969074875, 0.17144110073282259332, 0.17464740365558503732, 0.17788841598362911678, 0.18116424424986021791, 0.18447499450044099745, 0.18782077230067786844, 0.19120168274079138437, 0.19461783044157579536, 0.19806931955994885874, 0.20155625379439706668, 0.20507873639031692914, 0.20863687014525575392, 0.21223075741405522665,
0.21586050011389926184, 0.21952619972926920577, 0.22322795731680850073, 0.22696587351009836486, 0.23074004852434915058, 0.23455058216100521662, 0.23839757381227100197, 0.24228112246555486009, 0.24620132670783548279, 0.25015828472995343956, 0.25415209433082674995, 0.25818285292159581790, 0.26225065752969622945, 0.26635560480286246676, 0.27049779101306581364, 0.27467731206038464853,
0.27889426347681040008, 0.28314874042999210735, 0.28744083772691747525, 0.29177064981753586537, 0.29613827079832111266, 0.30054379441577649956, 0.30498731406988627279, 0.30946892281750854048, 0.31398871337571754303, 0.31854677812509185619, 0.32314320911295074668, 0.32777809805654217756, 0.33245153634617935490, 0.33716361504833036733, 0.34191442490866091886, 0.34670405635502959951,
0.35153259950043935778, 0.35640014414594350933, 0.36130677978350950186, 0.36625259559883949212, 0.37123768047414912319, 0.37626212299090650015, 0.38132601143253014309, 0.38642943378704902591, 0.39157247774972325782, 0.39675523072562685067, 0.40197777983219579179, 0.40724021190173670393, 0.41254261348390375286, 0.41788507084813747428, 0.42326766998607168180, 0.42869049661390662420,
0.43415363617474894697, 0.43965717384091879127, 0.44520119451622786055, 0.45078578283822345885, 0.45641102318040466246, 0.46207699965440707235, 0.46778379611215897826, 0.47353149614800954526, 0.47932018310082680213, 0.48514994005607037231, 0.49102084984783561650, 0.49693299506087040829, 0.50288645803256870614, 0.50888132085493376078, 0.51491766537652139402, 0.52099557320435430086,
0.52711512570581309234, 0.53327640401050524499, 0.53947948901210718287, 0.54572446137018659762, 0.55201140151200012163, 0.55834038963426790847, 0.56471150570492922860, 0.57112482946487308499, 0.57758044042965062115, 0.58407841789116410336, 0.59061884091933691820, 0.59720178836376336395, 0.60382733885533779183, 0.61049557080786476249, 0.61720656241965110578, 0.62396039167507610923,
0.63075713634614682945, 0.63759687399403264241, 0.64447968197058214113, 0.65140563741982415724, 0.65837481727944846543, 0.66538729828227205498, 0.67244315695768752672, 0.67954246963309383744, 0.68668531243531349961, 0.69387176129198990804, 0.70110189193297312027, 0.70837577989168676318, 0.71569350050648072870, 0.72305512892196932562, 0.73046074009035366625, 0.73791040877273084142,
0.74540420954038744128, 0.75294221677607786614, 0.76052450467529242317, 0.76815114724750699349, 0.77582221831742359530, 0.78353779152619351667, 0.79129794033263023412, 0.79910273801440900865, 0.80695225766925160471, 0.81484657221610123923, 0.82278575439628354182, 0.83076987677465463644, 0.83879901174074000814, 0.84687323150985804876, 0.85499260812423383271, 0.86315721345410234555,
0.87136711919879716870, 0.87962239688783172564, 0.88792311788196631728, 0.89626935337426638650, 0.90466117439114956955, 0.91309865179341920260, 0.92158185627729460876, 0.93011085837542373245, 0.93868572845788800230, 0.94730653673319986652, 0.95597335324928611744, 0.96468624789446510981, 0.97344529039841254381, 0.98225055033311714503, 0.99110209711382979414, 1.00000000000000000000
);

// Converts a byte-representation of sRGB to a vec3 in linear colorspace
vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;

    return vec3(srgb_lut[r], srgb_lut[g], srgb_lut[b]);
}

uint resolve_color(uint c, uint defval) {
    // Convert a cell color to an actual color based on the color table
    int t = int(c & BYTE_MASK);
    uint r;
    switch(t) {
        case 1:
            r = color_table[(c >> 8) & BYTE_MASK];
            break;
        case 2:
            r = c >> 8;
            break;
        default:
            r = defval;
    }
    return r;
}

vec3 to_color(uint c, uint defval) {
    return color_to_vec(resolve_color(c, defval));
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, float(x) + 1.0) * sprite_dx;
    vec2 s_ypos = vec2(y, float(y) + 1.0) * sprite_dy;
    return vec3(s_xpos[pos.x], s_ypos[pos.y], z);
}

vec3 choose_color(float q, vec3 a, vec3 b) {
    return mix(b, a, q);
}

float are_integers_equal(float a, float b) { // return 1 if equal otherwise 0
    float delta = abs(a - b);  // delta can be 0, 1 or larger
    return step(delta, 0.5); // 0 if 0.5 < delta else 1
}

float is_cursor(uint xi, uint y) {
    float x = float(xi);
    float y_equal = are_integers_equal(float(y), cursor_y);
    float x1_equal = are_integers_equal(x, cursor_x);
    float x2_equal = are_integers_equal(x, cursor_w);
    float x_equal = step(0.5, x1_equal + x2_equal);
    return step(2.0, x_equal + y_equal);
}
// }}}


void main() {

    // set cell vertex position  {{{
    uint instance_id = uint(gl_InstanceID);
    /* The current cell being rendered */
    uint r = instance_id / xnum;
    uint c = instance_id - r * xnum;

    /* The position of this vertex, at a corner of the cell  */
    float left = xstart + c * dx;
    float top = ystart - r * dy;
    vec2 xpos = vec2(left, left + dx);
    vec2 ypos = vec2(top, top - dy);
    uvec2 pos = cell_pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos.x], ypos[pos.y], 0, 1);

    // }}}

    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, default_bg);
    uint text_attrs = sprite_coords[3];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & ONE);
    uint is_inverted = is_reversed + inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    float cell_has_cursor = is_cursor(c, r);
    float is_block_cursor = step(float(cursor_fg_sprite_idx), 0.5);
    float cell_has_block_cursor = cell_has_cursor * is_block_cursor;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark] + (ONE - has_mark) * bg_as_uint;
    vec3 bg = color_to_vec(bg_as_uint);
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    // }}}

    // Foreground {{{
#ifdef NEEDS_FOREGROUND

    // The character sprite being rendered
    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & Z_MASK);
    colored_sprite = float((sprite_coords.z & COLOR_MASK) >> 14);

    // Foreground
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + 1 + mark] + (ONE - has_mark) * fg_as_uint;
    foreground = color_to_vec(fg_as_uint);
    float has_dim = float((text_attrs >> DIM_SHIFT) & ONE);
    effective_text_alpha = inactive_text_alpha * mix(1.0, dim_opacity, has_dim);
    float in_url = float((is_selected & TWO) >> 1);
    decoration_fg = choose_color(in_url, color_to_vec(url_color), to_color(colors[2], fg_as_uint));
    // Selection
    vec3 selection_color = choose_color(use_cell_bg_for_selection_fg, bg, color_to_vec(highlight_fg));
    selection_color = choose_color(use_cell_fg_for_selection_fg, foreground, selection_color);
    foreground = choose_color(float(is_selected & ONE), selection_color, foreground);
    decoration_fg = choose_color(float(is_selected & ONE), selection_color, decoration_fg);
    // Underline and strike through (rendered via sprites)
    underline_pos = choose_color(in_url, to_sprite_pos(pos, url_style, ZERO, ZERO), to_sprite_pos(pos, (text_attrs >> DECORATION_SHIFT) & DECORATION_MASK, ZERO, ZERO));
    strike_pos = to_sprite_pos(pos, ((text_attrs >> STRIKE_SHIFT) & ONE) * STRIKE_SPRITE_INDEX, ZERO, ZERO);

    // Cursor
    cursor_color_vec = vec4(color_to_vec(cursor_bg), 1.0);
    vec3 final_cursor_text_color = color_to_vec(cursor_fg);
    foreground = choose_color(cell_has_block_cursor, final_cursor_text_color, foreground);
    decoration_fg = choose_color(cell_has_block_cursor, final_cursor_text_color, decoration_fg);
    cursor_pos = to_sprite_pos(pos, cursor_fg_sprite_idx * uint(cell_has_cursor), ZERO, ZERO);
#endif
    // }}}

    // Background {{{
#ifdef NEEDS_BACKROUND
    float cell_has_non_default_bg = step(1, float(abs(bg_as_uint - default_colors[1])));
    draw_bg = 1;

#if defined(BACKGROUND)
    background = bg;
    // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
    uint draw_bg_mask = uint(2 * cell_has_non_default_bg + (1 - cell_has_non_default_bg));
    draw_bg = step(1, float(draw_bg_bitfield & draw_bg_mask));
#endif

#ifdef TRANSPARENT
    // Set bg_alpha to background_opacity on cells that have the default background color
    // Which means they must not have a block cursor or a selection or reverse video
    // On other cells it should be 1. For the SPECIAL program it should be 1 on cells with
    // selections/block cursor and 0 everywhere else.
    float is_special_cell = cell_has_block_cursor + float(is_selected & ONE);
#ifndef SPECIAL
    is_special_cell += cell_has_non_default_bg + float(is_reversed);
#endif
    bg_alpha = step(0.5, is_special_cell);
#ifndef SPECIAL
    bg_alpha = bg_alpha + (1.0f - bg_alpha) * background_opacity;
    bg_alpha *= draw_bg;
#endif
#endif

#if defined(SPECIAL) || defined(SIMPLE)
    // Selection and cursor
    bg = choose_color(float(is_selected & ONE), choose_color(use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(highlight_bg)), bg);
    background = choose_color(cell_has_block_cursor, color_to_vec(cursor_bg), bg);
#if !defined(TRANSPARENT) && defined(SPECIAL)
    float is_special_cell = cell_has_block_cursor + float(is_selected & ONE);
    bg_alpha = step(0.5, is_special_cell);
#endif
#endif

#endif
    // }}}

}
