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

type Field interface {
	IsDefault() bool
	Serialize() string
}

type Action int

func (self Action) IsDefault() bool { return self == Action_invalid }
func (self Action) Serialize() string {
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
func (self Compression) Serialize() string {
	switch self {
	default:
		return "none"
	case Compression_zlib:
		return "zlib"
	}
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

func (self FileType) String() string {
	switch self {
	case FileType_regular:
		return "FileType.Regular"
	case FileType_directory:
		return "FileType.Directory"
	case FileType_symlink:
		return "FileType.SymbolicLink"
	case FileType_link:
		return "FileType.Link"
	}
	return "FileType.Unknown"
}

func (self FileType) IsDefault() bool { return self == FileType_regular }
func (self FileType) Serialize() string {
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

type TransmissionType int

const (
	TransmissionType_simple TransmissionType = iota
	TransmissionType_rsync
)

func (self TransmissionType) IsDefault() bool { return self == TransmissionType_simple }
func (self TransmissionType) Serialize() string {
	switch self {
	default:
		return "simple"
	case TransmissionType_rsync:
		return "rsync"
	}
}

type QuietLevel int

const (
	Quiet_none QuietLevel = iota
	Quiet_acknowledgements
	Quiet_errors
)

func (self QuietLevel) IsDefault() bool { return self == Quiet_none }
func (self QuietLevel) Serialize() string {
	switch self {
	default:
		return "0"
	case Quiet_acknowledgements:
		return "1"
	case Quiet_errors:
		return "2"
	}
}

type FileTransmissionCommand struct {
	Action      Action           `name:"ac"`
	Compression Compression      `name:"zip"`
	Ftype       FileType         `name:"ft"`
	Ttype       TransmissionType `name:"tt"`
	Quiet       QuietLevel       `name:"q"`

	Id          string        `name:"id"`
	File_id     string        `name:"fid"`
	Bypass      string        `name:"pw" encoding:"base64"`
	Name        string        `name:"n" encoding:"base64"`
	Status      string        `name:"st" encoding:"base64"`
	Parent      string        `name:"pr"`
	Mtime       time.Duration `name:"mod"`
	Permissions fs.FileMode   `name:"prm"`
	Size        uint64        `name:"sz"`

	Data []byte `name:"d"`
}

func escape_semicolons(x string) string {
	return strings.ReplaceAll(x, ";", ";;")
}

func (self *FileTransmissionCommand) Serialize(prefix_with_osc_code ...bool) string {
	ans := strings.Builder{}
	v := reflect.ValueOf(*self)
	typ := v.Type()
	fields := reflect.VisibleFields(typ)
	found := false
	if len(prefix_with_osc_code) > 0 && prefix_with_osc_code[0] {
		ans.WriteString(strconv.Itoa(kitty.FileTransferCode))
		found = true
	}
	for _, field := range fields {
		if name := field.Tag.Get("name"); name != "" {
			val := v.FieldByIndex(field.Index)
			encoded_val := ""
			switch val.Kind() {
			case reflect.String:
				sval := val.String()
				if sval != "" {
					enc := field.Tag.Get("encoding")
					switch enc {
					case "base64":
						encoded_val = base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(sval))
					default:
						encoded_val = escape_semicolons(wcswidth.StripEscapeCodes(sval))
					}
				}
			case reflect.Slice:
				switch val.Elem().Type().Kind() {
				case reflect.Uint8:
					bval := val.Bytes()
					if len(bval) > 0 {
						encoded_val = base64.StdEncoding.EncodeToString(bval)
					}
				}
			case reflect.Uint64:
				encoded_val = strconv.FormatUint(val.Uint(), 10)
			default:
				if val.CanInterface() {
					i := val.Interface()
					if field, ok := i.(Field); ok {
						if !field.IsDefault() {
							encoded_val = field.Serialize()
						}
					} else if field, ok := i.(time.Duration); ok {
						if field != 0 {
							encoded_val = strconv.FormatInt(int64(field), 10)
						}
					} else if field, ok := i.(fs.FileMode); ok {
						field = field.Perm()
						if field != 0 {
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
	}
	return ans.String()
}
