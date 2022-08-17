package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"golang.org/x/crypto/curve25519"
	"kitty/tools/base85"
	"kitty/tools/utils"
	"os"
	"strings"
	"time"
)

func curve25519_key_pair() (private_key []byte, public_key []byte, err error) {
	private_key = make([]byte, 32)
	_, err = rand.Read(private_key)
	if err == nil {
		public_key, err = curve25519.X25519(private_key[:], curve25519.Basepoint)
	}
	return
}

func curve25519_derive_shared_secret(private_key []byte, public_key []byte) (secret []byte, err error) {
	secret, err = curve25519.X25519(private_key[:], public_key[:])
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

func encrypt(plaintext []byte, alice_public_key []byte) (iv []byte, tag []byte, ciphertext []byte, bob_public_key []byte, err error) {
	bob_private_key, bob_public_key, err := curve25519_key_pair()
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

func Encrypt_cmd(cmd *utils.RemoteControlCmd, password string, other_pubkey []byte) (encrypted_cmd utils.EncryptedRemoteControlCmd, err error) {
	if len(other_pubkey) == 0 {
		raw := os.Getenv("KITTY_PUBLIC_KEY")
		if len(raw) == 0 {
			err = errors.New("No KITTY_PUBLIC_KEY environment variable set cannot use passwords")
			return
		}
		if !strings.HasPrefix(raw, "1:") {
			err = fmt.Errorf("KITTY_PUBLIC_KEY has unknown protocol: %s", raw[:2])
			return
		}
		other_pubkey, err = b85_decode(raw[2:])
		if err != nil {
			return
		}
	}
	cmd.Password = password
	cmd.Timestamp = time.Now().UnixNano()
	plaintext, err := json.Marshal(cmd)
	if err != nil {
		return
	}
	iv, tag, ciphertext, pubkey, err := encrypt(plaintext, other_pubkey)
	encrypted_cmd = utils.EncryptedRemoteControlCmd{
		Version: cmd.Version, IV: b85_encode(iv), Tag: b85_encode(tag), Pubkey: b85_encode(pubkey), Encrypted: b85_encode(ciphertext)}
	return
}

// }}}
