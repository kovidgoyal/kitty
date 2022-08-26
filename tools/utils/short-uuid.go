// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"crypto/rand"
	"math"
	"math/big"

	"github.com/ALTree/bigfloat"
	"github.com/google/uuid"
)

const (
	ESCAPE_CODE_SAFE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "
	HUMAN_ALPHABET            = "23456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

func num_to_string(number *big.Int, alphabet []rune, alphabet_len *big.Int, pad_to_length int) string {
	var zero, digit big.Int
	if number.Sign() < 0 {
		*number = zero
	}
	capacity := 64
	if pad_to_length > capacity {
		capacity = pad_to_length
	}
	ans := make([]rune, 0, capacity)
	for number.Cmp(&zero) == 1 {
		number.DivMod(number, alphabet_len, &digit)
		ans = append(ans, alphabet[digit.Uint64()])
	}
	al := len(ans)
	if pad_to_length > -1 && al < pad_to_length {
		ans = ans[:pad_to_length]
		for i := al; i < pad_to_length; i++ {
			ans[i] = alphabet[0]
		}
	}
	return string(ans)
}

func get_padding_length(alphabet_len int) int {
	bi := big.NewInt(2)
	bi = bi.Exp(bi, big.NewInt(128), nil)
	bb := new(big.Float).SetPrec(256)
	bb.SetInt(bi)
	log_al := bigfloat.Log(big.NewFloat(float64(alphabet_len)).SetPrec(256))
	log_b := bigfloat.Log(bb)
	res := new(big.Float).SetPrec(256)
	res = res.Quo(log_b, log_al)
	val, _ := res.Float64()
	return int(math.Ceil(val))
}

type ShortUUID struct {
	alphabet      []rune
	alphabet_len  big.Int
	pad_to_length int
}

func CreateShortUUID(alphabet string) *ShortUUID {
	if alphabet == "" {
		alphabet = HUMAN_ALPHABET
	}
	var ans = ShortUUID{
		alphabet: []rune(alphabet),
	}
	ans.pad_to_length = get_padding_length(len(ans.alphabet))
	ans.alphabet_len.SetUint64(uint64(len(ans.alphabet)))
	return &ans
}

func (self *ShortUUID) Random(num_bits int64) (string, error) {
	max := big.NewInt(0).Exp(big.NewInt(2), big.NewInt(num_bits), nil)
	bi, err := rand.Int(rand.Reader, max)
	if err != nil {
		return "", err
	}
	return num_to_string(bi, self.alphabet, &self.alphabet_len, self.pad_to_length), nil
}

func (self *ShortUUID) Uuid4() (string, error) {
	b, err := uuid.NewRandom()
	if err != nil {
		return "", err
	}
	bb, err := b.MarshalBinary()
	if err != nil {
		return "", err
	}
	var bi big.Int
	bi.SetBytes(bb)
	return num_to_string(&bi, self.alphabet, &self.alphabet_len, self.pad_to_length), nil
}

var HumanUUID *ShortUUID

func HumanUUID4() (string, error) {
	if HumanUUID == nil {
		HumanUUID = CreateShortUUID(HUMAN_ALPHABET)
	}
	return HumanUUID.Uuid4()
}

func HumanRandomId(num_bits int64) (string, error) {
	if HumanUUID == nil {
		HumanUUID = CreateShortUUID(HUMAN_ALPHABET)
	}
	return HumanUUID.Random(num_bits)
}
