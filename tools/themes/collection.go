// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"archive/zip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"kitty/tools/utils"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

var _ = fmt.Print

type JSONMetadata struct {
	Etag      string `json:"etag"`
	Timestamp string `json:"timestamp"`
}

var ErrNoCacheFound = errors.New("No cache found and max cache age is negative")

func fetch_cached(name, url string, max_cache_age time.Duration) (string, error) {
	cache_path := filepath.Join(utils.CacheDir(), name+".zip")
	zf, err := zip.OpenReader(cache_path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return "", err
	}
	var jm JSONMetadata
	err = json.Unmarshal(utils.UnsafeStringToBytes(zf.Comment), &jm)
	if err == nil {
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
	return fetch_cached("kitty-themes", "https://codeload.github.com/kovidgoyal/kitty-themes/zip/master", max_cache_age)
}
