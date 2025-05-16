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
	groups := make(map[string]*style_group)
	seen_map := make(map[string]map[string]string)
	get := func(key string, ordering int) *style_group {
		sg := groups[key]
		seen := seen_map[key]
		if sg == nil {
			ans.style_groups = append(ans.style_groups, style_group{name: key, ordering: ordering, styles: make([]string, 0)})
			sg = &ans.style_groups[len(ans.style_groups)-1]
			groups[key] = sg
			sg.style_sort_map = make(map[string]string)
			seen = make(map[string]string)
			seen_map[key] = seen
		}
		return sg
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
			sg := get(ax.Name, ax.Ordering)
			for _, v := range ax.Values {
				if v.Name != "" && !has(v.Name, sg.style_sort_map) {
					sort_key := fmt.Sprintf("%09d:%s", int(v.Value*10000), strings.ToLower(v.Name))
					sg.style_sort_map[v.Name] = sort_key
					sg.styles = append(sg.styles, v.Name)
				}
			}

		}
		for _, ma := range vd.Multi_axis_styles {
			sg := get("Styles", 0)
			if ma.Name != "" && !has(ma.Name, sg.style_sort_map) {
				sg.style_sort_map[ma.Name] = strings.ToLower(ma.Name)
				sg.styles = append(sg.styles, ma.Name)
			}
		}
	}
	ans.style_groups = utils.StableSortWithKey(ans.style_groups, func(sg style_group) int { return sg.ordering })
	for _, sg := range ans.style_groups {
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
	ans = &family_style_data{style_groups: make([]style_group, 0)}
	vds := make([]VariableData, len(fonts))
	for i, f := range fonts {
		vds[i] = variable_data_for(f)
	}
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
	}
	for _, sg := range ans.style_groups {
		slices.Sort(sg.styles)
	}
	return
}
