#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, kitty contributors

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch


def method(source: str, signature: str) -> str:
    definition = re.search(r'^' + re.escape(signature) + r'[^;{\n]*\{', source, re.MULTILINE)
    if definition is None:
        raise ValueError(f'Method definition not found: {signature}')
    start = definition.start()
    return source[start:source.index('\n}\n', start) + 3]


@unittest.skipUnless(sys.platform == 'darwin', 'Cocoa composition recovery requires macOS')
class IMERecoveryTest(unittest.TestCase):

    def test_shutdown_does_not_finalize_composition(self) -> None:
        from kitty.window import Window

        for shutting_down in (False, True):
            window = SimpleNamespace(
                call_watchers=lambda *_: None, watchers=SimpleNamespace(on_close=[]),
                clipboard_request_manager=SimpleNamespace(close=lambda: None), kitten_result_processors=[],
                screen=SimpleNamespace(reset_callbacks=lambda: None), finish_scroll_animation=lambda: None,
                is_active=True, os_window_id=1, id=1,
            )
            with (
                patch('kitty.window.get_boss', return_value=SimpleNamespace(shutting_down=shutting_down)),
                patch('kitty.window.current_focused_os_window_id', return_value=1),
                patch('kitty.window.update_ime_position_for_window') as update,
            ):
                Window.destroy(cast(Window, window))
                if shutting_down:
                    update.assert_not_called()
                else:
                    update.assert_called_once_with(1, False, -1)

    def test_cocoa_composition_recovery(self) -> None:
        """Exercise real Cocoa receiver/focus methods through headless ports."""
        root = Path(__file__).resolve().parent.parent
        source = (root / 'glfw/cocoa_window.m').read_text()
        receiver_source = source[source.index('@implementation GLFWContentView'):]
        context_command = method(source[source.index('@implementation GLFWTextInputContext'):], '- (void)doCommandBySelector:')
        helper_start = source.index('static bool\nis_modifier_pressed(')
        modifier_helper = source[helper_start:source.index('\n}\n', helper_start) + 3]
        receiver = '\n'.join(method(receiver_source, signature) for signature in (
            '- (BOOL)hasMarkedText', '- (void)clearMarkedTextBuffer',
            '- (void)unmarkText', '- (void)setMarkedText:', '- (void)insertText:',
            '- (void)finishMarkedTextOnFocusLoss', '- (void)updateIMEStateFor:', '- (void)keyDown:',
            '- (void)cancelMarkedText', '- (void)cancelOperation:', '- (void)doCommandBySelector:',
            '- (void)flagsChanged:', '- (void)startDictation:',
        ))
        declarations = []
        for name in ('window', 'input_context', 'markedText', 'markedTextSelectedRange', 'interruptedMarkedText',
                     'finishing_marked_text', 'ime_session_closed', 'text_committed_during_key_event', 'marked_text_cleared_by_insert',
                     'in_key_handler', 'input_source_at_last_key_event'):
            declaration = re.search(r'^    [^;\n]+\b' + name + r';$', source, re.MULTILINE)
            self.assertIsNotNone(declaration, name)
            if declaration is not None:
                declarations.append(declaration.group(0))
        fixture = (PREFIX.replace('/* MODIFIER_HELPER */', modifier_helper) + '\n'.join(declarations) + '\n}\n'
                   + '- (void)finishMarkedTextOnFocusLoss;\n'
                   + '- (void)cancelMarkedText;\n- (void)cancelOperation:(id)sender;\n- (void)doCommandBySelector:(SEL)selector;\n'
                   + '- (void)updateIMEStateFor:(GLFWIMEUpdateType)which focused:(bool)focused;\n'
                   + '@end\n@implementation Probe\n- (id)inputContext { return input_context; }\n'
                   + '- (void)interpretKeyEvents:(NSArray *)events { (void)events;\n'
                   + 'if (fixture_key_mode == 1) [self setMarkedText:fixture_key_text selectedRange:kEmptyRange replacementRange:kEmptyRange];\n'
                   + 'if (fixture_key_mode == 3) { [self insertText:@"已确认" replacementRange:kEmptyRange];\n'
                   + '[self setMarkedText:fixture_key_text selectedRange:kEmptyRange replacementRange:kEmptyRange]; }\n'
                   + 'if (fixture_key_mode == 2 || fixture_key_mode == 3) [self finishMarkedTextOnFocusLoss]; }\n'
                   + receiver + '\n@end\n'
                   + '@interface Delegate : NSObject { @public _GLFWwindow *window; }\n@end\n@implementation Delegate\n'
                   + method(source, '- (void)windowDidResignKey:') + '\n@end\n'
                   + CASES.replace('@implementation GLFWTextInputContext\n',
                                   '@implementation GLFWTextInputContext\n' + context_command, 1))
        build = root / 'build'
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='ime-recovery-', dir=build) as directory:
            print(f'IME_RECOVERY_FIXTURE_DIRECTORY {directory}', flush=True)
            path = Path(directory)
            native_source = path / 'receiver.m'
            native_source.write_text(fixture)
            del fixture, receiver, receiver_source, context_command, source, modifier_helper
            library = path / 'receiver.dylib'
            compile_result = subprocess.run(
                ['/usr/bin/xcrun', 'clang', '-dynamiclib', '-fno-objc-arc', '-Wall', '-Werror',
                 '-framework', 'Cocoa', '-framework', 'Carbon', '-I', str(root),
                 str(native_source), '-o', str(library)], capture_output=True, text=True, check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            # Use a dylib in trusted system Python, avoiding code-evaluation UI
            # from launching a fresh executable. No GUI or real input context.
            result = subprocess.run(
                ['/usr/bin/python3', '-c',
                 'import ctypes,sys; sys.exit(ctypes.CDLL(sys.argv[1]).ime_recovery_run())', str(library)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('IME_RECOVERY_NATIVE_OK', result.stdout)
            print(result.stdout.strip(), flush=True)
        self.assertFalse(os.path.exists(directory), 'task-owned native fixture must be removed')


PREFIX = r'''
#import <Cocoa/Cocoa.h>
#import <Carbon/Carbon.h>
#import <IOKit/hidsystem/IOLLEvent.h>
#define GLFW_INCLUDE_NONE
#include "kitty/monotonic.h"
#include "glfw/glfw3.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const NSRange kEmptyRange = {NSNotFound, 0};
typedef struct {
    void *monitor; bool autoIconify;
    struct { id view; UInt32 deadKeyState; int (*textInputFilterCallback)(int, int, unsigned int, unsigned long); } ns;
} _GLFWwindow;
static struct { bool ignoreOSKeyboardProcessing; struct { char text[512]; id unicodeData; } ns; } _glfw;
static NSUInteger commits, clears, raw_keys;
static NSMutableString *delivered;
static _GLFWwindow *last_target;
#define debug_input(...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
@interface NSEvent (Fixture)
@property(readonly) BOOL ARepeat;
@end
static const char *format_text(const char *text) { (void)text; return ""; }
static const char *format_mods(int mods) { (void)mods; return ""; }
static const char *safe_name_for_keycode(unsigned key) { (void)key; return ""; }
static const char *_glfwGetKeyName(uint32_t key) { (void)key; return ""; }
static const char *polymorphic_string_as_utf8(id value) {
    if (!value) return "(nil)";
    return [value isKindOfClass:[NSAttributedString class]] ? [[value string] UTF8String] : [value UTF8String];
}
static bool is_ascii_control_char(char c) { return (c >= 0 && c < 32) || c == 127; }
static bool forward_dictation_selector_to_app(SEL selector, id sender) { (void)selector; (void)sender; return false; }
static NSUInteger remap_cocoa_flags(NSUInteger flags) { return flags; }
static NSEvent *event_with_remapped_flags(NSEvent *event, NSUInteger flags) { (void)flags; return event; }
static int translateFlags(NSUInteger flags) {
    return (flags & NSEventModifierFlagControl ? GLFW_MOD_CONTROL : 0) | (flags & NSEventModifierFlagOption ? GLFW_MOD_ALT : 0) |
           (flags & NSEventModifierFlagCommand ? GLFW_MOD_SUPER : 0);
}
static uint32_t translateKey(uint16_t key, bool mapped) {
    (void)mapped; return key == 0 ? 'a' : key == 123 ? GLFW_FKEY_LEFT : key;
}
static uint32_t vk_code_to_functional_key_code(unsigned key) {
    return key == 0x3d ? GLFW_FKEY_RIGHT_ALT : key == 0x37 ? GLFW_FKEY_LEFT_SUPER : GLFW_FKEY_LEFT_SHIFT;
}
static UInt32 convert_cocoa_to_carbon_modifiers(NSUInteger flags) { return (UInt32)flags; }
static void add_alternate_keys(GLFWkeyevent *ev, NSEvent *event) { (void)ev; (void)event; }
static OSStatus fixture_key_translate(const void *layout, UInt16 key, UInt16 action, UInt32 flags,
                                     UInt32 keyboard, OptionBits options, UInt32 *dead, UniCharCount capacity,
                                     UniCharCount *count, UniChar *text) {
    (void)layout; (void)key; (void)action; (void)flags; (void)keyboard; (void)options; (void)capacity; (void)text;
    *count = 0; *dead = 0; return noErr;
}
#define UCKeyTranslate fixture_key_translate
#define LMGetKbdType() 0
static void _glfwInputKeyboard(_GLFWwindow *window, GLFWkeyevent *event) {
    last_target = window;
    if (event->ime_state == GLFW_IME_COMMIT_TEXT) {
        ++commits;
        if (event->text) [delivered appendString:@(event->text)];
    } else if (event->ime_state == GLFW_IME_PREEDIT_CHANGED && (!event->text || !event->text[0])) ++clears;
    else if (event->ime_state == GLFW_IME_NONE && event->key) ++raw_keys;
}
static void _glfwInputWindowFocus(_GLFWwindow *window, bool focused);
static void finish_marked_text_on_focus_loss(_GLFWwindow *window);
static void _glfwPlatformIconifyWindow(_GLFWwindow *window) { (void)window; }
static void showCursor(_GLFWwindow *window) { (void)window; }
static bool _glfwPlatformWindowFocused(_GLFWwindow *window) { (void)window; return false; }
/* MODIFIER_HELPER */

@class Probe;
@interface GLFWTextInputContext : NSObject
@property(assign) Probe *client;
@property NSUInteger mode;
@property NSUInteger calls;
@property NSUInteger eventMode;
@property(copy) NSString *selectedKeyboardInputSource;
- (void)discardMarkedText;
- (BOOL)handleEvent:(NSEvent *)event;
- (void)invalidateCharacterCoordinates;
@end
@interface Probe : NSObject {
@public
    NSUInteger fixture_key_mode;
    NSString *fixture_key_text;
'''

CASES = r'''
@interface KeyEvent : NSObject
@property unsigned short keyCode;
@property NSUInteger modifierFlags;
@end
@implementation KeyEvent
@end
static void finish_marked_text_on_focus_loss(_GLFWwindow *window) { [window->ns.view finishMarkedTextOnFocusLoss]; }
static void _glfwInputWindowFocus(_GLFWwindow *window, bool focused) {
    [window->ns.view updateIMEStateFor:GLFW_IME_UPDATE_FOCUS focused:focused];
}
@implementation GLFWTextInputContext
- (BOOL)handleEvent:(NSEvent *)event { (void)event; if (self.eventMode == 2) [self.client finishMarkedTextOnFocusLoss]; return YES; }
- (void)invalidateCharacterCoordinates {}
- (void)discardMarkedText {
    ++self.calls;
    switch (self.mode) {
        case 0: break; // no client callback
        case 1: [self.client unmarkText]; break;
        case 2: [self.client setMarkedText:@"" selectedRange:kEmptyRange replacementRange:kEmptyRange]; break;
        case 3:
            [self.client unmarkText];
            [self.client insertText:@"最终识别结果" replacementRange:kEmptyRange];
            break;
        case 4:
            [self.client setMarkedText:@"" selectedRange:kEmptyRange replacementRange:kEmptyRange];
            [self.client insertText:@"最终识别结果" replacementRange:kEmptyRange];
            break;
        case 5:
            [self.client insertText:@"最终识别结果" replacementRange:kEmptyRange];
            [self.client unmarkText];
            break;
        case 6:
            [self.client setMarkedText:@"中断前的最后修订😀" selectedRange:kEmptyRange replacementRange:kEmptyRange];
            [self.client unmarkText];
            break;
        case 7:
            [self.client finishMarkedTextOnFocusLoss];
            [self.client unmarkText];
            break;
        case 8:
            [self.client insertText:nil replacementRange:kEmptyRange];
            [self.client insertText:@"" replacementRange:kEmptyRange];
            [self.client insertText:@"\t" replacementRange:kEmptyRange];
            [self.client unmarkText];
            break;
        case 9: [self doCommandBySelector:@selector(cancelOperation:)]; break;
        case 10: [self.client cancelOperation:nil]; break;
        case 11: self.client->window = NULL; break;
    }
}
@end
static void demand(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static Probe *fresh(void) {
    Probe *p = [[Probe alloc] init];
    p->markedText = [[NSMutableAttributedString alloc] init];
    p->markedTextSelectedRange = kEmptyRange;
    p->input_context = [[GLFWTextInputContext alloc] init];
    p->input_context.client = p;
    p->input_context.selectedKeyboardInputSource = @"fixture.input-source";
    p->window = calloc(1, sizeof(_GLFWwindow));
    p->window->ns.view = p;
    return p;
}
static void reset_events(void) { commits = clears = raw_keys = 0; [delivered setString:@""]; _glfw.ns.text[0] = 0; last_target = NULL; }
static void compose(Probe *p, NSString *text) {
    [p setMarkedText:text selectedRange:NSMakeRange(text.length, 0) replacementRange:kEmptyRange];
}
static NSString *repeated(NSString *s, NSUInteger count) {
    NSMutableString *text = [NSMutableString string];
    for (NSUInteger i = 0; i < count; ++i) [text appendString:s];
    return text;
}
static void finished(Probe *p) {
    demand(![p hasMarkedText] && p->markedTextSelectedRange.location == NSNotFound, "preedit must be cleared");
    demand(!p->finishing_marked_text && !p->interruptedMarkedText, "transaction retains no canceled text");
}
int ime_recovery_run(void) {
    @autoreleasepool {
        delivered = [[NSMutableString alloc] init];
        Probe *p = fresh();
        // Both focus notification paths run; only the current fragment is
        // appended, leaving the already committed prefix untouched.
        compose(p, @"下午三点"); compose(p, @"下午三点半在会议室");
        reset_events(); [delivered appendString:@"前一句已输入。"]; p->input_context.mode = 2;
        Delegate *delegate = [[Delegate alloc] init]; delegate->window = p->window;
        [delegate windowDidResignKey:nil];
        demand(commits == 1 && [delivered isEqualToString:@"前一句已输入。下午三点半在会议室"], "automatic voice refill appends current fragment once");
        demand(last_target == p->window, "refill targets the composing OS window"); finished(p);
        [delegate windowDidResignKey:nil]; [p unmarkText];
        demand(commits == 1 && p->input_context.calls == 1, "repeated focus/clear notifications do not duplicate");

        for (NSUInteger mode = 0; mode <= 8; ++mode) {
            p = fresh(); p->input_context.mode = mode;
            p->in_key_handler = 1; compose(p, @"ni hao"); p->in_key_handler = 0;
            reset_events(); [p updateIMEStateFor:GLFW_IME_UPDATE_FOCUS focused:false];
            NSString *expected = mode >= 3 && mode <= 5 ? @"最终识别结果" : mode == 6 ? @"中断前的最后修订😀" : @"ni hao";
            demand(commits == 1 && [delivered isEqualToString:expected], "all discard callback orders refill latest text exactly once");
            demand(p->input_context.calls == 1, "nested focus notification cannot reenter discard"); finished(p);
        }
        for (NSUInteger mode = 9; mode <= 10; ++mode) {
            p = fresh(); p->input_context.mode = mode; compose(p, @"用户主动取消"); reset_events();
            [p finishMarkedTextOnFocusLoss];
            demand(commits == 0 && delivered.length == 0, "explicit cancellation during focus loss consumes its fallback"); finished(p);
        }

        p = fresh(); compose(p, @"新候选"); reset_events();
        [p insertText:@"新句已确认" replacementRange:kEmptyRange];
        [p finishMarkedTextOnFocusLoss];
        demand(commits == 1 && [delivered isEqualToString:@"新句已确认"], "normal commit does not trigger another refill"); finished(p);
        compose(p, @"后面一段"); reset_events(); [p finishMarkedTextOnFocusLoss];
        demand(commits == 1 && [delivered isEqualToString:@"后面一段"], "previous successful input is never replayed");

        // Explicit empty preedit and the keyDown delete/Escape clearing path
        // cancel normally, outside the focus-loss transaction.
        p = fresh(); compose(p, @"ni hao"); reset_events(); compose(p, @""); [p finishMarkedTextOnFocusLoss];
        demand(commits == 0 && delivered.length == 0 && clears == 1, "explicit empty update must not resurrect text"); finished(p);
        compose(p, @"删除候选"); reset_events(); [p clearMarkedTextBuffer]; [p finishMarkedTextOnFocusLoss];
        demand(commits == 0 && delivered.length == 0, "explicit deletion/cancellation stays canceled");
        compose(p, @"取消"); reset_events(); [p setMarkedText:nil selectedRange:kEmptyRange replacementRange:kEmptyRange];
        [p finishMarkedTextOnFocusLoss]; demand(commits == 0, "nil preedit outside interruption cancels normally");

        // Exercise actual keyDown, including the input-source initialization
        // that runs before interpretKeyEvents. A direct buffer clear missed it.
        for (NSUInteger changed_source = 0; changed_source < 2; ++changed_source) {
            const unsigned short keys[] = {0x35, 0x33, 0x04};
            for (NSUInteger i = 0; i < 3; ++i) {
                p = fresh(); compose(p, @"尚未提交的语音或拼音"); reset_events();
                if (changed_source) p->input_source_at_last_key_event = [@"previous.input-source" retain];
                KeyEvent *event = [[KeyEvent alloc] init]; event.keyCode = keys[i];
                event.modifierFlags = keys[i] == 0x04 ? NSEventModifierFlagControl : 0;
                [p keyDown:(NSEvent *)event]; [p finishMarkedTextOnFocusLoss];
                demand(commits == 0 && delivered.length == 0, "first cancel key must not commit during input-source initialization/change");
                finished(p);
            }
        }
        for (NSUInteger i = 0; i < 2; ++i) {
            p = fresh(); compose(p, @"nihao"); p->fixture_key_mode = 1; p->fixture_key_text = @"niha";
            KeyEvent *backspace = [[KeyEvent alloc] init]; backspace.keyCode = i ? 0x04 : 0x33;
            backspace.modifierFlags = i ? NSEventModifierFlagControl : 0; reset_events();
            [p keyDown:(NSEvent *)backspace];
            demand(!p->ime_session_closed && [p->markedText.string isEqualToString:@"niha"] && commits == 0,
                   "Backspace and Ctrl+H edit the current composition instead of canceling its input session");
        }

        // An IME can consume Escape without sending the terminal a keyDown.
        // Its unmark/cancel callback must not turn the discarded text into input.
        p = fresh(); compose(p, @"输入法接管了Escape"); reset_events(); [p unmarkText]; [p unmarkText]; [p finishMarkedTextOnFocusLoss];
        demand(commits == 0 && delivered.length == 0 && clears == 1, "unmark outside focus protection cancels without refilling"); finished(p);
        compose(p, @"输入法取消命令"); reset_events(); [p->input_context doCommandBySelector:@selector(cancelOperation:)];
        [p finishMarkedTextOnFocusLoss]; demand(commits == 0 && delivered.length == 0, "input-context cancel selector reaches its client");
        p = fresh(); compose(p, @"键盘确认"); reset_events(); p->in_key_handler = 1;
        [p insertText:@"键盘确认" replacementRange:kEmptyRange]; p->in_key_handler = 0;
        demand(commits == 0 && strcmp(_glfw.ns.text, "键盘确认") == 0, "key-handler commit remains staged for its key event");
        [p finishMarkedTextOnFocusLoss]; demand(commits == 0, "focus cannot duplicate a staged successful commit");

        // Actual live ordering: Escape clears, IME resends preedit ~90 ms
        // later, then insertText arrives ~600 ms after Escape. No timer is used.
        p = fresh(); compose(p, @"nihao"); reset_events();
        KeyEvent *escape = [[KeyEvent alloc] init]; escape.keyCode = 0x35;
        [p keyDown:(NSEvent *)escape]; [p unmarkText];
        KeyEvent *command = [[KeyEvent alloc] init]; command.keyCode = 0x37;
        command.modifierFlags = NSEventModifierFlagCommand | NX_DEVICELCMDKEYMASK;
        [p flagsChanged:(NSEvent *)command];
        KeyEvent *arrow = [[KeyEvent alloc] init]; arrow.keyCode = 123;
        [p keyDown:(NSEvent *)arrow];
        compose(p, @"nihao"); [p insertText:@"你好" replacementRange:kEmptyRange];
        [p finishMarkedTextOnFocusLoss];
        demand(p->ime_session_closed && ![p hasMarkedText] && commits == 0 && delivered.length == 0,
               "late preedit and corrected commit cannot revive the canceled conversion");

        KeyEvent *letter = [[KeyEvent alloc] init]; letter.keyCode = 0;
        [p keyDown:(NSEvent *)letter]; compose(p, @"新输入");
        [p insertText:@"新输入" replacementRange:kEmptyRange];
        demand(!p->ime_session_closed && commits == 1 && [delivered isEqualToString:@"新输入"],
               "fresh keyboard input begins a new conversion after cancellation");

        compose(p, @"取消的语音"); [p keyDown:(NSEvent *)escape]; reset_events();
        KeyEvent *option = [[KeyEvent alloc] init]; option.keyCode = 0x3d;
        option.modifierFlags = NSEventModifierFlagOption | NX_DEVICERALTKEYMASK;
        [p flagsChanged:(NSEvent *)option]; compose(p, @"重新开始的语音");
        [p insertText:@"重新开始的语音" replacementRange:kEmptyRange];
        demand(!p->ime_session_closed && commits == 1 && [delivered isEqualToString:@"重新开始的语音"],
               "new dictation modifier starts the next voice conversion");

        compose(p, @"再取消"); [p keyDown:(NSEvent *)escape]; reset_events();
        [p->input_context doCommandBySelector:@selector(startDictation:)]; compose(p, @"系统听写");
        [p insertText:@"系统听写" replacementRange:kEmptyRange];
        demand(!p->ime_session_closed && commits == 1 && [delivered isEqualToString:@"系统听写"],
               "explicit system dictation start also reopens input");

        p = fresh(); compose(p, @"正常候选"); reset_events(); [p unmarkText];
        [p insertText:@"正常确认" replacementRange:kEmptyRange];
        demand(commits == 1 && [delivered isEqualToString:@"正常确认"], "unmark without explicit cancellation can precede a legitimate commit");

        p = fresh(); compose(p, @"中断的片段"); reset_events(); [p finishMarkedTextOnFocusLoss];
        compose(p, @"迟到的修订"); [p insertText:@"迟到的修订" replacementRange:kEmptyRange];
        demand(commits == 1 && [delivered isEqualToString:@"中断的片段"], "late finalization cannot duplicate a focus-loss fallback");

        NSString *reentrant_text = repeated(@"长文本😀", 1024);
        _glfw.ns.unicodeData = [NSData dataWithBytes:"x" length:1];
        p = fresh(); compose(p, reentrant_text); p->fixture_key_mode = 2; reset_events();
        [p keyDown:(NSEvent *)letter];
        demand(commits == 1 && [delivered isEqualToString:reentrant_text] && raw_keys == 0,
               "focus loss inside keyDown commits the complete draft without forwarding the consumed key"); finished(p);
        p = fresh(); p->fixture_key_mode = 3; p->fixture_key_text = reentrant_text; reset_events();
        [p keyDown:(NSEvent *)letter];
        demand(commits == 2 && [delivered isEqualToString:[@"已确认" stringByAppendingString:reentrant_text]] && raw_keys == 0,
               "staged prefix precedes reentrant focus fallback exactly once"); finished(p);
        _glfw.ns.unicodeData = nil;
        p = fresh(); compose(p, reentrant_text); p->input_context.eventMode = 2; reset_events();
        [p flagsChanged:(NSEvent *)option];
        demand(commits == 1 && [delivered isEqualToString:reentrant_text], "modifier callback focus loss also preserves the full draft"); finished(p);
        p = fresh(); compose(p, @"窗口正在移除"); p->input_context.mode = 11; reset_events();
        [p finishMarkedTextOnFocusLoss];
        demand(commits == 0, "a window removed by the input context cannot receive fallback input"); finished(p);

        p = fresh(); NSString *large = [repeated(@"甲😀", 65537) stringByAppendingString:@"结尾"];
        compose(p, large); reset_events(); [p finishMarkedTextOnFocusLoss];
        demand(commits == 1 && [delivered isEqualToString:large], "long Unicode refill is complete without fixed-buffer truncation"); finished(p);
        Probe *other = fresh(); compose(other, @"另一个窗口"); reset_events();
        [p finishMarkedTextOnFocusLoss]; demand(commits == 0 && [other hasMarkedText], "other window composition stays untouched");
        [other finishMarkedTextOnFocusLoss]; demand(commits == 1 && last_target == other->window, "each window refills its own input");
        [other startDictation:nil]; compose(other, @"关闭窗口"); other->window = NULL; reset_events();
        [other finishMarkedTextOnFocusLoss]; [other unmarkText];
        demand(commits == 0, "removed windows cannot receive automatic input");
        puts("IME_RECOVERY_NATIVE_OK: automatic voice/pinyin refill, original fragment, focus callbacks, final results, "
             "cancellation, commit deduplication, Unicode, window isolation");
        return 0;
    }
}
'''
