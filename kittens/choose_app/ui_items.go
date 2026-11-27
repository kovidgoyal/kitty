// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"cmp"
	"fmt"
	"path/filepath"
	"slices"

	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// item is an application shown in the chooser
type item struct {
	entry  *DesktopEntry
	choice Choice
	// whether this is one of the applications recommended for the targets, and its rank among them
	recommended bool
	rank        int
	// this item switches to typing a command instead of being an application
	opens_command_entry bool

	// results of matching against the current query
	score          uint
	name_matched   bool
	name_positions []int
}

func (it *item) is_custom_command() bool { return it.choice.DesktopID == "" }

func new_command_entry_item() *item {
	return &item{entry: &DesktopEntry{Name: "Type a command"}, opens_command_entry: true}
}

// secondary_texts are matched against the query when the name does not
// match. They are matched separately so that a match cannot be made of
// letters scattered over unrelated words.
func (it *item) secondary_texts() (ans []string) {
	e := it.entry
	if e.GenericName != "" {
		ans = append(ans, e.GenericName)
	}
	ans = append(ans, e.Keywords...)
	if toks, err := e.tokens(); err == nil && len(toks) > 0 {
		ans = append(ans, filepath.Base(toks[0].text))
	}
	return
}

// mime_types_of returns the distinct MIME types of the targets, in order
func mime_types_of(targets []Target) []string {
	return utils.Uniq(utils.Map(MimeTypeForTarget, targets))
}

// ChooserInput is what the chooser is choosing an application for
type ChooserInput struct {
	Targets []Target
	// The MIME types to choose for, those of the targets by default
	MimeTypes []string
	// Applications to recommend, after the ones recently chosen for the MIME types
	Recommend []Choice
	// The desktop file id of the application to select initially
	Preselect string
	// Shown to the user instead of the names of the targets
	DisplayName string
}

func NewChooserInput(targets []Target) *ChooserInput {
	return &ChooserInput{Targets: targets, MimeTypes: mime_types_of(targets)}
}

// recommended_choices returns the applications recommended for opening all the
// MIME types: those recently chosen for the type first, then the explicitly
// recommended ones, then the ones that can open the type in order of
// preference. When there are multiple types, only applications suitable for
// all of them are recommended, unless there are none, in which case those
// suitable for any are.
func recommended_choices(db *AppDatabase, store *ChoiceStore, mimes []string, extra []Choice) (ans []Choice) {
	per_mime := make([][]Choice, len(mimes))
	for i, m := range mimes {
		var q []Choice
		add := func(c Choice) {
			if !slices.ContainsFunc(q, c.Equal) {
				q = append(q, c)
			}
		}
		for _, c := range store.Recent(m) {
			if _, err := c.Entry(db); err == nil {
				add(c)
			}
		}
		for _, c := range extra {
			if _, err := c.Entry(db); err == nil {
				add(c)
			}
		}
		for _, e := range db.AppsFor(m) {
			add(Choice{DesktopID: e.ID})
		}
		per_mime[i] = q
	}
	if len(per_mime) == 0 {
		return nil
	}
	in_all := func(c Choice) bool {
		for _, q := range per_mime[1:] {
			if !slices.ContainsFunc(q, c.Equal) {
				return false
			}
		}
		return true
	}
	ans = utils.Filter(per_mime[0], in_all)
	if len(ans) == 0 {
		for _, q := range per_mime {
			for _, c := range q {
				if !slices.ContainsFunc(ans, c.Equal) {
					ans = append(ans, c)
				}
			}
		}
	}
	return
}

// build_items returns the recommended applications in order of preference,
// followed by all other applications sorted by name
func build_items(db *AppDatabase, store *ChoiceStore, input *ChooserInput) (ans []*item) {
	seen := utils.NewSet[string]()
	// Applications can have multiple desktop files with the same name and
	// command, for example, for different file types, show only the first
	type name_and_exec struct{ name, exec string }
	seen_names := utils.NewSet[name_and_exec]()
	for _, c := range recommended_choices(db, store, input.MimeTypes, input.Recommend) {
		e, err := c.Entry(db)
		if err != nil {
			continue
		}
		seen.Add(e.ID)
		if k := (name_and_exec{e.Name, e.Exec}); !seen_names.Has(k) {
			seen_names.Add(k)
			ans = append(ans, &item{entry: e, choice: c, recommended: true, rank: len(ans)})
		}
	}
	for _, e := range db.AllApps() {
		if k := (name_and_exec{e.Name, e.Exec}); !seen.Has(e.ID) && !seen_names.Has(k) {
			seen_names.Add(k)
			ans = append(ans, &item{entry: e, choice: Choice{DesktopID: e.ID}, rank: len(ans)})
		}
	}
	return
}

// filter_items returns the items matching the query, best matches first.
// Matches on the name rank above matches on the generic name, keywords and
// executable name. Ties are broken by preferring recommended applications.
// With an empty query all items are returned in their original order.
func filter_items(items []*item, query string, matcher *fzf.FuzzyMatcher) ([]*item, error) {
	for _, it := range items {
		it.score, it.name_matched, it.name_positions = 0, false, nil
	}
	if query == "" {
		return items, nil
	}
	names := make([]string, len(items))
	var secondary []string
	var secondary_owner []int
	for i, it := range items {
		names[i] = it.entry.Name
		for _, x := range it.secondary_texts() {
			secondary = append(secondary, x)
			secondary_owner = append(secondary_owner, i)
		}
	}
	name_scores, err := matcher.ScoreWithCache(names, query)
	if err != nil {
		return nil, err
	}
	secondary_scores, err := matcher.ScoreWithCache(secondary, query)
	if err != nil {
		return nil, err
	}
	best_secondary := make([]uint, len(items))
	for j, s := range secondary_scores {
		best_secondary[secondary_owner[j]] = max(best_secondary[secondary_owner[j]], s.Score)
	}
	ans := make([]*item, 0, len(items))
	for i, it := range items {
		if s := name_scores[i]; s.Score > 0 {
			it.score, it.name_matched, it.name_positions = s.Score, true, slices.Sorted(slices.Values(s.Positions))
		} else if best_secondary[i] > 0 {
			it.score = best_secondary[i]
		} else {
			continue
		}
		ans = append(ans, it)
	}
	slices.SortStableFunc(ans, func(a, b *item) int {
		if a.name_matched != b.name_matched {
			return utils.IfElse(a.name_matched, -1, 1)
		}
		if c := cmp.Compare(b.score, a.score); c != 0 {
			return c
		}
		if a.recommended != b.recommended {
			return utils.IfElse(a.recommended, -1, 1)
		}
		return cmp.Compare(a.rank, b.rank)
	})
	return ans, nil
}
