package desktop_ui

import (
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/kovidgoyal/dbus"
	"github.com/kovidgoyal/dbus/introspect"
	"github.com/kovidgoyal/dbus/prop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

const PORTAL_APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
const PORTAL_COLOR_SCHEME_KEY = "color-scheme"
const PORTAL_ACCENT_COLOR_KEY = "accent-color"
const PORTAL_CONTRAST_KEY = "contrast"
const PORTAL_BUS_NAME = "org.freedesktop.impl.portal.desktop.kitty"
const SETTINGS_OBJECT_PATH = "/org/freedesktop/portal/desktop"
const SETTINGS_INTERFACE = "org.freedesktop.impl.portal.Settings"
const CHANGE_SETTINGS_OBJECT_PATH = "/net/kovidgoyal/kitty/portal"
const CHANGE_SETTINGS_INTERFACE = "net.kovidgoyal.kitty.settings"
const DESKTOP_PORTAL_NAME = "org.freedesktop.portal.Desktop"

// Special portal setting used to check if we are being called by xdg-desktop-portal
const SETTINGS_CANARY_NAMESPACE = "net.kovidgoyal.kitty"
const SETTINGS_CANARY_KEY = "status"

type ColorScheme uint32

const (
	NO_PREFERENCE ColorScheme = iota
	DARK
	LIGHT
)

type SettingsMap map[string]map[string]dbus.Variant

type Portal struct {
	bus      *dbus.Conn
	settings SettingsMap
	lock     sync.Mutex
}

func to_color(spec string) (v dbus.Variant, err error) {
	if col, err := style.ParseColor(spec); err == nil {
		return dbus.MakeVariant([]float64{float64(col.Red) / 255., float64(col.Green) / 255., float64(col.Blue) / 255.}), nil
	}
	return
}

func NewPortal(opts *Options) (p *Portal, err error) {
	ans := Portal{}
	ans.settings = SettingsMap{
		SETTINGS_CANARY_NAMESPACE: map[string]dbus.Variant{
			SETTINGS_CANARY_KEY: dbus.MakeVariant("running"),
		},
	}
	ans.settings[PORTAL_APPEARANCE_NAMESPACE] = map[string]dbus.Variant{}
	switch opts.Color_scheme {
	case "dark":
		ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(DARK))
	case "light":
		ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(LIGHT))
	default:
		ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(NO_PREFERENCE))
	}
	ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_ACCENT_COLOR_KEY], err = to_color(opts.AccentColor)
	var contrast uint32
	if opts.Contrast == "high" {
		contrast = 1
	}
	ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_CONTRAST_KEY] = dbus.MakeVariant(contrast)
	return &ans, nil
}

type PropSpec map[string]*prop.Prop
type SignalSpec map[string][]struct {
	Name, Type string
}
type MethodSpec map[string][]struct {
	Name, Type string
	Out        bool
}

func ExportInterface(conn *dbus.Conn, object any, interface_name, object_path string, method_spec MethodSpec, prop_spec PropSpec, signal_spec SignalSpec) (err error) {
	op := dbus.ObjectPath(object_path)
	method_map := make(map[string]string, len(method_spec))
	methods := []introspect.Method{}
	if len(method_spec) > 0 {
		for method_name, args := range method_spec {
			method_map[method_name] = method_name
			meth_args := make([]introspect.Arg, len(args))
			for i, a := range args {
				meth_args[i] = introspect.Arg{
					Name:      a.Name,
					Type:      a.Type,
					Direction: utils.IfElse(a.Out, "out", "in"),
				}
			}
			methods = append(methods, introspect.Method{
				Name: method_name,
				Args: meth_args,
			})
		}
	}
	if err = conn.ExportWithMap(object, method_map, op, interface_name); err != nil {
		return fmt.Errorf("failed to export interface: %s at object path: %s with error: %w", interface_name, object_path, err)
	}
	var properties []introspect.Property
	p := prop.Map{interface_name: prop_spec}
	if len(prop_spec) > 0 {
		if props, err := prop.Export(conn, op, p); err != nil {
			return fmt.Errorf("failed to export properties with error: %w", err)
		} else {
			properties = props.Introspection(interface_name)
		}
	}
	var signals []introspect.Signal
	if len(signal_spec) > 0 {
		for signal_name, args := range signal_spec {
			sig_args := make([]introspect.Arg, len(args))
			for i, a := range args {
				sig_args[i] = introspect.Arg{
					Name:      a.Name,
					Type:      a.Type,
					Direction: "out",
				}
			}
			signals = append(signals, introspect.Signal{
				Name: signal_name,
				Args: sig_args,
			})
		}
	}

	interface_data := introspect.Interface{
		Name:       interface_name,
		Methods:    methods,
		Properties: properties,
		Signals:    signals,
	}
	interfaces := []introspect.Interface{
		introspect.IntrospectData, interface_data,
	}
	if len(properties) > 0 {
		interfaces = append(interfaces, prop.IntrospectData)
	}
	n := &introspect.Node{Name: object_path, Interfaces: interfaces}
	if err = conn.Export(introspect.NewIntrospectable(n), op, introspect.IntrospectData.Name); err != nil {
		return fmt.Errorf("failed to export introspected methods with error: %w", err)
	}
	return
}

