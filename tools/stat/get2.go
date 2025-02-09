//go:build darwin || freebsd || netbsd

package stat

import (
	"fmt"
	"io/fs"
	"time"
)

var _ = fmt.Print

func Get(f fs.FileInfo) (ans StatResult) {
	u := ans.setup_common(f)
	if u != nil {
		ans.Has_atime = true
		ans.Has_ctime = true
		ans.Ctime = time.Unix(u.Ctimespec.Unix())
		ans.Atime = time.Unix(u.Atimespec.Unix())
	}
	return
}
