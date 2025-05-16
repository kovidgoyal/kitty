package choose_fonts

import (
	"fmt"
	"maps"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

var _ = fmt.Print

type VariableAxis struct {
	Minimum float64 `json:"minimum"`
	Maximum float64 `json:"maximum"`
	Default float64 `json:"default"`
	Hidden  bool    `json:"hidden"`
	Tag     string  `json:"tag"`
	Strid   string  `json:"strid"`
}

type NamedStyle struct {
	Axis_values     map[string]float64 `json:"axis_values"`
	Name            string             `json:"name"`
	Postscript_name string             `json:"psname"`
}

type DesignAxisValue struct {
	Format       int     `json:"format"`
	Flags        int     `json:"flags"`
	Name         string  `json:"name"`
	Value        float64 `json:"value"`
	Minimum      float64 `json:"minimum"`
	Maximum      float64 `json:"maximum"`
	Linked_value float64 `json:"linked_value"`
}

type DesignAxis struct {
	Tag      string            `json:"tag"`
	Name     string            `json:"name"`
	Ordering int               `json:"ordering"`
	Values   []DesignAxisValue `json:"values"`
}

type AxisValue struct {
	Design_index int     `json:"design_index"`
	Value        float64 `json:"value"`
}

type MultiAxisStyle struct {
	Flags  int         `json:"flags"`
	Name   string      `json:"name"`
	Values []AxisValue `json:"values"`
}

type ListedFont struct {
	Family          string         `json:"family"`
	Style           string         `json:"style"`
	Fullname        string         `json:"full_name"`
	Postscript_name string         `json:"postscript_name"`
	Is_monospace    bool           `json:"is_monospace"`
	Is_variable     bool           `json:"is_variable"`
	Descriptor      map[string]any `json:"descriptor"`
}

type VariableData struct {
	Axes                              []VariableAxis   `json:"axes"`
	Named_styles                      []NamedStyle     `json:"named_styles"`
	Variations_postscript_name_prefix string           `json:"variations_postscript_name_prefix"`
	Elided_fallback_name              string           `json:"elided_fallback_name"`
	Design_axes                       []DesignAxis     `json:"design_axes"`
	Multi_axis_styles                 []MultiAxisStyle `json:"multi_axis_styles"`
}

type ResolvedFace struct {
	Family  string `json:"family"`
	Spec    string `json:"spec"`
	Setting string `json:"setting"`
}

type ResolvedFaces struct {
	Font_family      ResolvedFace `json:"font_family"`
	Bold_font        ResolvedFace `json:"bold_font"`
	Italic_font      ResolvedFace `json:"italic_font"`
	Bold_italic_font ResolvedFace `json:"bold_italic_font"`
}

type ListResult struct {
	Fonts          map[string][]ListedFont `json:"fonts"`
	Resolved_faces ResolvedFaces           `json:"resolved_faces"`
}

type FeatureData struct {
	Is_index bool     `json:"is_index"`
	Name     string   `json:"name"`
	Tooltip  string   `json:"tooltip"`
	Sample   string   `json:"sample"`
	Params   []string `json:"params"`
}

type RenderedSampleTransmit struct {
	Path                 string                 `json:"path"`
	Variable_data        VariableData           `json:"variable_data"`
	Style                string                 `json:"style"`
	Psname               string                 `json:"psname"`
	Spec                 string                 `json:"spec"`
	Features             map[string]FeatureData `json:"features"`
	Applied_features     map[string]string      `json:"applied_features"`
	Variable_named_style NamedStyle             `json:"variable_named_style"`
	Variable_axis_map    map[string]float64     `json:"variable_axis_map"`
	Cell_width           int                    `json:"cell_width"`
	Cell_height          int                    `json:"cell_height"`
	Canvas_width         int                    `json:"canvas_width"`
	Canvas_height        int                    `json:"canvas_height"`
}

func (self RenderedSampleTransmit) default_axis_values() (ans map[string]float64) {
	ans = make(map[string]float64)
	for _, ax := range self.Variable_data.Axes {
		ans[ax.Tag] = ax.Default
	}
	return
}

func (self RenderedSampleTransmit) current_axis_values() (ans map[string]float64) {
	ans = make(map[string]float64, len(self.Variable_data.Axes))
	for _, ax := range self.Variable_data.Axes {
		ans[ax.Tag] = ax.Default
	}
	if self.Variable_named_style.Name != "" {
		maps.Copy(ans, self.Variable_named_style.Axis_values)
	} else {
		maps.Copy(ans, self.Variable_axis_map)
	}
	return
}

var variable_data_cache map[string]VariableData
var variable_data_cache_mutex sync.Mutex

func (f ListedFont) cache_key() string {
	key := f.Postscript_name
	if key == "" {
		key = "path:" + f.Descriptor["path"].(string)
	} else {
		key = "psname:" + key
	}
	return key
}

func ensure_variable_data_for_fonts(fonts ...ListedFont) error {
	descriptors := make([]map[string]any, 0, len(fonts))
	keys := make([]string, 0, len(fonts))
	variable_data_cache_mutex.Lock()
	for _, f := range fonts {
		key := f.cache_key()
		if _, found := variable_data_cache[key]; !found {
			descriptors = append(descriptors, f.Descriptor)
			keys = append(keys, key)
		}
	}
	variable_data_cache_mutex.Unlock()
	var data []VariableData
	if err := kitty_font_backend.query("read_variable_data", map[string]any{"descriptors": descriptors}, &data); err != nil {
		return err
	}
	variable_data_cache_mutex.Lock()
	for i, key := range keys {
		variable_data_cache[key] = data[i]
	}
	variable_data_cache_mutex.Unlock()
	return nil
}

func initialize_variable_data_cache() {
	variable_data_cache = make(map[string]VariableData)
}

func _cached_vd(key string) (ans VariableData, found bool) {
	variable_data_cache_mutex.Lock()
	defer variable_data_cache_mutex.Unlock()
	ans, found = variable_data_cache[key]
	return
}

func variable_data_for(f ListedFont) VariableData {
	key := f.cache_key()
	ans, found := _cached_vd(key)
	if found {
		return ans
	}
	if err := ensure_variable_data_for_fonts(f); err != nil {
		panic(err)
	}
	ans, found = _cached_vd(key)
	return ans
}

func has_variable_data_for_font(font ListedFont) bool {
	_, found := _cached_vd(font.cache_key())
	return found
}

type ParsedFontFeature struct {
	tag     string
	val     uint
	is_bool bool
}

func (self ParsedFontFeature) String() string {
	if self.is_bool {
		return utils.IfElse(self.val == 0, "-", "+") + self.tag
	}
	return fmt.Sprintf("%s=%d", self.tag, self.val)
}

type settable_string struct {
	val    string
	is_set bool
}

type FontSpec struct {
	family, style, postscript_name, full_name, system, variable_name settable_string
	axes                                                             map[string]float64
	features                                                         []*ParsedFontFeature
}

func (self FontSpec) String() string {
	if self.system.val != "" {
		return self.system.val
	}
	ans := strings.Builder{}
	a := func(k string, v settable_string) {
		if v.is_set {
			ans.WriteString(fmt.Sprintf(" %s=%s", k, shlex.Quote(v.val)))
		}
	}
	a(`family`, self.family)
	a(`style`, self.style)
	a(`postscript_name`, self.postscript_name)
	a(`full_name`, self.full_name)
	a(`variable_name`, self.variable_name)
	for name, val := range self.axes {
		a(name, settable_string{strconv.FormatFloat(val, 'f', -1, 64), true})
	}
	if len(self.features) > 0 {
		buf := strings.Builder{}
		for _, f := range self.features {
			buf.WriteString(f.String())
			buf.WriteString(" ")
		}
		a(`features`, settable_string{strings.TrimSpace(buf.String()), true})
	}
	return strings.TrimSpace(ans.String())
}

func NewParsedFontFeature(x string, features map[string]FeatureData) (ans ParsedFontFeature, err error) {
	if x != "" {
		if x[0] == '+' || x[0] == '-' {
			return ParsedFontFeature{x[1:], utils.IfElse(x[0] == '+', uint(1), uint(0)), true}, nil
		} else {
			tag, val, found := strings.Cut(x, "=")
			fd, defn_found := features[tag]
			if defn_found && !fd.Is_index {
				return ParsedFontFeature{tag, 1, true}, nil
			}
			pff := ParsedFontFeature{tag: tag}
			if found {
				v, err := strconv.ParseUint(val, 10, 0)
				if err != nil {
					return ans, err
				}
				pff.val = uint(v)
			}
			return pff, nil
		}
	}
	return
}

func NewFontSpec(spec string, features map[string]FeatureData) (ans FontSpec, err error) {
	if spec == "" || spec == "auto" {
		ans.system = settable_string{"auto", true}
		return
	}
	parts, err := shlex.Split(spec)
	if err != nil {
		return
	}
	if !strings.Contains(parts[0], "=") {
		ans.system = settable_string{spec, true}
		return
	}
	for _, item := range parts {
		k, v, found := strings.Cut(item, "=")
		if !found {
			return ans, fmt.Errorf(fmt.Sprintf("The font specification %s is invalid as %s does not contain an =", spec, item))
		}
		switch k {
		case "family":
			ans.family = settable_string{v, true}
		case "style":
			ans.style = settable_string{v, true}
		case "full_name":
			ans.full_name = settable_string{v, true}
		case "postscript_name":
			ans.postscript_name = settable_string{v, true}
		case "variable_name":
			ans.variable_name = settable_string{v, true}
		case "features":
			for _, x := range utils.NewSeparatorScanner(v, " ").Split(v) {
				pff, err := NewParsedFontFeature(x, features)
				if err != nil {
					return ans, err
				}
				ans.features = append(ans.features, &pff)
			}
		default:
			if ans.axes == nil {
				ans.axes = make(map[string]float64)
			}
			f, err := strconv.ParseFloat(v, 64)
			if err != nil {
				return ans, err
			}
			ans.axes[k] = f
		}
	}
	return
}
