//go:build darwin

package machine_id

import (
	"fmt"
	"strings"

	"github.com/ebitengine/purego"
)

var _ = fmt.Print

func read_machine_id() (string, error) {
	const kIOMainPortDefault uint32 = 0
	const kCFStringEncodingUTF8 uint32 = 0x08000100

	// 1. Load System Frameworks
	iokit, err := purego.Dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", purego.RTLD_NOW)
	if err != nil {
		return "", err
	}
	defer purego.Dlclose(iokit)
	corefoundation, err := purego.Dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation", purego.RTLD_NOW)
	if err != nil {
		return "", err
	}
	defer purego.Dlclose(corefoundation)

	// 2. Register CoreFoundation Functions
	var cfStringCreateWithCString func(uintptr, *byte, uint32) uintptr
	purego.RegisterLibFunc(&cfStringCreateWithCString, corefoundation, "CFStringCreateWithCString")

	var cfStringGetCString func(uintptr, *byte, int64, uint32) bool
	purego.RegisterLibFunc(&cfStringGetCString, corefoundation, "CFStringGetCString")

	var cfRelease func(uintptr)
	purego.RegisterLibFunc(&cfRelease, corefoundation, "CFRelease")

	// 3. Register IOKit Functions
	var ioServiceMatching func(*byte) uintptr
	purego.RegisterLibFunc(&ioServiceMatching, iokit, "IOServiceMatching")

	var ioServiceGetMatchingService func(uint32, uintptr) uint32
	purego.RegisterLibFunc(&ioServiceGetMatchingService, iokit, "IOServiceGetMatchingService")

	var ioRegistryEntryCreateCFProperty func(uint32, uintptr, uintptr, uint32) uintptr
	purego.RegisterLibFunc(&ioRegistryEntryCreateCFProperty, iokit, "IORegistryEntryCreateCFProperty")

	var ioObjectRelease func(uint32)
	purego.RegisterLibFunc(&ioObjectRelease, iokit, "IOObjectRelease")

	// 4. Retrieve the UUID
	// Convert Go string to CFStringRef for the property key
	keyName := "IOPlatformUUID\x00"
	cfKey := cfStringCreateWithCString(0, &[]byte(keyName)[0], kCFStringEncodingUTF8)
	defer cfRelease(cfKey)

	// Look up the IOPlatformExpertDevice service
	className := "IOPlatformExpertDevice\x00"
	matchingDict := ioServiceMatching(&[]byte(className)[0])
	service := ioServiceGetMatchingService(kIOMainPortDefault, matchingDict)
	if service == 0 {
		return "", fmt.Errorf("failed to find IOPlatformExpertDevice service")
	}
	defer ioObjectRelease(service)

	// Get the property from the registry
	cfValue := ioRegistryEntryCreateCFProperty(service, cfKey, 0, 0)
	if cfValue == 0 {
		return "", fmt.Errorf("failed to find IOPlatformUUID property")
	}
	defer cfRelease(cfValue)

	// Convert the resulting CFString back to a Go string
	buf := make([]byte, 128)
	if cfStringGetCString(cfValue, &buf[0], 128, kCFStringEncodingUTF8) {
		return strings.TrimRight(string(buf), "\x00"), nil
	}
	return "", fmt.Errorf("failed to extract string from CFProperty")
}
