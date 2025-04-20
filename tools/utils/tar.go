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
	"strings"
)

var _ = fmt.Print

type TarExtractOptions struct {
	DontPreservePermissions bool
}

func ExtractAllFromTar(tr *tar.Reader, dest_path string, optss ...TarExtractOptions) (count int, err error) {
	opts := TarExtractOptions{}
	if len(optss) > 0 {
		opts = optss[0]
	}
	dest_path, err = filepath.Abs(dest_path)
	if err != nil {
		return
	}

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
		dest = strings.TrimLeft(dest, "/")
		if !filepath.IsLocal(dest) {
			continue
		}
		dest = filepath.Join(dest_path, dest)
		if dest, err = filepath.EvalSymlinks(dest); err != nil {
			if os.IsNotExist(err) {
				err = nil
			} else {
				return count, err
			}
		}
		if !strings.HasPrefix(filepath.Clean(dest), filepath.Clean(dest_path)+string(os.PathSeparator)) {
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
