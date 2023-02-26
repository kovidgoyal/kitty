// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"archive/zip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"kitty/tools/config"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"golang.org/x/exp/maps"
)

var _ = fmt.Print

type JSONMetadata struct {
	Etag      string `json:"etag"`
	Timestamp string `json:"timestamp"`
}

var ErrNoCacheFound = errors.New("No cache found and max cache age is negative")

func fetch_cached(name, url, cache_path string, max_cache_age time.Duration) (string, error) {
	cache_path = filepath.Join(cache_path, name+".zip")
	zf, err := zip.OpenReader(cache_path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return "", err
	}

	var jm JSONMetadata
	if err == nil {
		err = json.Unmarshal(utils.UnsafeStringToBytes(zf.Comment), &jm)
		if max_cache_age < 0 {
			return cache_path, nil
		}
		cache_age, err := utils.ISO8601Parse(jm.Timestamp)
		if err == nil {
			if time.Now().Before(cache_age.Add(max_cache_age)) {
				return cache_path, nil
			}
		}
	}
	if max_cache_age < 0 {
		return "", ErrNoCacheFound
	}
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	if jm.Etag != "" {
		req.Header.Add("If-None-Match", jm.Etag)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("Failed to download %s with error: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		if resp.StatusCode == http.StatusNotModified {
			return cache_path, nil
		}
		return "", fmt.Errorf("Failed to download %s with HTTP error: %s", url, resp.Status)
	}
	var tf, tf2 *os.File
	tf, err = os.CreateTemp(filepath.Dir(cache_path), name+".temp-*")
	if err == nil {
		tf2, err = os.CreateTemp(filepath.Dir(cache_path), name+".temp-*")
	}
	defer func() {
		if tf != nil {
			tf.Close()
			os.Remove(tf.Name())
			tf = nil
		}
		if tf2 != nil {
			tf2.Close()
			os.Remove(tf2.Name())
			tf2 = nil
		}
	}()
	if err != nil {
		return "", fmt.Errorf("Failed to create temp file in %s with error: %w", filepath.Dir(cache_path), err)
	}
	_, err = io.Copy(tf, resp.Body)
	if err != nil {
		return "", fmt.Errorf("Failed to download %s with error: %w", url, err)
	}
	r, err := zip.OpenReader(tf.Name())
	if err != nil {
		return "", fmt.Errorf("Failed to open downloaded zip file with error: %w", err)
	}
	w := zip.NewWriter(tf2)
	jm.Etag = resp.Header.Get("ETag")
	jm.Timestamp = utils.ISO8601Format(time.Now())
	comment, _ := json.Marshal(jm)
	w.SetComment(utils.UnsafeBytesToString(comment))
	for _, file := range r.File {
		err = w.Copy(file)
		if err != nil {
			return "", fmt.Errorf("Failed to copy zip file from source to destination archive")
		}
	}
	err = w.Close()
	if err != nil {
		return "", err
	}
	tf2.Close()
	err = os.Rename(tf2.Name(), cache_path)
	if err != nil {
		return "", fmt.Errorf("Failed to atomic rename temp file to %s with error: %w", cache_path, err)
	}
	tf2 = nil
	return cache_path, nil
}

func FetchCached(max_cache_age time.Duration) (string, error) {
	return fetch_cached("kitty-themes", "https://codeload.github.com/kovidgoyal/kitty-themes/zip/master", utils.CacheDir(), max_cache_age)
}

type ThemeMetadata struct {
	Name         string `json:"name"`
	Filepath     string `json:"file"`
	Is_dark      bool   `json:"is_dark"`
	Num_settings int    `json:"num_settings"`
	Blurb        string `json:"blurb"`
	License      string `json:"license"`
	Upstream     string `json:"upstream"`
	Author       string `json:"author"`
}

