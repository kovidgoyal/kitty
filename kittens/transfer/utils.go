// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/crypto"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
)

var _ = fmt.Print

var global_cwd, global_home string

func cwd_path() string {
	if global_cwd == "" {
		ans, _ := os.Getwd()
		return ans
	}
	return global_cwd
}

func home_path() string {
	if global_home == "" {
		return utils.Expanduser("~")
	}
	return global_home
}

func encode_bypass(request_id string, bypass string) (string, error) {
	q := request_id + ";" + bypass
	if pkey_encoded := os.Getenv("KITTY_PUBLIC_KEY"); pkey_encoded != "" {
		encryption_protocol, pubkey, err := crypto.DecodePublicKey(pkey_encoded)
		if err != nil {
			return "", err
		}
		encrypted, err := crypto.Encrypt_data(utils.UnsafeStringToBytes(q), pubkey, encryption_protocol)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("kitty-1:%s", utils.UnsafeBytesToString(encrypted)), nil
	}
	return "", fmt.Errorf("KITTY_PUBLIC_KEY env var not set, cannot transmit password securely")
}

func abspath(path string, use_home ...bool) string {
	if filepath.IsAbs(path) {
		return path
	}
	var base string
	if len(use_home) > 0 && use_home[0] {
		base = home_path()
	} else {
		base = cwd_path()
	}
	return filepath.Join(base, path)
}

func expand_home(path string) string {
	if strings.HasPrefix(path, "~"+string(os.PathSeparator)) {
		path = strings.TrimLeft(path[2:], string(os.PathSeparator))
		path = filepath.Join(home_path(), path)
	} else if path == "~" {
		path = home_path()
	}
	return path
}

func random_id() string {
	bytes := []byte{0, 0}
	rand.Read(bytes)
	return fmt.Sprintf("%x%s", os.Getpid(), hex.EncodeToString(bytes))
}

func run_with_paths(cwd, home string, f func()) {
	global_cwd, global_home = cwd, home
	defer func() { global_cwd, global_home = "", "" }()
	f()
}

func should_be_compressed(path, strategy string) bool {
	if strategy == "always" {
		return true
	}
	if strategy == "never" {
		return false
	}
	ext := strings.ToLower(filepath.Ext(path))
	if ext != "" {
		switch ext[1:] {
		case "zip", "odt", "odp", "pptx", "docx", "gz", "bz2", "xz", "svgz":
			return false
		}
	}
	mt := utils.GuessMimeType(path)
	if strings.HasSuffix(mt, "+zip") || (strings.HasPrefix(mt, "image/") && mt != "image/svg+xml") || strings.HasPrefix(mt, "video/") {
		return false
	}
	return true
}

func print_rsync_stats(total_bytes, delta_bytes, signature_bytes int64) {
	fmt.Println("Rsync stats:")
	fmt.Printf("  Delta size: %s Signature size: %s\n", humanize.Size(delta_bytes), humanize.Size(signature_bytes))
	frac := float64(delta_bytes+signature_bytes) / float64(utils.Max(1, total_bytes))
	fmt.Printf("  Transmitted: %s of a total of %s (%.1f%%)\n", humanize.Size(delta_bytes+signature_bytes), humanize.Size(total_bytes), frac*100)
}
