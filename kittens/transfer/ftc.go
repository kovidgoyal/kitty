// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"encoding/base64"
	"fmt"
	"io/fs"
	"kitty"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
	"reflect"
	"strconv"
	"strings"
	"time"
)

var _ = fmt.Print

type Serializable interface {
	IsDefault() bool
	String() string
}
type Unserializable interface {
	Unserialize(string) error
}

type Action int

func (self Action) IsDefault() bool { return self == Action_invalid }
func (self Action) String() string {
	switch self {
	default:
		return "invalid"
	case Action_file:
		return "file"
	case Action_data:
		return "data"
	case Action_end_data:
		return "end_data"
	case Action_receive:
		return "receive"
	case Action_send:
		return "send"
	case Action_cancel:
		return "cancel"
	case Action_status:
		return "status"
	case Action_finish:
		return "finish"
	}
}
func (self *Action) Unserialize(x string) (err error) {
	switch x {
	case "invalid":
		*self = Action_invalid
	case "file":
		*self = Action_file
	case "data":
		*self = Action_data
	case "end_data":
		*self = Action_end_data
	case "receive":
		*self = Action_receive
	case "send":
		*self = Action_send
	case "cancel":
		*self = Action_cancel
	case "status":
		*self = Action_status
	case "finish":
		*self = Action_finish
	default:
		err = fmt.Errorf("Unknown Action value: %#v", x)
	}
	return
}

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

type Compression int

const (
	Compression_none Compression = iota
	Compression_zlib
)

func (self Compression) IsDefault() bool { return self == Compression_none }
func (self Compression) String() string {
	switch self {
	default:
		return "none"
	case Compression_zlib:
		return "zlib"
	}
}
func (self *Compression) Unserialize(x string) (err error) {
	switch x {
	case "none":
		*self = Compression_none
	case "zlib":
		*self = Compression_zlib
	default:
		err = fmt.Errorf("Unknown Compression value: %#v", x)
	}
	return
}

type FileType int

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

func (self FileType) IsDefault() bool { return self == FileType_regular }
func (self FileType) String() string {
	switch self {
	default:
		return "regular"
	case FileType_directory:
		return "directory"
	case FileType_symlink:
		return "symlink"
	case FileType_link:
		return "link"
	}
}
func (self *FileType) Unserialize(x string) (err error) {
	switch x {
	case "regular":
		*self = FileType_regular
	case "directory":
		*self = FileType_directory
	case "symlink":
		*self = FileType_symlink
	case "link":
		*self = FileType_link
	default:
		err = fmt.Errorf("Unknown FileType value: %#v", x)
	}
	return
}

type TransmissionType int

const (
	TransmissionType_simple TransmissionType = iota
	TransmissionType_rsync
)

func (self TransmissionType) IsDefault() bool { return self == TransmissionType_simple }
func (self TransmissionType) String() string {
	switch self {
	default:
		return "simple"
	case TransmissionType_rsync:
		return "rsync"
	}
}
func (self *TransmissionType) Unserialize(x string) (err error) {
	switch x {
	case "simple":
		*self = TransmissionType_simple
	case "rsync":
		*self = TransmissionType_rsync
	default:
		err = fmt.Errorf("Unknown TransmissionType value: %#v", x)
	}
	return
}

type QuietLevel int

const (
	Quiet_none QuietLevel = iota
	Quiet_acknowledgements
	Quiet_errors
)

func (self QuietLevel) IsDefault() bool { return self == Quiet_none }
func (self QuietLevel) String() string {
	switch self {
	default:
		return "0"
	case Quiet_acknowledgements:
		return "1"
	case Quiet_errors:
		return "2"
	}
}
func (self *QuietLevel) Unserialize(x string) (err error) {
	switch x {
	case "0":
		*self = Quiet_none
	case "1":
		*self = Quiet_acknowledgements
	case "2":
		*self = Quiet_errors
	default:
		err = fmt.Errorf("Unknown QuietLevel value: %#v", x)
	}
	return
}

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
	Size        uint64        `json:"sz,omitempty"`

	Data []byte `json:"d,omitempty"`
}

func escape_semicolons(x string) string {
	return strings.ReplaceAll(x, ";", ";;")
}

var ftc_field_map = utils.Once(func() map[string]reflect.StructField {
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

func (self *FileTransmissionCommand) Serialize(prefix_with_osc_code ...bool) string {
	ans := strings.Builder{}
	v := reflect.ValueOf(*self)
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
					encoded_val = escape_semicolons(wcswidth.StripEscapeCodes(sval))
				}
			}
		case reflect.Slice:
			switch val.Type().Elem().Kind() {
			case reflect.Uint8:
				if bval := val.Bytes(); len(bval) > 0 {
					encoded_val = base64.RawStdEncoding.EncodeToString(bval)
				}
			}
		case reflect.Uint64:
			if uival := val.Uint(); uival != 0 {
				encoded_val = strconv.FormatUint(uival, 10)
			}
		default:
			if val.CanInterface() {
				switch field := val.Interface().(type) {
				case Serializable:
					if !field.IsDefault() {
						encoded_val = field.String()
					}
				case time.Duration:
					if field != 0 {
						encoded_val = strconv.FormatInt(int64(field), 10)
					}
				case fs.FileMode:
					if field = field.Perm(); field != 0 {
						encoded_val = strconv.FormatInt(int64(field), 10)
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

func NewFileTransmissionCommand(serialized string) (ans *FileTransmissionCommand, err error) {
	ans = &FileTransmissionCommand{}
	key_length, key_start, val_start, val_length := 0, 0, 0, 0
	has_semicolons := false
	field_map := ftc_field_map()
	v := reflect.Indirect(reflect.ValueOf(ans))

	handle_value := func(key, serialized_val string, has_semicolons bool) error {
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
					if has_semicolons {
						serialized_val = strings.ReplaceAll(serialized_val, `;;`, `;`)
					}
					val.SetString(serialized_val)
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
			case reflect.Uint64:
				b, err := strconv.ParseUint(serialized_val, 10, 64)
				if err != nil {
					return fmt.Errorf("The field %#v has invalid unsigned integer value with error: %w", key, err)
				}
				val.SetUint(b)
			default:
				if val.CanAddr() {
					switch field := val.Addr().Interface().(type) {
					case Unserializable:
						err = field.Unserialize(serialized_val)
						if err != nil {
							return fmt.Errorf("The field %#v has invalid enum value with error: %w", key, err)
						}
					case *time.Duration:
						b, err := strconv.ParseInt(serialized_val, 10, 64)
						if err != nil {
							return fmt.Errorf("The field %#v has invalid time value with error: %w", key, err)
						}
						*field = time.Duration(b)
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
				has_semicolons = false
			}
		} else {
			if ch == ';' {
				if i+1 < len(serialized) && serialized[i+1] == ';' {
					has_semicolons = true
					i++
				} else {
					val_length = i - val_start
					if key_length > 0 && val_start > 0 {
						err = handle_value(serialized[key_start:key_start+key_length], serialized[val_start:val_start+val_length], has_semicolons)
						if err != nil {
							return nil, err
						}
					}
					key_length = 0
					key_start = i + 1
					val_start = 0
					val_length = 0
				}
			}
		}
	}
	if key_length > 0 && val_start > 0 {
		err = handle_value(serialized[key_start:key_start+key_length], serialized[val_start:], has_semicolons)
		if err != nil {
			return nil, err
		}
	}
	return
}
