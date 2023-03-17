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

	mode := func(hdr *tar.Header) fs.FileMode {
		return fs.FileMode(hdr.Mode) & (fs.ModePerm | fs.ModeSetgid | fs.ModeSetuid | fs.ModeSticky)
	}

	set_metadata := func(chmod func(mode fs.FileMode) error, hdr *tar.Header) (err error) {
		if !opts.DontPreservePermissions && chmod != nil {
			perms := mode(hdr)
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
		switch hdr.Typeflag {
		case tar.TypeDir:
			err = os.MkdirAll(dest, 0o700)
			if err != nil {
				return
			}
			if err = set_metadata(func(m fs.FileMode) error { return os.Chmod(dest, m) }, hdr); err != nil {
				return
			}
		case tar.TypeReg, tar.TypeRegA:
			var d *os.File
			if d, err = os.Create(dest); err != nil {
				return
			}
			err = set_metadata(d.Chmod, hdr)
			if err == nil {
				_, err = io.Copy(d, tr)
			}
			d.Close()
			if err != nil {
				return
			}
		case tar.TypeLink:
			if err = os.Link(hdr.Linkname, dest); err != nil {
				return
			}
			if err = set_metadata(func(m fs.FileMode) error { return os.Chmod(dest, m) }, hdr); err != nil {
				return
			}
		case tar.TypeSymlink:
			if err = os.Symlink(hdr.Linkname, dest); err != nil {
				return
			}
			if err = set_metadata(nil, hdr); err != nil {
				return
			}
		}
	}
	return
}
