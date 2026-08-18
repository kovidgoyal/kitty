// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package secrets

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"math/big"

	"github.com/emmansun/base64"
)

var _ = fmt.Print

const DEFAULT_NUM_OF_BYTES_FOR_TOKEN = 32

func encode_bytes(input []byte, alphabet string) string {
	if len(input) == 0 {
		return ""
	}

	base := big.NewInt(int64(len(alphabet)))
	num := new(big.Int).SetBytes(input)
	mod := new(big.Int)

	var result []byte

	// Convert the large integer into the custom base system
	for num.Sign() > 0 {
		num.DivMod(num, base, mod)
		result = append(result, alphabet[mod.Int64()])
	}

	// Preserve leading zeros from the original byte slice
	for _, b := range input {
		if b != 0x00 {
			break
		}
		result = append(result, alphabet[0])
	}

	// Reverse the result slice since DivMod extracts digits backward
	for i, j := 0, len(result)-1; i < j; i, j = i+1, j-1 {
		result[i], result[j] = result[j], result[i]
	}

	return string(result)
}

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

func TokenAlphabet(nbytes int, alphabet string) (string, error) {
	b, err := TokenBytes(nbytes)
	if err != nil {
		return "", err
	}
	return encode_bytes(b, alphabet), nil
}
