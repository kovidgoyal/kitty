package dnd

import (
	"bytes"
	"container/list"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/emmansun/base64"
	"golang.org/x/sys/unix"
	"golang.org/x/text/unicode/norm"

	"github.com/kovidgoyal/go-parallel"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/streaming_base64"
)

var _ = fmt.Print

const copy_on_drop = 1
const move_on_drop = 2

type drop_dest struct {
	human_name, path string
	dest             io.WriteCloser
	mime_type        string
	completed        bool
	close_on_finish  bool
	b64_decoder      streaming_base64.StreamingBase64Decoder
}

func open_file_for_writing(path string) (*os.File, error) {
	f, err := os.Create(path)
	if errors.Is(err, os.ErrNotExist) {
		dir := filepath.Dir(path)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, err
		}
		return os.Create(path)
	}
	return f, err
}

func (d *drop_dest) write(chunk []byte) (err error) {
	if d.dest == nil {
		if d.path == "" {
			d.dest = &bufferWriteCloser{&bytes.Buffer{}}
		} else {
			d.dest, err = open_file_for_writing(d.path)
			d.close_on_finish = true
			if err != nil {
				return
			}
		}
	}
	_, err = d.dest.Write(chunk)
	return
}

func (d *drop_dest) finish() error {
	defer func() {
		d.completed = true
		if d.dest != nil && d.close_on_finish {
			d.dest.Close()
			d.dest = nil
		}
	}()
	if chunk, err := d.b64_decoder.Finish(); err != nil {
		return err
	} else if len(chunk) > 0 {
		return d.write(chunk)
	}
	return nil
}

func (d *drop_dest) add_data(x []byte, output_buf []byte, has_more bool) error {
	d.completed = false
	for chunk, err := range d.b64_decoder.Decode(x, output_buf) {
		if err == nil {
			err = d.write(chunk)
		}
		if err != nil {
			return err
		}
	}
	if !has_more {
		if chunk, err := d.b64_decoder.Finish(); err != nil {
			return err
		} else if len(chunk) > 0 {
			return d.write(chunk)
		}
	}
	return nil
}

type remote_dir_entry struct {
	base_dir              *dir_handle
	name                  string
	item_type             int
	children              []*remote_dir_entry
	num_children_finished int

	dest        io.WriteCloser
	b64_decoder streaming_base64.StreamingBase64Decoder
}

const case_conflict_template = "case-conflict-%d-%s"

// The key under which a case and normalization insensitive filesystem
// stores name, so that names that would alias each other compare equal.
func filesystem_name_key(name string) string {
	return strings.ToLower(norm.NFC.String(name))
}

func uniqify_child_names(names []string, is_case_sensitive_filesystem bool) []string {
	if !is_case_sensitive_filesystem {
		seen := utils.NewSet[string](len(names))
		for i, x := range names {
			names[i] = uniqify_name(x, seen)
		}
	}
	return names
}

func uniqify_name(name string, seen *utils.Set[string]) string {
	ans := name
	key := filesystem_name_key(ans)
	for q := 0; seen.Has(key); q++ {
		ans = fmt.Sprintf(case_conflict_template, q+1, name)
		key = filesystem_name_key(ans)
	}
	seen.Add(key)
	return ans
}

