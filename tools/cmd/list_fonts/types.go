package list_fonts

import (
	"fmt"
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

type DesignAxis struct {
	Format       int     `json:"format"`
	Flags        int     `json:"flags"`
	Name         string  `json:"name"`
	Value        float64 `json:"value"`
	Minimum      float64 `json:"minimum"`
	Maximum      float64 `json:"maximum"`
	Linked_value float64 `json:"linked_value"`
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

type VariableData struct {
	Axes                              []VariableAxis   `json:"axes"`
	Named_styles                      []NamedStyle     `json:"named_styles"`
	Variations_postscript_name_prefix string           `json:"variations_postscript_name_prefix"`
	Elided_fallback_name              string           `json:"elided_fallback_name"`
	Design_axes                       []DesignAxis     `json:"design_axes"`
	Multi_axis_styles                 []MultiAxisStyle `json:"multi_axis_styles"`
}

type ListedFont struct {
	Family          string         `json:"family"`
	Fullname        string         `json:"full_name"`
	Postscript_name string         `json:"postscript_name"`
	Is_monospace    bool           `json:"is_monospace"`
	Is_variable     bool           `json:"is_variable"`
	Variable_data   VariableData   `json:"variable_data"`
	Descriptor      map[string]any `json:"descriptor"`
}
