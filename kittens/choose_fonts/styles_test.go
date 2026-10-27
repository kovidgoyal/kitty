// License: GPLv3 Copyright: 2026, kitty contributors

package choose_fonts

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

type group_result struct {
	Name   string
	Styles []string
}

func group_results(ans *family_style_data) []group_result {
	ret := make([]group_result, len(ans.style_groups))
	for i, sg := range ans.style_groups {
		ret[i] = group_result{sg.name, sg.styles}
	}
	return ret
}

func TestStylesWithAttributeData(t *testing.T) {
	axis := func(name string, ordering int, style string, value float64) DesignAxis {
		return DesignAxis{Name: name, Ordering: ordering, Values: []DesignAxisValue{{Name: style, Value: value}}}
	}
	face := func(axes ...DesignAxis) VariableData { return VariableData{Design_axes: axes} }
	check := func(expected []group_result, items ...VariableData) {
		t.Helper()
		ans := &family_style_data{}
		styles_with_attribute_data(ans, items...)
		if diff := cmp.Diff(expected, group_results(ans)); diff != "" {
			t.Fatalf("Unexpected styles:\n%s", diff)
		}
	}

	// Styles added by later faces to groups created by earlier faces must not be lost
	check([]group_result{{"Weight", []string{"Regular", "Bold"}}, {"Italic", []string{"Upright", "Italic"}}},
		face(axis("Weight", 0, "Regular", 400), axis("Italic", 1, "Upright", 0)),
		face(axis("Weight", 0, "Bold", 700), axis("Italic", 1, "Italic", 1)))

	// Group order must not depend on the order of the faces
	a := face(axis("Weight", 1, "Regular", 400), axis("Italic", 2, "Upright", 0))
	b := face(axis("Weight", 2, "Bold", 700), axis("Italic", 1, "Italic", 1))
	expected := []group_result{{"Weight", []string{"Regular", "Bold"}}, {"Italic", []string{"Upright", "Italic"}}}
	check(expected, a, b)
	check(expected, b, a)

	// Multi axis styles are kept separate from a design axis named Styles
	ma := face(axis("Styles", 1, "Wide", 2))
	ma.Multi_axis_styles = []MultiAxisStyle{{Name: "Light Condensed"}, {Name: "Bold Expanded"}}
	mb := face(axis("Styles", 1, "Narrow", 1))
	mb.Multi_axis_styles = []MultiAxisStyle{{Name: "Light Condensed"}, {Name: "Black"}}
	check([]group_result{{"Styles", []string{"Black", "Bold Expanded", "Light Condensed"}}, {"Styles", []string{"Narrow", "Wide"}}}, ma, mb)
}

func TestStyleAxisValueOrder(t *testing.T) {
	for _, tt := range []struct {
		name   string
		values []DesignAxisValue
		want   []string
	}{
		{
			name: "negative slant values",
			values: []DesignAxisValue{
				{Name: "Oblique", Value: -5}, {Name: "Upright", Value: 0},
				{Name: "Backslant", Value: 5}, {Name: "More oblique", Value: -15},
				{Name: "Medium oblique", Value: -10},
			},
			want: []string{"More oblique", "Medium oblique", "Oblique", "Upright", "Backslant"},
		},
		{
			name: "fractional values",
			values: []DesignAxisValue{
				{Name: "Zero", Value: 0},
				{Name: "A positive", Value: 2.0 / 65536}, {Name: "Z positive", Value: 1.0 / 65536},
				{Name: "A negative", Value: -1.0 / 65536}, {Name: "Z negative", Value: -2.0 / 65536},
			},
			want: []string{"Z negative", "A negative", "Zero", "Z positive", "A positive"},
		},
		{
			name: "large negative values",
			values: []DesignAxisValue{
				{Name: "Zero", Value: 0}, {Name: "Minimum", Value: -32768},
				{Name: "Maximum", Value: 32767 + 65535.0/65536},
				{Name: "Minus ten thousand", Value: -10000}, {Name: "Minus one", Value: -1},
			},
			want: []string{"Minimum", "Minus ten thousand", "Minus one", "Zero", "Maximum"},
		},
		{
			name: "equal values use stable case insensitive name order",
			values: []DesignAxisValue{
				{Name: "beta", Value: -10}, {Name: "alpha", Value: -10},
				{Name: "Alpha", Value: -10},
			},
			want: []string{"alpha", "Alpha", "beta"},
		},
	} {
		t.Run(tt.name, func(t *testing.T) {
			vd := VariableData{Design_axes: []DesignAxis{{Name: "Slant", Values: tt.values}}}
			fonts := make([]ListedFont, len(tt.values))
			vds := make([]VariableData, len(tt.values))
			for i, v := range tt.values {
				fonts[i].Style = v.Name
				vds[i].Design_axes = []DesignAxis{{Name: "Slant", Values: []DesignAxisValue{v}}}
			}
			for name, ans := range map[string]*family_style_data{
				"single face": styles_for_variable_data(vd),
				"family":      styles_in_family_from_variable_data(fonts, vds),
			} {
				t.Run(name, func(t *testing.T) {
					if diff := cmp.Diff([]group_result{{"Slant", tt.want}}, group_results(ans)); diff != "" {
						t.Fatalf("Unexpected styles (-want +got):\n%s", diff)
					}
				})
			}
		})
	}
}

func TestStylesInFamily(t *testing.T) {
	check := func(expected []group_result, fonts []ListedFont, vds []VariableData) {
		t.Helper()
		if diff := cmp.Diff(expected, group_results(styles_in_family_from_variable_data(fonts, vds))); diff != "" {
			t.Fatalf("Unexpected styles:\n%s", diff)
		}
	}
	// Without style attribute data, the de-duplicated style names of the fonts are used
	fonts := []ListedFont{{Style: "Regular"}, {Style: "Bold"}, {Style: ""}, {Style: "Bold"}, {Style: "Italic"}}
	check([]group_result{{"Styles", []string{"Bold", "Italic", "Regular"}}}, fonts, make([]VariableData, len(fonts)))

	// With style attribute data, styles are sorted by axis value, not by name
	vd := func(weight string, weight_value float64, italic string, italic_value float64) VariableData {
		return VariableData{Design_axes: []DesignAxis{
			{Name: "Weight", Ordering: 0, Values: []DesignAxisValue{{Name: weight, Value: weight_value}}},
			{Name: "Italic", Ordering: 1, Values: []DesignAxisValue{{Name: italic, Value: italic_value}}},
		}}
	}
	fonts = []ListedFont{{Style: "Bold"}, {Style: "Regular"}, {Style: "Light"}}
	check([]group_result{{"Weight", []string{"Light", "Regular", "Bold"}}, {"Italic", []string{"Upright", "Italic"}}},
		fonts, []VariableData{vd("Bold", 700, "Italic", 1), vd("Regular", 400, "Upright", 0), vd("Light", 300, "Upright", 0)})
}
