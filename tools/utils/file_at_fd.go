package utils

import (
	"container/list"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

// MkdirAt creates a new subdirectory named 'name' inside the directory
// pointed to by parentDir.
func MkdirAt(parentDir *os.File, name string, perm os.FileMode) (err error) {
	// parentDir.Fd() gives us the base directory handle
	fd := int(parentDir.Fd())

	// unix.Mkdirat(dirfd, path, mode)
	// We convert the os.FileMode to a uint32 for the syscall
	for {
		if err = unix.Mkdirat(fd, name, uint32(perm)); err != unix.EINTR {
			break
		}
	}
	if err != nil {
		return &fs.PathError{
			Op:   "mkdirat",
			Path: filepath.Join(parentDir.Name(), name),
			Err:  err,
		}
	}
	return nil
}

// OpenAt opens a file relative to the directory pointed to by dirFile.
// Matches the behavior of os.Open (read-only).
func OpenAt(dirFile *os.File, name string) (*os.File, error) {
	return openAt(dirFile, name, unix.O_RDONLY, 0)
}

// Opens a directory relative to the directory pointed to by dirFile.
// Matches the behavior of os.Open (read-only).
func OpenDirAt(dirFile *os.File, name string) (*os.File, error) {
	return openAt(dirFile, name, unix.O_RDONLY|unix.O_DIRECTORY, 0)
}

// Create a symlink named name in the directory pointed to by dirFile. The
// target of the symlink is set to target
func SymlinkAt(dirFile *os.File, name, target string) (err error) {
	for {
		if err = unix.Symlinkat(target, int(dirFile.Fd()), name); err != unix.EINTR {
			break
		}
	}
	if err != nil {
		return &fs.PathError{
			Op:   "symlinkat",
			Path: filepath.Join(dirFile.Name(), name),
			Err:  err,
		}

	}
	return
}

// CreateAt creates or truncates a file relative to the directory pointed to by dirFile.
// Matches the behavior of os.Create (read-write, creates if doesn't exist, truncates).
func CreateAt(dirFile *os.File, name string) (*os.File, error) {
	return openAt(dirFile, name, unix.O_RDWR|unix.O_CREAT|unix.O_TRUNC, 0666)
}

// Create the specified directory, open it and return the file object. If the
// directory already exists, it is opened and returned, without changing its
// permissions, matching the behavior of CreateAt().
func CreateDirAt(parent *os.File, name string, permissions os.FileMode) (*os.File, error) {
	if err := MkdirAt(parent, name, permissions); err != nil {
		if err == unix.EEXIST {
			return OpenDirAt(parent, name)
		}
		return nil, err
	}
	return OpenDirAt(parent, name)
}

// Internal helper to wrap the unix.Openat syscall
func openAt(dirFile *os.File, name string, flags int, perm os.FileMode) (ans *os.File, err error) {
	dirFd := int(dirFile.Fd())
	// Call the underlying system call
	var fd int
	for {
		if fd, err = unix.Openat(dirFd, name, flags|unix.O_CLOEXEC, uint32(perm)); err != unix.EINTR {
			break
		}
	}
	name = filepath.Join(dirFile.Name(), name)
	if err != nil {
		return nil, &os.PathError{Op: "openat", Path: name, Err: err}
	}
	return os.NewFile(uintptr(fd), name), nil
}

type UnixFileInfo struct {
	name string
	stat *unix.Stat_t
	mode os.FileMode
}

func NewUnixFileInfo(name string, stat *unix.Stat_t) os.FileInfo {
	rawMode := stat.Mode
	// Start with the standard 9-bit permissions
	mode := os.FileMode(rawMode & 0777)

	// Map the file type bits using S_IFMT
	switch rawMode & unix.S_IFMT {
	case unix.S_IFDIR:
		mode |= os.ModeDir
	case unix.S_IFLNK:
		mode |= os.ModeSymlink
	case unix.S_IFBLK:
		mode |= os.ModeDevice
	case unix.S_IFCHR:
		// Go uses ModeDevice | ModeCharDevice for character devices
		mode |= os.ModeDevice | os.ModeCharDevice
	case unix.S_IFIFO:
		mode |= os.ModeNamedPipe
	case unix.S_IFSOCK:
		mode |= os.ModeSocket
	}

	// Map setuid, setgid, and sticky bits
	if rawMode&unix.S_ISUID != 0 {
		mode |= os.ModeSetuid
	}
	if rawMode&unix.S_ISGID != 0 {
		mode |= os.ModeSetgid
	}
	if rawMode&unix.S_ISVTX != 0 {
		mode |= os.ModeSticky
	}
	return &UnixFileInfo{name, stat, mode}
}

func (m *UnixFileInfo) Name() string       { return m.name }
func (m *UnixFileInfo) Size() int64        { return m.stat.Size }
func (m *UnixFileInfo) Mode() os.FileMode  { return m.mode }
func (m *UnixFileInfo) ModTime() time.Time { return time.Unix(m.stat.Mtim.Unix()) }
func (m *UnixFileInfo) IsDir() bool        { return m.Mode().IsDir() }
func (m *UnixFileInfo) Sys() any           { return m.stat }
func (m *UnixFileInfo) Dev() uint64        { return uint64(m.stat.Rdev) }

// Get file info relative to the parent FD, follows symlinks
func StatAt(dirFile *os.File, name string) (ans os.FileInfo, err error) {
	var stat unix.Stat_t
	for {
		if err = unix.Fstatat(int(dirFile.Fd()), name, &stat, 0); err != unix.EINTR {
			break
		}
	}
	name = filepath.Join(dirFile.Name(), name)
	if err != nil {
		return nil, &os.PathError{Op: "statat", Path: name, Err: err}
	}
	return NewUnixFileInfo(name, &stat), nil
}

// Get file info relative to the parent FD, do not follows symlinks
func LstatAt(dirFile *os.File, name string) (ans os.FileInfo, err error) {
	var stat unix.Stat_t
	for {
		if err = unix.Fstatat(int(dirFile.Fd()), name, &stat, unix.AT_SYMLINK_NOFOLLOW); err != unix.EINTR {
			break
		}
	}
	name = filepath.Join(dirFile.Name(), name)
	if err != nil {
		return nil, &os.PathError{Op: "lstatat", Path: name, Err: err}
	}
	return NewUnixFileInfo(name, &stat), nil
}

// Remove file relative to parent fd
func UnlinkAt(parent *os.File, name string) (err error) {
	for {
		if err = unix.Unlinkat(int(parent.Fd()), name, 0); err != unix.EINTR {
			break
		}
	}
	if err != nil {
		err = &os.PathError{Op: "unlinkat", Path: filepath.Join(parent.Name(), name), Err: err}
	}
	return
}

// Remove empty directory relative to parent fd
func RemoveDirAt(parent *os.File, name string) (err error) {
	for {
		if err = unix.Unlinkat(int(parent.Fd()), name, unix.AT_REMOVEDIR); err != unix.EINTR {
			break
		}
	}
	if err != nil {
		err = &os.PathError{Op: "unlinkat", Path: filepath.Join(parent.Name(), name), Err: err}
	}
	return
}

// Create a hardlink pointing to oldname called newname relative to the
// specified directories. If oldname is a symlink,
// a new symlink is created pointing to its target when follow_symlinks is true otherwise to it.
func LinkAt(oldparent *os.File, oldname string, newparent *os.File, newname string, follow_symlinks bool) (err error) {
	flags := IfElse(follow_symlinks, unix.AT_SYMLINK_FOLLOW, 0)
	for {
		if err = unix.Linkat(int(oldparent.Fd()), oldname, int(newparent.Fd()), newname, flags); err != unix.EINTR {
			break
		}
	}
	if err != nil {
		err = &os.PathError{Op: "linkat", Path: fmt.Sprintf("%s -> %s", filepath.Join(newparent.Name(), newname), filepath.Join(oldparent.Name(), oldname)), Err: err}
	}
	return
}

// RemoveChildren recursively removes all files and subdirectories
// within the directory pointed to by dirFile. Removes all it can but returns
// the first error, if any.
func RemoveChildren(dirFile *os.File) error {
	var firstErr error

	// Rewind directory pointer to ensure we start from the beginning
	if _, err := dirFile.Seek(0, io.SeekStart); err != nil {
		return err
	}

	for {
		// Read names in small chunks to handle very large directories
		names, err := dirFile.Readdirnames(64)
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			if firstErr == nil {
				firstErr = &os.PathError{Op: "readdirnames", Path: dirFile.Name(), Err: err}
			}
			break
		}

		for _, name := range names {
			var stat os.FileInfo
			// Get file info relative to the parent FD
			if stat, err = LstatAt(dirFile, name); err != nil {
				if firstErr == nil {
					firstErr = err
				}
				continue
			}
			if stat.IsDir() {
				// Open subdirectory relative to parent FD
				var childFile *os.File
				if childFile, err = OpenDirAt(dirFile, name); err != nil {
					if firstErr == nil {
						firstErr = err
					}
					continue
				}
				if err := RemoveChildren(childFile); err != nil && firstErr == nil {
					firstErr = err
				}
				childFile.Close()

				// Remove the empty subdirectory
				if err = RemoveDirAt(dirFile, name); err != nil && firstErr == nil {
					firstErr = err
				}
			} else {
				// Remove file/symlink
				if err = UnlinkAt(dirFile, name); err != nil && firstErr == nil {
					firstErr = err
				}
			}
		}
	}
	_, _ = dirFile.Seek(0, io.SeekStart)
	return firstErr
}

