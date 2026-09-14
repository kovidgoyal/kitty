// License: GPL v3
// Headless regression test for the actual Cocoa module's IME receiver.
// Build/run instructions and fixture limits: cocoa_ime_commit.md.
#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#undef MAX
#undef MIN
#include "../glfw/internal.h"

static id<NSTextInputClient> view;
static Ivar handlerIvar;
static NSMutableData *delivered;
static NSMutableArray *results;
static NSUInteger commitCount, clearCount, previewBytes;
static BOOL allPassed = YES;

static void
capture(GLFWwindow *window, GLFWkeyevent *event) {
    (void)window;
    if (event->ime_state == GLFW_IME_COMMIT_TEXT) {
        ++commitCount;
        if (event->text) [delivered appendBytes:event->text length:strlen(event->text)];
    } else if (event->ime_state == GLFW_IME_PREEDIT_CHANGED) {
        if (!event->text || !event->text[0]) ++clearCount;
        else previewBytes = strlen(event->text);
    }
}

static void
set_handler(int mode) {
    memcpy((char *)view + ivar_getOffset(handlerIvar), &mode, sizeof(mode));
}

static NSString *
repeat(NSString *unit, NSUInteger n) {
    NSMutableString *s = [NSMutableString string];
    for (NSUInteger i = 0; i < n; ++i) [s appendString:unit];
    return s;
}

static void
reset_observed(void) {
    [delivered setLength:0];
    commitCount = clearCount = 0;
}

static void
prepare(NSString *marked) {
    set_handler(0);
    // Reset both the native text buffer and preedit through the real method.
    [view setMarkedText:@"reset" selectedRange:NSMakeRange(5, 0) replacementRange:NSMakeRange(NSNotFound, 0)];
    [view setMarkedText:marked selectedRange:NSMakeRange(marked.length, 0) replacementRange:NSMakeRange(NSNotFound, 0)];
    reset_observed();
}

static void
insert(id text) {
    [view insertText:text replacementRange:NSMakeRange(NSNotFound, 0)];
}

static void
check(NSString *name, NSString *expected, NSUInteger commits, NSUInteger clears, BOOL marked) {
    NSData *bytes = [expected dataUsingEncoding:NSUTF8StringEncoding];
    BOOL same = [delivered isEqualToData:bytes];
    BOOL passed = same && commitCount == commits && clearCount == clears && [view hasMarkedText] == marked;
    allPassed &= passed;
    [results addObject:@{
        @"case" : name,
        @"expected_utf8_bytes" : @(bytes.length),
        @"committed_utf8_bytes" : @(delivered.length),
        @"commit_events" : @(commitCount),
        @"preedit_clear_events" : @(clearCount),
        @"has_marked_text_after" : @([view hasMarkedText]),
        @"content_matches" : @(same),
        @"passed" : @(passed)
    }];
}

