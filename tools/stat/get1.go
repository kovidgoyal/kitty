//go:build aix || linux || dragonfly || openbsd || solaris

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
		ans.Ctime = time.Unix(u.Ctim.Unix())
		ans.Atime = time.Unix(u.Atim.Unix())
	}
	return
}