func DupFile(f *os.File) (ans *os.File, err error) {
	var fd int
	for {
		if fd, err = unix.Dup(int(f.Fd())); err != unix.EINTR {
			break
		}
	}
	if err != nil {
		return nil, &os.PathError{Op: "dup", Path: f.Name(), Err: err}
	}
	return os.NewFile(uintptr(fd), f.Name()), nil
}

func ReadLinkAt(parent *os.File, name string) (ans string, err error) {
	buf := [unix.PathMax]byte{}
	n, err := readLinkAt(parent, name, buf[:])
	if err != nil {
		return "", &os.PathError{Op: "readlinkat", Path: filepath.Join(parent.Name(), name), Err: err}
	}
	return UnsafeBytesToString(buf[:n]), nil
}

func ConvertFileModeToUnix(goMode os.FileMode) uint32 {
	// 1. Start with the basic permission bits (0777)
	unixMode := uint32(goMode.Perm())

	// 2. Map the type bits
	// We use the os.ModeXXX constants to identify the type
	switch {
	case goMode.IsDir():
		unixMode |= unix.S_IFDIR
	case goMode&os.ModeSymlink != 0:
		unixMode |= unix.S_IFLNK
	case goMode&os.ModeNamedPipe != 0:
		unixMode |= unix.S_IFIFO
	case goMode&os.ModeSocket != 0:
		unixMode |= unix.S_IFSOCK
	case goMode&os.ModeDevice != 0:
		if goMode&os.ModeCharDevice != 0 {
			unixMode |= unix.S_IFCHR
		} else {
			unixMode |= unix.S_IFBLK
		}
	default:
		// Default to a regular file
		unixMode |= unix.S_IFREG
	}

	// 3. Map special bits
	if goMode&os.ModeSetuid != 0 {
		unixMode |= unix.S_ISUID
	}
	if goMode&os.ModeSetgid != 0 {
		unixMode |= unix.S_ISGID
	}
	if goMode&os.ModeSticky != 0 {
		unixMode |= unix.S_ISVTX
	}

	return unixMode
}

