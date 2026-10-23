// License: GPLv3 Copyright: 2026, kitty contributors

package choose_fonts

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestStylesWithAttributeData(t *testing.T) {
	face := func(weight string, weight_value float64, italic string, italic_value float64) VariableData {
		return VariableData{Design_axes: []DesignAxis{
			{Name: "Weight", Ordering: 0, Values: []DesignAxisValue{{Name: weight, Value: weight_value}}},
			{Name: "Italic", Ordering: 1, Values: []DesignAxisValue{{Name: italic, Value: italic_value}}},
		}}
	}
	ans := &family_style_data{}
	styles_with_attribute_data(ans, face("Regular", 400, "Upright", 0), face("Bold", 700, "Italic", 1))
	actual := map[string][]string{}
	for _, sg := range ans.style_groups {
		actual[sg.name] = sg.styles
	}
	if diff := cmp.Diff(map[string][]string{"Weight": {"Regular", "Bold"}, "Italic": {"Upright", "Italic"}}, actual); diff != "" {
		t.Fatalf("Unexpected styles:\n%s", diff)
	}
}
