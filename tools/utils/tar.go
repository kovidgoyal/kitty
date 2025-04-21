// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"archive/tar"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

var _ = fmt.Print

type TarExtractOptions struct {
	DontPreservePermissions bool
}

func volnamelen(path string) int {
	return len(filepath.VolumeName(path))
}

func EvalSymlinksThatExist(path string) (string, error) {
	volLen := volnamelen(path)
	pathSeparator := string(os.PathSeparator)

	if volLen < len(path) && os.IsPathSeparator(path[volLen]) {
		volLen++
	}
	vol := path[:volLen]
	dest := vol
	linksWalked := 0
	for start, end := volLen, volLen; start < len(path); start = end {
		for start < len(path) && os.IsPathSeparator(path[start]) {
			start++
		}
		end = start
		for end < len(path) && !os.IsPathSeparator(path[end]) {
			end++
		}

		// On Windows, "." can be a symlink.
		// We look it up, and use the value if it is absolute.
		// If not, we just return ".".
		isWindowsDot := runtime.GOOS == "windows" && path[volnamelen(path):] == "."

		// The next path component is in path[start:end].
		if end == start {
			// No more path components.
			break
		} else if path[start:end] == "." && !isWindowsDot {
			// Ignore path component ".".
			continue
		} else if path[start:end] == ".." {
			// Back up to previous component if possible.
			// Note that volLen includes any leading slash.

			// Set r to the index of the last slash in dest,
			// after the volume.
			var r int
			for r = len(dest) - 1; r >= volLen; r-- {
				if os.IsPathSeparator(dest[r]) {
					break
				}
			}
			if r < volLen || dest[r+1:] == ".." {
				// Either path has no slashes
				// (it's empty or just "C:")
				// or it ends in a ".." we had to keep.
				// Either way, keep this "..".
				if len(dest) > volLen {
					dest += pathSeparator
				}
				dest += ".."
			} else {
				// Discard everything since the last slash.
				dest = dest[:r]
			}
			continue
		}

		// Ordinary path component. Add it to result.

		if len(dest) > volnamelen(dest) && !os.IsPathSeparator(dest[len(dest)-1]) {
			dest += pathSeparator
		}

		dest += path[start:end]

		// Resolve symlink.

		fi, err := os.Lstat(dest)
		if err != nil {
			if os.IsNotExist(err) {
				if end < len(path) {
					dest += path[end:]
				}
				return filepath.Clean(dest), nil
			}
			return "", err
		}

		if fi.Mode()&fs.ModeSymlink == 0 {
			if !fi.Mode().IsDir() && end < len(path) {
				return "", fmt.Errorf("%s is not a directory while resolving symlinks in %s", dest, path)
			}
			continue
		}

		// Found symlink.

		linksWalked++
		if linksWalked > 255 {
			return "", fmt.Errorf("EvalSymlinksThatExist: too many symlinks in %s", path)
		}

		link, err := os.Readlink(dest)
		if err != nil {
			return "", err
		}

		if isWindowsDot && !filepath.IsAbs(link) {
			// On Windows, if "." is a relative symlink,
			// just return ".".
			break
		}

		path = link + path[end:]

		v := volnamelen(link)
		if v > 0 {
			// Symlink to drive name is an absolute path.
			if v < len(link) && os.IsPathSeparator(link[v]) {
				v++
			}
			vol = link[:v]
			dest = vol
			end = len(vol)
		} else if len(link) > 0 && os.IsPathSeparator(link[0]) {
			// Symlink to absolute path.
			dest = link[:1]
			end = 1
			vol = link[:1]
			volLen = 1
		} else {
			// Symlink to relative path; replace last
			// path component in dest.
			var r int
			for r = len(dest) - 1; r >= volLen; r-- {
				if os.IsPathSeparator(dest[r]) {
					break
				}
			}
			if r < volLen {
				dest = vol
			} else {
				dest = dest[:r]
			}
			end = 0
		}
	}
	return filepath.Clean(dest), nil
}

func ExtractAllFromTar(tr *tar.Reader, dest_path string, optss ...TarExtractOptions) (count int, err error) {
	opts := TarExtractOptions{}
	if len(optss) > 0 {
		opts = optss[0]
	}
	if !filepath.IsAbs(dest_path) {
		if dest_path, err = filepath.Abs(dest_path); err != nil {
			return
		}
	}
	if dest_path, err = filepath.EvalSymlinks(dest_path); err != nil {
		return
	}
	dest_path = filepath.Clean(dest_path)

	mode := func(hdr int64) fs.FileMode {
		return fs.FileMode(hdr) & (fs.ModePerm | fs.ModeSetgid | fs.ModeSetuid | fs.ModeSticky)
	}

	set_metadata := func(chmod func(mode fs.FileMode) error, hdr_mode int64) (err error) {
		if !opts.DontPreservePermissions && chmod != nil {
			perms := mode(hdr_mode)
			if err = chmod(perms); err != nil {
				return err
			}
		}
		count++
		return
	}
	needed_prefix := dest_path + string(os.PathSeparator)

	for {
		var hdr *tar.Header
		hdr, err = tr.Next()
		if errors.Is(err, io.EOF) {
			err = nil
			break
		}
		if err != nil {
			return count, err
		}
		dest := hdr.Name
		if !filepath.IsAbs(dest) {
			dest = filepath.Join(dest_path, dest)
		}
		if dest, err = EvalSymlinksThatExist(dest); err != nil {
			return count, err
		}
		if !strings.HasPrefix(dest, needed_prefix) {
			continue
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			err = os.MkdirAll(dest, 0o700)
			if err != nil {
				return
			}
			if err = set_metadata(func(m fs.FileMode) error { return os.Chmod(dest, m) }, hdr.Mode); err != nil {
				return
			}
		case tar.TypeReg:
			var d *os.File
			if err = os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
				return
			}
			if d, err = os.Create(dest); err != nil {
				return
			}
			err = set_metadata(d.Chmod, hdr.Mode)
			if err == nil {
				_, err = io.Copy(d, tr)
			}
			d.Close()
			if err != nil {
				return
			}
		case tar.TypeLink:
			if err = os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
				return
			}
			link_target := hdr.Linkname
			if !filepath.IsAbs(link_target) {
				link_target = filepath.Join(filepath.Dir(dest), link_target)
			}
			if err = os.Link(link_target, dest); err != nil {
				return
			}
			if err = set_metadata(func(m fs.FileMode) error { return os.Chmod(dest, m) }, hdr.Mode); err != nil {
				return
			}
		case tar.TypeSymlink:
			if err = os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
				return
			}
			link_target := hdr.Linkname
			if !filepath.IsAbs(link_target) {
				link_target = filepath.Join(filepath.Dir(dest), link_target)
			}
			// We dont care about the link target being outside dest_path as
			// we use EvalSymlinks on dest, so a symlink pointing outside
			// dest_path cannot cause writes outside dest_path.
			if err = os.Symlink(link_target, dest); err != nil {
				return
			}
			if err = set_metadata(nil, hdr.Mode); err != nil {
				return
			}
		}
	}
	return
}
