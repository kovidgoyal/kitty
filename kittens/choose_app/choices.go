// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const choices_version = 1

// The number of recently used applications to keep for each MIME type
const max_recent_choices = 8

// ChoicesPath is the file in which the applications chosen by the user are stored
func ChoicesPath() string {
	return filepath.Join(utils.CacheDir(), "choose-app", "choices.json")
}

type choices_data struct {
	Version int `json:"version"`
	// MIME type to the application to always use for it
	Remembered map[string]Choice `json:"remembered"`
	// MIME type to recently chosen applications, most recent first
	Recent map[string][]Choice `json:"recent"`
}

// ChoiceStore holds the applications previously chosen by the user, keyed
// by canonical MIME type. URLs use MIME types of the form x-scheme-handler/https.
type ChoiceStore struct {
	path string
	data choices_data
}

func canonical_mime_type(mime string) string {
	return utils.MimeTypeAliases(mime)[0]
}

func (s *ChoiceStore) reset() {
	s.data = choices_data{Version: choices_version, Remembered: map[string]Choice{}, Recent: map[string][]Choice{}}
}

func (s *ChoiceStore) load() error {
	s.reset()
	raw, err := os.ReadFile(s.path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		return fmt.Errorf("failed to read the remembered applications from %s with error: %w", s.path, err)
	}
	var d choices_data
	if err = json.Unmarshal(raw, &d); err != nil {
		return fmt.Errorf("the remembered applications in %s are corrupted and will be ignored, error: %w", s.path, err)
	}
	if d.Version != choices_version {
		return fmt.Errorf("the remembered applications in %s have unknown version %d and will be ignored", s.path, d.Version)
	}
	if d.Remembered != nil {
		s.data.Remembered = d.Remembered
	}
	if d.Recent != nil {
		s.data.Recent = d.Recent
	}
	return nil
}

// LoadChoiceStore loads the stored choices. When an error is returned the
// store is still usable and is empty.
func LoadChoiceStore(path string) (*ChoiceStore, error) {
	s := &ChoiceStore{path: path}
	return s, s.load()
}

// Remembered returns the application the user chose to always use for the
// specified MIME type
func (s *ChoiceStore) Remembered(mime string) (Choice, bool) {
	c, found := s.data.Remembered[canonical_mime_type(mime)]
	return c, found
}

// Recent returns the applications recently chosen for the specified MIME
// type, most recent first
func (s *ChoiceStore) Recent(mime string) []Choice {
	return s.data.Recent[canonical_mime_type(mime)]
}

// update performs a locked read-modify-write of the stored choices, so that
// concurrent instances do not lose each others changes
func (s *ChoiceStore) update(modify func()) (err error) {
	if err = os.MkdirAll(filepath.Dir(s.path), 0o700); err != nil {
		return fmt.Errorf("failed to create the directory for storing remembered applications with error: %w", err)
	}
	lf, err := os.OpenFile(s.path+".lock", os.O_RDWR|os.O_CREATE, 0o600)
	if err != nil {
		return fmt.Errorf("failed to open the lock file for remembered applications with error: %w", err)
	}
	defer lf.Close()
	if err = utils.LockFileExclusive(lf); err != nil {
		return fmt.Errorf("failed to lock the remembered applications with error: %w", err)
	}
	defer func() { _ = utils.UnlockFile(lf) }()
	if lerr := s.load(); lerr != nil {
		// A corrupted file is replaced, any other error is fatal
		var serr *json.SyntaxError
		var terr *json.UnmarshalTypeError
		if !errors.As(lerr, &serr) && !errors.As(lerr, &terr) {
			return lerr
		}
	}
	modify()
	raw, err := json.MarshalIndent(s.data, "", "  ")
	if err != nil {
		return err
	}
	if err = utils.AtomicWriteFile(s.path, bytes.NewReader(raw), 0o600); err != nil {
		return fmt.Errorf("failed to save the remembered applications to %s with error: %w", s.path, err)
	}
	return nil
}

// RecordChoice records that the user chose the specified application for the
// MIME type, making it the application always used for that type if remember is true.
func (s *ChoiceStore) RecordChoice(mime string, choice Choice, remember bool) error {
	mime = canonical_mime_type(mime)
	return s.update(func() {
		recent := slices.DeleteFunc(slices.Clone(s.data.Recent[mime]), choice.Equal)
		recent = slices.Insert(recent, 0, choice)
		s.data.Recent[mime] = recent[:min(len(recent), max_recent_choices)]
		if remember {
			s.data.Remembered[mime] = choice
		}
	})
}

// Forget removes the remembered application for the specified MIME types,
// returning the MIME types that had a remembered application
func (s *ChoiceStore) Forget(mimes ...string) (forgotten []string, err error) {
	err = s.update(func() {
		for _, m := range mimes {
			m = canonical_mime_type(m)
			if _, found := s.data.Remembered[m]; found {
				delete(s.data.Remembered, m)
				forgotten = append(forgotten, m)
			}
		}
	})
	return
}

// Resolution is how a file or URL is opened without asking the user
type Resolution struct {
	Choice Choice `json:"choice"`
	// One of open_with, remembered or system_default
	Source string `json:"source"`
	// The open_with setting used, if any
	Rule string `json:"rule,omitempty"`
}

// Resolver decides which application to use to open files and URLs without
// asking the user
type Resolver struct {
	Settings *Settings
	Store    *ChoiceStore
	DB       *AppDatabase
}

// MimeTypesFor returns the MIME type of the target followed by its aliases and
// the types it is a sub-class of
func (r *Resolver) MimeTypesFor(t Target) (mime string, all []string) {
	mime = MimeTypeForTarget(t)
	return mime, r.DB.mime_types_for(mime)
}

// Resolve returns the application to open the target with, in order of
// priority: the first matching open_with setting, the application remembered
// for its MIME type and the system default application for its MIME type, if
// allowed by the settings. Settings and remembered applications that refer to
// applications that are no longer installed are skipped, with a warning.
func (r *Resolver) Resolve(t Target) (ans Resolution, found bool, warnings []string) {
	mime, all_mimes := r.MimeTypesFor(t)
	usable := func(c Choice) bool {
		if _, err := c.Entry(r.DB); err != nil {
			warnings = append(warnings, err.Error())
			return false
		}
		return true
	}
	for _, rule := range r.Settings.Rules {
		if rule.Matches(t, all_mimes) {
			if usable(rule.Choice) {
				return Resolution{Choice: rule.Choice, Source: "open_with", Rule: rule.Spec}, true, warnings
			}
			warnings[len(warnings)-1] = fmt.Sprintf("ignoring open_with %s as %s", rule.Spec, warnings[len(warnings)-1])
		}
	}
	if c, ok := r.Store.Remembered(mime); ok {
		if usable(c) {
			return Resolution{Choice: c, Source: "remembered"}, true, warnings
		}
		warnings[len(warnings)-1] = fmt.Sprintf("ignoring the remembered application for %s as %s", mime, warnings[len(warnings)-1])
	}
	if r.Settings.Use_system_defaults {
		if e := r.DB.DefaultAppFor(mime); e != nil {
			return Resolution{Choice: Choice{DesktopID: e.ID}, Source: "system_default"}, true, warnings
		}
	}
	return
}