func do_local_copy(ctx context.Context, dest_dir *os.File, uri_list []string, action int, copy_mode string) (err error) {
	disallow_hardlinks := action == copy_on_drop && copy_mode == "independent"
	// Never copy the staging directory into itself, even if it is reachable
	// from a source by a route the up-front check cannot see, such as a bind mount.
	staging_info, err := dest_dir.Stat()
	if err != nil {
		return err
	}
	var src_file *os.File
	defer func() {
		if src_file != nil {
			src_file.Close()
		}
	}()
	for _, path := range uri_list {
		if path == "" {
			continue
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if src_file != nil {
			src_file.Close()
		}
		st, err := os.Lstat(path)
		if err != nil {
			return err
		}
		// Each source needs its own staging entry. Reusing an entry could
		// truncate a hard link to an earlier source, including inside a directory.
		name := filepath.Base(path)
		for q := 1; ; q++ {
			if _, err := utils.LstatAt(dest_dir, name); errors.Is(err, fs.ErrNotExist) {
				break
			} else if err != nil {
				return err
			}
			name = fmt.Sprintf(case_conflict_template, q, filepath.Base(path))
		}
		if st.IsDir() {
			if src_file, err = os.Open(path); err != nil {
				return err
			}
			if err := utils.MkdirAt(dest_dir, name, st.Mode().Perm()); err != nil {
				return err
			}
			d, err := utils.OpenDirAt(dest_dir, name)
			if err != nil {
				return err
			}
			err = utils.CopyFolderContents(ctx, src_file, d, utils.CopyFolderOptions{
				Disallow_hardlinks: disallow_hardlinks,
				Filter_files: func(parent *os.File, child os.FileInfo) bool {
					if child.IsDir() {
						return !os.SameFile(child, staging_info)
					}
					return child.Mode().IsRegular() || child.Mode()&fs.ModeSymlink != 0
				},
			})
			d.Close()
			if err != nil {
				return err
			}
		} else if st.Mode().IsRegular() {
			if !disallow_hardlinks {
				// First try a hard link
				dest := filepath.Join(dest_dir.Name(), name)
				if err = os.Link(path, dest); err == nil {
					continue
				}
			}
			if src_file, err = os.Open(path); err != nil {
				return err
			}
			d, err := utils.CreateExclusiveAt(dest_dir, name, st.Mode().Perm())
			if err != nil {
				return err
			}
			err = utils.CopyFileAndClose(ctx, src_file, d)
			src_file = nil // already closed
			if err != nil {
				return err
			}
		} else if st.Mode()&fs.ModeSymlink != 0 {
			target, err := os.Readlink(path)
			if err != nil {
				return err
			}
			dest := filepath.Join(dest_dir.Name(), name)
			if err := os.Symlink(target, dest); err != nil {
				return err
			}
		}
	}
	return
}

func do_local_copy_in_goroutine(ctx context.Context, dest_dir *os.File, completion chan error, uri_list []string, action int, copy_mode string, wakeup func()) {
	var err error
	defer func() {
		if r := recover(); r != nil {
			err = parallel.Format_stacktrace_on_panic(r, 1)
		}
		completion <- err
		wakeup()
	}()
	err = do_local_copy(ctx, dest_dir, uri_list, action, copy_mode)
}

type path_stack[T any] struct {
	s list.List
}

func (p *path_stack[T]) push(x T)    { p.s.PushBack(x) }
func (p *path_stack[T]) pop() T      { return p.s.Remove(p.s.Front()).(T) }
func (p *path_stack[T]) empty() bool { return p.s.Front() == nil }

// Return whether name in dir is a directory or a symlink to one. Both
// find_overwrites and rename_contents merge into such entries.
func is_dir_at(dir *os.File, name string) (bool, error) {
	st, err := utils.StatAt(dir, name)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return false, nil // dangling symlink
		}
		return false, err
	}
	return st.IsDir(), nil
}

// Return the name under which the entry described by info, which was looked
// up as name, is actually stored in dir, whose entries are dest_entries.
// These differ when the filesystem resolves case or Unicode normalization
// aliases.
func stored_name(dir *os.File, dest_entries []os.DirEntry, name string, info os.FileInfo) (string, error) {
	for _, e := range dest_entries {
		if e.Name() == name {
			return name, nil
		}
	}
	for _, e := range dest_entries {
		einfo, err := utils.LstatAt(dir, e.Name())
		if err != nil {
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			return "", err
		}
		if same, err := same_file(einfo, info); err != nil {
			return "", err
		} else if same {
			return e.Name(), nil
		}
	}
	return name, nil
}

type overwrite_dir struct {
	src, dest string
	// Whether dest is the root or was reached through a symlink, so that its
	// actual ancestors may differ from the directories it was reached through
	via_symlink bool
}

// Return a list of relative paths, as stored in dest_dir, for all entries in
// the tree rooted at src_dir that also exist in the tree rooted at dest_dir,
// except for directories that exist in both places. Symlinks to directories
// in dest_dir are treated as directories, matching rename_contents. Fail if
// any directory that would be merged into is inside one of move_sources,
// since those are removed once the drop completes.
func find_overwrites(src_dir *os.File, dest_dir *os.File, move_sources []os.FileInfo) (ans []string, err error) {
	stack := path_stack[overwrite_dir]{}
	stack.push(overwrite_dir{".", ".", true})
	join := func(parent, name string) string {
		return utils.IfElse(parent == ".", name, filepath.Join(parent, name))
	}
	for !stack.empty() {
		relpath := stack.pop()
		if err = func() (err error) {
			sd, err := utils.OpenDirAt(src_dir, relpath.src)
			if err != nil {
				return err
			}
			defer sd.Close()
			dd, err := utils.OpenDirAt(dest_dir, relpath.dest)
			if err != nil {
				return err
			}
			defer dd.Close()
			if len(move_sources) > 0 {
				// A real subdirectory of a directory that is not inside a
				// source is itself inside one only if it is that source.
				// Directories reached through symlinks need a full check.
				var inside bool
				if relpath.via_symlink {
					inside, err = destination_is_within_source(dd, move_sources)
				} else {
					inside, err = is_any_of(dd, move_sources)
				}
				if err != nil {
					return err
				}
				if inside {
					return fmt.Errorf("cannot merge dropped files into the directory %s as it is inside a directory being moved", dd.Name())
				}
			}
			src_children, err := sd.ReadDir(0)
			if err != nil {
				return err
			}
			var dest_entries []os.DirEntry
			for _, x := range src_children {
				// Let the destination filesystem resolve case and Unicode aliases,
				// just as it does when renaming the staged entries into place.
				// Any error here other than the entry not existing would also
				// make renaming the staged entry into place fail.
				d, err := utils.LstatAt(dd, x.Name())
				if errors.Is(err, fs.ErrNotExist) {
					continue
				} else if err != nil {
					return err
				}
				if dest_entries == nil {
					if dest_entries, err = dd.ReadDir(0); err != nil {
						return err
					}
				}
				name, err := stored_name(dd, dest_entries, x.Name(), d)
				if err != nil {
					return err
				}
				dest_is_dir, is_symlink := d.IsDir(), d.Mode()&fs.ModeSymlink != 0
				if is_symlink {
					if dest_is_dir, err = is_dir_at(dd, x.Name()); err != nil {
						return err
					}
				}
				switch {
				case x.IsDir() && dest_is_dir:
					stack.push(overwrite_dir{join(relpath.src, x.Name()), join(relpath.dest, name), is_symlink})
				case dest_is_dir:
					return fmt.Errorf("cannot replace the existing directory %s with a dropped file", join(relpath.dest, name))
				default:
					ans = append(ans, join(relpath.dest, name))
				}
			}
			return
		}(); err != nil {
			return nil, err
		}
	}
	return
}

