package utils

import (
	"os"
	"os/user"
	"path/filepath"
	"runtime"
	"strings"
)

func Expanduser(path string) string {
	if !strings.HasPrefix(path, "~") {
		return path
	}
	home, err := os.UserHomeDir()
	if err != nil {
		usr, err := user.Current()
		if err == nil {
			home = usr.HomeDir
		}
	}
	if err != nil || home == "" {
		return path
	}
	if path == "~" {
		return home
	}
	path = strings.ReplaceAll(path, string(os.PathSeparator), "/")
	parts := strings.Split(path, "/")
	if parts[0] == "~" {
		parts[0] = home
	} else {
		uname := parts[0][1:]
		if uname != "" {
			u, err := user.Lookup(uname)
			if err == nil && u.HomeDir != "" {
				parts[0] = u.HomeDir
			}
		}
	}
	return strings.Join(parts, string(os.PathSeparator))
}

func Abspath(path string) string {
	q, err := filepath.Abs(path)
	if err == nil {
		return q
	}
	return path
}

var config_dir string

func ConfigDir() string {
	if config_dir != "" {
		return config_dir
	}
	if os.Getenv("KITTY_CONFIG_DIRECTORY") != "" {
		config_dir = Abspath(Expanduser(os.Getenv("KITTY_CONFIG_DIRECTORY")))
	} else {
		var locations []string
		if os.Getenv("XDG_CONFIG_HOME") != "" {
			locations = append(locations, os.Getenv("XDG_CACHE_HOME"))
		}
		locations = append(locations, Expanduser("~/.config"))
		if runtime.GOOS == "darwin" {
			locations = append(locations, Expanduser("~/Library/Preferences"))
		}
		for _, loc := range locations {
			if loc != "" {
				q := filepath.Join(loc, "kitty")
				if _, err := os.Stat(filepath.Join(q, "kitty.conf")); err == nil {
					config_dir = q
					break
				}
			}
		}
		for _, loc := range locations {
			if loc != "" {
				config_dir = filepath.Join(loc, "kitty")
				break
			}
		}
	}

	return config_dir
}
