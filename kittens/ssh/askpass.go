// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base32"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
)

var _ = fmt.Print

func fatal(err error) {
	cli.ShowError(err)
	os.Exit(1)
}

func trigger_ask(name string) {
	term, err := tty.OpenControllingTerm()
	if err != nil {
		fatal(err)
	}
	defer term.Close()
	_, err = term.WriteString("\x1bP@kitty-ask|" + name + "\x1b\\")
	if err != nil {
		fatal(err)
	}

}

func isPasswordPrompt(msg string) bool {
	q := strings.ToLower(msg)
	if strings.Contains(q, "passphrase") {
		return false
	}
	return strings.Contains(q, "password")
}

func isOTPPrompt(msg string) bool {
	q := strings.ToLower(msg)
	if strings.Contains(q, "passphrase") {
		return false
	}
	if strings.Contains(q, "verification code") || strings.Contains(q, "one-time password") || strings.Contains(q, "one time password") || strings.Contains(q, "authenticator code") || strings.Contains(q, "authentication code") || strings.Contains(q, "two-factor") || strings.Contains(q, "2fa") || strings.Contains(q, "otp") || strings.Contains(q, "passcode") {
		return true
	}
	return false
}

func generateTOTP(secret string, digits, period int64, t time.Time) (string, error) {
	s := strings.ToUpper(strings.TrimSpace(secret))
	s = strings.ReplaceAll(s, " ", "")
	key, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(s)
	if err != nil {
		return "", fmt.Errorf("invalid TOTP secret: %w", err)
	}
	counter := uint64(t.Unix() / period)
	var buf [8]byte
	binary.BigEndian.PutUint64(buf[:], counter)
	mac := hmac.New(sha1.New, key)
	_, _ = mac.Write(buf[:])
	sum := mac.Sum(nil)
	off := sum[len(sum)-1] & 0x0f
	code := (uint32(sum[off])&0x7f)<<24 | (uint32(sum[off+1])&0xff)<<16 | (uint32(sum[off+2])&0xff)<<8 | (uint32(sum[off+3]) & 0xff)
	mod := uint32(1)
	for i := int64(0); i < digits; i++ {
		mod *= 10
	}
	val := code % mod
	fmtstr := fmt.Sprintf("%%0%dd", digits)
	return fmt.Sprintf(fmtstr, val), nil
}

func RunSSHAskpass() {
	msg := os.Args[len(os.Args)-1]
	prompt := os.Getenv("SSH_ASKPASS_PROMPT")
	is_confirm := prompt == "confirm"
	q_type := "get_line"
	if is_confirm {
		q_type = "confirm"
	}
	is_fingerprint_check := strings.Contains(msg, "(yes/no/[fingerprint])")

	// Auto-fill from ssh.conf if configured
	if !is_confirm && !is_fingerprint_check {
		host := os.Getenv("KITTY_SSH_ASKPASS_HOST")
		user := os.Getenv("KITTY_SSH_ASKPASS_USER")
		if host != "" {
			if cfg, bad_lines, err := load_config(host, user, nil); err == nil && cfg != nil {
				for _, bl := range bad_lines {
					if bl.Err != nil {
						// Only fail for our secret backend errors to avoid
						// unrelated ssh.conf issues breaking askpass.
						if strings.Contains(bl.Err.Error(), "Unsupported secret backend") {
							fatal(bl.Err)
						}
					}
				}
				// Password autofill
				if isPasswordPrompt(msg) && cfg.Password != "" {
					fmt.Println(cfg.Password)
					return
				}
				// OTP autofill
				if isOTPPrompt(msg) && cfg.Totp_secret != "" {
					code, err := generateTOTP(cfg.Totp_secret, int64(cfg.Totp_digits), int64(cfg.Totp_period), time.Now())
					if err == nil {
						fmt.Println(code)
						return
					}
				}
			}
		}
	}
	q := map[string]any{
		"message":     msg,
		"type":        q_type,
		"is_password": !is_fingerprint_check,
	}
	data, err := json.Marshal(q)
	if err != nil {
		fatal(err)
	}
	data_shm, err := shm.CreateTemp("askpass-*", uint64(len(data)+32))
	if err != nil {
		fatal(fmt.Errorf("Failed to create SHM file with error: %w", err))
	}
	defer data_shm.Close()
	defer func() { _ = data_shm.Unlink() }()

	data_shm.Slice()[0] = 0
	if err = shm.WriteWithSize(data_shm, data, 1); err != nil {
		fatal(fmt.Errorf("Failed to write to SHM file with error: %w", err))
	}
	if err = data_shm.Flush(); err != nil {
		fatal(fmt.Errorf("Failed to flush SHM file with error: %w", err))
	}
	trigger_ask(data_shm.Name())
	for {
		time.Sleep(50 * time.Millisecond)
		if data_shm.Slice()[0] == 1 {
			break
		}
	}
	data, err = shm.ReadWithSize(data_shm, 1)
	if err != nil {
		fatal(fmt.Errorf("Failed to read from SHM file with error: %w", err))
	}
	response := ""
	if is_confirm {
		var ok bool
		err = json.Unmarshal(data, &ok)
		if err != nil {
			fatal(fmt.Errorf("Failed to parse response data: %#v with error: %w", string(data), err))
		}
		response = "no"
		if ok {
			response = "yes"
		}
	} else {
		err = json.Unmarshal(data, &response)
		if err != nil {
			fatal(fmt.Errorf("Failed to parse response data: %#v with error: %w", string(data), err))
		}
		if is_fingerprint_check {
			response = strings.ToLower(response)
			if response == "y" {
				response = "yes"
			} else if response == "n" {
				response = "no"
			}
		}
	}
	if response != "" {
		fmt.Println(response)
	}
}
