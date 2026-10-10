// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"archive/tar"
	"context"
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
	DontPreserveSuidAndSgid bool
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

// Resolve symlinks in all but the last component of path
func eval_symlinks_in_parent(path string) (string, error) {
	parent, err := EvalSymlinksThatExist(filepath.Dir(path))
	if err != nil {
		return "", err
	}
	return filepath.Join(parent, filepath.Base(path)), nil
}

func is_symlink_path(path string) (bool, error) {
	st, err := os.Lstat(path)
	if err != nil {
		return false, err
	}
	return st.Mode()&fs.ModeSymlink != 0, nil
}

func remove_existing_non_dir(path string) error {
	st, err := os.Lstat(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		return err
	}
	if st.IsDir() {
		return fmt.Errorf("cannot replace the directory %s with a non-directory", path)
	}
	return os.Remove(path)
}

// Hardlink src to dest, falling back to copying if the hardlink cannot be
// created, for example, because the filesystem does not support hardlinks.
// If src is a symlink, dest becomes a copy of the symlink, since os.Link()
// follows symlinks on some platforms.
func link_or_copy(src, dest string) (is_symlink bool, err error) {
	st, err := os.Lstat(src)
	if err != nil {
		return false, err
	}
	if st.Mode()&fs.ModeSymlink != 0 {
		target, err := os.Readlink(src)
		if err != nil {
			return false, err
		}
		if !filepath.IsAbs(target) {
			target = filepath.Join(filepath.Dir(src), target)
		}
		return true, os.Symlink(target, dest)
	}
	if !st.Mode().IsRegular() {
		return false, fmt.Errorf("cannot hardlink %s to %s as it is not a regular file", dest, src)
	}
	link_err := os.Link(src, dest)
	if link_err == nil {
		return false, nil
	}
	s, err := os.Open(src)
	if err != nil {
		return false, errors.Join(link_err, err)
	}
	d, err := os.OpenFile(dest, os.O_WRONLY|os.O_CREATE|os.O_EXCL, st.Mode().Perm())
	if err != nil {
		s.Close()
		return false, errors.Join(link_err, err)
	}
	if err = CopyFileAndClose(context.Background(), s, d); err != nil {
		return false, errors.Join(link_err, err, os.Remove(dest))
	}
	return false, nil
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
		// yes, we really want to preserve sticky bits and setuid/setgid bits
		return fs.FileMode(hdr) & (fs.ModePerm | fs.ModeSetgid | fs.ModeSetuid | fs.ModeSticky)
	}

	set_metadata := func(chmod func(mode fs.FileMode) error, hdr_mode int64) (err error) {
		if !opts.DontPreservePermissions && chmod != nil {
			perms := mode(hdr_mode)
			if opts.DontPreserveSuidAndSgid {
				perms = perms &^ (os.ModeSetuid | os.ModeSetgid)
			}
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
		if hdr.Typeflag == tar.TypeDir {
			dest, err = EvalSymlinksThatExist(dest)
		} else {
			// Only resolve symlinks in the parent directory so that an
			// existing entry at this path is replaced rather than written
			// through
			dest, err = eval_symlinks_in_parent(dest)
		}
		if err != nil {
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
			// Remove rather than truncate any existing file as it may be
			// hardlinked to another extracted file
			if err = remove_existing_non_dir(dest); err != nil {
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
			// Hardlink targets are relative to the archive root
			link_target := hdr.Linkname
			if !filepath.IsAbs(link_target) {
				link_target = filepath.Join(dest_path, link_target)
			}
			// A hardlink to a symlink links to the symlink itself, not to
			// what it points to
			if link_target, err = eval_symlinks_in_parent(link_target); err != nil {
				return
			}
			if !strings.HasPrefix(link_target, needed_prefix) {
				return count, fmt.Errorf("the hardlink %s points to %s which is outside the destination directory", hdr.Name, hdr.Linkname)
			}
			var is_symlink bool
			// GNU tar creates hardlinks to self when the same path is
			// archived more than once
			if link_target != dest {
				if err = remove_existing_non_dir(dest); err != nil {
					return
				}
				if is_symlink, err = link_or_copy(link_target, dest); err != nil {
					return
				}
			} else if is_symlink, err = is_symlink_path(dest); err != nil {
				return
			}
			chmod := func(m fs.FileMode) error { return os.Chmod(dest, m) }
			if is_symlink {
				// os.Chmod() follows symlinks
				chmod = nil
			}
			if err = set_metadata(chmod, hdr.Mode); err != nil {
				return
			}
		case tar.TypeSymlink:
			if err = os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
				return
			}
			if err = remove_existing_non_dir(dest); err != nil {
				return
			}
			link_target := hdr.Linkname
			if !filepath.IsAbs(link_target) {
				link_target = filepath.Join(filepath.Dir(dest), link_target)
			}
			// We dont care about the link target being outside dest_path as
			// we resolve symlinks in dest and never write through a
			// symlink, so a symlink pointing outside dest_path cannot cause
			// writes outside dest_path.
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
