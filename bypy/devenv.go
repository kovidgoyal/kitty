// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"bufio"
	"bytes"
	"errors"
	"flag"
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

const (
	folder                     = "dependencies"
	fonts_folder               = "fonts"
	macos_prefix               = "/Users/Shared/kitty-build/sw/sw"
	macos_python               = "python/Python.framework/Versions/Current/bin/python3"
	macos_python_framework     = "python/Python.framework/Versions/Current/Python"
	macos_python_framework_exe = "python/Python.framework/Versions/Current/Resources/Python.app/Contents/MacOS/Python"
	NERD_URL                   = "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/NerdFontsSymbolsOnly.tar.xz"
)

func root_dir() string {
	f, e := filepath.Abs(filepath.Join(folder, runtime.GOOS+"-"+runtime.GOARCH))
	if e != nil {
		exit(e)
	}
	return f
}

func fonts_dir() string {
	f, e := filepath.Abs(fonts_folder)
	if e != nil {
		exit(e)
	}
	return f
}

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

type dependency struct {
	path     string
	basename string
	is_id    bool
}

func lines(exe string, cmd ...string) []string {
	c := exec.Command(exe, cmd...)
	c.Stderr = os.Stderr
	out, err := c.Output()
	if err != nil {
		exit(fmt.Errorf("Failed to run '%s' with error: %w", strings.Join(append([]string{exe}, cmd...), " "), err))
	}
	ans := []string{}
	for s := bufio.NewScanner(bytes.NewReader(out)); s.Scan(); {
		ans = append(ans, s.Text())
	}
	return ans
}

func get_dependencies(path string) (ans []dependency) {
	a := lines("otool", "-D", path)
	install_name := strings.TrimSpace(a[len(a)-1])
	for _, line := range lines("otool", "-L", path) {
		line = strings.TrimSpace(line)
		if strings.Contains(line, "compatibility") && !strings.HasSuffix(line, ":") {
			idx := strings.IndexByte(line, '(')
			dep := strings.TrimSpace(line[:idx])
			ans = append(ans, dependency{path: dep, is_id: dep == install_name})
		}
	}
	return
}

func get_local_dependencies(path string) (ans []dependency) {
	for _, dep := range get_dependencies(path) {
		for _, y := range []string{filepath.Join(macos_prefix, "lib") + "/", filepath.Join(macos_prefix, "python", "Python.framework") + "/", "@rpath/"} {
			if strings.HasPrefix(dep.path, y) {
				if y == "@rpath/" {
					dep.basename = "lib/" + dep.path[len(y):]
				} else {
					y = macos_prefix + "/"
					dep.basename = dep.path[len(y):]
				}
				ans = append(ans, dep)
				break
			}
		}
	}
	return
}

