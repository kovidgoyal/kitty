package choose_fonts

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"slices"
	"strings"
)

var _ = fmt.Print

type style_group struct {
	name           string
	ordering       int
	styles         []string
	style_sort_map map[string]string
}

type family_style_data struct {
	style_groups             []style_group
	has_variable_faces       bool
	has_style_attribute_data bool
}

func styles_with_attribute_data(ans *family_style_data, items ...VariableData) {
	// Multi axis styles are kept in their own group, separate from any design axis that happens to be named Styles
	type group_key struct {
		name             string
		multi_axis_style bool
	}
	// Store indices, not pointers, as appending to ans.style_groups can reallocate it
	groups := make(map[group_key]int)
	get := func(key group_key, ordering int) *style_group {
		idx, found := groups[key]
		if found {
			// Use the lowest ordering from any face so that the result does not depend on the order of the faces
			ans.style_groups[idx].ordering = min(ans.style_groups[idx].ordering, ordering)
		} else {
			idx = len(ans.style_groups)
			ans.style_groups = append(ans.style_groups, style_group{name: key.name, ordering: ordering, styles: make([]string, 0), style_sort_map: make(map[string]string)})
			groups[key] = idx
		}
		return &ans.style_groups[idx]
	}
	has := func(n string, m map[string]string) bool {
		_, found := m[n]
		return found
	}
	for _, vd := range items {
		for _, ax := range vd.Design_axes {
			if ax.Name == "" {
				continue
			}
			sg := get(group_key{name: ax.Name}, ax.Ordering)
			for _, v := range ax.Values {
				if v.Name != "" && !has(v.Name, sg.style_sort_map) {
					sort_key := fmt.Sprintf("%09d:%s", int(v.Value*10000), strings.ToLower(v.Name))
					sg.style_sort_map[v.Name] = sort_key
					sg.styles = append(sg.styles, v.Name)
				}
			}

		}
		for _, ma := range vd.Multi_axis_styles {
			sg := get(group_key{name: "Styles", multi_axis_style: true}, 0)
			if ma.Name != "" && !has(ma.Name, sg.style_sort_map) {
				sg.style_sort_map[ma.Name] = strings.ToLower(ma.Name)
				sg.styles = append(sg.styles, ma.Name)
			}
		}
	}
	ans.style_groups = utils.StableSortWithKey(ans.style_groups, func(sg style_group) int { return sg.ordering })
	for i := range ans.style_groups {
		sg := &ans.style_groups[i]
		sg.styles = utils.StableSortWithKey(sg.styles, func(s string) string { return sg.style_sort_map[s] })
	}

}

func styles_for_variable_data(vd VariableData) (ans *family_style_data) {
	ans = &family_style_data{style_groups: make([]style_group, 0)}
	styles_with_attribute_data(ans, vd)
	return
}

func styles_in_family(family string, fonts []ListedFont) (ans *family_style_data) {
	_ = family
	vds := make([]VariableData, len(fonts))
	for i, f := range fonts {
		vds[i] = variable_data_for(f)
	}
	return styles_in_family_from_variable_data(fonts, vds)
}

// vds must contain the variable data for each font in fonts, in the same order
func styles_in_family_from_variable_data(fonts []ListedFont, vds []VariableData) (ans *family_style_data) {
	ans = &family_style_data{style_groups: make([]style_group, 0)}
	for _, vd := range vds {
		if len(vd.Design_axes) > 0 {
			ans.has_style_attribute_data = true
		}
		if len(vd.Axes) > 0 {
			ans.has_variable_faces = true
		}
	}
	if ans.has_style_attribute_data {
		styles_with_attribute_data(ans, vds...)
	} else {
		ans.style_groups = append(ans.style_groups, style_group{name: "Styles", styles: make([]string, 0)})
		sg := &ans.style_groups[0]
		seen := utils.NewSet[string]()
		for _, f := range fonts {
			if f.Style != "" && !seen.Has(f.Style) {
				seen.Add(f.Style)
				sg.styles = append(sg.styles, f.Style)
			}
		}
		// styles_with_attribute_data has already sorted by axis value, only sort by name here
		slices.Sort(sg.styles)
	}
	return
}
