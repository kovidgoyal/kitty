// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"math"
	"testing"
)

func TestParseOklch(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  RGBA
	}{
		{
			name:  "basic oklch",
			input: "0.5 0.1 180",
			want:  RGBA{Red: 0, Green: 117, Blue: 101}, // cyan-ish with gamut mapping
		},
		{
			name:  "white",
			input: "1.0 0 0",
			want:  RGBA{Red: 255, Green: 255, Blue: 255},
		},
		{
			name:  "black",
			input: "0 0 0",
			want:  RGBA{Red: 0, Green: 0, Blue: 0},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseOklch(tt.input)
			if err != nil {
				t.Errorf("parseOklch() error = %v", err)
				return
			}
			// Allow some tolerance due to rounding
			if math.Abs(float64(got.Red)-float64(tt.want.Red)) > 2 ||
				math.Abs(float64(got.Green)-float64(tt.want.Green)) > 2 ||
				math.Abs(float64(got.Blue)-float64(tt.want.Blue)) > 2 {
				t.Errorf("parseOklch() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestParseLab(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  RGBA
	}{
		{
			name:  "basic lab",
			input: "50 0 0",
			want:  RGBA{Red: 198, Green: 198, Blue: 198}, // light gray (LAB 50 is lighter than sRGB 50%)
		},
		{
			name:  "white",
			input: "100 0 0",
			want:  RGBA{Red: 255, Green: 255, Blue: 255},
		},
		{
			name:  "black",
			input: "0 0 0",
			want:  RGBA{Red: 0, Green: 0, Blue: 0},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseLab(tt.input)
			if err != nil {
				t.Errorf("parseLab() error = %v", err)
				return
			}
			// Allow some tolerance due to rounding
			if math.Abs(float64(got.Red)-float64(tt.want.Red)) > 2 ||
				math.Abs(float64(got.Green)-float64(tt.want.Green)) > 2 ||
				math.Abs(float64(got.Blue)-float64(tt.want.Blue)) > 2 {
				t.Errorf("parseLab() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestParseColor(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		wantErr bool
	}{
		{
			name:    "oklch format",
			input:   "oklch(0.5 0.1 180)",
			wantErr: false,
		},
		{
			name:    "lab format",
			input:   "lab(50 0 0)",
			wantErr: false,
		},
		{
			name:    "with inline comment",
			input:   "oklch(0.5 0.1 180) # vibrant color",
			wantErr: false,
		},
		{
			name:    "hex color",
			input:   "#ff0000",
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := ParseColor(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseColor() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
