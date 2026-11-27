// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/emmansun/base64"
)

var _ = fmt.Print

// The OSC code used to request XDG activation tokens from the terminal, see
// docs/misc-protocol.rst
const ACTIVATION_TOKEN_CODE = 5524

// IsValidActivationTokenId returns true if id can be used as the identifier
// of an activation token request: 1 to 64 characters from a-z A-Z 0-9 _ + . -
func IsValidActivationTokenId(id string) bool {
	if len(id) < 1 || len(id) > 64 {
		return false
	}
	for _, c := range []byte(id) {
		if !(c == '_' || c == '+' || c == '.' || c == '-' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) {
			return false
		}
	}
	return true
}

// QueryActivationTokenSupport asks the terminal whether it can provide XDG
// activation tokens, use ParseActivationTokenResponse() to handle the reply
func (self *Loop) QueryActivationTokenSupport(id string) error {
	if !IsValidActivationTokenId(id) {
		return fmt.Errorf("invalid activation token request identifier: %#v", id)
	}
	self.QueueWriteString(fmt.Sprintf("\x1b]%d;i=%s:p=?\x1b\\", ACTIVATION_TOKEN_CODE, id))
	return nil
}

// RequestActivationToken asks the terminal for an XDG activation token, use
// ParseActivationTokenResponse() to handle the reply, which can arrive after
// the replies to later requests. Use a different identifier for every request.
func (self *Loop) RequestActivationToken(id string) error {
	if !IsValidActivationTokenId(id) {
		return fmt.Errorf("invalid activation token request identifier: %#v", id)
	}
	self.QueueWriteString(fmt.Sprintf("\x1b]%d;i=%s\x1b\\", ACTIVATION_TOKEN_CODE, id))
	return nil
}

// ActivationTokenResponse is a reply to QueryActivationTokenSupport() or RequestActivationToken()
type ActivationTokenResponse struct {
	Id string
	// Whether this is the reply to a query for support
	IsQueryReply bool
	// The token, empty if an error occurred
	Token string
	// The error code, such as ENOTFOCUSED, if no token was provided
	Error string
}

// ParseActivationTokenResponse parses raw, the contents of an OSC escape
// code, returning false if it is not a reply to an activation token request
func ParseActivationTokenResponse(raw []byte) (ans ActivationTokenResponse, ok bool) {
	prefix := fmt.Appendf(nil, "%d;", ACTIVATION_TOKEN_CODE)
	if !bytes.HasPrefix(raw, prefix) {
		return
	}
	metadata, payload, _ := strings.Cut(string(raw[len(prefix):]), ";")
	for item := range strings.SplitSeq(metadata, ":") {
		k, v, found := strings.Cut(item, "=")
		if !found {
			return ans, false
		}
		switch k {
		case "i":
			ans.Id = v
		case "e":
			ans.Error = v
		case "p":
			ans.IsQueryReply = v == "?"
		}
	}
	if ans.Id == "" {
		return ans, false
	}
	switch {
	case ans.IsQueryReply:
		return ans, payload == "ok"
	case ans.Error != "":
		return ans, true
	}
	token, err := base64.StdEncoding.DecodeString(payload)
	if err != nil || len(token) == 0 {
		return ans, false
	}
	ans.Token = string(token)
	return ans, true
}