// Rename the contents of src_dir into dest_dir, handling the case of
// directories already existing in dest_dir transparently. Existing
// directories and symlinks to directories are merged into, other existing
// entries are replaced.
func rename_contents(src_dir *os.File, dest_dir *os.File) (err error) {
	stack := path_stack[string]{}
	stack.push(".")
	for !stack.empty() {
		relpath := stack.pop()
		if err = func() error {
			sd, err := utils.OpenDirAt(src_dir, relpath)
			if err != nil {
				return err
			}
			defer sd.Close()
			dd, err := utils.OpenDirAt(dest_dir, relpath)
			if err != nil {
				return err
			}
			defer dd.Close()
			for {
				src_children, err := sd.ReadDir(64)
				if err != nil {
					if errors.Is(err, io.EOF) {
						break
					}
					return err
				}
				for _, child := range src_children {
					crelpath := utils.IfElse(relpath == ".", child.Name(), filepath.Join(relpath, child.Name()))
					rerr := utils.RenameAt(sd, child.Name(), dd, child.Name())
					if rerr == nil {
						continue
					}
					if _, err := utils.LstatAt(dd, child.Name()); err != nil {
						if errors.Is(err, fs.ErrNotExist) {
							return rerr
						}
						return err
					}
					dest_is_dir, err := is_dir_at(dd, child.Name())
					if err != nil {
						return err
					}
					switch {
					case child.IsDir() && dest_is_dir:
						stack.push(crelpath)
					case dest_is_dir:
						return fmt.Errorf("cannot replace the existing directory %s with a dropped file: %w", filepath.Join(dest_dir.Name(), crelpath), rerr)
					case child.IsDir():
						// rename() cannot replace a non-directory with a directory
						if err := utils.UnlinkAt(dd, child.Name()); err != nil {
							return err
						}
						if err := utils.RenameAt(sd, child.Name(), dd, child.Name()); err != nil {
							return err
						}
					default:
						return rerr
					}
				}
			}
			return nil
		}(); err != nil {
			return err
		}
	}
	return
}

func (d *remote_dir_entry) add_remote_data(data []byte, output_buf []byte, has_more bool, is_case_sensitive_filesystem bool) error {
	if len(data) > 0 {
		for chunk, derr := range d.b64_decoder.Decode(data, output_buf) {
			if derr != nil {
				return derr
			}
			if _, derr = d.dest.Write(chunk); derr != nil {
				return derr
			}
		}
	} else if !has_more {
		if chunk, derr := d.b64_decoder.Finish(); derr != nil {
			return derr
		} else {
			if _, derr = d.dest.Write(chunk); derr != nil {
				return derr
			}
		}
		defer func() {
			d.dest.Close()
			d.dest = nil
			d.base_dir = d.base_dir.unref()
		}()
		if dest, ok := d.dest.(*bufferWriteCloser); ok {
			if d.item_type == 1 {
				if derr := utils.SymlinkAt(d.base_dir.handle, d.name, dest.String()); derr != nil {
					return derr
				}
			} else { // directory
				if f, derr := utils.CreateDirAt(d.base_dir.handle, d.name, 0o755); derr != nil {
					return derr
				} else {
					handle := new_dir_handle(f)
					defer handle.unref()
					s := utils.NewSeparatorScanner("", "\x00")
					for _, name := range uniqify_child_names(s.Split(dest.String()), is_case_sensitive_filesystem) {
						d.children = append(d.children, &remote_dir_entry{name: name, base_dir: handle.newref()})
					}
				}
			}
		}
	}
	return nil
}

type parsed_uri_kind int

const (
	parsed_uri_file parsed_uri_kind = iota
	parsed_uri_data
)

type parsed_uri struct {
	kind parsed_uri_kind
	path string // for file URIs: the local filesystem path (empty if not a valid file URI)
	mime string // for data URIs: the MIME type
	data []byte // for data URIs: the decoded payload
}

// ext_for_mime returns a file extension (with leading dot) for a MIME type.
func ext_for_mime(mime string) string {
	for _, x := range utils.GuessFileExtensions(mime) {
		return x
	}
	return ""
}

