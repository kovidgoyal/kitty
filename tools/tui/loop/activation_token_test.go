// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestActivationTokenResponses(t *testing.T) {
	for raw, expected := range map[string]ActivationTokenResponse{
		"5524;i=q:p=?;ok":          {Id: "q", IsQueryReply: true},
		"5524;i=t1;dG9rZW4=":       {Id: "t1", Token: "token"},
		"5524;i=t1:e=ENOTFOCUSED":  {Id: "t1", Error: "ENOTFOCUSED"},
		"5524;i=t1:x=new;dG9rZW4=": {Id: "t1", Token: "token"},
	} {
		actual, ok := ParseActivationTokenResponse([]byte(raw))
		if !ok {
			t.Fatalf("Valid response not parsed: %#v", raw)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Incorrect parse of %#v:\n%s", raw, diff)
		}
	}
	for _, raw := range []string{"", "5524", "552;i=x;dG9rZW4=", "5524;dG9rZW4=", "5524;i=t1;", "5524;i=t1;!!!", "5524;i=q:p=?;no", "5524;junk;x", "2254;a=q"} {
		if ans, ok := ParseActivationTokenResponse([]byte(raw)); ok {
			t.Fatalf("Invalid response %#v parsed as: %#v", raw, ans)
		}
	}
}
