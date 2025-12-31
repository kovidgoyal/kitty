// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"errors"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

var _ = fmt.Println

// Color space conversion functions for wide gamut color support
// Implements OKLCH, Display P3, and CIE LAB color formats with
// CSS Color Module Level 4 gamut mapping.

// srgbToLinear converts sRGB component (0-1) to linear light
func srgbToLinear(c float64) float64 {
	if c <= 0.04045 {
		return c / 12.92
	}
	return math.Pow((c+0.055)/1.055, 2.4)
}

// linearToSrgb converts linear light component (0-1) to sRGB
func linearToSrgb(c float64) float64 {
	if c <= 0.0031308 {
		return c * 12.92
	}
	return 1.055*math.Pow(c, 1.0/2.4) - 0.055
}

// oklabToLinearSrgb converts OKLab to linear sRGB
func oklabToLinearSrgb(l, a, b float64) (float64, float64, float64) {
	l_ := l + 0.3963377774*a + 0.2158037573*b
	m_ := l - 0.1055613458*a - 0.0638541728*b
	s_ := l - 0.0894841775*a - 1.2914855480*b

	l_cubed := l_ * l_ * l_
	m_cubed := m_ * m_ * m_
	s_cubed := s_ * s_ * s_

	r := +4.0767416621*l_cubed - 3.3077115913*m_cubed + 0.2309699292*s_cubed
	g := -1.2684380046*l_cubed + 2.6097574011*m_cubed - 0.3413193965*s_cubed
	b_val := -0.0041960863*l_cubed - 0.7034186147*m_cubed + 1.7076147010*s_cubed

	return r, g, b_val
}

// oklchToSrgb converts OKLCH to sRGB (without gamut mapping)
func oklchToSrgb(l, c, h float64) (float64, float64, float64) {
	// Convert OKLCH to OKLab
	hRad := h * math.Pi / 180.0
	a := c * math.Cos(hRad)
	b := c * math.Sin(hRad)

	// Convert OKLab to linear sRGB
	rLin, gLin, bLin := oklabToLinearSrgb(l, a, b)

	// Apply sRGB transfer function
	r := linearToSrgb(rLin)
	g := linearToSrgb(gLin)
	bVal := linearToSrgb(bLin)

	return r, g, bVal
}

// srgbToOklab converts sRGB to OKLab (for deltaE calculations)
func srgbToOklab(r, g, b float64) (float64, float64, float64) {
	rLin := srgbToLinear(r)
	gLin := srgbToLinear(g)
	bLin := srgbToLinear(b)

	l_ := 0.4122214708*rLin + 0.5363325363*gLin + 0.0514459929*bLin
	m_ := 0.2119034982*rLin + 0.6806995451*gLin + 0.1073969566*bLin
	s_ := 0.0883024619*rLin + 0.2817188376*gLin + 0.6299787005*bLin

	l_ = math.Cbrt(l_)
	m_ = math.Cbrt(m_)
	s_ = math.Cbrt(s_)

	l := 0.2104542553*l_ + 0.7936177850*m_ - 0.0040720468*s_
	a := 1.9779984951*l_ - 2.4285922050*m_ + 0.4505937099*s_
	bVal := 0.0259040371*l_ + 0.7827717662*m_ - 0.8086757660*s_

	return l, a, bVal
}

// deltaEOk calculates perceptual color difference in OKLab space
func deltaEOk(lab1, lab2 [3]float64) float64 {
	dl := lab1[0] - lab2[0]
	da := lab1[1] - lab2[1]
	db := lab1[2] - lab2[2]
	return math.Sqrt(dl*dl + da*da + db*db)
}