// parse_data_uri decodes a data: URI and returns the MIME type and raw data.
func parse_data_uri(uri string) (mime string, data []byte, err error) {
	rest := strings.TrimPrefix(uri, "data:")
	comma_idx := strings.Index(rest, ",")
	if comma_idx < 0 {
		err = fmt.Errorf("invalid data URI: no comma found")
		return
	}
	header := rest[:comma_idx]
	payload := rest[comma_idx+1:]

	is_base64 := strings.HasSuffix(header, ";base64")
	if is_base64 {
		header = header[:len(header)-7]
	}

	mime = strings.TrimSpace(header)
	if mime == "" {
		mime = "text/plain"
	}
	// Strip parameters (e.g. ;charset=UTF-8) so the MIME type is clean.
	mime, _, _ = strings.Cut(mime, ";")

	if is_base64 {
		payload = strings.NewReplacer("\r", "", "\n", "", " ", "").Replace(payload)
		data, err = base64.StdEncoding.DecodeString(payload)
		if err != nil {
			data, err = base64.RawURLEncoding.DecodeString(payload)
		}
	} else {
		var unescaped string
		unescaped, err = url.PathUnescape(payload)
		if err != nil {
			return
		}
		data = []byte(unescaped)
	}
	return
}

func parse_uri_list(src string) (ans []parsed_uri, err error) {
	for _, line := range utils.NewSeparatorScanner("", "\r\n").Split(src) {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "file://") {
			p, err := url.Parse(line)
			if err != nil {
				return nil, err
			}
			ans = append(ans, parsed_uri{kind: parsed_uri_file, path: filepath.Clean(p.Path)})
		} else if strings.HasPrefix(line, "data:") {
			m, d, derr := parse_data_uri(line)
			if derr != nil {
				// Invalid data URI: treat as an unrecognised entry (empty path) so the caller
				// skips it without failing, matching the behaviour for unknown URI schemes.
				ans = append(ans, parsed_uri{kind: parsed_uri_file})
			} else {
				ans = append(ans, parsed_uri{kind: parsed_uri_data, mime: m, data: d})
			}
		} else {
			ans = append(ans, parsed_uri{kind: parsed_uri_file}) // unknown URI scheme: empty entry
		}
	}
	return
}

type drop_status struct {
	offered_mimes      []string
	accepted_mimes     []string
	uri_list           []parsed_uri
	cell_x, cell_y     int
	action             int
	in_window          bool
	reading_data       bool
	is_remote_client   bool
	source_allowed_ops int
	move_sources       map[int]move_source // local move sources, by index in uri_list

	dropping_to          *dir_handle
	root_remote_dir      *remote_dir_entry
	open_remote_dir      *remote_dir_entry
	current_remote_entry *remote_dir_entry // used for m=1 only
	pending_remote_dirs  []*remote_dir_entry
	data_requests        struct {
		pending         []DC
		in_flight_count int
	}
	local_copy struct {
		ctx        context.Context
		cancel_ctx context.CancelFunc
		completion chan error
	}
}

func (d *drop_status) reset() {
	if d.local_copy.ctx != nil {
		d.local_copy.cancel_ctx()
		<-d.local_copy.completion
	}
	if d.dropping_to != nil {
		d.dropping_to = d.dropping_to.unref()
	}
	*d = drop_status{cell_x: -1, cell_y: -1}
}

func (d *drop_dest) reset() {
	if d.dest != nil && d.dest != os.Stdout {
		if d.close_on_finish {
			d.dest.Close()
			d.dest = nil
		} else {
			d.dest.(*bufferWriteCloser).Reset()
		}
	}
	d.completed = false
	d.close_on_finish = false
	d.b64_decoder = streaming_base64.StreamingBase64Decoder{}
}

func (dnd *dnd) reset_drop() {
	if dnd.drop_status.root_remote_dir != nil {
		dnd.drop_status.root_remote_dir.close_tree()
		dnd.drop_status.root_remote_dir = nil
	}
	dnd.drop_status.reset()
	for _, x := range dnd.drop_dests {
		x.reset()
	}
}

func (root *remote_dir_entry) close_tree() {
	if root.base_dir != nil {
		root.base_dir = root.base_dir.unref()
	}
	for _, child := range root.children {
		child.close_tree()
	}
}

func (dnd *dnd) end_drop(success bool) {
	if dnd.drop_status.reading_data {
		// Remove the sources of a move before signalling the end of the drop,
		// so that the drop is complete when the terminal is told it has finished
		if success && dnd.drop_status.action == move_on_drop && !dnd.drop_status.is_remote_client {
			for i, src := range dnd.drop_status.move_sources {
				// Placement can replace a source path through a destination symlink.
				path := dnd.drop_status.uri_list[i].path
				st, err := src.current(path)
				if err != nil || st == nil {
					continue
				}
				if st.IsDir() {
					os.RemoveAll(path)
				} else {
					os.Remove(path)
				}
			}
		}
		dnd.lp.QueueDnDData(DC{
			Type: 'r', Operation: utils.IfElse(success, dnd.drop_status.action, 0)}) // end drop
	}
	dnd.reset_drop()
	if success && dnd.has_exit_on("drop-finish") {
		dnd.lp.Quit(0)
	}
}

