package at

import (
	"encoding/json"
	"fmt"
	"kitty/tools/crypto"
	"kitty/tools/utils"
	"testing"
)

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
	serializer, err := create_serializer("", "")
	if err != nil {
		t.Fatal(err)
	}
	var ver = [3]int{1, 2, 3}
	rc := utils.RemoteControlCmd{
		Cmd: "test", Version: ver,
	}
	simple := func(expected string) {
		actual, err := serializer(&rc)
		if err != nil {
			t.Fatal(err)
		}
		as := string(actual)
		if as != expected {
			t.Fatalf("Incorrect serialization: %s != %s", expected, as)
		}
	}
	simple(`{"cmd":"test","version":[1,2,3]}`)
	pubkey_b, _, err := crypto.KeyPair("1")
	if err != nil {
		t.Fatal(err)
	}
	pubkey, err := crypto.EncodePublicKey(pubkey_b, "1")
	if err != nil {
		t.Fatal(err)
	}
	serializer, err = create_serializer("tpw", pubkey)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := serializer(&rc)
	var ec utils.EncryptedRemoteControlCmd
	err = json.Unmarshal([]byte(raw), &ec)
	if err != nil {
		t.Fatal(err)
	}
	if ec.Version != ver {
		t.Fatal("Incorrect version in encrypted command: ", ec.Version)
	}
}
