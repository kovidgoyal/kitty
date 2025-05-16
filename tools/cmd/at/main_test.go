// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"encoding/json"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/crypto"
	"github.com/kovidgoyal/kitty/tools/utils"
	"testing"
)

func TestEncodeJSON(t *testing.T) {
	tests := map[string]string{
		"a b\nc\td\a": `a b\nc\td\u0007`,
		"•":           `\u2022`,
		`a"b\c`:       `a\"b\\c`,
		"\U0001f123":  `\ud83c\udd23`,
	}
	var s escaped_string
	for x, expected := range tests {
		s = escaped_string(x)
		expected = `"` + expected + `"`
		actualb, _ := s.MarshalJSON()
		actual := string(actualb)
		if expected != actual {
			t.Fatalf("Failed for %#v\n%#v != %#v", x, expected, actual)
		}
	}

}

func TestCommandToJSON(t *testing.T) {
	pv := fmt.Sprint(ProtocolVersion[0], ",", ProtocolVersion[1], ",", ProtocolVersion[2])
	rc, err := create_rc_ls([]string{})
	if err != nil {
		t.Fatal(err)
	}

	marshal := func(rc *utils.RemoteControlCmd) string {
		q, err := json.Marshal(rc)
		if err != nil {
			t.Fatal(err)
		}
		return string(q)
	}

	test := func(rc *utils.RemoteControlCmd, rest string) {
		q := marshal(rc)
		expected := `{"cmd":"` + rc.Cmd + `","version":[` + pv + `]`
		expected += rest + "}"
		if q != expected {
			t.Fatalf("expected != actual: %#v != %#v", expected, q)
		}
	}
	test(rc, "")
}

func TestRCSerialization(t *testing.T) {
	io_data := rc_io_data{}
	err := create_serializer(password{"", false}, "", &io_data)
	if err != nil {
		t.Fatal(err)
	}
	var ver = [3]int{1, 2, 3}
	rc := utils.RemoteControlCmd{
		Cmd: "test", Version: ver,
	}
	simple := func(expected string) {
		actual, err := io_data.serializer(&rc)
		if err != nil {
			t.Fatal(err)
		}
		as := string(actual)
		if as != expected {
			t.Fatalf("Incorrect serialization: %s != %s", expected, as)
		}
	}
	simple(string(`{"cmd":"test","version":[1,2,3]}`))
	pubkey_b, _, err := crypto.KeyPair("1")
	if err != nil {
		t.Fatal(err)
	}
	pubkey, err := crypto.EncodePublicKey(pubkey_b, "1")
	if err != nil {
		t.Fatal(err)
	}
	err = create_serializer(password{"tpw", true}, pubkey, &io_data)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io_data.serializer(&rc)
	if err != nil {
		t.Fatal(err)
	}
	var ec utils.EncryptedRemoteControlCmd
	err = json.Unmarshal([]byte(raw), &ec)
	if err != nil {
		t.Fatal(err)
	}
	if ec.Version != ver {
		t.Fatal("Incorrect version in encrypted command: ", ec.Version)
	}
}
