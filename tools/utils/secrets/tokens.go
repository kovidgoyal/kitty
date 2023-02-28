// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package secrets

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"fmt"
)

var _ = fmt.Print

const DEFAULT_NUM_OF_BYTES_FOR_TOKEN = 32

func TokenBytes(nbytes ...int) ([]byte, error) {
	if len(nbytes) == 0 {
		nbytes = []int{DEFAULT_NUM_OF_BYTES_FOR_TOKEN}
	}
	buf := make([]byte, nbytes[0])
	_, err := rand.Read(buf)
	if err != nil {
		return nil, err
	}
	return buf, nil
}

func TokenHex(nbytes ...int) (string, error) {
	b, err := TokenBytes(nbytes...)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func TokenBase64(nbytes ...int) (string, error) {
	b, err := TokenBytes(nbytes...)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(b), nil
}
