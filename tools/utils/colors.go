package utils

import (
	"fmt"
)

var _ = fmt.Print

func RGBLuminance(r, g, b float32) float32 {
	// From ITU BT 601 https://www.itu.int/rec/R-REC-BT.601
	return 0.299*r + 0.587*g + 0.114*b
}

func RGBContrast(r1, g1, b1, r2, g2, b2 float32) float32 {
	al := RGBLuminance(r1, g1, b1)
	bl := RGBLuminance(r2, g2, b2)
	if al < bl {
		al, bl = bl, al
	}
	return (al + 0.05) / (bl + 0.05)
}
