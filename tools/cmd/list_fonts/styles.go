package list_fonts

import (
	"fmt"
	"kitty/tools/utils"
)

var _ = fmt.Print

type family_style_data struct {
	styles                   []string
	has_variable_faces       bool
	has_style_attribute_data bool
}

func styles_in_family(family string, fonts []ListedFont) (ans *family_style_data) {
	_ = family
	ans = &family_style_data{styles: make([]string, 0)}
	for _, f := range fonts {
		vd := variable_data_for(f)
		if len(vd.Design_axes) > 0 {
			ans.has_style_attribute_data = true
		}
		if len(vd.Axes) > 0 {
			ans.has_variable_faces = true
		}
	}
	seen := utils.NewSet[string]()
	add := func(x string) {
		if !seen.Has(x) {
			seen.Add(x)
			ans.styles = append(ans.styles, x)
		}
	}
	if ans.has_style_attribute_data {
		for _, f := range fonts {
			vd := variable_data_for(f)
			for _, ax := range vd.Design_axes {
				for _, v := range ax.Values {
					add(v.Name)
				}
			}
		}
	} else {
		for _, f := range fonts {
			add(f.Style)
		}
	}
	return
}
