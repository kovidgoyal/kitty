package humanize

import (
	"fmt"
	"math"
)

// IEC Sizes.
// kibis of bits
const (
	Byte = 1 << (iota * 10)
	KiByte
	MiByte
	GiByte
	TiByte
	PiByte
	EiByte
)

// SI Sizes.
const (
	IByte = 1
	KByte = IByte * 1000
	MByte = KByte * 1000
	GByte = MByte * 1000
	TByte = GByte * 1000
	PByte = TByte * 1000
	EByte = PByte * 1000
)

func logn(n, b float64) float64 {
	return math.Log(n) / math.Log(b)
}

func humanize_bytes(s uint64, base float64, sizes []string, sep string) string {
	if s < 10 {
		return fmt.Sprintf("%d%sB", s, sep)
	}
	e := math.Floor(logn(float64(s), base))
	suffix := sizes[int(e)]
	val := math.Floor(float64(s)/math.Pow(base, e)*10+0.5) / 10
	f := "%.0f%s%s"
	if val < 10 {
		f = "%.1f%s%s"
	}
	return fmt.Sprintf(f, val, sep, suffix)
}

// Bytes produces a human readable representation of an SI size.
// Bytes(82854982) -> 83 MB
func Bytes(s uint64) string {
	sizes := []string{"B", "kB", "MB", "GB", "TB", "PB", "EB"}
	return humanize_bytes(s, 1000, sizes, " ")
}

// IBytes produces a human readable representation of an IEC size.
// IBytes(82854982) -> 79 MiB
func IBytes(s uint64) string {
	sizes := []string{"B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"}
	return humanize_bytes(s, 1024, sizes, " ")
}
