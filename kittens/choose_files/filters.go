package choose_files

import (
	"fmt"
	"path/filepath"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type Filter struct {
	Name, Type, Pattern string
	Match               func(filename string) bool
	// The individual filters making up a combined filter, Type and Pattern are empty for combined filters
	sub_filters []Filter
}

func (f Filter) String() string {
	if len(f.sub_filters) > 0 {
		return strings.Join(utils.Map(Filter.String, f.sub_filters), ", ")
	}
	return fmt.Sprintf("%s:%s:%s", f.Type, f.Pattern, f.Name)
}

// The sorted, de-duplicated type:pattern specs of the matchers making up this filter
func (f Filter) specs() []string {
	if len(f.sub_filters) == 0 {
		return []string{f.Type + ":" + f.Pattern}
	}
	ans := utils.Map(func(sf Filter) string { return sf.Type + ":" + sf.Pattern }, f.sub_filters)
	slices.Sort(ans)
	return slices.Compact(ans)
}

// Whether the two filters match the same set of files, regardless of their names
func (f Filter) Equal(other Filter) bool {
	if f.Match == nil || other.Match == nil {
		return f.Match == nil && other.Match == nil
	}
	return slices.Equal(f.specs(), other.specs())
}

func NewFilter(spec string) (*Filter, error) {
	parts := strings.SplitN(spec, ":", 3)
	if len(parts) != 3 {
		return nil, fmt.Errorf("%#v is not a valid filter specifier, must have at least two colons", spec)
	}
	ans := &Filter{Name: parts[2], Pattern: parts[1], Type: parts[0]}
	if _, err := filepath.Match(ans.Pattern, "test"); err != nil {
		return nil, fmt.Errorf("%#v is not a valid glob pattern with error: %w", ans.Pattern, err)
	}
	if ans.Pattern != "*" && ans.Pattern != "" {
		switch ans.Type {
		case "glob":
			ans.Match = func(filename string) bool {
				m, _ := filepath.Match(ans.Pattern, filename)
				return m
			}
		case "mime":
			ans.Match = func(filename string) bool {
				mime := utils.GuessMimeType(filename)
				if mime == "" {
					return false
				}
				for _, q := range utils.MimeTypeAliases(mime) {
					if m, _ := filepath.Match(ans.Pattern, q); m {
						return true
					}
				}
				return false
			}
		default:
			return nil, fmt.Errorf("%#v is not a valid filter type", ans.Type)
		}
	}
	return ans, nil
}

func CombinedFilter(filters ...Filter) Filter {
	if len(filters) == 0 {
		return Filter{}
	}
	var flattened []Filter
	for _, f := range filters {
		if f.Match == nil {
			return f
		}
		if len(f.sub_filters) > 0 {
			flattened = append(flattened, f.sub_filters...)
		} else {
			flattened = append(flattened, f)
		}
	}
	if len(flattened) == 1 {
		return flattened[0]
	}
	ans := Filter{Name: filters[0].Name, sub_filters: flattened}
	matchers := utils.Map(func(f Filter) func(filename string) bool { return f.Match }, flattened)
	ans.Match = func(filename string) bool {
		for _, m := range matchers {
			if m(filename) {
				return true
			}
		}
		return false
	}
	return ans
}
