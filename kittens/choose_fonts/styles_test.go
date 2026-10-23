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
