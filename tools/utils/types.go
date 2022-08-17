package utils

type RemoteControlCmd struct {
	Cmd        string                 `json:"cmd"`
	Version    [3]int                 `json:"version"`
	NoResponse bool                   `json:"no_response,omitifempty"`
	Payload    map[string]interface{} `json:"payload,omitifempty"`
	Timestamp  int64                  `json:"timestamp,omitifempty"`
	Password   string                 `json:"password,omitifempty"`
}

type EncryptedRemoteControlCmd struct {
	Version   [3]int `json:"version"`
	IV        string `json:"iv"`
	Tag       string `json:"tag"`
	Pubkey    string `json:"pubkey"`
	Encrypted string `json:"encrypted"`
}
