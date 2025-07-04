package choose_files

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type Filter struct {
	Name, Type, Pattern string
	Match               func(filename string) bool
}

func (f Filter) String() string {
	return fmt.Sprintf("%s:%s:%s", f.Type, f.Pattern, f.Name)
}

func (f Filter) Equal(other Filter) bool {
	return f.Type == other.Type && f.Pattern == other.Pattern
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
				m, _ := filepath.Match(ans.Pattern, mime)
				return m
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
	for _, f := range filters {
		if f.Match == nil {
			return f
		}
	}
	ans := filters[0]
	matchers := utils.Map(func(f Filter) func(filename string) bool { return f.Match }, filters)
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
