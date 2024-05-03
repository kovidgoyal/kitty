package list_fonts

import (
	"fmt"
	"kitty/tools/utils"
)

var _ = fmt.Print

func styles_in_family(family string, fonts []ListedFont) (ans []string, is_variable bool) {
	has_style_attribute_data := false
	for _, f := range fonts {
		vd := variable_data_for(f)
		if len(vd.Design_axes) > 0 {
			has_style_attribute_data = true
			break
		}
	}
	ans = make([]string, 0)
	seen := utils.NewSet[string]()
	add := func(x string) {
		if !seen.Has(x) {
			seen.Add(x)
			ans = append(ans, x)
		}
	}
	if has_style_attribute_data {
	} else {
		for _, f := range fonts {
			add(f.Style)
		}
	}
	debugprintln(111111111, family, has_style_attribute_data, ans)
	return
}