func change_dep(path string, dep dependency) {
	cmd := []string{}
	fid := filepath.Join(root_dir(), dep.basename)
	if dep.is_id {
		cmd = append(cmd, "-id", fid)
	} else {
		cmd = append(cmd, "-change", dep.path, fid)
	}
	cmd = append(cmd, path)
	c := exec.Command("install_name_tool", cmd...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	if err := c.Run(); err != nil {
		exit(fmt.Errorf("Failed to run command '%s' with error: %w", strings.Join(c.Args, " "), err))
	}
}

func fix_dependencies_in_lib(path string) {
	path, err := filepath.EvalSymlinks(path)
	if err != nil {
		exit(err)
	}
	if s, err := os.Stat(path); err != nil {
		exit(err)
	} else if err := os.Chmod(path, s.Mode().Perm()|0o200); err != nil {
		exit(err)
	}
	for _, dep := range get_local_dependencies(path) {
		change_dep(path, dep)
	}
	if ldeps := get_local_dependencies(path); len(ldeps) > 0 {
		exit(fmt.Errorf("Failed to fix local dependencies in: %s", path))
	}
}

func cached_download(url string) string {
	fname := filepath.Base(url)
	fmt.Println("Downloading", fname)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		exit(err)
	}
	etag_file := filepath.Join(folder, fname+".etag")
	if etag, err := os.ReadFile(etag_file); err == nil {
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
		if err := os.WriteFile(etag_file, []byte(etag), 0o644); err != nil {
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

func dependencies_for_docs() {
	fmt.Println("Downloading get-pip.py")
	rq, err := http.Get("https://bootstrap.pypa.io/get-pip.py")
	if err != nil {
		exit(err)
	}
	defer rq.Body.Close()
	if rq.StatusCode != http.StatusOK {
		exit(fmt.Errorf("Server responded with HTTP error: %s", rq.Status))
	}
	gp, err := os.Create(filepath.Join(folder, "get-pip.py"))
	if err != nil {
		exit(err)
	}
	defer gp.Close()
	if _, err = io.Copy(gp, rq.Body); err != nil {
		exit(err)
	}
	python := setup_to_run_python()

	run := func(exe string, args ...string) {
		c := exec.Command(exe, args...)
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		if err := c.Run(); err != nil {
			exit(err)
		}
	}
	run(python, gp.Name())
	run(python, "-m", "pip", "install", "-r", "docs/requirements.txt")
}

func dependencies(args []string) {
	chdir_to_base()
	nf := flag.NewFlagSet("deps", flag.ExitOnError)
	docsptr := nf.Bool("for-docs", false, "download the dependencies needed to build the documentation")
	if err := nf.Parse(args); err != nil {
		exit(err)
	}
	if *docsptr {
		dependencies_for_docs()
		fmt.Println("Dependencies needed to generate documentation have been installed. Build docs with ./dev.sh docs")
		exit(0)
	}
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
		prefix = macos_prefix
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
	if err := os.RemoveAll(root_dir()); err != nil {
		exit(err)
	}
	if err := os.MkdirAll(folder, 0o755); err != nil {
		exit(err)
	}
	tarfile, _ := filepath.Abs(cached_download(url))
	root := root_dir()
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
	if runtime.GOOS == "darwin" {
		fix_dependencies_in_lib(filepath.Join(root, macos_python))
		fix_dependencies_in_lib(filepath.Join(root, macos_python_framework))
		fix_dependencies_in_lib(filepath.Join(root, macos_python_framework_exe))
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
			if runtime.GOOS == "darwin" {
				if ext == ".so" || ext == ".dylib" {
					fix_dependencies_in_lib(path)
				}
			}
		}
		return err
	}); err != nil {
		exit(err)
	}
	tarfile, _ = filepath.Abs(cached_download(NERD_URL))
	root = fonts_dir()
	if err := os.MkdirAll(root, 0o755); err != nil {
		exit(err)
	}
	cmd = exec.Command("tar", "xf", tarfile, "SymbolsNerdFontMono-Regular.ttf")
	cmd.Dir = root
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err = cmd.Run(); err != nil {
		exit(err)
	}

	fmt.Println(`Dependencies downloaded. Now build kitty with: ./dev.sh build`)
}

// }}}

func prepend(env_var, path string) {
	val := os.Getenv(env_var)
	if val != "" {
		val = string(filepath.ListSeparator) + val
	}
	os.Setenv(env_var, path+val)
}

func setup_to_run_python() (python string) {
	root := root_dir()
	for _, x := range os.Environ() {
		if strings.HasPrefix(x, "PYTHON") {
			a, _, _ := strings.Cut(x, "=")
			os.Unsetenv(a)
		}
	}
	switch runtime.GOOS {
	case "linux":
		prepend("LD_LIBRARY_PATH", filepath.Join(root, "lib"))
		os.Setenv("PYTHONHOME", root)
		python = filepath.Join(root, "bin", "python")
	case `darwin`:
		python = filepath.Join(root, macos_python)
	default:
		exit("Building is only supported on Linux and macOS")
	}
	return
}

func build(args []string) {
	chdir_to_base()
	if _, err := os.Stat(folder); err != nil {
		dependencies(nil)
	}
	root := root_dir()
	os.Setenv("DEVELOP_ROOT", root)
	prepend("PKG_CONFIG_PATH", filepath.Join(root, "lib", "pkgconfig"))
	if runtime.GOOS == "darwin" {
		os.Setenv("PKGCONFIG_EXE", filepath.Join(root, "bin", "pkg-config"))
	}
	python := setup_to_run_python()
	args = append([]string{"setup.py", "develop"}, args...)
	cmd := exec.Command(python, args...)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "The following build command failed:", python, strings.Join(args, " "))
		exit(err)
	}
	fmt.Println("Build successful. Run kitty as: kitty/launcher/kitty")
}

func docs(args []string) {
	setup_to_run_python()
	nf := flag.NewFlagSet("deps", flag.ExitOnError)
	livereload := nf.Bool("live-reload", false, "build the docs and make them available via s local server with live reloading for ease of development")
	failwarn := nf.Bool("fail-warn", false, "make warnings fatal when building the docs")
	if err := nf.Parse(args); err != nil {
		exit(err)
	}
	exe := filepath.Join(root_dir(), "bin", "sphinx-build")
	aexe := filepath.Join(root_dir(), "bin", "sphinx-autobuild")
	target := "docs"

	if *livereload {
		target = "develop-docs"
	}
	cmd := []string{target, "SPHINXBUILD=" + exe, "SPHINXAUTOBUILD=" + aexe}
	if *failwarn {
		cmd = append(cmd, "FAILWARN=1")
	}
	c := exec.Command("make", cmd...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	err := c.Run()
	if err != nil {
		exit(err)
	}
	fmt.Println("docs successfully built")
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
	case "docs":
		docs(os.Args[2:])
	case "-h", "--help":
		fmt.Fprintln(os.Stderr, "Usage: ./dev.sh [build|deps|docs] [options...]")
	default:
		exit(`Expected "deps" or "build" subcommands`)
	}
}
