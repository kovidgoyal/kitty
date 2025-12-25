// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"testing"
)

// Benchmark color parsing functions to demonstrate performance

func BenchmarkParseOklch(b *testing.B) {
	for i := 0; i < b.N; i++ {
		_, _ = parseOklch("0.5 0.1 180")
	}
}

func BenchmarkParseLab(b *testing.B) {
	for i := 0; i < b.N; i++ {
		_, _ = parseLab("50 0 0")
	}
}

func BenchmarkParseColorHex(b *testing.B) {
	for i := 0; i < b.N; i++ {
		_, _ = ParseColor("#ff0000")
	}
}

func BenchmarkParseColorOklch(b *testing.B) {
	for i := 0; i < b.N; i++ {
		_, _ = ParseColor("oklch(0.5 0.1 180)")
	}
}

func BenchmarkParseColorLab(b *testing.B) {
	for i := 0; i < b.N; i++ {
		_, _ = ParseColor("lab(50 0 0)")
	}
}

func BenchmarkParseColorWithComment(b *testing.B) {
	for i := 0; i < b.N; i++ {
		_, _ = ParseColor("oklch(0.5 0.1 180) # vibrant color")
	}
}

// Benchmark the gamut mapping algorithm specifically
func BenchmarkOklchToSrgbGamutMap(b *testing.B) {
	for i := 0; i < b.N; i++ {
		oklchToSrgbGamutMap(0.7, 0.4, 25) // Very saturated color requiring gamut mapping
	}
}

func BenchmarkOklchToSrgbGamutMapInGamut(b *testing.B) {
	for i := 0; i < b.N; i++ {
		oklchToSrgbGamutMap(0.5, 0.05, 180) // Already in gamut
	}
}

// Benchmark parsing many colors (simulating config file parsing)
func BenchmarkParseManyColors(b *testing.B) {
	colors := []string{
		"#ff0000",
		"#00ff00",
		"#0000ff",
		"oklch(0.5 0.1 180)",
		"lab(50 20 -30)",
		"rgb:ff/00/00",
		"red",
		"blue",
		"green",
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		for _, color := range colors {
			_, _ = ParseColor(color)
		}
	}
}
