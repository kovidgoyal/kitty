//go:build !linux && !darwin

package utils

import (
	"time"
)

func MonotonicRaw() (time.Time, error) {
	return time.Now(), nil
}
