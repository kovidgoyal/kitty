// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"image"
	"math"
	"strings"
	"sync"

	"golang.org/x/image/font"
	"golang.org/x/image/font/gofont/goregular"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"

	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

// Applications without an icon are shown with a placeholder: the first
// letter of their name, or a prompt for custom commands. It is rendered as an
// image, rather than as text drawn with the text sizing protocol, so that it
// can be partially displayed, clipped to the grid, as the grid is scrolled.
// The image uses indexed color data, the default foreground color, partially
// transparent, so it looks like dim text in any color scheme.

const (
	placeholder_color = 249 // the default foreground color
	placeholder_alpha = 0.5
	// The text used for custom commands and names whose first letter is
	// not in the font
	command_placeholder = ">_"
)

var placeholder_font = sync.OnceValues(func() (*opentype.Font, error) {
	return opentype.Parse(goregular.TTF)
})

// placeholder_text returns the text to display for an item without an icon
func placeholder_text(it *item) string {
	if it.is_custom_command() {
		return command_placeholder
	}
	for _, r := range it.entry.Name {
		if wcswidth.Runewidth(r) == 1 {
			return strings.ToUpper(string(r))
		}
		break
	}
	return command_placeholder
}

// render_placeholder renders text, centered, in an image of the specified
// size whose text height is a fraction of the height of the image, returning
// the image as palette index and alpha pairs
func render_placeholder(text string, width, height int, text_height float64) ([]byte, error) {
	f, err := placeholder_font()
	if err != nil {
		return nil, fmt.Errorf("failed to load the font for placeholders: %w", err)
	}
	new_face := func(size float64) (font.Face, error) {
		return opentype.NewFace(f, &opentype.FaceOptions{Size: size, DPI: 72, Hinting: font.HintingNone})
	}
	// Scale the font so that its ascent plus descent is text_height
	face, err := new_face(float64(height))
	if err != nil {
		return nil, err
	}
	m := face.Metrics()
	natural := float64(m.Ascent+m.Descent) / 64
	if natural <= 0 {
		return nil, fmt.Errorf("the font for placeholders has invalid metrics")
	}
	size := float64(height) * float64(height) * text_height / natural
	_ = face.Close()
	if face, err = new_face(size); err != nil {
		return nil, err
	}
	defer face.Close()
	if _, ok := face.GlyphAdvance([]rune(text)[0]); !ok {
		text = command_placeholder
	}
	m = face.Metrics()
	img := image.NewAlpha(image.Rect(0, 0, width, height))
	d := font.Drawer{Dst: img, Src: image.Opaque, Face: face}
	advance := d.MeasureString(text)
	text_h := m.Ascent + m.Descent
	d.Dot = fixed.Point26_6{
		X: (fixed.I(width) - advance) / 2,
		Y: (fixed.I(height)-text_h)/2 + m.Ascent,
	}
	d.DrawString(text)
	ans := make([]byte, 2*width*height)
	for i, a := range img.Pix {
		if a > 0 {
			ans[2*i], ans[2*i+1] = placeholder_color, uint8(math.Round(float64(a)*placeholder_alpha))
		}
	}
	return ans, nil
}
