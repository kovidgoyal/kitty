package base85

import (
	"testing"
	"fmt"
)

func TestChunked (t *testing.T) {
	a := []byte("M")
	fmt.Printf("a %#v\n", a)
	b := make([]byte, EncodedLen(len(a)))
	encodeChunk(b, a)
	fmt.Printf("b %#v\n", b)
	c := make([]byte, DecodedLen(len(b)))
	decodeChunk(c, b)
	fmt.Printf("c %#v\n", c)

	a = []byte("Ma")
	fmt.Printf("a %#v\n", a)
	b = make([]byte, EncodedLen(len(a)))
	encodeChunk(b, a)
	fmt.Printf("b %#v\n", b)
	c = make([]byte, DecodedLen(len(b)))
	decodeChunk(c, b)
	fmt.Printf("c %#v\n", c)

	a = []byte("Man")
	fmt.Printf("a %#v\n", a)
	b = make([]byte, EncodedLen(len(a)))
	encodeChunk(b, a)
	fmt.Printf("b %#v\n", b)
	c = make([]byte, DecodedLen(len(b)))
	decodeChunk(c, b)
	fmt.Printf("c %#v\n", c)

	a = []byte("Man ")
	fmt.Printf("a %#v\n", a)
	b = make([]byte, EncodedLen(len(a)))
	encodeChunk(b, a)
	fmt.Printf("b %#v\n", b)
	c = make([]byte, DecodedLen(len(b)))
	decodeChunk(c, b)
	fmt.Printf("c %#v\n", c)

	a = []byte("Manual")
	fmt.Printf("a %#v\n", a)
	b = make([]byte, EncodedLen(len(a)))
	n := Encode(b, a)
	fmt.Printf("b %#v %d\n", b, n)
	c = make([]byte, DecodedLen(len(b)))
	n, _ = Decode(c, b)
	fmt.Printf("c %#v %d\n", c, n)

	a = []byte("Manual")
	fmt.Printf("a %s\n", a)
	sb := EncodeToString(a) + "\""
	fmt.Printf("b %#v\n", sb)
	sc, err := DecodeString(sb)
	fmt.Printf("c %s %s\n", sc, err)
}