func parse_theme_metadata(path string) (*ThemeMetadata, string, error) {
	var in_metadata, in_blurb, finished_metadata bool
	ans := ThemeMetadata{}
	settings := utils.NewSet[string]()
	read_is_dark := func(key, val string) (err error) {
		settings.Add(key)
		if key == "background" {
			val = strings.TrimSpace(val)
			if val != "" {
				bg, err := style.ParseColor(val)
				if err == nil {
					ans.Is_dark = utils.Max(bg.Red, bg.Green, bg.Green) < 115
				}
			}
		}
		return
	}
	read_metadata := func(line string) (err error) {
		is_block := strings.HasPrefix(line, "## ")
		if in_metadata && !is_block {
			finished_metadata = true
		}
		if finished_metadata {
			return
		}
		if !in_metadata && is_block {
			in_metadata = true
		}
		if !in_metadata {
			return
		}
		line = line[3:]
		if in_blurb {
			ans.Blurb += " " + line
			return
		}
		key, val, found := strings.Cut(line, ":")
		if !found {
			return
		}
		key = strings.TrimSpace(strings.ToLower(key))
		val = strings.TrimSpace(val)
		switch key {
		case "name":
			ans.Name = val
		case "author":
			ans.Author = val
		case "upstream":
			ans.Upstream = val
		case "blurb":
			ans.Blurb = val
			in_blurb = true
		case "license":
			ans.License = val
		}
		return
	}
	source := ""
	cp := config.ConfigParser{LineHandler: read_is_dark, CommentsHandler: read_metadata, SourceHandler: func(code, path string) { source = code }}
	err := cp.ParseFiles(path)
	if err != nil {
		return nil, "", err
	}
	ans.Num_settings = settings.Len()
	return &ans, source, nil
}

type Theme struct {
	metadata *ThemeMetadata

	code            string
	zip_reader      *zip.File
	is_user_defined bool
}

type Themes struct {
	name_map  map[string]*Theme
	index_map []string
}

var camel_case_pat = (&utils.Once[*regexp.Regexp]{Run: func() *regexp.Regexp {
	return regexp.MustCompile(`([a-z])([A-Z])`)
}}).Get

func theme_name_from_file_name(fname string) string {
	fname = fname[:len(fname)-len(path.Ext(fname))]
	fname = strings.ReplaceAll(fname, "_", " ")
	fname = camel_case_pat().ReplaceAllString(fname, "$1 $2")
	return strings.Join(utils.Map(strings.Split(fname, " "), strings.Title), " ")
}

func (self *Themes) add_from_dir(dirpath string) error {
	entries, err := os.ReadDir(dirpath)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			err = nil
		}
		return err
	}
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".conf") {
			m, conf, err := parse_theme_metadata(filepath.Join(dirpath, e.Name()))
			if err != nil {
				return err
			}
			if m.Name == "" {
				m.Name = theme_name_from_file_name(e.Name())
			}
			t := Theme{metadata: m, is_user_defined: true, code: conf}
			self.name_map[m.Name] = &t
		}
	}
	return nil
}

func (self *Themes) add_from_zip_file(zippath string) error {
	r, err := zip.OpenReader(zippath)
	if err != nil {
		return err
	}
	name_map := make(map[string]*zip.File, len(r.File))
	var themes []ThemeMetadata
	theme_dir := ""
	for _, file := range r.File {
		name_map[file.Name] = file
		if path.Base(file.Name) == "themes.json" {
			theme_dir = path.Dir(file.Name)
			fr, err := file.Open()
			if err != nil {
				return fmt.Errorf("Error while opening %s from the ZIP file: %w", file.Name, err)
			}
			defer fr.Close()
			raw, err := io.ReadAll(fr)
			if err != nil {
				return fmt.Errorf("Error while reading %s from the ZIP file: %w", file.Name, err)
			}
			err = json.Unmarshal(raw, &themes)
			if err != nil {
				return fmt.Errorf("Error while decoding %s: %w", file.Name, err)
			}
		}
	}
	if theme_dir == "" {
		return fmt.Errorf("No themes.json found in ZIP file")
	}
	for _, theme := range themes {
		key := path.Join(theme_dir, theme.Filepath)
		f := name_map[key]
		if f != nil {
			t := Theme{metadata: &theme, zip_reader: f}
			self.name_map[theme.Name] = &t
		}
	}
	return nil
}

func LoadThemes(cache_age_in_days time.Duration, ignore_no_cache bool) (*Themes, error) {
	zip_path, err := FetchCached(cache_age_in_days * time.Hour * 24)
	ans := Themes{name_map: make(map[string]*Theme)}
	if err != nil {
		if !errors.Is(err, ErrNoCacheFound) || ignore_no_cache {
			return nil, err
		}
	} else {
		if err = ans.add_from_zip_file(zip_path); err != nil {
			return nil, err
		}
	}
	if err = ans.add_from_dir(filepath.Join(utils.ConfigDir(), "themes")); err != nil {
		return nil, err
	}
	ans.index_map = maps.Keys(ans.name_map)
	ans.index_map = utils.StableSortWithKey(ans.index_map, strings.ToLower)
	return &ans, nil
}