int
main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 2) {
            fprintf(stderr, "usage: cocoa_ime_commit /path/to/glfw-cocoa.so\n");
            return 2;
        }
        void *module = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
        if (!module) {
            fprintf(stderr, "dlopen: %s\n", dlerror());
            return 2;
        }
        Class klass = objc_getClass("GLFWContentView");
        Ivar windowIvar = class_getInstanceVariable(klass, "window");
        Ivar markedIvar = class_getInstanceVariable(klass, "markedText");
        handlerIvar = class_getInstanceVariable(klass, "in_key_handler");
        if (!klass || !windowIvar || !markedIvar || !handlerIvar) {
            fprintf(stderr, "native receiver layout missing\n");
            return 2;
        }
        view = class_createInstance(klass, 0);
        _GLFWwindow *fixtureWindow = calloc(1, sizeof(*fixtureWindow));
        if (!view || !fixtureWindow) return 2;
        fixtureWindow->callbacks.keyboard = capture;
        memcpy((char *)view + ivar_getOffset(windowIvar), &fixtureWindow, sizeof(fixtureWindow));
        object_setIvar(view, markedIvar, [[NSMutableAttributedString alloc] init]);
        delivered = [[NSMutableData alloc] init];
        results = [[NSMutableArray alloc] init];

        NSArray *cases = @[
            @[ @"ascii-510", repeat(@"a", 510) ],
            @[ @"ascii-511", repeat(@"a", 511) ],
            @[ @"ascii-512", repeat(@"a", 512) ],
            @[ @"ascii-513", repeat(@"a", 513) ],
            @[ @"han-170-bytes-510", repeat(@"文", 170) ],
            @[ @"han-171-bytes-513", repeat(@"文", 171) ],
            @[ @"mixed-bytes-511", [repeat(@"文", 170) stringByAppendingString:@"a"] ],
            @[ @"mixed-bytes-512", [repeat(@"文", 170) stringByAppendingString:@"ab"] ],
            @[ @"han-383-bytes-1149", repeat(@"文", 383) ],
            @[ @"emoji-bytes-512", repeat(@"😀", 128) ],
            @[ @"han-bytes-90000", repeat(@"文", 30000) ],
            @[ @"short-after-long", @"done" ]
        ];
        for (NSArray *c in cases) {
            NSString *input = c[1];
            prepare(input);
            BOOL previewMatches = previewBytes == [input lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
            insert(input);
            check(c[0], input, 1, 1, NO);
            if (!previewMatches) {
                allPassed = NO;
                fprintf(stderr, "Full preedit was not delivered for %s\n", [c[0] UTF8String]);
            }
        }

        prepare(@"");
        NSString *unmarked = repeat(@"x", 2048);
        insert(unmarked);
        check(@"unmarked-long", unmarked, 1, 0, NO);

        prepare(@"候选");
        NSString *attributedText = repeat(@"文😀e\u0301\n", 128);
        insert([[[NSAttributedString alloc] initWithString:attributedText] autorelease]);
        check(@"attributed-long", attributedText, 1, 1, NO);

        prepare(@"");
        insert(@"甲");
        insert(@"乙");
        check(@"separate-event-loop-commits", @"甲乙", 2, 0, NO);

        prepare(@"待确认");
        insert(nil);
        check(@"nil-keeps-preedit", @"", 0, 0, YES);
        insert(@"");
        check(@"empty-keeps-preedit", @"", 0, 0, YES);
        insert(@"\n");
        check(@"control-keeps-preedit", @"", 0, 0, YES);
        insert(@"\x7f");
        check(@"delete-keeps-preedit", @"", 0, 0, YES);

        // Simulate insertText callbacks while keyDown is collecting text. They
        // must not bypass the surrounding key's dispatch by emitting commits.
        prepare(@"");
        set_handler(1);
        insert(@"甲");
        insert(@"乙");
        check(@"key-handler-defers-two-callbacks", @"", 0, 0, NO);
        // Use the existing modifier branch to observe the pending accumulator;
        // this is a fixture probe, not a simulated physical modifier gesture.
        set_handler(2);
        insert(@"丙");
        check(@"existing-buffer-still-accumulates", @"甲乙丙", 1, 0, NO);

        prepare(@"候选");
        set_handler(1);
        insert(@"已确认");
        check(@"key-handler-unmarks-without-early-commit", @"", 0, 0, NO);

        // The narrowly scoped fix intentionally leaves modifier buffering alone.
        prepare(@"");
        set_handler(2);
        insert(repeat(@"m", 511));
        check(@"modifier-short-behavior", repeat(@"m", 511), 1, 0, NO);
        prepare(@"");
        set_handler(2);
        insert(repeat(@"m", 512));
        check(@"modifier-overflow-unchanged", @"", 0, 0, NO);

        NSDictionary *report = @{
            @"native_module" : @(argv[1]),
            @"all_passed" : @(allPassed),
            @"cases" : results,
            @"capture_boundary" : @"native GLFW keyboard callback; no input method, GUI or terminal child",
            @"key_handler_tests" : @"receiver callback state fixtures; not full physical key dispatch"
        };
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
        fwrite(json.bytes, 1, json.length, stdout);
        fputc('\n', stdout);
        return allPassed ? 0 : 1;
    }
}