// oklchToSrgbGamutMap converts OKLCH to sRGB with CSS Color Module Level 4 gamut mapping
func oklchToSrgbGamutMap(l, c, h float64) (float64, float64, float64) {
	// Constants from CSS Color Module Level 4
	const jnd = 0.02              // Just Noticeable Difference threshold
	const minConvergence = 0.0001 // Binary search precision
	const epsilon = 0.00001       // Small value for floating point comparisons

	// Edge cases: pure black or white
	if l <= 0.0 {
		return 0.0, 0.0, 0.0
	}
	if l >= 1.0 {
		return 1.0, 1.0, 1.0
	}

	// If chroma is very small, color is achromatic
	if c < epsilon {
		gray := linearToSrgb(l)
		return gray, gray, gray
	}

	// Try the original color first
	r, g, b := oklchToSrgb(l, c, h)

	// Check if already in gamut
	if r >= 0.0 && r <= 1.0 && g >= 0.0 && g <= 1.0 && b >= 0.0 && b <= 1.0 {
		return r, g, b
	}

	// Binary search for maximum in-gamut chroma
	lowChroma := 0.0
	highChroma := c

	for (highChroma - lowChroma) > minConvergence {
		midChroma := (highChroma + lowChroma) * 0.5

		// Try this chroma value
		rTest, gTest, bTest := oklchToSrgb(l, midChroma, h)

		// Check if in gamut (before clipping)
		inGamut := rTest >= 0.0 && rTest <= 1.0 &&
			gTest >= 0.0 && gTest <= 1.0 &&
			bTest >= 0.0 && bTest <= 1.0

		if inGamut {
			// In gamut - try higher chroma
			lowChroma = midChroma
		} else {
			// Out of gamut - clip and check deltaE
			rClipped := math.Max(0.0, math.Min(1.0, rTest))
			gClipped := math.Max(0.0, math.Min(1.0, gTest))
			bClipped := math.Max(0.0, math.Min(1.0, bTest))

			// Convert both to OKLab for comparison
			lTest, aTest, bTestLab := srgbToOklab(rTest, gTest, bTest)
			testLab := [3]float64{lTest, aTest, bTestLab}

			lClip, aClip, bClip := srgbToOklab(rClipped, gClipped, bClipped)
			clippedLab := [3]float64{lClip, aClip, bClip}

			// Calculate perceptual difference
			de := deltaEOk(testLab, clippedLab)

			if de < jnd {
				// Difference is imperceptible - accept this chroma
				lowChroma = midChroma
			} else {
				// Difference is noticeable - reduce chroma more
				highChroma = midChroma
			}
		}
	}

	// Use the final chroma value and clip to ensure in-gamut
	rFinal, gFinal, bFinal := oklchToSrgb(l, lowChroma, h)
	return math.Max(0.0, math.Min(1.0, rFinal)),
		math.Max(0.0, math.Min(1.0, gFinal)),
		math.Max(0.0, math.Min(1.0, bFinal))
}

// labToOklch converts CIE LAB to OKLCH for gamut mapping
func labToOklch(l, a, b float64) (float64, float64, float64) {
	// LAB to XYZ (using D65 illuminant)
	y := (l + 16) / 116
	x := a/500 + y
	z := y - b/200

	fInv := func(t float64) float64 {
		delta := 6.0 / 29.0
		if t > delta {
			return t * t * t
		}
		return 3 * delta * delta * (t - 4.0/29.0)
	}

	// D65 white point
	const xN = 0.95047
	const yN = 1.00000
	const zN = 1.08883

	xVal := xN * fInv(x)
	yVal := yN * fInv(y)
	zVal := zN * fInv(z)

	// XYZ to linear sRGB
	rLin := +3.2404542*xVal - 1.5371385*yVal - 0.4985314*zVal
	gLin := -0.9692660*xVal + 1.8760108*yVal + 0.0415560*zVal
	bLin := +0.0556434*xVal - 0.2040259*yVal + 1.0572252*zVal

	// Convert to OKLab
	l_ := 0.4122214708*rLin + 0.5363325363*gLin + 0.0514459929*bLin
	m_ := 0.2119034982*rLin + 0.6806995451*gLin + 0.1073969566*bLin
	s_ := 0.0883024619*rLin + 0.2817188376*gLin + 0.6299787005*bLin

	l_ = math.Cbrt(l_)
	m_ = math.Cbrt(m_)
	s_ = math.Cbrt(s_)

	lOk := 0.2104542553*l_ + 0.7936177850*m_ - 0.0040720468*s_
	aOk := 1.9779984951*l_ - 2.4285922050*m_ + 0.4505937099*s_
	bOk := 0.0259040371*l_ + 0.7827717662*m_ - 0.8086757660*s_

	// Convert OKLab to OKLCH
	c := math.Sqrt(aOk*aOk + bOk*bOk)
	h := math.Atan2(bOk, aOk) * 180.0 / math.Pi
	if h < 0 {
		h += 360
	}

	return lOk, c, h
}

