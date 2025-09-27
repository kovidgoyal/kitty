// License: GPLv3 Copyright: 2025

package ssh

import (
    "fmt"
    "path/filepath"
    "strconv"
    "strings"

    "github.com/kovidgoyal/kitty/tools/config"
)

// AuthEntry holds per-host auth automation data parsed from ssh.conf
type AuthEntry struct {
    Hostname    string // space-separated patterns, may include user@host
    Password    string
    TOTPSecret  string
    TOTPDigits  int // default 6
    TOTPPeriod  int // default 30
}

type authConfigSet struct {
    entries []*AuthEntry
}

func (a *authConfigSet) lineHandler(key, val string) error {
    if key == "hostname" {
        a.entries = append(a.entries, &AuthEntry{Hostname: strings.TrimSpace(val)})
        return nil
    }
    if len(a.entries) == 0 {
        // Ensure there is always a default block
        a.entries = append(a.entries, &AuthEntry{Hostname: "*"})
    }
    cur := a.entries[len(a.entries)-1]
    switch key {
    case "password":
        cur.Password = strings.TrimSpace(val)
        return nil
    case "totp_secret":
        cur.TOTPSecret = strings.TrimSpace(val)
        return nil
    case "totp_digits":
        vv := strings.TrimSpace(val)
        if vv == "" {
            cur.TOTPDigits = 0
            return nil
        }
        n, err := strconv.Atoi(vv)
        if err != nil {
            return fmt.Errorf("Failed to parse totp_digits = %#v with error: %w", val, err)
        }
        cur.TOTPDigits = n
        return nil
    case "totp_period":
        vv := strings.TrimSpace(val)
        if vv == "" {
            cur.TOTPPeriod = 0
            return nil
        }
        n, err := strconv.Atoi(vv)
        if err != nil {
            return fmt.Errorf("Failed to parse totp_period = %#v with error: %w", val, err)
        }
        cur.TOTPPeriod = n
        return nil
    default:
        // ignore unrelated keys
        return nil
    }
}

// matchAuthEntry finds the best matching AuthEntry using the same matching logic as ssh.conf
func matchAuthEntry(hostnameToMatch, usernameToMatch string, entries []*AuthEntry) *AuthEntry {
    matcher := func(e *AuthEntry) bool {
        for _, pat := range strings.Split(e.Hostname, " ") {
            upat := "*"
            if strings.Contains(pat, "@") {
                upat, pat, _ = strings.Cut(pat, "@")
            }
            var hostMatched, userMatched bool
            if matched, err := filepath.Match(pat, hostnameToMatch); matched && err == nil {
                hostMatched = true
            }
            if matched, err := filepath.Match(upat, usernameToMatch); matched && err == nil {
                userMatched = true
            }
            if hostMatched && userMatched {
                return true
            }
        }
        return false
    }
    for i := len(entries) - 1; i >= 0; i-- {
        if matcher(entries[i]) {
            return entries[i]
        }
    }
    if len(entries) > 0 {
        return entries[0]
    }
    return &AuthEntry{Hostname: "*"}
}

// LoadAuthForHost parses ssh.conf and returns the auth settings for the matching host/user
func LoadAuthForHost(hostnameToMatch, usernameToMatch string, paths ...string) (*AuthEntry, error) {
    acs := &authConfigSet{entries: []*AuthEntry{&AuthEntry{Hostname: "*"}}}
    p := config.ConfigParser{LineHandler: acs.lineHandler}
    if err := p.LoadConfig("ssh.conf", paths, nil); err != nil {
        return nil, err
    }
    // Defaults
    for _, e := range acs.entries {
        if e.TOTPDigits == 0 {
            e.TOTPDigits = 6
        }
        if e.TOTPPeriod == 0 {
            e.TOTPPeriod = 30
        }
    }
    return matchAuthEntry(hostnameToMatch, usernameToMatch, acs.entries), nil
}