func (self *Portal) Start() (err error) {
	if self.bus, err = dbus.SessionBus(); err != nil {
		return fmt.Errorf("could not connect to session D-Bus: %s", err)
	}
	reply, err := self.bus.RequestName(PORTAL_BUS_NAME, dbus.NameFlagDoNotQueue)
	if err != nil {
		return fmt.Errorf("failed to register dbus name: %v", err)
	}
	if reply != dbus.RequestNameReplyPrimaryOwner {
		return fmt.Errorf("can't register D-Bus name: name already taken")
	}
	props := PropSpec{
		"version": {Value: uint32(1), Writable: false, Emit: prop.EmitFalse},
	}
	signals := SignalSpec{
		"SettingChanged": {{"namespace", "s"}, {"key", "s"}, {"value", "v"}},
	}
	methods := MethodSpec{
		"Read":    {{"namespace", "s", false}, {"key", "s", false}, {"value", "v", true}},
		"ReadAll": {{"namespaces", "as", false}, {"value", "a{sa{sv}}", true}},
	}
	if err = ExportInterface(self.bus, self, SETTINGS_INTERFACE, SETTINGS_OBJECT_PATH, methods, props, signals); err != nil {
		return
	}
	methods = MethodSpec{
		"ChangeSetting": {{"namespace", "s", false}, {"key", "s", false}, {"value", "v", false}},
		"RemoveSetting": {{"namespace", "s", false}, {"key", "s", false}},
	}
	props["version"].Value = uint32(1)
	if err = ExportInterface(self.bus, self, CHANGE_SETTINGS_INTERFACE, CHANGE_SETTINGS_OBJECT_PATH, methods, props, nil); err != nil {
		return
	}
	return
}

func ParseValueWithSignature(value, value_type_signature string) (v dbus.Variant, err error) {
	var s dbus.Signature
	if value_type_signature != "" {
		if value_type_signature[0] == '@' {
			value_type_signature = value_type_signature[1:]
		}
		s, err = dbus.ParseSignature(value_type_signature)
		if err != nil {
			return dbus.Variant{}, fmt.Errorf("%s is not a valid type signature: %w", value_type_signature, err)
		}
	}
	v, err = dbus.ParseVariant(value, s)
	if err != nil {
		if value_type_signature == "" {
			return dbus.Variant{}, fmt.Errorf("could not guess the data type of: %s with error: %w", value, err)
		}
		return dbus.Variant{}, fmt.Errorf("%s is not a valid value for signature: %#v with error: %w", value, value_type_signature, err)
	}
	return v, nil
}

func ParseValue(value string) (dbus.Variant, error) {
	return ParseValueWithSignature(value, "")
}

type ShowSettingsOptions struct {
	AsJson             bool
	AllowOtherBackends bool
	InNamespace        []string
}