func (dnd *dnd) count_files_in_drop() int {
	n := 0
	for _, u := range dnd.drop_status.uri_list {
		if (u.kind == parsed_uri_file && u.path != "") || u.kind == parsed_uri_data {
			n++
		}
	}
	for mime, d := range dnd.drop_dests {
		if mime != "text/uri-list" && d.completed {
			n++
		}
	}
	return n
}

// Return the directories that end_drop will remove once the drop succeeds
func (dnd *dnd) move_source_dirs() (ans []os.FileInfo, err error) {
	if dnd.drop_status.action != move_on_drop || dnd.drop_status.is_remote_client {
		return nil, nil
	}
	for i, src := range dnd.drop_status.move_sources {
		info, err := src.current(dnd.drop_status.uri_list[i].path)
		if err != nil {
			if errors.Is(err, fs.ErrNotExist) {
				continue // end_drop has nothing to remove
			}
			return nil, err
		}
		if info != nil && info.IsDir() {
			ans = append(ans, info)
		}
	}
	return
}

// Rename the staged files into the output directory. If confirm_overwrites
// is true and existing files would be overwritten, return them instead
// without changing anything. end_drop removes the sources of a local move, so
// merging into them, for example via a symlink in the output directory, is
// rejected first.
func (dnd *dnd) place_staged_drop(staging_dir *os.File, confirm_overwrites bool) (overwrites []string, err error) {
	move_sources, err := dnd.move_source_dirs()
	if err != nil {
		return nil, err
	}
	if confirm_overwrites || len(move_sources) > 0 {
		if overwrites, err = find_overwrites(staging_dir, dnd.drop_output_dir, move_sources); err != nil {
			return nil, err
		}
		if confirm_overwrites && len(overwrites) > 0 {
			return overwrites, nil
		}
	}
	return nil, rename_contents(staging_dir, dnd.drop_output_dir)
}

func (dnd *dnd) all_drop_data_received() (err error) {
	dnd.num_dropped_files = dnd.count_files_in_drop()
	var staging_dir *os.File
	if dnd.drop_status.dropping_to != nil {
		staging_dir = dnd.drop_status.dropping_to.handle
		dnd.drop_status.dropping_to = nil
	}
	defer func() {
		if err == nil {
			if len(dnd.confirm_drop.overwrites) == 0 {
				dnd.end_drop(true)
			}
			err = dnd.render_screen()
		} else {
			dnd.end_drop(false)
		}
	}()
	if staging_dir != nil {
		overwrites, err := dnd.place_staged_drop(staging_dir, dnd.opts.ConfirmDropOverwrite)
		if err == nil && len(overwrites) > 0 {
			dnd.confirm_drop.overwrites = overwrites
			dnd.confirm_drop.staging_dir = staging_dir
			return dnd.render_screen()
		}
		staging_dir.Close()
		return err
	}
	return nil
}

func (dnd *dnd) drop_on_wakeup() error {
	if dnd.drop_status.local_copy.completion == nil {
		return nil
	}
	select {
	case err := <-dnd.drop_status.local_copy.completion:
		dnd.drop_status.local_copy.ctx = nil
		dnd.drop_status.local_copy.completion = nil
		if err != nil {
			return err
		}
		return dnd.all_drop_data_received()
	default:
		return nil
	}
}

func (dnd *dnd) new_tdir() (dir_file *os.File, err error) {
	dnd.tdir_counter++
	name := strconv.Itoa(dnd.tdir_counter)
	return utils.CreateDirAt(dnd.base_tempdir, name, 0o700)
}

// Identify a file by device and inode. Unlike os.SameFile this also works
// with the os.FileInfo objects returned by utils.StatAt.
func file_identity(info os.FileInfo) (dev, ino uint64, err error) {
	switch s := info.Sys().(type) {
	case *syscall.Stat_t:
		return uint64(s.Dev), uint64(s.Ino), nil
	case *unix.Stat_t:
		return uint64(s.Dev), uint64(s.Ino), nil
	}
	return 0, 0, fmt.Errorf("unknown stat result type for %s: %T", info.Name(), info.Sys())
}

func same_file(a, b os.FileInfo) (bool, error) {
	adev, aino, err := file_identity(a)
	if err != nil {
		return false, err
	}
	bdev, bino, err := file_identity(b)
	if err != nil {
		return false, err
	}
	return adev == bdev && aino == bino, nil
}

func matches_any(info os.FileInfo, candidates []os.FileInfo) (bool, error) {
	for _, c := range candidates {
		if same, err := same_file(info, c); err != nil || same {
			return same, err
		}
	}
	return false, nil
}

// Return whether dir is one of candidates
func is_any_of(dir *os.File, candidates []os.FileInfo) (bool, error) {
	info, err := dir.Stat()
	if err != nil {
		return false, err
	}
	return matches_any(info, candidates)
}

