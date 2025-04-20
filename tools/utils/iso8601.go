// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

var _ = fmt.Print

func is_digit(x byte) bool {
	return '0' <= x && x <= '9'
}

// The following is copied from the Go standard library to implement date range validation logic
// equivalent to the behaviour of Go's time.Parse.

func isLeap(year int) bool {
	return year%4 == 0 && (year%100 != 0 || year%400 == 0)
}

// daysInMonth is the number of days for non-leap years in each calendar month starting at 1
var daysInMonth = [13]int{0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31}

func daysIn(m time.Month, year int) int {
	if m == time.February && isLeap(year) {
		return 29
	}
	return daysInMonth[int(m)]
}

func ISO8601Parse(raw string) (time.Time, error) {
	orig := raw
	raw = strings.TrimSpace(raw)

	required_number := func(num_digits int) (int, error) {
		if len(raw) < num_digits {
			return 0, fmt.Errorf("Insufficient digits")
		}
		text := raw[:num_digits]
		raw = raw[num_digits:]
		ans, err := strconv.ParseUint(text, 10, 32)
		if err == nil && ans <= math.MaxInt {
			return int(ans), nil
		}
		return math.MaxInt, err

	}
	optional_separator := func(x byte) bool {
		if len(raw) > 0 && raw[0] == x {
			raw = raw[1:]
		}
		return len(raw) > 0 && is_digit(raw[0])
	}

	errf := func(msg string) (time.Time, error) {
		return time.Time{}, fmt.Errorf("Invalid ISO8601 timestamp: %#v. %s", orig, msg)
	}

	optional_separator('+')
	year, err := required_number(4)
	if err != nil {
		return errf("timestamp does not start with a 4 digit year")
	}
	var month int = 1
	var day int = 1
	if optional_separator('-') {
		month, err = required_number(2)
		if err != nil {
			return errf("timestamp does not have a valid 2 digit month")
		}
		if optional_separator('-') {
			day, err = required_number(2)
			if err != nil {
				return errf("timestamp does not have a valid 2 digit day")
			}
		}
	}

	var hour, minute, second int
	var nsec int64

	if len(raw) > 0 && (raw[0] == 'T' || raw[0] == ' ') {
		raw = raw[1:]
		hour, err = required_number(2)
		if err != nil {
			return errf("timestamp does not have a valid 2 digit hour")
		}
		if optional_separator(':') {
			minute, err = required_number(2)
			if err != nil {
				return errf("timestamp does not have a valid 2 digit minute")
			}
			if optional_separator(':') {
				second, err = required_number(2)
				if err != nil {
					return errf("timestamp does not have a valid 2 digit second")
				}
			}
		}
		if len(raw) > 0 && (raw[0] == '.' || raw[0] == ',') {
			raw = raw[1:]
			num_digits := 0
			for len(raw) > num_digits && is_digit(raw[num_digits]) {
				num_digits++
			}
			text := raw[:num_digits]
			raw = raw[num_digits:]
			extra := 9 - len(text)
			if extra < 0 {
				text = text[:9]
			}
			if text != "" {
				if nsec, err = strconv.ParseInt(text, 10, 0); err != nil {
					return errf("timestamp does not have a valid nanosecond field")
				}
				for ; extra > 0; extra-- {
					nsec *= 10
				}
			}
		}
	}
	switch {
	case month < 1 || month > 12:
		return errf("timestamp has invalid month value")
	case day < 1 || day > 31 || day > daysIn(time.Month(month), year):
		return errf("timestamp has invalid day value")
	case hour < 0 || hour > 23:
		return errf("timestamp has invalid hour value")
	case minute < 0 || minute > 59:
		return errf("timestamp has invalid minute value")
	case second < 0 || second > 59:
		return errf("timestamp has invalid second value")
	}
	loc := time.UTC
	tzsign, tzhour, tzminute := 0, 0, 0

	if len(raw) > 0 {
		switch raw[0] {
		case '+':
			tzsign = 1
		case '-':
			tzsign = -1
		}
	}
	if tzsign != 0 {
		raw = raw[1:]
		tzhour, err = required_number(2)
		if err != nil {
			return errf("timestamp has invalid timezone hour")
		}
		optional_separator(':')
		tzminute, err = required_number(2)
		if err != nil {
			tzminute = 0
		}
		seconds := tzhour*3600 + tzminute*60
		loc = time.FixedZone("", tzsign*seconds)
	}
	return time.Date(year, time.Month(month), day, hour, minute, second, int(nsec), loc), err
}

func ISO8601Format(x time.Time) string {
	return x.Format(time.RFC3339Nano)
}
