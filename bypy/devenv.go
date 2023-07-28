// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

const folder = "dependencies"

var _ = fmt.Print

func exit(x any) {
	switch v := x.(type) {
	case error:
		if v == nil {
			os.Exit(0)
		}
		var ee *exec.ExitError
		if errors.As(v, &ee) {
			os.Exit(ee.ExitCode())
		}
	case string:
		if v == "" {
			os.Exit(0)
		}
	case int:
		os.Exit(v)
	}
	fmt.Fprintf(os.Stderr, "\x1b[31mError\x1b[m: %s\n", x)
	os.Exit(1)
}

// download deps {{{
func cached_download(url string) string {
	fname := filepath.Base(url)
	fmt.Println("Downloading", fname)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		exit(err)
	}
	if etag, err := os.ReadFile(filepath.Join(folder, "etag")); err == nil {
		if _, err := os.Stat(filepath.Join(folder, fname)); err == nil {
			req.Header.Add("If-None-Match", string(etag))
		}
	}

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		exit(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		if resp.StatusCode == http.StatusNotModified {
			return filepath.Join(folder, fname)
		}
		exit(fmt.Errorf("The server responded with the HTTP error: %s", resp.Status))
	}
	f, err := os.Create(filepath.Join(folder, fname))
	if err != nil {
		exit(err)
	}
	defer f.Close()
	if _, err := io.Copy(f, resp.Body); err != nil {
		exit(fmt.Errorf("Failed to download file with error: %w", err))
	}
	if etag := resp.Header.Get("ETag"); etag != "" {
		if err := os.WriteFile(filepath.Join(folder, "etag"), []byte(etag), 0o644); err != nil {
			exit(err)
		}
	}
	return f.Name()
}

func relocate_pkgconfig(path, old_prefix, new_prefix string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	nraw := bytes.ReplaceAll(raw, []byte(old_prefix), []byte(new_prefix))
	return os.WriteFile(path, nraw, 0o644)
}

func chdir_to_base() {
	_, filename, _, _ := runtime.Caller(0)
	base_dir := filepath.Dir(filepath.Dir(filename))
	if err := os.Chdir(base_dir); err != nil {
		exit(err)
	}
}
func dependencies(args []string) {
	chdir_to_base()
	data, err := os.ReadFile(".github/workflows/ci.py")
	if err != nil {
		exit(err)
	}
	pat := regexp.MustCompile("BUNDLE_URL = '(.+?)'")
	prefix := "/sw/sw"
	var url string
	if m := pat.FindStringSubmatch(string(data)); len(m) < 2 {
		exit("Failed to find BUNDLE_URL in ci.py")
	} else {
		url = m[1]
	}
	var which string
	switch runtime.GOOS {
	case "darwin":
		prefix = "/Users/Shared/kitty-build/sw/sw"
		which = "macos"
	case "linux":
		which = "linux"
		if runtime.GOARCH != "amd64" {
			exit("Pre-built dependencies are only available for the amd64 CPU architecture")
		}
	}
	if which == "" {
		exit("Prebuilt dependencies are only available for Linux and macOS")
	}
	url = strings.Replace(url, "{}", which, 1)
	if err := os.RemoveAll(filepath.Join(folder, "root")); err != nil {
		exit(err)
	}
	if err := os.MkdirAll(folder, 0o755); err != nil {
		exit(err)
	}
	tarfile, _ := filepath.Abs(cached_download(url))
	root, _ := filepath.Abs(filepath.Join(folder, "root"))
	if err := os.MkdirAll(root, 0o755); err != nil {
		exit(err)
	}
	cmd := exec.Command("tar", "xf", tarfile)
	cmd.Dir = root
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err = cmd.Run(); err != nil {
		exit(err)
	}
	if err = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.Type().IsRegular() {
			name := d.Name()
			ext := filepath.Ext(name)
			if ext == ".pc" || (ext == ".py" && strings.HasPrefix(name, "_sysconfigdata_")) {
				err = relocate_pkgconfig(path, prefix, root)
			}
			// remove libfontconfig so that we use the system one because
			// different distros stupidly use different fontconfig configuration dirs
			if strings.HasPrefix(name, "libfontconfig.so") {
				os.Remove(path)
			}
		}
		return err
	}); err != nil {
		exit(err)
	}
	fmt.Println(`Dependencies downloaded. Now build kitty with: make develop`)
}

// }}}

func prepend(env_var, path string) {
	val := os.Getenv(env_var)
	if val != "" {
		val = string(filepath.ListSeparator) + val
	}
	os.Setenv(env_var, path+val)
}

func build(args []string) {
	chdir_to_base()
	if _, err := os.Stat(folder); err != nil {
		dependencies(nil)
	}
	python := ""
	root, _ := filepath.Abs(filepath.Join(folder, "root"))
	os.Setenv("DEVELOP_ROOT", root)
	prepend("PKG_CONFIG_PATH", filepath.Join(root, "lib", "pkgconfig"))
	switch runtime.GOOS {
	case "linux":
		prepend("LD_LIBRARY_PATH", filepath.Join(root, "lib"))
		os.Setenv("PYTHONHOME", root)
		python = filepath.Join(root, "bin", "python")
	default:
		exit("Building is only supported on Linux and macOS")
	}
	cmd := exec.Command(python, "setup.py", "develop", "--debug")
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "The following build command failed:", python, strings.Join(args, " "))
		exit(err)
	}
	fmt.Println("Build successful. Run kitty as: kitty/launcher/kitty")
}

func main() {
	if len(os.Args) < 2 {
		exit(`Expected "deps" or "build" subcommands`)
	}
	switch os.Args[1] {
	case "deps":
		dependencies(os.Args[2:])
	case "build":
		build(os.Args[2:])
	default:
		exit(`Expected "deps" or "build" subcommands`)
	}
}