// Return whether dest_dir is one of sources or inside one of them.
// Walk up from dest_dir via .. relative to its file descriptor rather than
// its path, so that the result is correct even if dest_dir has been moved or
// its path contains symlinks. Comparing identities handles case aliases and
// stat only requires search permission on the ancestors.
func destination_is_within_source(dest_dir *os.File, sources []os.FileInfo) (bool, error) {
	info, err := dest_dir.Stat()
	if err != nil {
		return false, err
	}
	for rel := ".."; ; rel = filepath.Join(rel, "..") {
		if same, err := matches_any(info, sources); err != nil || same {
			return same, err
		}
		parent, err := utils.StatAt(dest_dir, rel)
		if err != nil {
			return false, err
		}
		if at_root, err := same_file(parent, info); err != nil || at_root {
			return false, err
		}
		info = parent
	}
}

// The state of a local move source before staging, so that end_drop does
// not remove anything that has since replaced it. The birth time, where the
// filesystem records one, distinguishes a replacement that reuses the inode
// number of the deleted source.
type move_source struct {
	info  os.FileInfo
	birth time.Time // zero if unknown
}

// Return the current file info of the move source at path, or nil if path
// no longer refers to the original source.
func (s move_source) current(path string) (os.FileInfo, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if same, err := same_file(s.info, info); err != nil || !same {
		return nil, err
	}
	if !s.birth.IsZero() && !birth_time(path, info).Equal(s.birth) {
		return nil, nil
	}
	return info, nil
}

func (dnd *dnd) all_mime_data_dropped() (err error) {
	drop_status := &dnd.drop_status
	if len(drop_status.uri_list) == 0 {
		dnd.num_dropped_files = dnd.count_files_in_drop()
		dnd.end_drop(true)
		return dnd.render_screen()
	}
	if !drop_status.is_remote_client {
		dest_info, err := dnd.drop_output_dir.Stat()
		if err != nil {
			return err
		}
		for i, u := range drop_status.uri_list {
			if u.kind != parsed_uri_file || u.path == "" {
				continue
			}
			source_info, err := os.Lstat(u.path)
			if err != nil {
				return err
			}
			if source_info.IsDir() {
				inside, err := destination_is_within_source(dnd.drop_output_dir, []os.FileInfo{source_info})
				if err != nil {
					return err
				}
				if inside {
					return fmt.Errorf("cannot drop directory %q into itself or one of its subdirectories", u.path)
				}
			}
			if drop_status.action != move_on_drop {
				continue
			}
			parent_info, err := os.Stat(filepath.Dir(u.path))
			if err != nil {
				return err
			}
			if os.SameFile(parent_info, dest_info) {
				// Moving into the source directory is a no-op. Exclude it
				// from both staging and end_drop's source cleanup.
				drop_status.uri_list[i].path = ""
				continue
			}
			if drop_status.move_sources == nil {
				drop_status.move_sources = make(map[int]move_source, len(drop_status.uri_list))
			}
			drop_status.move_sources[i] = move_source{info: source_info, birth: birth_time(u.path, source_info)}
		}
	}
	f, err := dnd.new_tdir()
	if err != nil {
		return err
	}
	dnd.drop_status.dropping_to = new_dir_handle(f)

	// Write data URIs directly into the staging directory (applies to both local and remote).
	data_uri_counter := 0
	for _, u := range drop_status.uri_list {
		if u.kind == parsed_uri_data {
			data_uri_counter++
			fname := fmt.Sprintf("data-uri-%d%s", data_uri_counter, ext_for_mime(u.mime))
			if werr := os.WriteFile(filepath.Join(f.Name(), fname), u.data, 0o644); werr != nil {
				return werr
			}
		}
	}

	if drop_status.is_remote_client {
		drop_status.root_remote_dir = &remote_dir_entry{}
		seen := utils.NewSet[string](len(drop_status.uri_list))
		idx := slices.Index(drop_status.offered_mimes, "text/uri-list")
		for i, u := range drop_status.uri_list {
			var c *remote_dir_entry
			if u.kind == parsed_uri_data || u.path == "" {
				c = &remote_dir_entry{}
				drop_status.root_remote_dir.num_children_finished++
			} else {
				name := filepath.Base(u.path)
				if !dnd.is_case_sensitive_filesystem {
					name = uniqify_name(name, seen)
				}
				c = &remote_dir_entry{base_dir: dnd.drop_status.dropping_to.newref(), name: name}
				dnd.queue_data_request(DC{Type: 'r', X: idx + 1, Y: i + 1})
			}
			drop_status.root_remote_dir.children = append(drop_status.root_remote_dir.children, c)
		}
		// If all children were pre-finished (e.g., all data URIs), complete the drop immediately.
		if drop_status.root_remote_dir.num_children_finished >= len(drop_status.root_remote_dir.children) {
			return dnd.all_drop_data_received()
		}
		drop_status.open_remote_dir = drop_status.root_remote_dir
	} else {
		// Build a file-path slice for the goroutine; data URI entries are already written above.
		file_paths := make([]string, len(drop_status.uri_list))
		for i, u := range drop_status.uri_list {
			if u.kind == parsed_uri_file {
				file_paths[i] = u.path
			}
		}
		drop_status.local_copy.ctx, drop_status.local_copy.cancel_ctx = context.WithCancel(context.Background())
		drop_status.local_copy.completion = make(chan error, 1)
		go do_local_copy_in_goroutine(drop_status.local_copy.ctx, f, drop_status.local_copy.completion, file_paths, drop_status.action, dnd.opts.CopyMode, func() { dnd.lp.WakeupMainThread() })
	}
	return
}