func fetch_settings(conn *dbus.Conn, namespaces ...string) (ans ReadAllType, err error) {
	path := "/" + strings.ToLower(strings.ReplaceAll(DESKTOP_PORTAL_NAME, ".", "/"))
	obj := conn.Object(DESKTOP_PORTAL_NAME, dbus.ObjectPath(path))
	interface_name := strings.ReplaceAll(DESKTOP_PORTAL_NAME, "Desktop", "Settings")
	if len(namespaces) == 0 {
		namespaces = append(namespaces, "")
	}
	call := obj.Call(interface_name+".ReadAll", dbus.FlagNoAutoStart, namespaces)
	if err = call.Store(&ans); err != nil {
		return nil, fmt.Errorf("Failed to read response from ReadAll with error: %w", err)
	}
	return
}

func show_settings(opts *ShowSettingsOptions) (err error) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return fmt.Errorf("failed to connect to system bus with error: %w", err)
	}
	defer conn.Close()
	var response ReadAllType
	response, err = fetch_settings(conn, opts.InNamespace...)
	if opts.AsJson {
		unwrapped := make(map[string]map[string]any, len(response))
		for ns, m := range response {
			w := make(map[string]any, len(m))
			for k, a := range m {
				w[k] = a.Value()
			}
			unwrapped[ns] = w
		}
		j, err := json.MarshalIndent(unwrapped, "", "  ")
		if err != nil {
			return fmt.Errorf("Failed to format the response as JSON: %w", err)
		}
		fmt.Println(string(j))
	} else {
		for ns, m := range response {
			fmt.Println(ns + ":")
			for key, v := range m {
				fmt.Printf("\t%s: %s\n", key, v)
			}
		}
	}
	if !opts.AllowOtherBackends {
		is_running_self := false
		if m, found := response[SETTINGS_CANARY_NAMESPACE]; found {
			_, is_running_self = m[SETTINGS_CANARY_KEY]
		}
		if !is_running_self {
			err = fmt.Errorf("the settings did not come from the desktop-ui kitten. Some other portal backend is providing the service.")
		}
	}
	return
}

var DataDirs = sync.OnceValue(func() (ans []string) {
	d := os.Getenv("XDG_DATA_DIRS")
	if d == "" {
		d = "/usr/local/share/:/usr/share/"
	}
	all := []string{os.Getenv("XDG_DATA_HOME")}
	all = append(all, strings.Split(d, ":")...)
	seen := map[string]bool{}
	for _, x := range all {
		if !seen[x] {
			seen[x] = true
			ans = append(ans, x)
		}
	}
	return
})

func IsDir(x string) bool {
	s, err := os.Stat(x)
	return err == nil && s.IsDir()
}

var WritableDataDirs = sync.OnceValue(func() (ans []string) {
	for _, x := range DataDirs() {
		if err := os.MkdirAll(x, 0o755); err == nil && unix.Access(x, unix.W_OK) == nil {
			ans = append(ans, x)
		}
	}
	return
})

var AllPortalInterfaces = sync.OnceValue(func() (ans []string) {
	return []string{SETTINGS_INTERFACE}
})

// enable-portal {{{
func patch_portals_conf(text []byte) []byte {
	lines := []string{}
	in_preferred := false
	for _, line := range utils.Splitlines(utils.UnsafeBytesToString(text)) {
		sl := strings.TrimSpace(line)
		if strings.HasPrefix(sl, "[") {
			in_preferred = sl == "[preferred]"
			lines = append(lines, line)
			for _, iface := range AllPortalInterfaces() {
				lines = append(lines, iface+"=kitty")
			}
		} else if in_preferred {
			remove := false
			for _, iface := range AllPortalInterfaces() {
				if strings.HasPrefix(sl, iface) {
					remove = true
					break
				}
			}
			if !remove {
				lines = append(lines, line)
			}
		}
	}
	return utils.UnsafeStringToBytes(strings.Join(lines, "\n"))
}

