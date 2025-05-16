// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io/fs"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type Serializable interface {
	String() string
	MarshalJSON() ([]byte, error)
}

type Unserializable interface {
	SetString(string) error
}

type Action int // enum

var _ Serializable = Action_cancel
var _ Unserializable = (*Action)(nil)

const (
	Action_invalid Action = iota
	Action_file
	Action_data
	Action_end_data
	Action_receive
	Action_send
	Action_cancel
	Action_status
	Action_finish
)

type Compression int // enum

var _ Serializable = Compression_none
var _ Unserializable = (*Compression)(nil)

const (
	Compression_none Compression = iota
	Compression_zlib
)

type FileType int // enum

var _ Serializable = FileType_regular
var _ Unserializable = (*FileType)(nil)

const (
	FileType_regular FileType = iota
	FileType_symlink
	FileType_directory
	FileType_link
)

func (self FileType) ShortText() string {
	switch self {
	case FileType_regular:
		return "fil"
	case FileType_directory:
		return "dir"
	case FileType_symlink:
		return "sym"
	case FileType_link:
		return "lnk"
	}
	return "und"
}

func (self FileType) Color() string {
	switch self {
	case FileType_regular:
		return "yellow"
	case FileType_directory:
		return "magenta"
	case FileType_symlink:
		return "blue"
	case FileType_link:
		return "green"
	}
	return ""
}

type TransmissionType int // enum

var _ Serializable = TransmissionType_simple
var _ Unserializable = (*TransmissionType)(nil)

const (
	TransmissionType_simple TransmissionType = iota
	TransmissionType_rsync
)

type QuietLevel int // enum

var _ Serializable = Quiet_none
var _ Unserializable = (*QuietLevel)(nil)

const (
	Quiet_none             QuietLevel = iota // 0
	Quiet_acknowledgements                   // 1
	Quiet_errors                             // 2
)

type FileTransmissionCommand struct {
	Action      Action           `json:"ac,omitempty"`
	Compression Compression      `json:"zip,omitempty"`
	Ftype       FileType         `json:"ft,omitempty"`
	Ttype       TransmissionType `json:"tt,omitempty"`
	Quiet       QuietLevel       `json:"q,omitempty"`

	Id          string        `json:"id,omitempty"`
	File_id     string        `json:"fid,omitempty"`
	Bypass      string        `json:"pw,omitempty" encoding:"base64"`
	Name        string        `json:"n,omitempty" encoding:"base64"`
	Status      string        `json:"st,omitempty" encoding:"base64"`
	Parent      string        `json:"pr,omitempty"`
	Mtime       time.Duration `json:"mod,omitempty"`
	Permissions fs.FileMode   `json:"prm,omitempty"`
	Size        int64         `json:"sz,omitempty" default:"-1"`

	Data []byte `json:"d,omitempty"`
}

var ftc_field_map = sync.OnceValue(func() map[string]reflect.StructField {
	ans := make(map[string]reflect.StructField)
	self := FileTransmissionCommand{}
	v := reflect.ValueOf(self)
	typ := v.Type()
	fields := reflect.VisibleFields(typ)
	for _, field := range fields {
		if name := field.Tag.Get("json"); name != "" && field.IsExported() {
			name, _, _ = strings.Cut(name, ",")
			ans[name] = field
		}
	}
	return ans
})

var safe_string_pat = sync.OnceValue(func() *regexp.Regexp {
	return regexp.MustCompile(`[^0-9a-zA-Z_:./@-]`)
})

func safe_string(x string) string {
	return safe_string_pat().ReplaceAllLiteralString(x, ``)
}

func (self FileTransmissionCommand) Serialize(prefix_with_osc_code ...bool) string {
	ans := strings.Builder{}
	v := reflect.ValueOf(self)
	found := false
	if len(prefix_with_osc_code) > 0 && prefix_with_osc_code[0] {
		ans.WriteString(strconv.Itoa(kitty.FileTransferCode))
		found = true
	}
	for name, field := range ftc_field_map() {
		val := v.FieldByIndex(field.Index)
		encoded_val := ""
		switch val.Kind() {
		case reflect.String:
			if sval := val.String(); sval != "" {
				enc := field.Tag.Get("encoding")
				switch enc {
				case "base64":
					encoded_val = base64.RawStdEncoding.EncodeToString(utils.UnsafeStringToBytes(sval))
				default:
					encoded_val = safe_string(sval)
				}
			}
		case reflect.Slice:
			switch val.Type().Elem().Kind() {
			case reflect.Uint8:
				if bval := val.Bytes(); len(bval) > 0 {
					encoded_val = base64.RawStdEncoding.EncodeToString(bval)
				}
			}
		case reflect.Int64:
			if ival := val.Int(); ival != 0 && (ival > 0 || name != "sz") {
				encoded_val = strconv.FormatInt(ival, 10)
			}
		default:
			if val.CanInterface() {
				switch field := val.Interface().(type) {
				case fs.FileMode:
					if field = field.Perm(); field != 0 {
						encoded_val = strconv.FormatInt(int64(field), 10)
					}
				case Serializable:
					if !val.Equal(reflect.Zero(val.Type())) {
						encoded_val = field.String()
					}
				}
			}
		}
		if encoded_val != "" {
			if found {
				ans.WriteString(";")
			} else {
				found = true
			}
			ans.WriteString(name)
			ans.WriteString("=")
			ans.WriteString(encoded_val)
		}
	}
	return ans.String()
}