func (dnd *dnd) request_mime_data() {
	accepted := utils.NewSetWithItems(dnd.drop_status.accepted_mimes...)
	seen := utils.NewSet[string](len(dnd.drop_status.accepted_mimes))
	for idx, m := range dnd.drop_status.offered_mimes {
		if accepted.Has(m) && !seen.Has(m) {
			dnd.queue_data_request(DC{Type: 'r', X: idx + 1})
			seen.Add(m)
		}
	}
}

var offered_mimes_buf strings.Builder

func (dnd *dnd) on_drop_move(cell_x, cell_y int, has_more bool, offered_mimes string, is_drop bool, source_allowed_ops int) (needs_rerender bool) {
	prev_status := dnd.drop_status
	dnd.drop_status.cell_x, dnd.drop_status.cell_y = cell_x, cell_y
	if offered_mimes != "" {
		offered_mimes_buf.WriteString(offered_mimes)
		if has_more {
			return
		}
		offered_mimes := offered_mimes_buf.String()
		dnd.drop_status.offered_mimes = strings.Fields(offered_mimes)
		dnd.drop_status.accepted_mimes = make([]string, 0, len(dnd.drop_status.offered_mimes))
		seen := utils.NewSet[string](len(dnd.drop_status.offered_mimes))
		for _, x := range dnd.drop_status.offered_mimes {
			if _, found := dnd.drop_dests[x]; found && !seen.Has(x) {
				dnd.drop_status.accepted_mimes = append(dnd.drop_status.accepted_mimes, x)
				seen.Add(x)
			}
		}
	}
	offered_mimes_buf.Reset()
	if source_allowed_ops != 0 {
		dnd.drop_status.source_allowed_ops = source_allowed_ops
	}
	if dnd.copy_button_region.has(cell_x, cell_y) {
		dnd.drop_status.action = copy_on_drop
	} else if dnd.move_button_region.has(cell_x, cell_y) {
		dnd.drop_status.action = move_on_drop
	} else {
		switch dnd.opts.DropAnywhere {
		case "disallowed":
			dnd.drop_status.action = 0
			dnd.drop_status.accepted_mimes = nil
		case "copy":
			dnd.drop_status.action = copy_on_drop
		case "move":
			dnd.drop_status.action = move_on_drop
		}
	}
	// Restrict to operations allowed by the drag source.
	if allowed := dnd.drop_status.source_allowed_ops; allowed != 0 && dnd.drop_status.action != 0 {
		if allowed&dnd.drop_status.action == 0 {
			dnd.drop_status.action = 0
			dnd.drop_status.accepted_mimes = nil
		}
	}
	dnd.drop_status.in_window = cell_x > -1 && cell_y > -1
	if !dnd.drop_status.in_window || dnd.drag_status.active { // disallow self drag and drop
		dnd.reset_drop()
	}
	mimes_changed := !slices.Equal(prev_status.accepted_mimes, dnd.drop_status.accepted_mimes)
	needs_rerender = prev_status.action != dnd.drop_status.action || mimes_changed
	if needs_rerender && !is_drop {
		c := DC{Type: 'm', Operation: dnd.drop_status.action}
		if dnd.drop_status.action != 0 && len(dnd.drop_status.accepted_mimes) > 0 {
			c.Payload = utils.UnsafeStringToBytes(strings.Join(dnd.drop_status.accepted_mimes, " "))
		}
		dnd.lp.QueueDnDData(c)
	}
	needs_rerender = needs_rerender || dnd.drop_status.in_window != prev_status.in_window
	if is_drop {
		needs_rerender = true
		if dnd.drop_status.action == 0 || len(dnd.drop_status.accepted_mimes) == 0 || dnd.drag_status.active {
			dnd.end_drop(false)
			return
		}
		dnd.drop_status.reading_data = true
		dnd.request_mime_data()
	}
	return
}

var drop_buf []byte

const max_inflight_data_rquests = 64

func (dnd *dnd) queue_data_request(cmd DC) {
	if dnd.drop_status.data_requests.in_flight_count < max_inflight_data_rquests {
		dnd.lp.QueueDnDData(cmd)
		dnd.drop_status.data_requests.in_flight_count++
	} else {
		dnd.drop_status.data_requests.pending = append(dnd.drop_status.data_requests.pending, cmd)
	}
}

func (dnd *dnd) data_request_completed() {
	dnd.drop_status.data_requests.in_flight_count--
	if len(dnd.drop_status.data_requests.pending) > 0 && dnd.drop_status.data_requests.in_flight_count < max_inflight_data_rquests {
		dnd.lp.QueueDnDData(dnd.drop_status.data_requests.pending[0])
		dnd.drop_status.data_requests.in_flight_count++
		dnd.drop_status.data_requests.pending = dnd.drop_status.data_requests.pending[1:]
	}
}