func enable_portal() (err error) {
	if len(WritableDataDirs()) == 0 {
		return fmt.Errorf("Could not find any writable data directories. Make sure XDG_DATA_DIRS is set and contains at least one directory for which you have write permission")
	}
	portals_dir := ""
	for _, x := range WritableDataDirs() {
		q := filepath.Join(x, "xdg-desktop-portal", "portals")
		if unix.Access(q, unix.W_OK) == nil && IsDir(q) {
			portals_dir = q
			break
		}
	}
	if portals_dir == "" {
		for _, x := range WritableDataDirs() {
			q := filepath.Join(x, "xdg-desktop-portal", "portals")
			if err := os.MkdirAll(q, 0o755); err == nil {
				portals_dir = q
				break
			}
		}
	}
	if portals_dir == "" {
		return fmt.Errorf("Could not find any writable portals directories. Make sure XDG_DATA_HOME is set and point to a directory for which you have write permission.")
	}
	portals_defn := filepath.Join(portals_dir, "kitty.portal")
	if err = os.WriteFile(portals_defn, utils.UnsafeStringToBytes(fmt.Sprintf(
		`[portal]
DBusName=%s
Interfaces=%s;
`, PORTAL_BUS_NAME, strings.Join(AllPortalInterfaces(), ";"))), 0o644); err != nil {
		return err
	}
	fmt.Println("Wrote kitty portal definition to:", portals_defn)
	dbus_service_dir := ""
	for _, x := range WritableDataDirs() {
		q := filepath.Join(x, "dbus-1", "services")
		if err := os.MkdirAll(q, 0o755); err == nil {
			dbus_service_dir = q
			break
		}
	}
	if dbus_service_dir == "" {
		return fmt.Errorf("Could not find any writable portals directories. Make sure XDG_DATA_HOME is set and point to a directory for which you have write permission.")
	}
	dbus_service_defn := filepath.Join(dbus_service_dir, PORTAL_BUS_NAME+".desktop")
	if err = os.WriteFile(dbus_service_defn, utils.UnsafeStringToBytes(fmt.Sprintf(
		`[D-BUS Service]
Name=%s
Exec=kitten run-server
`, PORTAL_BUS_NAME)), 0o644); err != nil {
		return err
	}
	fmt.Println("Wrote kitty DBUS activation service file to:", dbus_service_defn)

	d := os.Getenv("XDG_CURRENT_DESKTOP")
	cf := os.Getenv("XDG_CONFIG_HOME")
	if cf == "" {
		cf = utils.Expanduser("~/.config")
	}
	cf = filepath.Join(cf, "xdg-desktop-portal")
	if err = os.MkdirAll(cf, 0o755); err != nil {
		return fmt.Errorf("failed to create %s to store the portals.conf file with error: %w", cf, err)
	}
	patched_file := ""
	desktops := utils.Filter(strings.Split(d, ":"), func(x string) bool { return x != "" })
	desktops = append(desktops, "")
	for _, x := range strings.Split(d, ":") {
		q := filepath.Join(cf, utils.IfElse(x == "", "portals.conf", fmt.Sprintf("%s-portals.conf", strings.ToLower(x))))
		if text, err := os.ReadFile(q); err == nil {
			text := patch_portals_conf(text)
			if err = os.WriteFile(q, text, 0o644); err == nil {
				patched_file = q
				break
			}
		}
	}
	if patched_file == "" {
		x := desktops[0]
		q := filepath.Join(cf, utils.IfElse(x == "", "portals.conf", fmt.Sprintf("%s-portals.conf", strings.ToLower(x))))
		text := patch_portals_conf([]byte{})
		if err = os.WriteFile(q, text, 0o644); err != nil {
			return err
		}
		patched_file = q
	}
	fmt.Printf("Patched %s to use the kitty portals\n", patched_file)
	return
}

// }}}

type SetOptions struct {
	Namespace, DataType string
}

func set_variant_setting(namespace, key string, v dbus.Variant, remove_setting bool) (err error) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return fmt.Errorf("failed to connect to system bus with error: %w", err)
	}
	defer conn.Close()
	method := "ChangeSetting"
	var vals = []any{namespace, key}
	if remove_setting {
		method = "RemoveSetting"
	} else {
		vals = append(vals, v)
	}
	obj := conn.Object(PORTAL_BUS_NAME, dbus.ObjectPath(CHANGE_SETTINGS_OBJECT_PATH))
	call := obj.Call(CHANGE_SETTINGS_INTERFACE+"."+method, dbus.FlagNoAutoStart, vals...)
	if err = call.Store(); err != nil {
		return fmt.Errorf("failed to call %s with error: %w", method, err)
	}
	return
}

func set_setting(key, value string, opts *SetOptions) (err error) {
	remove_setting := false
	var v dbus.Variant
	if value == "" {
		remove_setting = true
	} else {
		if v, err = ParseValueWithSignature(value, opts.DataType); err != nil {
			return err
		}
	}
	return set_variant_setting(opts.Namespace, key, v, remove_setting)
}

