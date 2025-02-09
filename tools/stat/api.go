package stat

import (
	"fmt"
	"io/fs"
	"syscall"
	"time"
)

var _ = fmt.Print

type StatResult struct {
	Name                 string
	Size                 int64
	Mode                 fs.FileMode
	Ctime, Mtime, Atime  time.Time
	Has_ctime, Has_atime bool
	Dev, Ino             uint64
	Has_dev, Has_ino     bool
	Number_links         uint64
	Has_number_links     bool
	Uid, Gid             uint64
	Has_uid, Has_gid     bool
}

func (s *StatResult) setup_common(f fs.FileInfo) (u *syscall.Stat_t) {
	s.Name = f.Name()
	s.Size = f.Size()
	s.Mode = f.Mode()
	s.Mtime = f.ModTime()
	ok := false
	u, ok = f.Sys().(*syscall.Stat_t)
	if !ok {
		u = nil
	}
	if u != nil {
		s.Has_atime = true
		s.Has_ctime = true
		s.Dev = uint64(u.Dev)
		s.Ino = uint64(u.Ino)
		s.Has_dev = true
		s.Has_ino = true
		s.Number_links = uint64(u.Nlink)
		s.Has_number_links = true
		s.Uid = uint64(u.Uid)
		s.Gid = uint64(u.Gid)
		s.Has_uid = true
		s.Has_gid = true
	}
	return
}