// parseOklch parses OKLCH color: oklch(l c h) or oklch(l, c, h)
func parseOklch(spec string) (RGBA, error) {
	spec = strings.TrimRight(spec, ")")
	parts := splitColorComponents(spec)

	if len(parts) != 3 {
		return RGBA{}, errors.New("not enough parts")
	}

	l, err := parseFloatValue(parts[0])
	if err != nil {
		return RGBA{}, err
	}
	c, err := parseFloatValue(parts[1])
	if err != nil {
		return RGBA{}, err
	}
	h, err := parseFloatValue(parts[2])
	if err != nil {
		return RGBA{}, err
	}

	// Validate for NaN and infinity
	if math.IsNaN(l) || math.IsInf(l, 0) ||
		math.IsNaN(c) || math.IsInf(c, 0) ||
		math.IsNaN(h) || math.IsInf(h, 0) {
		return RGBA{}, errors.New("invalid float value")
	}

	// Handle percentages for L
	if strings.Contains(parts[0], "%") {
		l /= 100.0
	}

	// Clamp to reasonable ranges
	l = max(0.0, min(l, 1.0))
	c = max(0.0, c)      // Chroma is unbounded
	h = math.Mod(h, 360) // Wrap hue to 0-360
	if h < 0 {
		h += 360
	}

	// Convert OKLCH to sRGB with gamut mapping
	r, g, b := oklchToSrgbGamutMap(l, c, h)
	return RGBA{as8bit(r), as8bit(g), as8bit(b), 0}, nil
}

func as8bit(x float64) uint8 { return uint8(math.Round(x * 255)) }

// parseLab parses LAB color: lab(l a b) or lab(l, a, b)
func parseLab(spec string) (RGBA, error) {
	spec = strings.TrimRight(spec, ")")
	parts := splitColorComponents(spec)

	if len(parts) != 3 {
		return RGBA{}, errors.New("not enough parts")
	}

	l, err := parseFloatValue(parts[0])
	if err != nil {
		return RGBA{}, err
	}
	a, err := parseFloatValue(parts[1])
	if err != nil {
		return RGBA{}, err
	}
	b, err := parseFloatValue(parts[2])
	if err != nil {
		return RGBA{}, err
	}

	// Validate for NaN and infinity
	if math.IsNaN(l) || math.IsInf(l, 0) ||
		math.IsNaN(a) || math.IsInf(a, 0) ||
		math.IsNaN(b) || math.IsInf(b, 0) {
		return RGBA{}, errors.New("invalid float value")
	}

	// Clamp L to 0-100
	l = max(0.0, min(l, 100.0))

	// Convert LAB to OKLCH, then use gamut mapping to sRGB
	lOk, c, h := labToOklch(l, a, b)

	// Apply gamut mapping in OKLCH space
	r, g, bVal := oklchToSrgbGamutMap(lOk, c, h)
	return RGBA{as8bit(r), as8bit(g), as8bit(bVal), 0}, nil
}

// splitColorComponents splits color components by comma or whitespace
func splitColorComponents(spec string) []string {
	re := regexp.MustCompile(`[,\s]+`)
	parts := re.Split(spec, -1)

	var result []string
	for _, part := range parts {
		part = strings.TrimSpace(part)
		part = strings.TrimRight(part, "%,")
		if part != "" {
			result = append(result, part)
		}
	}
	return result
}

// parseFloatValue parses a float value, handling percentages
func parseFloatValue(s string) (float64, error) {
	s = strings.TrimSpace(s)
	s = strings.TrimRight(s, "%,")
	return strconv.ParseFloat(s, 64)
}
