package kitty

import (
	_ "embed"
	"fmt"
	"regexp"
	"runtime/debug"
	"strconv"
)

//go:embed kitty/constants.py
var raw string

type VersionType struct {
	major, minor, patch int
}

var VersionString string
var Version VersionType
var VCSRevision string

func init() {
	var verpat = regexp.MustCompile(`Version\((\d+),\s*(\d+),\s*(\d+)\)`)
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

}
