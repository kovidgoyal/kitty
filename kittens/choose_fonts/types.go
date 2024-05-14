package choose_fonts

import (
	"fmt"
	"sync"
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
	Family string `json:"family"`
	Spec   string `json:"spec"`
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

type RenderedSampleTransmit struct {
	Path                 string             `json:"path"`
	Variable_data        VariableData       `json:"variable_data"`
	Style                string             `json:"style"`
	Psname               string             `json:"psname"`
	Variable_named_style NamedStyle         `json:"variable_named_style"`
	Variable_axis_map    map[string]float64 `json:"variable_axis_map"`
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
