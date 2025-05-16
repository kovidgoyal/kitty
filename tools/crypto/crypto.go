// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/base85"
)

func curve25519_key_pair() (private_key []byte, public_key []byte, err error) {
	curve := ecdh.X25519()
	privkey, err := curve.GenerateKey(rand.Reader)
	if err == nil {
		pubkey := privkey.PublicKey()
		return privkey.Bytes(), pubkey.Bytes(), nil
	}
	return nil, nil, err
}

func curve25519_derive_shared_secret(private_key []byte, public_key []byte) (secret []byte, err error) {
	prkey, err := ecdh.X25519().NewPrivateKey(private_key)
	if err != nil {
		return nil, fmt.Errorf("Invalid X25519 private key: %w", err)
	}
	pubkey, err := ecdh.X25519().NewPublicKey(public_key)
	if err != nil {
		return nil, fmt.Errorf("Invalid X25519 public key: %w", err)
	}
	secret, err = prkey.ECDH(pubkey)
	if err != nil {
		err = fmt.Errorf("Failed to perform ECDH shared secret derivation: %w", err)
	}
	return
}

func b85_encode(data []byte) (encoded string) {
	encoded = base85.EncodeToString(data)
	return
}

func b85_decode(data string) (decoded []byte, err error) {
	decoded, err = base85.DecodeString(data)
	return
}

func encrypt(plaintext []byte, alice_public_key []byte, encryption_protocol string) (iv []byte, tag []byte, ciphertext []byte, bob_public_key []byte, err error) {
	bob_private_key, bob_public_key, err := KeyPair(encryption_protocol)
	if err != nil {
		return
	}
	shared_secret_raw, err := curve25519_derive_shared_secret(bob_private_key, alice_public_key)
	if err != nil {
		return
	}
	shared_secret_hashed := sha256.Sum256(shared_secret_raw)
	shared_secret := shared_secret_hashed[:]
	block, err := aes.NewCipher(shared_secret)
	if err != nil {
		return
	}
	aesgcm, err := cipher.NewGCM(block)
	if err != nil {
		return
	}
	iv = make([]byte, aesgcm.NonceSize())
	_, err = rand.Read(iv)
	if err != nil {
		return
	}
	output := aesgcm.Seal(nil, iv, plaintext, nil)
	ciphertext = output[0 : len(output)-16]
	tag = output[len(output)-16:]
	return
}

func KeyPair(encryption_protocol string) (private_key []byte, public_key []byte, err error) {
	switch encryption_protocol {
	case "1":
		return curve25519_key_pair()
	default:
		err = fmt.Errorf("Unknown encryption protocol: %s", encryption_protocol)
		return
	}
}

func EncodePublicKey(pubkey []byte, encryption_protocol string) (ans string, err error) {
	switch encryption_protocol {
	case "1":
		ans = fmt.Sprintf("1:%s", b85_encode(pubkey))
	default:
		err = fmt.Errorf("Unknown encryption protocol: %s", encryption_protocol)
		return
	}
	return
}

func DecodePublicKey(raw string) (encryption_protocol string, pubkey []byte, err error) {
	encryption_protocol, encoded_pubkey, found := strings.Cut(raw, ":")
	if !found {
		return "", nil, fmt.Errorf("Invalid encoded pubkey, no : in string")
	}
	pubkey, err = b85_decode(encoded_pubkey)
	return
}

func Encrypt_cmd(cmd *utils.RemoteControlCmd, password string, other_pubkey []byte, encryption_protocol string) (encrypted_cmd utils.EncryptedRemoteControlCmd, err error) {
	cmd.Password = password
	cmd.Timestamp = time.Now().UnixNano()
	plaintext, err := json.Marshal(cmd)
	if err != nil {
		return
	}
	iv, tag, ciphertext, pubkey, err := encrypt(plaintext, other_pubkey, encryption_protocol)
	encrypted_cmd = utils.EncryptedRemoteControlCmd{
		Version: cmd.Version, IV: b85_encode(iv), Tag: b85_encode(tag), Pubkey: b85_encode(pubkey), Encrypted: b85_encode(ciphertext)}
	if encryption_protocol != "1" {
		encrypted_cmd.EncProto = encryption_protocol
	}
	return
}

func Encrypt_data(data []byte, other_pubkey []byte, encryption_protocol string) (ans []byte, err error) {
	d := make([]byte, 0, uint64(len(data))+32)
	d = fmt.Appendf(d, "%s:", strconv.FormatInt(time.Now().UnixNano(), 10))
	d = append(d, data...)
	iv, tag, ciphertext, pubkey, err := encrypt(d, other_pubkey, encryption_protocol)
	if err != nil {
		return
	}
	ec := utils.EncryptedRemoteControlCmd{
		IV: b85_encode(iv), Tag: b85_encode(tag), Pubkey: b85_encode(pubkey), Encrypted: b85_encode(ciphertext)}
	if encryption_protocol != "1" {
		ec.EncProto = encryption_protocol
	}
	ans, err = json.Marshal(ec)
	return
}

// }}}
