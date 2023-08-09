// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"runtime"
	"strconv"
	"strings"
	"sync"

	"howett.net/plist"
)

var _ = fmt.Print

type PasswdEntry struct {
	Username, Pass, Uid, Gid, Gecos, Home, Shell string
}

func ParsePasswdLine(line string) (PasswdEntry, error) {
	parts := strings.Split(line, ":")
	if len(parts) == 7 {
		return PasswdEntry{parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]}, nil
	}
	return PasswdEntry{}, fmt.Errorf("passwd line has %d colon delimited fields instead of 7", len(parts))
}

func ParsePasswdDatabase(raw string) (ans map[string]PasswdEntry) {
	scanner := NewLineScanner(raw)
	ans = make(map[string]PasswdEntry)
	for scanner.Scan() {
		line := scanner.Text()
		if entry, e := ParsePasswdLine(line); e == nil {
			ans[entry.Uid] = entry
		}
	}
	return ans
}

func ParsePasswdFile(path string) (ans map[string]PasswdEntry, err error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return ParsePasswdDatabase(UnsafeBytesToString(raw)), nil
}

var passwd_err error
var passwd_database = sync.OnceValue(func() (ans map[string]PasswdEntry) {
	ans, passwd_err = ParsePasswdFile("/etc/passwd")
	return
})

func PwdEntryForUid(uid string) (ans PasswdEntry, err error) {
	pwd := passwd_database()
	if passwd_err != nil {
		return ans, passwd_err
	}
	ans, found := pwd[uid]
	if !found {
		return ans, fmt.Errorf("No user matching the UID: %#v found", uid)
	}
	return ans, nil
}

func parse_dscl_data(raw []byte) (ans map[string]PasswdEntry, err error) {
	var pd []any
	_, err = plist.Unmarshal(raw, &pd)
	if err != nil {
		return
	}
	ans = make(map[string]PasswdEntry, 256)
	for _, entry := range pd {
		if e, ok := entry.(map[string]any); ok {
			item := PasswdEntry{}
			for key, a := range e {
				array, ok := a.([]any)
				if !ok || len(array) == 0 || !strings.HasPrefix(key, "dsAttrTypeNative:") {
					continue
				}
				_, key, _ = strings.Cut(key, ":")
				if val, ok := array[0].(string); ok {
					switch key {
					case "uid":
						item.Uid = val
					case "gid":
						item.Gid = val
					case "home":
						item.Home = val
					case "name":
						item.Username = val
					case "realname":
						item.Gecos = val
					case "shell":
						item.Shell = val
					}
				}
			}
			ans[item.Uid] = item
		}
	}
	return
}

var dscl_error error

var dscl_user_database = sync.OnceValue(func() map[string]PasswdEntry {
	c := exec.Command("/usr/bin/dscl", "-plist", ".", "-readall", "/Users", "uid", "gid", "name", "realname", "home", "shell")
	raw, err := c.Output()
	if err != nil {
		dscl_error = err
		return nil
	}
	ans, err := parse_dscl_data(raw)
	if err != nil {
		dscl_error = err
		return nil
	}
	return ans

})

func LoginShellForUser(u *user.User) (ans string, err error) {
	var db map[string]PasswdEntry
	switch runtime.GOOS {
	case "darwin":
		db = dscl_user_database()
		err = dscl_error
	default:
		db = passwd_database()
		err = passwd_err
	}
	if err != nil {
		return
	}
	if rec, found := db[u.Uid]; found {
		return rec.Shell, nil
	}
	return ans, fmt.Errorf("No user record available for user with UID: %#v", u.Uid)
}

func CurrentUser() (ans *user.User, err error) {
	ans, err = user.Current()
	if err != nil && runtime.GOOS == "darwin" {
		uid := strconv.Itoa(os.Geteuid())
		db := dscl_user_database()
		if dscl_error != nil {
			err = dscl_error
			return
		}
		if rec, found := db[uid]; found {
			u := user.User{Uid: uid, Gid: rec.Gid, Username: rec.Username, Name: rec.Gecos, HomeDir: rec.Home}
			ans = &u
			err = nil
		} else {
			err = fmt.Errorf("Could not find the current uid: %d in the DSCL user database", os.Geteuid())
		}
	}
	return
}

func LoginShellForCurrentUser() (ans string, err error) {
	u, err := CurrentUser()
	if err != nil {
		return ans, err
	}
	return LoginShellForUser(u)
}