func MknodAt(parent *os.File, name string, mode os.FileMode, dev uint64) (err error) {
	unix_mode := ConvertFileModeToUnix(mode)
	if err = mknodAt(parent, name, unix_mode, dev); err != nil {
		err = &os.PathError{Op: "mknodat", Path: filepath.Join(parent.Name(), name), Err: err}
	}
	return
}

// Not thread safe reference counted wrapper for os.File
type RefCountedFile struct {
	f      *os.File
	refcnt atomic.Int32
}

func NewRefCountedFile(f *os.File) *RefCountedFile {
	ans := RefCountedFile{f: f}
	ans.refcnt.Add(1)
	return &ans
}

func (f *RefCountedFile) NewRef() *RefCountedFile {
	f.refcnt.Add(1)
	return f
}

func (f *RefCountedFile) Unref() *RefCountedFile {
	if f.refcnt.Add(-1) == 0 {
		f.f.Close()
		f.f = nil
	}
	return nil
}

func (f *RefCountedFile) File() *os.File { return f.f }

type CopyFolderOptions struct {
	Disallow_hardlinks bool
	Follow_symlinks    bool
	Filter_files       func(parent *os.File, child os.FileInfo) bool
}

func copy_file_and_close(ctx context.Context, src *os.File, dest *os.File) (err error) {
	err_chan := make(chan error)
	defer func() {
		src.Close()
		dest.Close()
	}()
	go func() {
		// this go routine will automatically exit when src/dest are closed
		// even if copying is not complete. io.Copy() automatically use
		// sendfile() or similar mechanisms for efficiency.
		_, err := io.Copy(dest, src)
		err_chan <- err
	}()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case err := <-err_chan:
		return err
	}
}