func (self FileTransmissionCommand) String() string {
	s := self
	s.Data = nil
	ans, _ := json.Marshal(s)
	return utils.UnsafeBytesToString(ans)
}

func NewFileTransmissionCommand(serialized string) (ans *FileTransmissionCommand, err error) {
	ans = &FileTransmissionCommand{}
	v := reflect.Indirect(reflect.ValueOf(ans))
	if err = utils.SetStructDefaults(v); err != nil {
		return
	}
	field_map := ftc_field_map()
	key_length, key_start, val_start := 0, 0, 0

	handle_value := func(key, serialized_val string) error {
		key = strings.TrimLeft(key, `;`)
		if field, ok := field_map[key]; ok {
			val := v.FieldByIndex(field.Index)
			switch val.Kind() {
			case reflect.String:
				switch field.Tag.Get("encoding") {
				case "base64":
					b, err := base64.RawStdEncoding.DecodeString(serialized_val)
					if err != nil {
						return fmt.Errorf("The field %#v has invalid base64 encoded value with error: %w", key, err)
					}
					val.SetString(utils.UnsafeBytesToString(b))
				default:
					val.SetString(safe_string(serialized_val))
				}
			case reflect.Slice:
				switch val.Type().Elem().Kind() {
				case reflect.Uint8:
					b, err := base64.RawStdEncoding.DecodeString(serialized_val)
					if err != nil {
						return fmt.Errorf("The field %#v has invalid base64 encoded value with error: %w", key, err)
					}
					val.SetBytes(b)
				}
			case reflect.Int64:
				b, err := strconv.ParseInt(serialized_val, 10, 64)
				if err != nil {
					return fmt.Errorf("The field %#v has invalid integer value with error: %w", key, err)
				}
				val.SetInt(b)
			default:
				if val.CanAddr() {
					switch field := val.Addr().Interface().(type) {
					case Unserializable:
						err = field.SetString(serialized_val)
						if err != nil {
							return fmt.Errorf("The field %#v has invalid enum value with error: %w", key, err)
						}
					case *fs.FileMode:
						b, err := strconv.ParseUint(serialized_val, 10, 32)
						if err != nil {
							return fmt.Errorf("The field %#v has invalid file mode value with error: %w", key, err)
						}
						*field = fs.FileMode(b).Perm()
					}

				}
			}
			return nil
		} else {
			return fmt.Errorf("The field name %#v is not known", key)
		}
	}

	for i := 0; i < len(serialized); i++ {
		ch := serialized[i]
		if key_length == 0 {
			if ch == '=' {
				key_length = i - key_start
				val_start = i + 1
			}
		} else {
			if ch == ';' {
				val_length := i - val_start
				if key_length > 0 && val_start > 0 {
					err = handle_value(serialized[key_start:key_start+key_length], serialized[val_start:val_start+val_length])
					if err != nil {
						return nil, err
					}
				}
				key_length = 0
				key_start = i + 1
				val_start = 0
			}
		}
	}
	if key_length > 0 && val_start > 0 {
		err = handle_value(serialized[key_start:key_start+key_length], serialized[val_start:])
		if err != nil {
			return nil, err
		}
	}
	return
}

func split_for_transfer(data []byte, file_id string, mark_last bool, callback func(*FileTransmissionCommand)) {
	const chunk_size = 4096
	for len(data) > 0 {
		chunk := data
		if len(chunk) > chunk_size {
			chunk = data[:chunk_size]
		}
		data = data[len(chunk):]
		callback(&FileTransmissionCommand{
			Action:  utils.IfElse(mark_last && len(data) == 0, Action_end_data, Action_data),
			File_id: file_id, Data: chunk})
	}
}
