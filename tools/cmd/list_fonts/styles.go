package list_fonts

import (
	"fmt"
	"kitty/tools/utils"
)

var _ = fmt.Print

type style_group struct {
	name     string
	ordering int
	styles   []string
}

type family_style_data struct {
	style_groups             []style_group
	has_variable_faces       bool
	has_style_attribute_data bool
}

func styles_in_family(family string, fonts []ListedFont) (ans *family_style_data) {
	_ = family
	ans = &family_style_data{style_groups: make([]style_group, 0)}
	for _, f := range fonts {
		vd := variable_data_for(f)
		if len(vd.Design_axes) > 0 {
			ans.has_style_attribute_data = true
		}
		if len(vd.Axes) > 0 {
			ans.has_variable_faces = true
		}
	}
	if ans.has_style_attribute_data {
		groups := make(map[string]*style_group)
		seen_map := make(map[string]*utils.Set[string])
		get := func(key string, ordering int) (*style_group, *utils.Set[string]) {
			sg := groups[key]
			seen := seen_map[key]
			if sg == nil {
				ans.style_groups = append(ans.style_groups, style_group{name: key, ordering: ordering, styles: make([]string, 0)})
				sg = &ans.style_groups[len(ans.style_groups)-1]
				groups[key] = sg
				seen = utils.NewSet[string]()
				seen_map[key] = seen
			}
			return sg, seen
		}
		for _, f := range fonts {
			vd := variable_data_for(f)
			for _, ax := range vd.Design_axes {
				if ax.Name == "" {
					continue
				}
				sg, seen := get(ax.Name, ax.Ordering)
				for _, v := range ax.Values {
					if v.Name != "" && !seen.Has(v.Name) {
						seen.Add(v.Name)
						sg.styles = append(sg.styles, v.Name)
					}
				}
			}
			for _, ma := range vd.Multi_axis_styles {
				sg, seen := get("Styles", 0)
				if ma.Name != "" && !seen.Has(ma.Name) {
					seen.Add(ma.Name)
					sg.styles = append(sg.styles, ma.Name)
				}
			}
		}
		utils.StableSortWithKey(ans.style_groups, func(sg style_group) int { return sg.ordering })
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
	return
}
