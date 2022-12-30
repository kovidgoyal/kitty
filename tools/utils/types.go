// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

type RemoteControlCmd struct {
	Cmd           string `json:"cmd"`
	Version       [3]int `json:"version"`
	NoResponse    bool   `json:"no_response,omitempty"`
	Timestamp     int64  `json:"timestamp,omitempty"`
	Password      string `json:"password,omitempty"`
	Async         string `json:"async,omitempty"`
	CancelAsync   bool   `json:"cancel_async,omitempty"`
	Stream        bool   `json:"stream,omitempty"`
	StreamId      string `json:"stream_id,omitempty"`
	KittyWindowId uint   `json:"kitty_window_id,omitempty"`
	Payload       any    `json:"payload,omitempty"`
}

type EncryptedRemoteControlCmd struct {
	Version   [3]int `json:"version"`
	IV        string `json:"iv"`
	Tag       string `json:"tag"`
	Pubkey    string `json:"pubkey"`
	Encrypted string `json:"encrypted"`
	EncProto  string `json:"enc_proto,omitempty"`
}