// Copy the contents of src_folder to dest_folder, recursively, preserving file
// permissions. Behavior around hard and symbolic links and filtering is
// controlled via the provided options. When symlink following is enabled,
// symlink loops are avoided and any sumlink that points to an already copied
// entry becomes a symlink pointing to the copied entry using a relative path.
// Existing regular files are overwritten, without changing their permissions.
// Existing directories also do not have their permissions updated.
func CopyFolderContents(ctx context.Context, src_folder *os.File, dest_folder *os.File, opts CopyFolderOptions) (final_error error) {
	is_ok := opts.Filter_files
	type dir_ident struct{ dev, inode uint64 }
	get_dir_ident := func(i os.FileInfo) dir_ident {
		s := i.Sys().(*unix.Stat_t)
		return dir_ident{uint64(s.Dev), uint64(s.Ino)}
	}
	var seen_map map[dir_ident]string
	if opts.Follow_symlinks {
		seen_map = make(map[dir_ident]string)
		if s, err := src_folder.Stat(); err != nil {
			return err
		} else {
			seen_map[get_dir_ident(s)] = src_folder.Name()
		}
	}
	if is_ok == nil {
		is_ok = func(*os.File, os.FileInfo) bool { return true }
	}
	type item struct {
		src_parent, dest_parent *RefCountedFile
		child                   os.FileInfo
	}
	queue := list.New()
	is_cancelled := func() bool {
		select {
		case <-ctx.Done():
			final_error = ctx.Err()
			return true
		default:
			return false
		}
	}
	defer func() {
		for {
			v := queue.Front()
			if v == nil {
				break
			}
			item := queue.Remove(v).(*item)
			if item.src_parent != nil {
				item.src_parent.Unref()
			}
			if item.dest_parent != nil {
				item.dest_parent.Unref()
			}
		}
	}()

	src, dest := NewRefCountedFile(src_folder), NewRefCountedFile(dest_folder)
	// Add an extra reference so that the files passed into this function are
	// not closed in do_one()
	src.NewRef()
	dest.NewRef()
	fail := func(lerr error) bool {
		final_error = lerr
		return false
	}
	mark_as_seen := func(dest_parent *os.File, child string, child_file *os.File) bool {
		if !opts.Follow_symlinks {
			return true
		}
		var st os.FileInfo
		var serr error
		var path string
		if child_file == nil {
			st, serr = LstatAt(dest_parent, child)
			path = filepath.Join(dest_parent.Name(), child)
		} else {
			st, serr = child_file.Stat()
			path = child_file.Name()
		}
		if serr != nil {
			final_error = serr
			return false
		}
		seen_map[get_dir_ident(st)] = filepath.Clean(path)
		return true
	}

	var do_one_child func(src *RefCountedFile, dest *RefCountedFile, child os.FileInfo, from_symlink bool) bool
	do_one_child = func(src *RefCountedFile, dest *RefCountedFile, child os.FileInfo, from_symlink bool) bool {
		if child.IsDir() {
			queue.PushBack(&item{src.NewRef(), dest.NewRef(), child})
		} else {
			// First try a hardlink which works for regular files and symlinks at least
			if !opts.Disallow_hardlinks && LinkAt(src.File(), child.Name(), dest.File(), child.Name(), opts.Follow_symlinks) == nil {
				return true
			}
			t := child.Mode().Type()
			switch {
			case t.IsRegular():
				sf, err := OpenAt(src.File(), child.Name())
				if err != nil {
					return fail(err)
				}
				df, err := CreateDirAt(dest.File(), child.Name(), child.Mode().Perm())
				if err != nil {
					sf.Close()
					return fail(err)
				}
				if err = copy_file_and_close(ctx, sf, df); err != nil {
					UnlinkAt(dest.File(), child.Name()) // dont leave partially copied files around
					return fail(err)
				}
				if !mark_as_seen(dest.File(), df.Name(), df) {
					return false
				}
			case t&os.ModeSymlink != 0:
				if opts.Follow_symlinks && !from_symlink {
					rpath, err := filepath.EvalSymlinks(filepath.Join(src.File().Name(), child.Name()))
					if err != nil {
						return do_one_child(src, dest, child, true)
					}
					parent_dir := filepath.Dir(rpath)
					pfd, err := unix.Open(parent_dir, unix.O_DIRECTORY|unix.O_RDONLY|unix.O_CLOEXEC, 0)
					if err != nil {
						return do_one_child(src, dest, child, true)
					}
					pdf := os.NewFile(uintptr(pfd), parent_dir)
					child_name := filepath.Base(rpath)
					defer pdf.Close()
					st, err := StatAt(pdf, child_name)
					if err != nil {
						return do_one_child(src, dest, child, true)
					}
					id := get_dir_ident(st)
					if existing_path, found := seen_map[id]; found {
						target, err := filepath.Rel(dest.File().Name(), existing_path)
						if err != nil {
							return do_one_child(src, dest, child, true)
						}
						if err = SymlinkAt(dest.File(), child.Name(), target); err != nil {
							return fail(err)
						}
						if !mark_as_seen(dest.File(), child.Name(), nil) {
							return false
						}
					}
					return do_one_child(NewRefCountedFile(pdf), dest, st, true)
				} else {
					target, err := ReadLinkAt(src.File(), child.Name())
					if err != nil {
						return fail(err)
					}
					if err = SymlinkAt(dest.File(), child.Name(), target); err != nil {
						return fail(err)
					}
					if !mark_as_seen(dest.File(), child.Name(), nil) {
						return false
					}
				}
			case t&os.ModeDevice != 0:
				if err := MknodAt(dest.File(), child.Name(), child.Mode(), child.(*UnixFileInfo).Dev()); err != nil {
					return fail(err)
				}
				if !mark_as_seen(dest.File(), child.Name(), nil) {
					return false
				}
			}

		}
		return true
	}

	do_one := func(src *RefCountedFile, dest *RefCountedFile) bool {
		defer func() {
			src = src.Unref()
			dest = dest.Unref()
		}()
		if is_cancelled() {
			return false
		}
		children, err := src.File().Readdir(-1)
		if err != nil {
			return fail(err)
		}
		for _, child := range children {
			if is_cancelled() {
				return false
			}
			if !is_ok(src.File(), child) {
				continue
			}
			if !do_one_child(src, dest, child, false) {
				return false
			}
		}
		return true
	}

	next_dir := func(src_parent *RefCountedFile, dest_parent *RefCountedFile, child os.FileInfo) (ok bool) {
		src, dest = nil, nil
		defer func() {
			src_parent.Unref()
			dest_parent.Unref()
			if !ok {
				if src != nil {
					src = src.Unref()
				}
				if dest != nil {
					dest = dest.Unref()
				}
			}
		}()
		sf, err := OpenDirAt(src_parent.File(), child.Name())
		if err != nil {
			final_error = err
			return false
		}
		df, err := CreateDirAt(dest_parent.File(), child.Name(), child.Mode().Perm())
		if err != nil {
			sf.Close()
			final_error = err
			return false
		}
		src, dest = NewRefCountedFile(sf), NewRefCountedFile(df)
		ok = mark_as_seen(dest_parent.File(), child.Name(), df)
		return
	}

	for {
		if !do_one(src, dest) {
			return
		}
		v := queue.Front()
		if v == nil {
			break
		}
		n := queue.Remove(v).(*item)
		if !next_dir(n.src_parent, n.dest_parent, n.child) {
			return
		}
	}
	return
}
