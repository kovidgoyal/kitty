// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"fmt"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestStringLiteralParsing(t *testing.T) {
	for q, expected := range map[string]string{
		`abc`:                    `abc`,
		`a\nb\M`:                 "a\nb\\M",
		`a\x20\x1\u1234\123\12|`: "a \\x1\u1234\123\x0a|",
	} {
		actual, err := StringLiteral(q)
		if err != nil {
			t.Fatal(err)
		}
		if expected != actual {
			t.Fatalf("Failed with input: %#v\n%#v != %#v", q, expected, actual)
		}
	}
}

func TestParseMap(t *testing.T) {
	// Test without --allow-fallback (default "shifted")
	ka, err := ParseMap("ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted" {
		t.Fatalf("Expected AllowFallback 'shifted', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}
	if diff := cmp.Diff([]string{"ctrl+c"}, ka.Normalized_keys); diff != "" {
		t.Fatalf("Keys mismatch:\n%s", diff)
	}

	// Test with --allow-fallback=ascii
	ka, err = ParseMap("--allow-fallback=ascii ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "ascii" {
		t.Fatalf("Expected AllowFallback 'ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test with --allow-fallback=shifted,ascii
	ka, err = ParseMap("--allow-fallback=shifted,ascii cmd+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted,ascii" {
		t.Fatalf("Expected AllowFallback 'shifted,ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}
	if diff := cmp.Diff([]string{"super+c"}, ka.Normalized_keys); diff != "" {
		t.Fatalf("Keys mismatch:\n%s", diff)
	}

	// Test with --allow-fallback and action args
	ka, err = ParseMap("--allow-fallback=shifted,ascii ctrl+shift+f launch --type=tab grep")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted,ascii" {
		t.Fatalf("Expected AllowFallback 'shifted,ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "launch" {
		t.Fatalf("Expected Name 'launch', got %#v", ka.Name)
	}
	if ka.Args != "--type=tab grep" {
		t.Fatalf("Expected Args '--type=tab grep', got %#v", ka.Args)
	}

	// Test space form: --allow-fallback ascii (without =)
	ka, err = ParseMap("--allow-fallback ascii ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "ascii" {
		t.Fatalf("Expected AllowFallback 'ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}
	if diff := cmp.Diff([]string{"ctrl+c"}, ka.Normalized_keys); diff != "" {
		t.Fatalf("Keys mismatch:\n%s", diff)
	}

	// Test space form: --allow-fallback shifted,ascii
	ka, err = ParseMap("--allow-fallback shifted,ascii cmd+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted,ascii" {
		t.Fatalf("Expected AllowFallback 'shifted,ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test --allow-fallback=none (equals form)
	ka, err = ParseMap("--allow-fallback=none ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "" {
		t.Fatalf("Expected AllowFallback '', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test --allow-fallback none (space form)
	ka, err = ParseMap("--allow-fallback none ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "" {
		t.Fatalf("Expected AllowFallback '', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test error: unknown flag
	_, err = ParseMap("--allow-fallbak=ascii ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for unknown flag --allow-fallbak")
	}

	// Test error: unknown flag without =
	_, err = ParseMap("--unknown ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for unknown flag --unknown")
	}

	// Test error: invalid allow-fallback value
	_, err = ParseMap("--allow-fallback=typo ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for invalid allow-fallback value 'typo'")
	}

	// Test error: invalid allow-fallback value in space form
	_, err = ParseMap("--allow-fallback typo ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for invalid allow-fallback value 'typo' in space form")
	}
}

func TestNormalizeShortcuts(t *testing.T) {
	for q, expected_ := range map[string]string{
		`a`:           `a`,
		`+`:           `plus`,
		`cmd+b>opt+>`: `super+b alt+>`,
		`cmd+>>opt+>`: `super+> alt+>`,
	} {
		expected := strings.Split(expected_, " ")
		actual := NormalizeShortcuts(q)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("failed with input: %#v\n%s", q, diff)
		}
	}
}
