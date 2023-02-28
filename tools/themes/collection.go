// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"archive/zip"
	"bufio"
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
	"strconv"
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

func parse_theme_metadata(path string) (*ThemeMetadata, map[string]string, error) {
	var in_metadata, in_blurb, finished_metadata bool
	ans := ThemeMetadata{}
	settings := map[string]string{}
	read_is_dark := func(key, val string) (err error) {
		settings[key] = val
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
	cp := config.ConfigParser{LineHandler: read_is_dark, CommentsHandler: read_metadata}
	err := cp.ParseFiles(path)
	if err != nil {
		return nil, nil, err
	}
	ans.Num_settings = len(settings)
	return &ans, settings, nil
}

type Theme struct {
	metadata *ThemeMetadata

	code            string
	settings        map[string]string
	zip_reader      *zip.File
	is_user_defined bool
}

func (self *Theme) load_code() (string, error) {
	if self.zip_reader != nil {
		f, err := self.zip_reader.Open()
		self.zip_reader = nil
		if err != nil {
			return "", err
		}
		defer f.Close()
		data, err := io.ReadAll(f)
		if err != nil {
			return "", err
		}
		self.code = utils.UnsafeBytesToString(data)
	}
	return self.code, nil
}

func (self *Theme) Settings() (map[string]string, error) {
	if self.zip_reader != nil {
		code, err := self.load_code()
		if err != nil {
			return nil, err
		}
		self.settings = make(map[string]string, 64)
		scanner := bufio.NewScanner(strings.NewReader(code))
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line != "" && line[0] != '#' {
				key, val, found := strings.Cut(line, " ")
				if found {
					self.settings[key] = val
				}
			}
		}
	}
	return self.settings, nil
}

func (self *Theme) AsEscapeCodes() (string, error) {
	settings, err := self.Settings()
	if err != nil {
		return "", err
	}
	w := strings.Builder{}
	w.Grow(4096)

	set_color := func(i int, sharp string) {
		w.WriteByte(';')
		w.WriteString(strconv.Itoa(i))
		w.WriteByte(';')
		w.WriteString(sharp)
	}

	set_default_color := func(name, defval string, num int) {
		w.WriteString("\033]")
		defer func() { w.WriteString("\033\\") }()
		val, found := settings[name]
		if !found {
			val = defval
		}
		if val != "" {
			rgba, err := style.ParseColor(val)
			if err == nil {
				w.WriteString(strconv.Itoa(num))
				w.WriteByte(';')
				w.WriteString(rgba.AsRGBSharp())
				return
			}
		}
		w.WriteByte('1')
		w.WriteString(strconv.Itoa(num))
	}
	set_default_color("foreground", style.DefaultColors.Foreground, 10)
	set_default_color("background", style.DefaultColors.Background, 11)
	set_default_color("cursor", style.DefaultColors.Cursor, 12)
	set_default_color("selection_background", style.DefaultColors.SelectionBg, 17)
	set_default_color("selection_foreground", style.DefaultColors.SelectionFg, 19)

	w.WriteString("\033]4")
	for i := 0; i < 256; i++ {
		key := "color" + strconv.Itoa(i)
		val := settings[key]
		if val != "" {
			rgba, err := style.ParseColor(val)
			if err == nil {
				set_color(i, rgba.AsRGBSharp())
				continue
			}
		}
		rgba := style.RGBA{}
		rgba.FromRGB(style.ColorTable[i])
		set_color(i, rgba.AsRGBSharp())
	}
	w.WriteString("\033\\")
	return w.String(), nil
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

func (self *Themes) AddFromFile(path string) (*Theme, error) {
	m, conf, err := parse_theme_metadata(path)
	if err != nil {
		return nil, err
	}
	if m.Name == "" {
		m.Name = theme_name_from_file_name(filepath.Base(path))
	}
	t := Theme{metadata: m, is_user_defined: true, settings: conf}
	self.name_map[m.Name] = &t
	return &t, nil

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
			if _, err = self.AddFromFile(filepath.Join(dirpath, e.Name())); err != nil {
				return err
			}
		}
	}
	return nil
}

func (self *Themes) add_from_zip_file(zippath string) (io.Closer, error) {
	r, err := zip.OpenReader(zippath)
	if err != nil {
		return nil, err
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
				return nil, fmt.Errorf("Error while opening %s from the ZIP file: %w", file.Name, err)
			}
			defer fr.Close()
			raw, err := io.ReadAll(fr)
			if err != nil {
				return nil, fmt.Errorf("Error while reading %s from the ZIP file: %w", file.Name, err)
			}
			err = json.Unmarshal(raw, &themes)
			if err != nil {
				return nil, fmt.Errorf("Error while decoding %s: %w", file.Name, err)
			}
		}
	}
	if theme_dir == "" {
		return nil, fmt.Errorf("No themes.json found in ZIP file")
	}
	for _, theme := range themes {
		key := path.Join(theme_dir, theme.Filepath)
		f := name_map[key]
		if f != nil {
			t := Theme{metadata: &theme, zip_reader: f}
			self.name_map[theme.Name] = &t
		}
	}
	return r, nil
}

func (self *Themes) ThemeByName(name string) *Theme {
	return self.name_map[name]
}

func LoadThemes(cache_age time.Duration) (ans *Themes, closer io.Closer, err error) {
	zip_path, err := FetchCached(cache_age)
	ans = &Themes{name_map: make(map[string]*Theme)}
	if err != nil {
		return nil, nil, err
	}
	if closer, err = ans.add_from_zip_file(zip_path); err != nil {
		return nil, nil, err
	}
	if err = ans.add_from_dir(filepath.Join(utils.ConfigDir(), "themes")); err != nil {
		return nil, nil, err
	}
	ans.index_map = maps.Keys(ans.name_map)
	ans.index_map = utils.StableSortWithKey(ans.index_map, strings.ToLower)
	return ans, closer, nil
}

func ThemeFromFile(path string) (*Theme, error) {
	ans := &Themes{name_map: make(map[string]*Theme)}
	return ans.AddFromFile(path)
}
