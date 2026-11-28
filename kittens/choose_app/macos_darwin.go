// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"unsafe"

	"github.com/ebitengine/purego"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// Minimal bindings to the Objective-C runtime, for querying LaunchServices
// via NSWorkspace and UTType. The runtime and frameworks are loaded only when
// first needed, so as not to slow down the startup of other kittens.

type objc_id = uintptr

type objc_runtime struct {
	get_class func(name string) objc_id
	register  func(name string) objc_id
	// objc_msgSend with the various signatures we need
	send      func(obj, sel objc_id) objc_id
	send1     func(obj, sel, a objc_id) objc_id
	send_cstr func(obj, sel objc_id, s string) objc_id
	send_str  func(obj, sel objc_id) string
	send_uint func(obj, sel objc_id) uint
	send_idx  func(obj, sel objc_id, i uint) objc_id
	send_out  func(obj, sel objc_id, out unsafe.Pointer, key, err objc_id) uintptr
	send_rect func(obj, sel objc_id, rect unsafe.Pointer, a, b objc_id) objc_id
	send_rep  func(obj, sel objc_id, typ uint, props objc_id) objc_id
	send_save func(obj, sel, path objc_id, atomically bool) uintptr

	sels, classes map[string]objc_id
}

var load_objc = sync.OnceValues(func() (*objc_runtime, error) {
	libobjc, err := purego.Dlopen("/usr/lib/libobjc.A.dylib", purego.RTLD_GLOBAL|purego.RTLD_NOW)
	if err != nil {
		return nil, fmt.Errorf("failed to load the Objective-C runtime: %w", err)
	}
	for _, fw := range []string{"Foundation", "AppKit", "UniformTypeIdentifiers"} {
		if _, err = purego.Dlopen(fmt.Sprintf("/System/Library/Frameworks/%s.framework/%s", fw, fw), purego.RTLD_GLOBAL|purego.RTLD_NOW); err != nil {
			return nil, fmt.Errorf("failed to load the %s framework: %w", fw, err)
		}
	}
	r := &objc_runtime{sels: map[string]objc_id{}, classes: map[string]objc_id{}}
	purego.RegisterLibFunc(&r.get_class, libobjc, "objc_getClass")
	purego.RegisterLibFunc(&r.register, libobjc, "sel_registerName")
	msg_send, err := purego.Dlsym(libobjc, "objc_msgSend")
	if err != nil {
		return nil, err
	}
	for _, fptr := range []any{&r.send, &r.send1, &r.send_cstr, &r.send_str, &r.send_uint, &r.send_idx, &r.send_out, &r.send_rect, &r.send_rep, &r.send_save} {
		purego.RegisterFunc(fptr, msg_send)
	}
	return r, nil
})

// objc_mutex serializes all use of the runtime, as the autorelease pools
// used are per thread
var objc_mutex sync.Mutex

// with_objc runs f on a locked OS thread inside an autorelease pool
func with_objc(f func(r *objc_runtime)) error {
	r, err := load_objc()
	if err != nil {
		return err
	}
	objc_mutex.Lock()
	defer objc_mutex.Unlock()
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	pool := r.msg(r.msg(r.class("NSAutoreleasePool"), "alloc"), "init")
	defer r.msg(pool, "drain")
	f(r)
	return nil
}

func (r *objc_runtime) sel(name string) objc_id {
	ans, found := r.sels[name]
	if !found {
		ans = r.register(name)
		r.sels[name] = ans
	}
	return ans
}

func (r *objc_runtime) class(name string) objc_id {
	ans, found := r.classes[name]
	if !found {
		ans = r.get_class(name)
		r.classes[name] = ans
	}
	return ans
}

// msg sends a message with no arguments, returning nil for a nil receiver
func (r *objc_runtime) msg(obj objc_id, sel string) objc_id {
	if obj == 0 {
		return 0
	}
	return r.send(obj, r.sel(sel))
}

// msg1 sends a message with one object argument, returning nil for a nil receiver
func (r *objc_runtime) msg1(obj objc_id, sel string, arg objc_id) objc_id {
	if obj == 0 {
		return 0
	}
	return r.send1(obj, r.sel(sel), arg)
}

// nsstring returns an autoreleased NSString
func (r *objc_runtime) nsstring(s string) objc_id {
	return r.send_cstr(r.class("NSString"), r.sel("stringWithUTF8String:"), s)
}

// gostring returns the contents of an NSString, the empty string for nil
func (r *objc_runtime) gostring(s objc_id) string {
	if s == 0 {
		return ""
	}
	return r.send_str(s, r.sel("UTF8String"))
}

func (r *objc_runtime) each(array objc_id, f func(item objc_id)) {
	if array == 0 {
		return
	}
	for i := range r.send_uint(array, r.sel("count")) {
		f(r.send_idx(array, r.sel("objectAtIndex:"), i))
	}
}