func set_color_scheme(which string) (err error) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return fmt.Errorf("failed to connect to system bus with error: %w", err)
	}
	defer conn.Close()
	val := NO_PREFERENCE
	var res ReadAllType
	if res, err = fetch_settings(conn, PORTAL_APPEARANCE_NAMESPACE); err != nil {
		return fmt.Errorf("failed to read existing color scheme setting with error: %w", err)
	}
	if m, found := res[PORTAL_APPEARANCE_NAMESPACE]; found {
		if v, found := m[PORTAL_COLOR_SCHEME_KEY]; found {
			v.Store(&val)
		}
	}
	nval := val
	switch which {
	case "toggle":
		switch val {
		case LIGHT:
			nval = DARK
		case DARK:
			nval = LIGHT
		}
	case "no-preference":
		nval = NO_PREFERENCE
	case "light":
		nval = LIGHT
	case "dark":
		nval = DARK
	default:
		return fmt.Errorf("%s is not a valid value of the color-scheme", which)
	}
	if val == nval {
		return
	}
	obj := conn.Object(PORTAL_BUS_NAME, dbus.ObjectPath(CHANGE_SETTINGS_OBJECT_PATH))
	call := obj.Call(CHANGE_SETTINGS_INTERFACE+".ChangeSetting", dbus.FlagNoAutoStart, PORTAL_APPEARANCE_NAMESPACE, PORTAL_COLOR_SCHEME_KEY, dbus.MakeVariant(nval))
	if err = call.Store(); err != nil {
		return fmt.Errorf("failed to call ChangeSetting with error: %w", err)
	}
	return
}

func (self *Portal) ChangeSetting(namespace, key string, value dbus.Variant) *dbus.Error {
	self.lock.Lock()
	defer self.lock.Unlock()
	if self.settings[namespace] == nil {
		self.settings[namespace] = map[string]dbus.Variant{}
	}
	self.settings[namespace][key] = value

	if e := self.bus.Emit(
		SETTINGS_OBJECT_PATH,
		SETTINGS_INTERFACE+".SettingChanged",
		namespace,
		key,
		value,
	); e != nil {
		fmt.Fprintf(os.Stderr, "Couldn't emit signal: %s", e)
	}
	return nil
}

func (self *Portal) RemoveSetting(namespace, key string) *dbus.Error {
	self.lock.Lock()
	defer self.lock.Unlock()
	existed := false
	if m := self.settings[namespace]; m != nil {
		_, existed = m[key]
	}
	if !existed {
		return nil
	}
	delete(self.settings[namespace], key)
	return nil
}

func (self *Portal) Read(namespace, key string) (dbus.Variant, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	if m, found := self.settings[namespace]; found {
		if v, found := m[key]; found {
			return v, nil
		}
	}
	return dbus.Variant{}, dbus.NewError("org.freedesktop.portal.Error.NotFound", []any{fmt.Sprintf("the setting %s in the namespace %s is not supported", key, namespace)})
}

type ReadAllType map[string]map[string]dbus.Variant

func (self *Portal) ReadAll(namespaces []string) (ReadAllType, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	var matched_namespaces = SettingsMap{}
	if len(namespaces) == 0 {
		matched_namespaces = self.settings
	} else {
		for _, namespace := range namespaces {
			if namespace == "" {
				matched_namespaces = self.settings
				break
			} else {
				if strings.HasSuffix(namespace, ".*") {
					namespace = namespace[:len(namespace)-1]
					for candidate := range self.settings {
						if strings.HasPrefix(candidate, namespace) {
							matched_namespaces[candidate] = map[string]dbus.Variant{}
						}
					}
				} else if _, found := self.settings[namespace]; found {
					matched_namespaces[namespace] = map[string]dbus.Variant{}
				}
			}
		}
	}
	values := map[string]map[string]dbus.Variant{}
	for namespace := range matched_namespaces {
		values[namespace] = make(map[string]dbus.Variant, len(self.settings[namespace]))
		maps.Copy(values[namespace], self.settings[namespace])
	}
	return values, nil
}
