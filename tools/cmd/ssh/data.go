// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"bytes"
	_ "embed"
	"encoding/binary"
	"fmt"
	"kitty/tools/utils"
	"strconv"
	"strings"
)

var _ = fmt.Print

//go:embed data_generated.bin
var embedded_data string

type Container = map[string][]byte

var Data = (&utils.Once[Container]{Run: func() Container {
	raw := utils.ReadCompressedEmbeddedData(embedded_data)
	num_of_entries := binary.LittleEndian.Uint32(raw)
	raw = raw[4:]
	ans := make(Container, num_of_entries)
	idx := bytes.IndexByte(raw, '\n')
	text := utils.UnsafeBytesToString(raw[:idx])
	raw = raw[idx+1:]
	for _, record := range strings.Split(text, ",") {
		parts := strings.Split(record, " ")
		offset, _ := strconv.Atoi(parts[1])
		size, _ := strconv.Atoi(parts[2])
		ans[parts[0]] = raw[offset : offset+size]
	}
	return ans
}}).Get