func (r *objc_runtime) url_path(url objc_id) string {
	return r.gostring(r.msg(url, "path"))
}

// macos_content_type returns the uniform type identifier of the file, the
// preferred MIME type for it, if any, and whether it is a dynamic type,
// which are generated for files of unknown types.
func macos_content_type(path string) (uti, mime string, dynamic, ok bool) {
	_ = with_objc(func(r *objc_runtime) {
		url := r.msg1(r.class("NSURL"), "fileURLWithPath:", r.nsstring(path))
		var t objc_id
		if url == 0 || r.send_out(url, r.sel("getResourceValue:forKey:error:"), unsafe.Pointer(&t), r.nsstring("NSURLContentTypeKey"), 0)&0xff == 0 {
			t = 0
		}
		if t == 0 {
			// the file does not exist, use its extension
			if ext := strings.TrimPrefix(filepath.Ext(path), "."); ext != "" {
				t = r.msg1(r.class("UTType"), "typeWithFilenameExtension:", r.nsstring(ext))
			}
		}
		if t == 0 {
			return
		}
		uti, mime = r.gostring(r.msg(t, "identifier")), r.gostring(r.msg(t, "preferredMIMEType"))
		dynamic, ok = r.msg(t, "isDynamic")&0xff != 0, uti != ""
	})
	return
}

// What to look up applications for
type app_query_kind int

const (
	query_uti app_query_kind = iota
	query_mime
	query_scheme
)

// macos_apps_for returns the paths of the application bundles that can open
// the specified type of file or URL scheme and the path of the default one, if any
func macos_apps_for(kind app_query_kind, val string) (default_app string, apps []string, err error) {
	err = with_objc(func(r *objc_runtime) {
		ws := r.msg(r.class("NSWorkspace"), "sharedWorkspace")
		var list, def objc_id
		if kind == query_scheme {
			url := r.msg1(r.class("NSURL"), "URLWithString:", r.nsstring(val+":"))
			if url == 0 {
				return
			}
			list, def = r.msg1(ws, "URLsForApplicationsToOpenURL:", url), r.msg1(ws, "URLForApplicationToOpenURL:", url)
		} else {
			t := r.msg1(r.class("UTType"), utils.IfElse(kind == query_uti, "typeWithIdentifier:", "typeWithMIMEType:"), r.nsstring(val))
			if t == 0 {
				return
			}
			list, def = r.msg1(ws, "URLsForApplicationsToOpenContentType:", t), r.msg1(ws, "URLForApplicationToOpenContentType:", t)
		}
		r.each(list, func(url objc_id) {
			if p := r.url_path(url); p != "" {
				apps = append(apps, p)
			}
		})
		default_app = r.url_path(def)
	})
	return
}

// macos_display_names returns the localized names of the specified files, as
// shown in Finder
func macos_display_names(paths []string) (ans []string, err error) {
	ans = make([]string, len(paths))
	err = with_objc(func(r *objc_runtime) {
		fm := r.msg(r.class("NSFileManager"), "defaultManager")
		for i, p := range paths {
			ans[i] = r.gostring(r.msg1(fm, "displayNameAtPath:", r.nsstring(p)))
		}
	})
	return
}

// The value of NSBitmapImageFileTypePNG
const ns_png_file_type = 4

// macos_write_icon writes the icon of the file, as shown by Finder, to
// output_path as a PNG image, using the image closest to the specified size
func macos_write_icon(path, output_path string, px int) (err error) {
	if werr := with_objc(func(r *objc_runtime) {
		ws := r.msg(r.class("NSWorkspace"), "sharedWorkspace")
		img := r.msg1(ws, "iconForFile:", r.nsstring(path))
		if img == 0 {
			err = fmt.Errorf("no icon found for %s", path)
			return
		}
		// an NSRect of the desired size, in points, used to select the image
		rect := [4]float64{0, 0, float64(px), float64(px)}
		cg := r.send_rect(img, r.sel("CGImageForProposedRect:context:hints:"), unsafe.Pointer(&rect), 0, 0)
		runtime.KeepAlive(&rect)
		if cg == 0 {
			err = fmt.Errorf("failed to get an image for the icon of %s", path)
			return
		}
		rep := r.msg(r.msg1(r.msg(r.class("NSBitmapImageRep"), "alloc"), "initWithCGImage:", cg), "autorelease")
		data := r.send_rep(rep, r.sel("representationUsingType:properties:"), ns_png_file_type, r.msg(r.class("NSDictionary"), "dictionary"))
		if data == 0 {
			err = fmt.Errorf("failed to convert the icon of %s to PNG", path)
			return
		}
		if r.send_save(data, r.sel("writeToFile:atomically:"), r.nsstring(output_path), true)&0xff == 0 {
			err = fmt.Errorf("failed to write the icon of %s to %s", path, output_path)
		}
	}); werr != nil {
		return werr
	}
	return
}
