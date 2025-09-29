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
    // The secret backends currently supported are:
    //   - text: store the secret directly in the config as plain text
    // The config format is "backend:secret". For backward compatibility,
    // a value without a backend is treated as "text:<value>".
    Password           string
    PasswordBackend    string
    TOTPSecret         string
    TOTPSecretBackend  string
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
        b, s, err := parseBackendSecret("password", val)
        if err != nil {
            return err
        }
        cur.PasswordBackend = b
        cur.Password = s
        return nil
    case "totp_secret":
        b, s, err := parseBackendSecret("totp_secret", val)
        if err != nil {
            return err
        }
        cur.TOTPSecretBackend = b
        cur.TOTPSecret = s
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
    // Surface errors related only to our auth lines so users get feedback
    // for invalid backend specifications while ignoring unrelated ssh.conf issues.
    for _, bl := range p.BadLines() {
        line := strings.TrimSpace(bl.Line)
        if strings.HasPrefix(line, "password ") || strings.HasPrefix(line, "totp_secret ") {
            if bl.Err != nil {
                return nil, bl.Err
            }
        }
    }
    // Defaults
    for _, e := range acs.entries {
        if e.TOTPDigits == 0 {
            e.TOTPDigits = 6
        }
        if e.TOTPPeriod == 0 {
            e.TOTPPeriod = 30
        }
        // Normalize empty backends to text for backward compatibility
        if e.Password != "" && e.PasswordBackend == "" {
            e.PasswordBackend = "text"
        }
        if e.TOTPSecret != "" && e.TOTPSecretBackend == "" {
            e.TOTPSecretBackend = "text"
        }
    }
    return matchAuthEntry(hostnameToMatch, usernameToMatch, acs.entries), nil
}

// parseBackendSecret parses a value of the form "backend:secret".
// Currently only the "text" backend is supported. A value without a colon
// is treated as a plain text secret for backward compatibility.
func parseBackendSecret(settingKey, raw string) (backend, secret string, err error) {
    v := strings.TrimSpace(raw)
    if v == "" {
        return "", "", nil
    }
    if b, s, ok := strings.Cut(v, ":"); ok {
        b = strings.ToLower(strings.TrimSpace(b))
        s = strings.TrimSpace(s)
        switch b {
        case "text":
            return b, s, nil
        default:
            return "", "", fmt.Errorf("Unsupported secret backend %q for %s. Supported backends: text", b, settingKey)
        }
    }
    // No backend specified; treat as text backend for backward compatibility
    return "text", v, nil
}