func (dnd *dnd) on_remote_drop_data(cmd DC) (err error) {
	drop_status := &dnd.drop_status
	if drop_status.open_remote_dir == nil {
		return fmt.Errorf("got a remote data response form the terminal without an open remote dir")
	}
	if cmd.X == 0 && cmd.Y == 0 && cmd.Yp == 0 {
		if drop_status.current_remote_entry == nil {
			return fmt.Errorf("got a remote data response form the terminal without a current remote entry")
		}
	} else {
		num := utils.IfElse(cmd.Yp != 0 && cmd.Yp != 1, cmd.X, cmd.Y) - 1
		if num < 0 || num >= len(drop_status.open_remote_dir.children) {
			return fmt.Errorf("got a remote data response from the terminal for an entry that does not exist")
		}
		drop_status.current_remote_entry = drop_status.open_remote_dir.children[num]
	}
	e := drop_status.current_remote_entry
	if e.dest == nil {
		e.item_type = cmd.Xp
		switch cmd.Xp {
		case 0:
			f, err := utils.CreateExclusiveAt(e.base_dir.handle, e.name, 0o666)
			if err != nil {
				return err
			}
			e.dest = f
		default:
			e.dest = &bufferWriteCloser{&bytes.Buffer{}}
		}
	}
	if sz := max(4096, len(cmd.Payload)+4); len(drop_buf) < sz {
		drop_buf = make([]byte, sz)
	}
	if err = e.add_remote_data(cmd.Payload, drop_buf, cmd.Has_more, dnd.is_case_sensitive_filesystem); err != nil {
		return err
	}
	if e.dest == nil { // received all data for this entry
		drop_status.current_remote_entry = nil
		parent := drop_status.open_remote_dir
		parent.num_children_finished++
		dnd.data_request_completed()
		if parent.num_children_finished >= len(parent.children) { // parent is finished
			drop_status.open_remote_dir = nil
			if parent.base_dir != nil {
				parent.base_dir = parent.base_dir.unref()
			}
			if parent.item_type != 0 {
				dnd.lp.QueueDnDData(DC{Type: 'r', Yp: parent.item_type}) // close directory in terminal
			}
			for _, c := range parent.children {
				is_pending := false
				if c.item_type != 0 && c.item_type != 1 {
					if len(c.children) > 0 {
						dnd.drop_status.pending_remote_dirs = append(dnd.drop_status.pending_remote_dirs, c)
						is_pending = true
					}
				}
				if !is_pending {
					if c.base_dir != nil {
						c.base_dir = c.base_dir.unref()
					}
				}
			}
			if len(drop_status.pending_remote_dirs) > 0 {
				drop_status.open_remote_dir = drop_status.pending_remote_dirs[0]
				drop_status.pending_remote_dirs = drop_status.pending_remote_dirs[1:]
				for i := range drop_status.open_remote_dir.children {
					dnd.queue_data_request(DC{Type: 'r', X: i + 1, Yp: drop_status.open_remote_dir.item_type})
				}
			} else {
				return dnd.all_drop_data_received()
			}
		}
	}
	return nil
}

func (dnd *dnd) on_drop_data(cmd DC) error {
	drop_status := &dnd.drop_status
	if drop_status.root_remote_dir != nil {
		return dnd.on_remote_drop_data(cmd)
	}
	idx := cmd.X - 1
	if idx < 0 || idx > len(drop_status.offered_mimes) {
		return fmt.Errorf("terminal sent drop data for an index (%d) outside the list of accepted MIMEs (length: %d)", idx, len(drop_status.offered_mimes))
	}
	mime := drop_status.offered_mimes[idx]
	dest := dnd.drop_dests[mime]
	if cmd.Xp == 1 && mime == "text/uri-list" {
		drop_status.is_remote_client = true
	}
	if !cmd.Has_more && len(cmd.Payload) == 0 {
		if err := dest.finish(); err != nil {
			return err
		}
		if mime == "text/uri-list" {
			b := dest.dest.(*bufferWriteCloser)
			var err error
			if drop_status.uri_list, err = parse_uri_list(b.String()); err != nil {
				return err
			}
		}
		pending := false
		expecting := utils.NewSetWithItems(drop_status.accepted_mimes...)
		for _, d := range dnd.drop_dests {
			if !d.completed && expecting.Has(d.mime_type) {
				pending = true
				break
			}
		}
		if !pending {
			return dnd.all_mime_data_dropped()
		}
		return nil
	}
	if sz := max(4096, len(cmd.Payload)+4); len(drop_buf) < sz {
		drop_buf = make([]byte, sz)
	}
	return dest.add_data(cmd.Payload, drop_buf, cmd.Has_more)
}

func (dnd *dnd) drop_confirm(accepted bool) error {
	staging_dir := dnd.confirm_drop.staging_dir
	dnd.confirm_drop.overwrites = nil
	dnd.confirm_drop.staging_dir = nil
	defer staging_dir.Close()
	if !accepted {
		dnd.num_dropped_files = 0
	}
	if accepted {
		// Symlinks in the output directory may have changed while awaiting
		// confirmation, so place_staged_drop checks them again.
		if _, err := dnd.place_staged_drop(staging_dir, false); err != nil {
			dnd.end_drop(false)
			return err
		}
		dnd.end_drop(true)
	} else {
		dnd.end_drop(false)
	}
	return dnd.render_screen()
}
