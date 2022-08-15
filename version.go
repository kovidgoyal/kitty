package kitty

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"runtime/debug"
	"strconv"
	"strings"
)

//go:embed kitty/constants.py
var raw string

type VersionType struct {
	major, minor, patch int
}

var VersionString string
var Version VersionType
var VCSRevision string
var WebsiteBaseUrl string
var DefaultPager []string

func init() {
	verpat := regexp.MustCompile(`Version\((\d+),\s*(\d+),\s*(\d+)\)`)
	matches := verpat.FindStringSubmatch(raw)
	major, err := strconv.Atoi(matches[1])
	minor, err := strconv.Atoi(matches[2])
	patch, err := strconv.Atoi(matches[3])
	if err != nil {
		panic(err)
	}
	Version.major = major
	Version.minor = minor
	Version.patch = patch
	VersionString = fmt.Sprint(major, ".", minor, ".", patch)
	bi, ok := debug.ReadBuildInfo()
	if ok {
		for _, bs := range bi.Settings {
			if bs.Key == "vcs.revision" {
				VCSRevision = bs.Value
			}
		}
	}
	website_pat := regexp.MustCompile(`website_base_url\s+=\s+['"](.+?)['"]`)
	matches = website_pat.FindStringSubmatch(raw)
	WebsiteBaseUrl = matches[1]
	if matches[1] == "" {
		panic(fmt.Errorf("Failed to find the website base url"))
	}
	pager_pat := regexp.MustCompile(`default_pager_for_help\s+=\s+\((.+?)\)`)
	matches = pager_pat.FindStringSubmatch(raw)
	if matches[1] == "" {
		panic(fmt.Errorf("Failed to find the default_pager_for_help"))
	}
	text := strings.ReplaceAll("[" + matches[1] + "]", "'", "\"")
	err = json.Unmarshal([]byte(text), &DefaultPager)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Failed to unmarshal default pager text:", text)
		panic(err)
	}
}
