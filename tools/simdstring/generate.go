// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>
//go:build ignore

// See https://www.quasilyte.dev/blog/post/go-asm-complementary-reference/
// for differences between AT&T and Go assembly
package main

import (
	"bytes"
	"fmt"
	"go/types"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"unsafe"
)

var _ = fmt.Print

type Register struct {
	Name       string
	Size       int
	Restricted bool
}

func (r Register) String() string            { return r.Name }
func (r Register) ARMFullWidth() string      { return fmt.Sprintf("%s.B%d", r, r.Size/8) }
func (r Register) AddressInRegister() string { return fmt.Sprintf("(%s)", r) }

type Arch string

const (
	X86   Arch = "386"
	AMD64 Arch = "amd64"
	ARM64 Arch = "arm64"
)

type ISA struct {
	Bits                       int
	Goarch                     Arch
	Registers                  []Register
	UsedRegisters              map[Register]bool
	Sizes                      types.Sizes
	GeneralPurposeRegisterSize int
	HasSIMD                    bool
}

const ByteSlice types.BasicKind = 100001

func (isa *ISA) NativeAdd() string {
	if isa.Goarch == ARM64 {
		return "ADD"
	}
	if isa.GeneralPurposeRegisterSize == 32 {
		return "ADDL"
	}
	return "ADDQ"
}

func (isa *ISA) NativeSubtract() string {
	if isa.Goarch == ARM64 {
		return "SUB"
	}
	if isa.GeneralPurposeRegisterSize == 32 {
		return "SUBL"
	}
	return "SUBQ"
}

func (isa *ISA) add_regs(size int, names ...string) {
	for _, r := range names {
		isa.Registers = append(isa.Registers, Register{r, size, false})
	}
}

func (ans *ISA) add_x86_regs() {
	ans.add_regs(ans.GeneralPurposeRegisterSize, `AX`, `BX`, `DX`, `SI`, `DI`, `BP`)
	if ans.GeneralPurposeRegisterSize == 64 {
		ans.add_regs(ans.GeneralPurposeRegisterSize, `R8`, `R9`, `R10`, `R11`, `R12`, `R13`, `R14`, `R15`)
	}
	// CX is used for shift and rotate instructions
	ans.Registers = append(ans.Registers, Register{`CX`, ans.GeneralPurposeRegisterSize, true})
	// SP is the stack pointer used by the Go runtime
	ans.Registers = append(ans.Registers, Register{`SP`, ans.GeneralPurposeRegisterSize, true})
	ans.add_regs(128, `X0`, `X1`, `X2`, `X3`, `X4`, `X5`, `X6`, `X7`, `X8`, `X9`, `X10`, `X11`, `X12`, `X13`, `X14`, `X15`)
	if ans.Goarch == AMD64 {
		ans.add_regs(256,
			`Y0`, `Y1`, `Y2`, `Y3`, `Y4`, `Y5`, `Y6`, `Y7`, `Y8`, `Y9`, `Y10`, `Y11`, `Y12`, `Y13`, `Y14`, `Y15`)
	}
}

func Createi386ISA(bits int) ISA {
	ans := ISA{
		Bits:                       bits,
		GeneralPurposeRegisterSize: 32,
		Goarch:                     X86,
		Sizes:                      types.SizesFor(runtime.Compiler, string(X86)),
		HasSIMD:                    bits == 128,
	}
	ans.add_x86_regs()
	return ans
}

func CreateAMD64ISA(bits int) ISA {
	ans := ISA{
		Bits:                       bits,
		GeneralPurposeRegisterSize: 64,
		Goarch:                     AMD64,
		Sizes:                      types.SizesFor(runtime.Compiler, string(AMD64)),
		HasSIMD:                    true,
	}
	ans.add_x86_regs()
	return ans
}

func CreateARM64ISA(bits int) ISA {
	ans := ISA{
		Bits:                       bits,
		Goarch:                     ARM64,
		GeneralPurposeRegisterSize: 64,
		Sizes:                      types.SizesFor(runtime.Compiler, string(ARM64)),
		HasSIMD:                    bits == 128,
	}
	ans.add_regs(ans.GeneralPurposeRegisterSize,
		`R0`, `R1`, `R2`, `R3`, `R4`, `R5`, `R6`, `R7`, `R8`, `R9`, `R10`, `R11`, `R12`, `R13`, `R14`, `R15`)
	ans.add_regs(128,
		`V0`, `V1`, `V2`, `V3`, `V4`, `V5`, `V6`, `V7`, `V8`, `V9`, `V10`, `V11`, `V12`, `V13`, `V14`, `V15`,
		`V16`, `V17`, `V18`, `V19`, `V20`, `V21`, `V22`, `V23`, `V24`, `V25`, `V26`, `V27`, `V28`, `V29`, `V30`, `V31`,
	)
	return ans
}

func AsVar(s types.BasicKind, name string) *types.Var {
	var t types.Type
	switch s {
	case ByteSlice:
		t = types.NewSlice(types.Typ[types.Byte])
	default:
		t = types.Typ[s]
	}
	return types.NewParam(0, nil, name, t)

}

type FunctionParam struct {
	Name string
	Type types.BasicKind
}

type Function struct {
	Name            string
	Desc            string
	Params, Returns []FunctionParam
	UsedRegisters   map[Register]bool

	Size                        int
	ISA                         ISA
	ParamOffsets, ReturnOffsets []int
	Instructions                []string
	Used256BitReg               bool
}

func (f *Function) Reg() Register {
	for _, r := range f.ISA.Registers {
		if !r.Restricted && r.Size == f.ISA.GeneralPurposeRegisterSize && !f.UsedRegisters[r] {
			f.UsedRegisters[r] = true
			return r
		}
	}
	b := []string{}
	for _, r := range f.ISA.Registers {
		if !r.Restricted && r.Size == f.ISA.GeneralPurposeRegisterSize {
			b = append(b, r.Name)
		}
	}
	panic(fmt.Sprint("No available general purpose registers, used registers: ", strings.Join(b, ", ")))
}

func (f *Function) RegForShifts() Register {
	if f.ISA.Goarch == ARM64 {
		return f.Reg()
	}
	for _, r := range f.ISA.Registers {
		if r.Name == "CX" {
			if f.UsedRegisters[r] {
				panic("The register for shifts is already used")
			}
			return r
		}
	}
	panic("No register for shifts found")
}

func (f *Function) Vec(size ...int) Register {
	szq := f.ISA.Bits
	if len(size) > 0 {
		szq = size[0]
	}
	if f.ISA.Goarch == ARM64 {
		for _, r := range f.ISA.Registers {
			if r.Size == szq && !r.Restricted && !f.UsedRegisters[r] {
				f.UsedRegisters[r] = true
				if r.Size > 128 {
					f.Used256BitReg = true
				}
				return r
			}
		}
	} else {
		// In Intels crazy architecture AVX registers and SSE registers are the same hardware register so changing
		// one can change the other. Sigh.
		used := make(map[uint32]bool, len(f.UsedRegisters))
		for r, is_used := range f.UsedRegisters {
			if is_used && r.Size > f.ISA.GeneralPurposeRegisterSize {
				used[r.ARMId()] = true
			}
		}
		for _, r := range f.ISA.Registers {
			if r.Size == szq && !r.Restricted && !used[r.ARMId()] {
				f.UsedRegisters[r] = true
				if r.Size > 128 {
					f.Used256BitReg = true
				}
				return r
			}
		}

	}
	panic("No available vector registers")
}

func (f *Function) ReleaseReg(r ...Register) {
	for _, x := range r {
		f.UsedRegisters[x] = false
	}
}

func (f *Function) instr(items ...any) {
	sarr := make([]string, len(items))
	for i, val := range items {
		var f string
		if i > 0 && i < len(items)-1 {
			f = "%s,"
		} else {
			f = "%s"
		}
		sarr[i] = fmt.Sprintf(f, val)
	}
	f.Instructions = append(f.Instructions, "\t"+strings.Join(sarr, " "))
}

func (f *Function) MemLoadForBasicType(t types.BasicKind) string {
	if f.ISA.Goarch == ARM64 {
		switch t {
		case types.Uint8:
			return "MOVBU"
		case types.Int8:
			return "MOVB"
		case types.Uint16:
			return "MOVHU"
		case types.Int16:
			return "MOVH"
		case types.Uint32:
			return "MOVWU"
		case types.Int32:
			return "MOVW"
		case types.Uint64, types.Uintptr, ByteSlice, types.String, types.Uint, types.Int64, types.Int:
			return `MOVD`
		}
	} else {
		if f.ISA.GeneralPurposeRegisterSize == 32 {
			switch t {
			case types.Uint8:
				return "MOVBLZX"
			case types.Int8:
				return "MOVBLSX"
			case types.Uint16:
				return "MOVWLZX"
			case types.Int16:
				return "MOVWLSX"
			case types.Uint32, types.Uintptr, types.Int32, ByteSlice, types.String, types.Int, types.Uint:
				return "MOVL"
			}
		} else {
			switch t {
			case types.Uint8:
				return "MOVBQZX"
			case types.Int8:
				return "MOVBQSX"
			case types.Uint16:
				return "MOVWQZX"
			case types.Int16:
				return "MOVWQSX"
			case types.Uint32:
				return "MOVLQZX"
			case types.Int32:
				return "MOVLQSX"
			case types.Int64, types.Uint64, types.Uintptr, ByteSlice, types.String, types.Int, types.Uint:
				return "MOVQ"
			}
		}
	}
	panic(fmt.Sprint("Unknown type: ", t))
}

func (f *Function) LoadUnsignedBytesFromMemory(addr string, n int, dest Register) {
	defer f.AddTrailingComment(dest, "=", n, "byte(s) from the memory pointed to by", addr)
	switch n {
	case 1:
		if dest.Size != f.ISA.GeneralPurposeRegisterSize {
			panic(fmt.Sprintf("cannot load %d bytes into vector register", n))
		}
		f.instr(f.MemLoadForBasicType(types.Byte), addr, dest)
	case 2:
		if dest.Size != f.ISA.GeneralPurposeRegisterSize {
			panic(fmt.Sprintf("cannot load %d bytes into vector register", n))
		}
		f.instr(f.MemLoadForBasicType(types.Uint16), addr, dest)
	case 4:
		if dest.Size != f.ISA.GeneralPurposeRegisterSize {
			panic(fmt.Sprintf("cannot load %d bytes into vector register", n))
		}
		f.instr(f.MemLoadForBasicType(types.Uint32), addr, dest)
	case 8:
		if dest.Size != f.ISA.GeneralPurposeRegisterSize {
			panic(fmt.Sprintf("cannot load %d bytes into vector register", n))
		}
		if dest.Size*8 > f.ISA.GeneralPurposeRegisterSize {
			panic(fmt.Sprintf("cannot load %d bytes into %d bit register", n, dest.Size))
		}
		f.instr(f.MemLoadForBasicType(types.Uint64), addr, dest)
	default:
		if dest.Size*8 != f.ISA.GeneralPurposeRegisterSize {
			panic(fmt.Sprintf("cannot load %d bytes into %d bit register", n, dest.Size))
		}
		f.instr(f.MemLoadForBasicType(types.Uintptr), addr, dest)
	}
}

func (f *Function) LoadParam(p string) Register {
	r := f.Reg()
	for i, q := range f.Params {
		if q.Name == p {
			offset := f.ParamOffsets[i]
			mov := f.MemLoadForBasicType(q.Type)
			f.instr(mov, fmt.Sprintf("%s+%d(FP)", q.Name, offset), r)
			f.AddTrailingComment("load the function parameter", p, "into", r)
		}
	}
	return r
}

func (f *Function) set_return_value(offset int, q FunctionParam, val any) {
	mov := f.MemLoadForBasicType(q.Type)
	vr := val_repr_for_arithmetic(val)
	defer f.AddTrailingComment("save the value:", val, "to the function return parameter:", q.Name)
	if f.ISA.Goarch == ARM64 && strings.HasPrefix(vr, `$`) {
		// no way to store an immediate value into a memory address
		temp := f.Reg()
		f.SetRegisterTo(temp, val)
		defer f.ReleaseReg(temp)
		vr = temp.Name
	}
	f.instr(mov, vr, fmt.Sprintf("%s+%d(FP)", q.Name, offset))
}

func (f *Function) SetReturnValue(p string, val any) {
	for i, q := range f.Returns {
		if q.Name == p {
			f.set_return_value(f.ReturnOffsets[i], q, val)
			break
		}
	}
}

func (f *Function) CountTrailingZeros(r, ans Register) {
	if r.Size == f.ISA.GeneralPurposeRegisterSize {
		if f.ISA.Goarch == ARM64 {
			f.instr("RBIT", r, r)
			f.AddTrailingComment("reverse the bits")
			f.instr("CLZ", r, ans)
			f.AddTrailingComment(ans, "= number of leading zeros in", r)
		} else {
			f.instr("BSFL", ans, ans)
			f.AddTrailingComment(ans, "= number of trailing zeros in", r)
		}
	} else {
		panic("cannot count trailing zeros in a vector register")
	}
}

func (f *Function) Comment(x ...any) {
	f.Instructions = append(f.Instructions, space_join("\t//", x...))
}

func shrn8b_immediate4(a, b Register) uint32 {
	return (0x0f0c84 << 8) | (a.ARMId()<<5 | b.ARMId())
}

func encode_cmgt16b(a, b, dest Register) (ans uint32) {
	return 0x271<<21 | b.ARMId()<<16 | 0xd<<10 | a.ARMId()<<5 | dest.ARMId()
}

func (f *Function) MaskForCountDestructive(vec, ans Register) {
	// vec is clobbered by this function
	f.Comment("Count the number of bytes to the first 0xff byte and put the result in", ans)
	if f.ISA.Goarch == ARM64 {
		// See https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/porting-x86-vector-bitmask-optimizations-to-arm-neon
		f.Comment("Go assembler doesn't support the shrn instruction, below we have: shrn.8b", vec, vec, "#4")
		f.Comment("It is shifting right by four bits in every 16 bit word and truncating to 8 bits storing the result in the lower 64 bits of", vec)
		f.instr("WORD", fmt.Sprintf("$0x%x", shrn8b_immediate4(vec, vec)))
		f.instr("FMOVD", "F"+vec.Name[1:], ans)
		f.AddTrailingComment("Extract the lower 64 bits from", vec, "and put them into", ans)
	} else {
		if f.ISA.Bits == 128 {
			f.instr("PMOVMSKB", vec, ans)
		} else {
			f.instr("VPMOVMSKB", vec, ans)
		}
		f.AddTrailingComment(ans, "= mask of the highest bit in every byte in", vec)
	}
}

func (f *Function) shift_self(right bool, self, amt any) {
	op := ""
	if right {
		op = "SHRQ"
		if f.ISA.Goarch == ARM64 {
			op = "LSR"
		}
	} else {
		op = "SHLQ"
		if f.ISA.Goarch == ARM64 {
			op = "LSL"
		}
	}
	switch v := amt.(type) {
	case Register:
		if f.ISA.Goarch != ARM64 && v.Name != "CX" {
			panic("On Intel only the CX register can be used for shifts")
		}
		f.instr(op, v, self)
	default:
		f.instr(op, val_repr_for_arithmetic(v), self)
	}
}

func (f *Function) ShiftSelfRight(self, amt any) {
	f.shift_self(true, self, amt)
}

func (f *Function) ShiftSelfLeft(self, amt any) {
	f.shift_self(false, self, amt)
}

func (f *Function) ShiftMaskRightDestructive(mask, amt any) {
	// The amt register is clobbered by this function
	switch n := amt.(type) {
	case Register:
		if f.ISA.Goarch == ARM64 {
			f.Comment("The mask has 4 bits per byte, so multiply", n, "by 4")
			f.ShiftSelfLeft(n, 2)
		}
		f.ShiftSelfRight(mask, n)
	case int:
		if f.ISA.Goarch == ARM64 {
			n <<= 2
		}
		f.ShiftSelfRight(mask, n)
	default:
		panic(fmt.Sprintf("Cannot shift by: %s", amt))
	}
}

func (f *Function) CountLeadingZeroBytesInMask(src, ans Register) {
	if f.ISA.Goarch == ARM64 {
		f.CountTrailingZeros(src, ans)
		f.instr("UBFX", "$2", ans, "$30", ans)
		f.AddTrailingComment(ans, ">>= 2 (divide by 4)")
	} else {
		f.CountTrailingZeros(src, ans)
	}
}

func (f *Function) CountBytesToFirstMatchDestructive(vec, ans Register) {
	// vec is clobbered by this function
	f.Comment("Count the number of bytes to the first 0xff byte and put the result in", ans)
	f.MaskForCountDestructive(vec, ans)
	f.CountLeadingZeroBytesInMask(ans, ans)
	f.BlankLine()
}

func (f *Function) LoadParamLen(p string) Register {
	r := f.Reg()
	for i, q := range f.Params {
		if q.Name == p {
			offset := f.ParamOffsets[i]
			if q.Type == ByteSlice || q.Type == types.String {
				offset += int(f.ISA.Sizes.Sizeof(types.Typ[types.Uintptr]))
			}
			mov := f.MemLoadForBasicType(q.Type)
			f.instr(mov, fmt.Sprintf("%s_len+%d(FP)", q.Name, offset), r)
			f.AddTrailingComment("load the length of the function parameter", q.Name, "into", r)
			break
		}
	}
	return r
}

func (f *Function) unaligned_move() string {
	switch f.ISA.Goarch {
	case X86, AMD64:
		if f.ISA.Bits == 128 {
			return "MOVOU"
		}
		return "VMOVDQU"
	default:
		panic("Unknown arch: " + string(f.ISA.Goarch))
	}
}

func (f *Function) aligned_move() string {
	switch f.ISA.Goarch {
	case X86, AMD64:
		if f.ISA.Bits == 128 {
			return "MOVOA"
		}
		return "VMOVDQA"
	default:
		panic("Unknown arch: " + string(f.ISA.Goarch))
	}
}

func (f *Function) LoadPointerUnaligned(register_containing_pointer_value Register, dest Register) {
	addr := register_containing_pointer_value.AddressInRegister()
	if f.ISA.Goarch == ARM64 {
		f.instr(`VLD1`, addr, "["+dest.ARMFullWidth()+"]")
	} else {
		f.instr(f.unaligned_move(), addr, dest)
	}
	f.AddTrailingComment("load memory from the address in", register_containing_pointer_value, "to", dest)
}

func (f *Function) LoadPointerAligned(register_containing_pointer_value Register, dest Register) {
	addr := register_containing_pointer_value.AddressInRegister()
	if f.ISA.Goarch == ARM64 {
		f.instr(`VLD1`, addr, "["+dest.ARMFullWidth()+"]")
	} else {
		f.instr(f.aligned_move(), addr, dest)
	}
	f.AddTrailingComment("load memory from the address in", register_containing_pointer_value, "to", dest)
}

func (f *Function) StoreUnalignedToPointer(vec, register_containing_pointer_value Register) {
	if f.ISA.Goarch == ARM64 {
		f.instr(`VST1`, "["+vec.ARMFullWidth()+"]", fmt.Sprintf("(%s)", register_containing_pointer_value))
	} else {
		f.instr(f.unaligned_move(), vec, fmt.Sprintf("(%s)", register_containing_pointer_value))
	}
	f.AddTrailingComment("store the value of", vec, "in to the memory whose address is in:", register_containing_pointer_value)
}

func (f *Function) test_if_zero(a Register) {
	if f.ISA.Goarch == ARM64 {
		f.instr("AND", a, a, a)
	}
	switch a.Size {
	case 32:
		f.instr("TESTL", a, a)
	case 64:
		f.instr("TESTQ", a, a)
	case 128:
		f.instr("PTEST", a, a)
	default:
		f.instr("VPTEST", a, a)
	}
	f.AddTrailingComment("test if", a, "is zero")

}

func (f *Function) JumpTo(label string) {
	f.instr("JMP", label)
	f.AddTrailingComment("jump to:", label)
}

func (f *Function) jump_on_zero_check(a Register, label string, on_zero bool) {
	if f.ISA.Goarch == ARM64 {
		if a.Size > f.ISA.GeneralPurposeRegisterSize {
			temp := f.Vec()
			defer f.ReleaseReg(temp)
			f.instr("VDUP", a.Name+".D[1]", temp)
			f.AddTrailingComment(`duplicate the upper 64 bits of`, a, "into the lower and upper 64 bits of", temp)
			f.Or(a, temp, temp)
			a = f.Reg()
			defer f.ReleaseReg(a)
			f.instr("FMOVD", "F"+temp.Name[1:], a)
			f.AddTrailingComment(a, "= lower 64bits of", temp)
		}
		if on_zero {
			f.instr("CBZ", a, label)
		} else {
			f.instr("CBNZ", a, label)
		}
	} else {
		f.test_if_zero(a)
		if on_zero {
			f.instr("JZ", label)
		} else {
			f.instr("JNZ", label)
		}
	}
}

func (f *Function) JumpIfZero(a Register, label string) {
	f.jump_on_zero_check(a, label, true)
	f.AddTrailingComment("jump to:", label, "if", a, "is zero")
}

func (f *Function) JumpIfNonZero(a Register, label string) {
	f.jump_on_zero_check(a, label, false)
	f.AddTrailingComment("jump to:", label, "if", a, "is non-zero")
}

func (f *Function) compare(a, b Register) {
	if f.ISA.Goarch == ARM64 {
		f.instr("CMP", b, a)
	} else {
		if a.Size == 32 {
			f.instr("CMPL", a, b)
		} else {
			f.instr("CMPQ", a, b)
		}
	}
	f.AddTrailingComment("compare", a, "to", b)
}

func (f *Function) JumpIfLessThan(a, b Register, label string) {
	f.compare(a, b)
	if f.ISA.Goarch == ARM64 {
		f.instr("BLT", label)
	} else {
		f.instr("JLT", label)
	}
	f.AddTrailingComment("jump to:", label, "if", a, "<", b)
}

func (f *Function) JumpIfLessThanOrEqual(a, b Register, label string) {
	f.compare(a, b)
	if f.ISA.Goarch == ARM64 {
		f.instr("BLE", label)
	} else {
		f.instr("JLE", label)
	}
	f.AddTrailingComment("jump to:", label, "if", a, "<=", b)
}

func (f *Function) JumpIfEqual(a, b Register, label string) {
	f.compare(a, b)
	if f.ISA.Goarch == ARM64 {
		f.instr("BEQ", label)
	} else {
		f.instr("JE", label)
	}
	f.AddTrailingComment("jump to:", label, "if", a, "==", b)
}

func (f *Function) Or(a, b, dest Register) {
	if f.ISA.Goarch == ARM64 {
		f.instr("VORR", a.ARMFullWidth(), b.ARMFullWidth(), dest.ARMFullWidth())
	} else {
		if f.ISA.Bits == 128 {
			switch dest.Name {
			case b.Name:
				f.instr("POR", a, b)
			case a.Name:
				f.instr("POR", b, a)
			default:
				f.CopyRegister(b, dest)
				f.instr("POR", a, dest)
			}
		} else {
			f.instr("VPOR", a, b, dest)
		}
	}
	f.AddTrailingComment(dest, "=", a, "|", b, "(bitwise)")
}

func (f *Function) And(a, b, dest Register) {
	if f.ISA.Goarch == ARM64 {
		f.instr("VAND", a.ARMFullWidth(), b.ARMFullWidth(), dest.ARMFullWidth())
	} else {
		if f.ISA.Bits == 128 {
			switch dest.Name {
			case b.Name:
				f.instr("PAND", a, b)
			case a.Name:
				f.instr("PAND", b, a)
			default:
				f.CopyRegister(b, dest)
				f.instr("PAND", a, dest)
			}
		} else {
			f.instr("VPAND", a, b, dest)
		}
	}
	f.AddTrailingComment(dest, "=", a, "&", b, "(bitwise)")
}

func (f *Function) ClearRegisterToZero(r Register) {
	defer func() { f.AddTrailingComment("set", r, "to zero") }()
	if f.ISA.Goarch == ARM64 {
		if r.Size == f.ISA.GeneralPurposeRegisterSize {
			f.instr(f.MemLoadForBasicType(types.Int32), val_repr_for_arithmetic(0), r)
		} else {
			f.instr("VMOVI", "$0", r.ARMFullWidth())
		}
		return
	}
	switch r.Size {
	case 128:
		f.instr("PXOR", r, r)
	case f.ISA.GeneralPurposeRegisterSize:
		if r.Size == 32 {
			f.instr("XORL", r, r)
		} else {
			f.instr("XORQ", r, r)
		}
	case 256:
		f.instr("VPXOR", r, r, r)
	}
}

func (f *Function) AllOnesRegister(r Register) {
	switch r.Size {
	default:
		f.CmpEqEpi8(r, r, r)
	case f.ISA.GeneralPurposeRegisterSize:
		if f.ISA.Goarch == ARM64 {
			f.instr("MOVD", "$-1", r)
		} else {
			switch r.Size {
			case 32:
				f.instr("MOVL", "$0xFFFFFFFF")
			case 64:
				f.instr("MOVQ", "$0xFFFFFFFFFFFFFFFF")
			}
		}
		f.AddTrailingComment(r, "= all ones")
	}
}

func (f *Function) CopyRegister(a, ans Register) {
	if a.Size != ans.Size {
		panic("Can only copy registers of equal sizes")
	}
	if a.Size > f.ISA.GeneralPurposeRegisterSize {
		if f.ISA.Goarch == ARM64 {
			f.instr("VDUP", a.Name[1:]+".D2", ans.Name+".D2")
		} else {
			f.instr(f.aligned_move(), a, ans)
		}
	} else {
		if f.ISA.Goarch == ARM64 {
			f.instr("MOVD", a, ans)
		} else {
			if a.Size == 32 {
				f.instr("MOVL", a, ans)
			} else {
				f.instr("MOVQ", a, ans)
			}
		}
	}
	f.AddTrailingComment(ans, "=", a)
}

func (f *Function) SetRegisterTo(self Register, val any) {
	switch v := val.(type) {
	case Register:
		f.CopyRegister(self, v)
	case int:
		if self.Size != f.ISA.GeneralPurposeRegisterSize {
			panic("TODO: Cannot yet set constant values in vector registers")
		}
		switch v {
		case 0:
			f.ClearRegisterToZero(self)
		case -1:
			f.AllOnesRegister(self)
		default:
			if f.ISA.Goarch == ARM64 {
				f.instr("MOVD", val_repr_for_arithmetic(v), self)
			} else {
				f.instr("MOVL", val_repr_for_arithmetic(v), self)
			}
			f.AddTrailingComment(self, "= ", v)
		}
	case string:
		f.instr(f.MemLoadForBasicType(types.Uintptr), v)
		f.AddTrailingComment(self, "=", self.Size/8, "bytes at the address", v)
	default:
		panic(fmt.Sprintf("cannot set register to value: %#v", val))
	}
}

func (r Register) ARMId() uint32 {
	num, err := strconv.ParseUint(r.Name[1:], 10, 32)
	if err != nil {
		panic(err)
	}
	return uint32(num)
}

func (f *Function) cmp(a, b, ans Register, op, c_rep string) {
	if a.Size != b.Size || a.Size != ans.Size {
		panic("Can only compare registers of equal sizes")
	}
	if f.ISA.Goarch == ARM64 {
		if op == "EQ" {
			f.instr("VCMEQ", a.ARMFullWidth(), b.ARMFullWidth(), ans.ARMFullWidth())
		} else {
			f.instr("WORD", fmt.Sprintf("$0x%x", encode_cmgt16b(a, b, ans)))
		}
	} else {
		fop := `PCMP` + op + "B"
		if f.ISA.Bits == 128 {
			if op == "EQ" {
				switch ans.Name {
				case a.Name:
					f.instr(fop, b, ans)
				case b.Name:
					f.instr(fop, a, ans)
				default:
					f.CopyRegister(a, ans)
					f.instr(fop, b, ans)
				}
			} else {
				// order matters, we want destination aka 2nd arg to be both a and ans
				switch ans.Name {
				case a.Name:
					f.instr(fop, b, a)
				case b.Name:
					vec := f.Vec(a.Size)
					f.CopyRegister(a, vec)
					f.instr(fop, b, vec)
					f.CopyRegister(vec, b)
					f.ReleaseReg(vec)
				default:
					f.CopyRegister(a, ans)
					f.instr(fop, b, ans)
				}
			}
		} else {
			f.instr("V"+fop, b, a, ans)
		}
	}
	f.AddTrailingComment(ans, "= 0xff on every byte where", a.Name+"[n]", c_rep, b.Name+"[n] and zero elsewhere")
}

func (f *Function) CmpGtEpi8(a, b, ans Register) {
	f.cmp(a, b, ans, "GT", ">")
}

func (f *Function) CmpLtEpi8(a, b, ans Register) {
	f.cmp(b, a, ans, "GT", ">")
}

func (f *Function) CmpEqEpi8(a, b, ans Register) {
	f.cmp(a, b, ans, "EQ", "==")
}

func (f *Function) Set1Epi8(val any, vec Register) {
	if vec.Size != 128 && vec.Size != 256 {
		panic("Set1Epi8 only works on vector registers")
	}
	do_shuffle_load := func(r Register) {
		f.instr("MOVL", r, vec)
		shuffle_mask := f.Vec()
		f.ClearRegisterToZero(shuffle_mask)
		f.instr("PSHUFB", shuffle_mask, vec)
		f.ReleaseReg(shuffle_mask)
	}

	switch v := val.(type) {
	default:
		panic("unknown type for set1_epi8")
	case int:
		switch v {
		case 0:
			f.ClearRegisterToZero(vec)
			return
		case -1:
			f.AllOnesRegister(vec)
			return
		}
		r := f.Reg()
		defer f.ReleaseReg(r)
		f.SetRegisterTo(r, v)
		f.Set1Epi8(r, vec)
	case Register:
		f.Comment("Set all bytes of", vec, "to the lowest byte in", v)
		if v.Size != f.ISA.GeneralPurposeRegisterSize {
			panic("Can only set1_epi8 from a general purpose register")
		}
		if f.ISA.Goarch == ARM64 {
			f.instr("VMOV", v, vec.ARMFullWidth())
		} else {
			switch vec.Size {
			case 128:
				do_shuffle_load(v)
			case 256:
				temp := f.Vec(128)
				defer f.ReleaseReg(temp)
				f.instr("VMOVD", v, temp)
				f.instr("VPBROADCASTB", temp, vec)
			}
		}
		defer f.Comment()
	case string:
		f.Comment("Set all bytes of", vec, "to the first byte in", v)
		if f.ISA.Goarch == ARM64 {
			r := f.LoadParam(v)
			f.instr("VMOV", r, vec.ARMFullWidth())
			f.ReleaseReg(r)
			return
		}
		switch vec.Size {
		case 128:
			r := f.LoadParam(v)
			defer f.ReleaseReg(r)
			do_shuffle_load(r)
		case 256:
			f.instr("VPBROADCASTB", f.ParamPos(v), vec)
		}
		defer f.Comment()
	}
}

func (isa *ISA) structsize(vs []*types.Var) int64 {
	n := len(vs)
	if n == 0 {
		return 0
	}
	offsets := isa.Sizes.Offsetsof(vs)
	return offsets[n-1] + isa.Sizes.Sizeof(vs[n-1].Type())
}

func tuplevars(params []FunctionParam) []*types.Var {
	vars := make([]*types.Var, len(params))
	for i, p := range params {
		vars[i] = AsVar(p.Type, p.Name)
	}
	return vars
}

func NewFunction(isa ISA, name, description string, params, returns []FunctionParam) *Function {
	name = fmt.Sprintf("%s_%d", name, isa.Bits)
	ans := Function{Name: name, Desc: description, Params: params, Returns: returns, ISA: isa}
	vars := tuplevars(params)
	vars = append(vars, types.NewParam(0, nil, "sentinel", types.Typ[types.Uint64]))
	offsets := isa.Sizes.Offsetsof(vars)
	n := len(params)
	paramssize := int(offsets[n])
	ans.ParamOffsets = make([]int, n)
	ans.Size = paramssize
	for i := range ans.ParamOffsets {
		ans.ParamOffsets[i] = int(offsets[i])
	}
	if len(returns) > 0 {
		vars = tuplevars(returns)
		offsets = isa.Sizes.Offsetsof(vars)
		ans.ReturnOffsets = make([]int, len(offsets))
		for i, off := range offsets {
			ans.ReturnOffsets[i] = paramssize + int(off)
		}
		ans.Size += int(isa.structsize(vars))
	}
	return &ans
}

func (s *Function) ParamPos(name string) string {
	for n, i := range s.Params {
		if i.Name == name {
			return fmt.Sprintf("%s+%d(FP)", i.Name, s.ParamOffsets[n])
		}
	}
	panic(fmt.Errorf("Unknown parameter: %s", name))
}

func (s *Function) print_signature(w io.Writer) {
	fmt.Fprintf(w, "func %s(", s.Name)
	print_p := func(p FunctionParam) {
		var tname string
		if p.Type == ByteSlice {
			tname = "[]byte"
		} else {
			tname = types.Universe.Lookup(types.Typ[p.Type].String()).String()
		}
		tname, _ = strings.CutPrefix(tname, "type ")
		fmt.Fprintf(w, "%s %s", p.Name, tname)
	}
	for i, p := range s.Params {
		if i > 0 {
			fmt.Fprint(w, ", ")
		}
		print_p(p)
	}
	fmt.Fprint(w, ")")
	if len(s.Returns) == 0 {
		return
	}
	fmt.Fprint(w, " (")
	for i, p := range s.Returns {
		if i > 0 {
			fmt.Fprint(w, ", ")
		}
		print_p(p)
	}
	fmt.Fprint(w, ")")
}

func (s *Function) OutputStub(w io.Writer) {
	if s.Desc != "" {
		fmt.Fprintln(w, "// "+s.Desc)
		fmt.Fprintln(w, "//")
	}
	if s.ISA.HasSIMD {
		fmt.Fprintln(w, "//go:noescape")
	}
	s.print_signature(w)
	if s.ISA.HasSIMD {
		fmt.Fprintln(w)
	} else {
		fmt.Fprintln(w, "{")
		fmt.Fprintln(w, "panic(\"No SIMD implementations for this function\")")
		fmt.Fprintln(w, "}")
	}
	fmt.Fprintln(w)
}

func (s *Function) BlankLine() { s.Instructions = append(s.Instructions, "") }

func (s *Function) Return() {
	if s.Used256BitReg {
		s.instr("VZEROUPPER")
		s.AddTrailingComment("zero upper bits of AVX registers to avoid dependencies when switching between SSE and AVX code")
	}
	s.instr("RET")
	s.AddTrailingComment("return from function")
	s.BlankLine()
}

func (s *Function) end_function() {
	amt := 16
	if s.Used256BitReg {
		amt = 32
	}
	s.instr(fmt.Sprintf("PCALIGN $%d\n", amt))
	s.Return()
}

func (s *Function) Label(name string) {
	s.Instructions = append(s.Instructions, name+":")
	s.AddTrailingComment("jump target")
}

func space_join(prefix string, x ...any) string {
	b := strings.Builder{}
	if prefix != "" {
		b.WriteString(prefix)
		b.WriteByte(' ')
	}
	for _, x := range x {
		b.WriteString(fmt.Sprint(x))
		b.WriteByte(' ')
	}
	return b.String()

}

func (s *Function) AddTrailingComment(x ...any) {
	s.Instructions[len(s.Instructions)-1] += space_join(" //", x...)
}

func val_repr_for_arithmetic(val any) (ans string) {
	switch v := val.(type) {
	case int:
		if v < 0 {
			return fmt.Sprintf("$%d", v)
		}
		return fmt.Sprintf("$0x%x", v)
	case string:
		return val.(string)
	case fmt.Stringer:
		return val.(fmt.Stringer).String()
	default:
		return fmt.Sprint(val)
	}
}

func (f *Function) AndSelf(self Register, val any) {
	switch f.ISA.Goarch {
	case ARM64:
		f.instr("AND", val_repr_for_arithmetic(val), self)
	case AMD64:
		f.instr("ANDQ", val_repr_for_arithmetic(val), self)
	case X86:
		f.instr("ANDL", val_repr_for_arithmetic(val), self)
	default:
		panic("Unknown architecture for AND")
	}
	f.AddTrailingComment(self, "&=", val)
}

func (f *Function) NegateSelf(self Register) {
	if f.ISA.Goarch == "ARM64" {
		f.instr("NEG", self, self)
	} else {
		f.instr("NEGQ", self)
	}
	f.AddTrailingComment(self, "*= -1")
}

func (f *Function) AddToSelf(self Register, val any) {
	f.instr(f.ISA.NativeAdd(), val_repr_for_arithmetic(val), self) // pos += sizeof(vec)
	f.AddTrailingComment(self, "+=", val)
}

func (f *Function) SubtractFromSelf(self Register, val any) {
	f.instr(f.ISA.NativeSubtract(), val_repr_for_arithmetic(val), self) // pos += sizeof(vec)
	f.AddTrailingComment(self, "-=", val)
}

func (s *Function) SetRegisterToOffset(dest Register, base_register Register, constant_offset int, offset_register Register) {
	if s.ISA.Goarch == ARM64 {
		s.SetRegisterTo(dest, constant_offset)
		s.AddToSelf(dest, base_register)
		s.AddToSelf(dest, offset_register)
	} else {
		addr := fmt.Sprintf("%d(%s)(%s*1)", constant_offset, base_register, offset_register)
		s.instr(s.ISA.LEA(), addr, dest)
		s.AddTrailingComment(dest, "=", base_register, "+", offset_register, "+", constant_offset)
	}
}

func (s *Function) OutputASM(w io.Writer) {
	if !s.ISA.HasSIMD {
		return
	}
	fmt.Fprint(w, "// ")
	s.print_signature(w)
	fmt.Fprintf(w, "\nTEXT ·%s(SB), NOSPLIT|TOPFRAME|NOFRAME, $0-%d\n", s.Name, s.Size)

	has_trailing_return := false
	for _, i := range s.Instructions {
		if len(i) == 0 {
			continue
		}
		if strings.HasPrefix(i, "\tRET ") {
			has_trailing_return = true
		} else {
			has_trailing_return = false
		}
	}

	if !has_trailing_return {
		s.Return()
	}
	for _, i := range s.Instructions {
		fmt.Fprintln(w, i)
	}
	fmt.Fprintln(w)
}

type State struct {
	ISA                           ISA
	ActiveFunction                *Function
	ASMOutput, StubOutput         strings.Builder
	TestASMOutput, TestStubOutput strings.Builder
}

var package_name = "simdstring"

func NewState(isa ISA, build_tags ...string) *State {
	ans := &State{ISA: isa}
	if len(build_tags) == 0 {
		build_tags = append(build_tags, string(isa.Goarch))
	}

	build_tag := func(w io.Writer, is_test bool) {
		fmt.Fprintf(w, "//go:build %s\n", strings.Join(build_tags, " "))
	}
	asm := func(w io.Writer) {
		fmt.Fprintln(w, "// Generated by generate.go do not edit")
		fmt.Fprintln(w, "// vim: ft=goasm")
		build_tag(w, w == &ans.TestASMOutput)
		fmt.Fprintln(w, "\n#include \"go_asm.h\"")
		fmt.Fprintln(w, "#include \"textflag.h\"")
		fmt.Fprintln(w)
	}
	asm(&ans.ASMOutput)
	asm(&ans.TestASMOutput)

	stub := func(w io.Writer) {
		fmt.Fprintln(w, "// Generated by generate.go do not edit")
		build_tag(w, w == &ans.TestStubOutput)
		fmt.Fprintln(w, "\npackage "+package_name)
		fmt.Fprintln(w)
	}
	stub(&ans.StubOutput)
	stub(&ans.TestStubOutput)
	return ans
}

func (s *State) OutputFunction() {
	if s.ActiveFunction == nil {
		return
	}
	if strings.HasPrefix(s.ActiveFunction.Name, "test_") {
		s.ActiveFunction.OutputASM(&s.TestASMOutput)
		s.ActiveFunction.OutputStub(&s.TestStubOutput)
	} else {
		s.ActiveFunction.OutputASM(&s.ASMOutput)
		s.ActiveFunction.OutputStub(&s.StubOutput)
	}
	s.ActiveFunction = nil
}

func (s *State) NewFunction(name, description string, params, returns []FunctionParam) *Function {
	s.OutputFunction()
	s.ActiveFunction = NewFunction(s.ISA, name, description, params, returns)
	s.ActiveFunction.UsedRegisters = make(map[Register]bool)
	return s.ActiveFunction
}

func (f *Function) load_vec_from_param(param string) Register {
	src := f.LoadParam(param)
	vec := f.Vec()
	f.LoadPointerUnaligned(src, vec)
	f.ReleaseReg(src)
	return vec
}

func (f *Function) store_vec_in_param(vec Register, param string) {
	ans := f.LoadParam(param)
	f.StoreUnalignedToPointer(vec, ans)
	f.ReleaseReg(ans)
}

func (s *State) test_load() {
	f := s.NewFunction("test_load_asm", "Test loading of vector register", []FunctionParam{{"src", ByteSlice}, {"ans", ByteSlice}}, nil)
	if !s.ISA.HasSIMD {
		return
	}
	vec := f.load_vec_from_param("src")
	f.store_vec_in_param(vec, `ans`)
}

func (s *State) test_set1_epi8() {
	f := s.NewFunction("test_set1_epi8_asm", "Test broadcast of byte into vector", []FunctionParam{{"b", types.Byte}, {"ans", ByteSlice}}, nil)
	if !s.ISA.HasSIMD {
		return
	}
	vec := f.Vec()
	r := f.LoadParam("b")
	q := f.Reg()
	f.SetRegisterTo(q, int(' '))
	f.JumpIfEqual(r, q, "space")
	f.SetRegisterTo(q, 11)
	f.JumpIfEqual(r, q, "eleven")
	f.Set1Epi8("b", vec)
	f.store_vec_in_param(vec, `ans`)
	f.Return()
	f.Label("space")
	f.Set1Epi8(int(' '), vec)
	f.store_vec_in_param(vec, `ans`)
	f.Return()
	f.Label("eleven")
	f.Set1Epi8(-1, vec)
	f.store_vec_in_param(vec, `ans`)
	f.Return()

}

func (s *State) test_cmpeq_epi8() {
	f := s.NewFunction("test_cmpeq_epi8_asm", "Test byte comparison of two vectors", []FunctionParam{{"a", ByteSlice}, {"b", ByteSlice}, {"ans", ByteSlice}}, nil)
	if !s.ISA.HasSIMD {
		return
	}
	a := f.load_vec_from_param("a")
	b := f.load_vec_from_param("b")
	f.CmpEqEpi8(a, b, a)
	f.store_vec_in_param(a, "ans")
}

func (s *State) test_cmplt_epi8() {
	f := s.NewFunction(
		"test_cmplt_epi8_asm", "Test byte comparison of two vectors", []FunctionParam{{"a", ByteSlice}, {"b", ByteSlice}, {"which", types.Int}, {"ans", ByteSlice}}, nil)
	if !s.ISA.HasSIMD {
		return
	}
	which := f.LoadParam("which")
	a := f.load_vec_from_param("a")
	b := f.load_vec_from_param("b")
	r := f.Reg()
	f.SetRegisterTo(r, 1)
	f.JumpIfEqual(which, r, "one")
	f.SetRegisterTo(r, 2)
	f.JumpIfEqual(which, r, "two")
	ans := f.Vec()
	f.CmpLtEpi8(a, b, ans)
	f.store_vec_in_param(ans, "ans")
	f.Return()
	f.Label("one")
	f.CmpLtEpi8(a, b, a)
	f.store_vec_in_param(a, "ans")
	f.Return()
	f.Label("two")
	f.CmpLtEpi8(a, b, b)
	f.store_vec_in_param(b, "ans")
	f.Return()
}

func (s *State) test_or() {
	f := s.NewFunction("test_or_asm", "Test OR of two vectors", []FunctionParam{{"a", ByteSlice}, {"b", ByteSlice}, {"ans", ByteSlice}}, nil)
	if !s.ISA.HasSIMD {
		return
	}
	a := f.load_vec_from_param("a")
	b := f.load_vec_from_param("b")
	f.Or(a, b, a)
	f.store_vec_in_param(a, "ans")
}

func (s *State) test_jump_if_zero() {
	f := s.NewFunction("test_jump_if_zero_asm", "Test jump on zero register", []FunctionParam{{"a", ByteSlice}}, []FunctionParam{{"ans", types.Int}})
	if !s.ISA.HasSIMD {
		return
	}
	a := f.load_vec_from_param("a")
	f.JumpIfZero(a, "zero")
	f.SetReturnValue("ans", 1)
	f.Return()
	f.Label("zero")
	f.SetReturnValue("ans", 0)
}

func (s *State) test_count_to_match() {
	f := s.NewFunction("test_count_to_match_asm", "Test counting bytes to first match", []FunctionParam{{"a", ByteSlice}, {"b", types.Byte}}, []FunctionParam{{"ans", types.Int}})
	if !s.ISA.HasSIMD {
		return
	}
	a := f.load_vec_from_param("a")
	b := f.Vec()
	f.Set1Epi8("b", b)
	f.CmpEqEpi8(a, b, b)
	f.JumpIfZero(b, "fail")
	res := f.Reg()
	f.CountBytesToFirstMatchDestructive(b, res)
	f.SetReturnValue("ans", res)
	f.Return()
	f.Label("fail")
	f.SetReturnValue("ans", -1)
}

func (isa *ISA) LEA() string {
	if isa.GeneralPurposeRegisterSize == 32 {
		return "LEAL"
	}
	return "LEAQ"
}

func (s *State) index_func(f *Function, test_bytes func(bytes_to_test, test_ans Register)) {
	pos := f.Reg()
	test_ans := f.Vec()
	bytes_to_test := f.Vec()
	data_start := f.LoadParam(`data`)
	limit := f.LoadParamLen(`data`)
	f.JumpIfZero(limit, "fail")
	f.AddToSelf(limit, data_start)
	mask := f.Reg()

	vecsz := f.ISA.Bits / 8
	f.CopyRegister(data_start, pos)

	func() {
		unaligned_bytes := f.RegForShifts()
		defer f.ReleaseReg(unaligned_bytes)
		f.CopyRegister(data_start, unaligned_bytes)
		f.AndSelf(unaligned_bytes, vecsz-1)
		f.SubtractFromSelf(pos, unaligned_bytes)
		f.Comment(fmt.Sprintf("%s is now aligned to a %d byte boundary so loading from it is safe", pos, vecsz))
		f.LoadPointerAligned(pos, bytes_to_test)
		test_bytes(bytes_to_test, test_ans)
		f.MaskForCountDestructive(test_ans, mask)
		f.Comment("We need to shift out the possible extra bytes at the start of the string caused by the unaligned read")
		f.ShiftMaskRightDestructive(mask, unaligned_bytes)
		f.JumpIfZero(mask, "loop_start")
		f.CopyRegister(data_start, pos)
		f.JumpTo("byte_found_in_mask")
	}()

	f.Comment("Now loop over aligned blocks")
	f.Label("loop_start")
	f.AddToSelf(pos, vecsz)
	f.JumpIfLessThanOrEqual(limit, pos, "fail")
	f.LoadPointerAligned(pos, bytes_to_test)
	test_bytes(bytes_to_test, test_ans)
	f.JumpIfNonZero(test_ans, "byte_found_in_vec")
	f.JumpTo("loop_start")

	f.Label("byte_found_in_vec")
	f.MaskForCountDestructive(test_ans, mask)
	f.Comment("Get the result from", mask, "and return it")
	f.Label("byte_found_in_mask")
	f.CountLeadingZeroBytesInMask(mask, mask)
	f.AddToSelf(mask, pos)
	f.JumpIfLessThanOrEqual(limit, mask, "fail")
	f.SubtractFromSelf(mask, data_start)
	f.SetReturnValue("ans", mask)
	f.Return()
	f.Label("fail")
	f.SetReturnValue("ans", -1)
	f.Return()
}

func (s *State) indexbyte2_body(f *Function) {
	b1 := f.Vec()
	b2 := f.Vec()
	f.Set1Epi8("b1", b1)
	f.Set1Epi8("b2", b2)
	test_bytes := func(bytes_to_test, test_ans Register) {
		f.CmpEqEpi8(bytes_to_test, b1, test_ans)
		f.CmpEqEpi8(bytes_to_test, b2, bytes_to_test)
		f.Or(test_ans, bytes_to_test, test_ans)
	}
	s.index_func(f, test_bytes)
}

func (s *State) indexbyte2() {
	f := s.NewFunction("index_byte2_asm", "Find the index of either of two bytes", []FunctionParam{{"data", ByteSlice}, {"b1", types.Byte}, {"b2", types.Byte}}, []FunctionParam{{"ans", types.Int}})
	if s.ISA.HasSIMD {
		s.indexbyte2_body(f)
	}
	f = s.NewFunction("index_byte2_string_asm", "Find the index of either of two bytes", []FunctionParam{{"data", types.String}, {"b1", types.Byte}, {"b2", types.Byte}}, []FunctionParam{{"ans", types.Int}})
	if s.ISA.HasSIMD {
		s.indexbyte2_body(f)
	}

}

func (s *State) indexbyte_body(f *Function) {
	b := f.Vec()
	f.Set1Epi8("b", b)
	test_bytes := func(bytes_to_test, test_ans Register) {
		f.CmpEqEpi8(bytes_to_test, b, test_ans)
	}
	s.index_func(f, test_bytes)
}

func (s *State) indexbyte() {
	f := s.NewFunction("index_byte_asm", "Find the index of a byte", []FunctionParam{{"data", ByteSlice}, {"b", types.Byte}}, []FunctionParam{{"ans", types.Int}})
	if s.ISA.HasSIMD {
		s.indexbyte_body(f)
	}
	f = s.NewFunction("index_byte_string_asm", "Find the index of a byte", []FunctionParam{{"data", types.String}, {"b", types.Byte}}, []FunctionParam{{"ans", types.Int}})
	if s.ISA.HasSIMD {
		s.indexbyte_body(f)
	}

}

func (s *State) indexc0_body(f *Function) {
	lower := f.Vec()
	upper := f.Vec()
	del := f.Vec()
	f.Set1Epi8(-1, lower)
	f.Set1Epi8(int(' '), upper)
	f.Set1Epi8(0x7f, del)

	test_bytes := func(bytes_to_test, test_ans Register) {
		temp := f.Vec()
		defer f.ReleaseReg(temp)
		f.CmpEqEpi8(bytes_to_test, del, test_ans)
		f.CmpLtEpi8(bytes_to_test, upper, temp)
		f.CmpGtEpi8(bytes_to_test, lower, bytes_to_test)
		f.And(temp, bytes_to_test, bytes_to_test)
		f.Or(test_ans, bytes_to_test, test_ans)
	}
	s.index_func(f, test_bytes)
}

func (s *State) indexc0() {
	f := s.NewFunction("index_c0_asm", "Find the index of a C0 control code", []FunctionParam{{"data", ByteSlice}}, []FunctionParam{{"ans", types.Int}})
	if s.ISA.HasSIMD {
		s.indexc0_body(f)
	}
	f = s.NewFunction("index_c0_string_asm", "Find the index of a C0 control code", []FunctionParam{{"data", types.String}}, []FunctionParam{{"ans", types.Int}})
	if s.ISA.HasSIMD {
		s.indexc0_body(f)
	}

}

func (s *State) Generate() {
	s.test_load()
	s.test_set1_epi8()
	s.test_cmpeq_epi8()
	s.test_cmplt_epi8()
	s.test_or()
	s.test_jump_if_zero()
	s.test_count_to_match()

	s.indexbyte2()
	s.indexc0()
	s.indexbyte()

	s.OutputFunction()
}

// CLI {{{
func exit(msg any) {
	fmt.Fprintf(os.Stderr, "%s\n", msg)
	os.Exit(1)
}

func write_file(name, text string) {
	b := unsafe.Slice(unsafe.StringData(text), len(text))
	if existing, err := os.ReadFile(name); err == nil && bytes.Equal(existing, b) {
		return
	}
	if err := os.WriteFile(name, b, 0664); err != nil {
		exit(err)
	}
}

func do_one(s *State) {
	s.Generate()

	if s.ISA.HasSIMD {
		write_file(fmt.Sprintf("asm_%d_%s_generated.s", s.ISA.Bits, s.ISA.Goarch), s.ASMOutput.String())
		write_file(fmt.Sprintf("asm_%d_%s_generated_test.s", s.ISA.Bits, s.ISA.Goarch), s.TestASMOutput.String())
	}
	write_file(fmt.Sprintf("asm_%d_%s_generated.go", s.ISA.Bits, s.ISA.Goarch), s.StubOutput.String())
	write_file(fmt.Sprintf("asm_%d_%s_generated_test.go", s.ISA.Bits, s.ISA.Goarch), s.TestStubOutput.String())
}

func create_isa(arch Arch, bits int) ISA {
	switch arch {
	case AMD64:
		return CreateAMD64ISA(bits)
	case ARM64:
		return CreateARM64ISA(bits)
	}
	panic("Unknown ISA arch")
}

func main() {
	output_dir, err := os.Getwd()
	if err != nil {
		exit(err)
	}
	if len(os.Args) > 1 {
		if output_dir, err = filepath.Abs(os.Args[len(os.Args)-1]); err != nil {
			exit(err)
		}
	}
	if err = os.MkdirAll(output_dir, 0755); err != nil {
		exit(err)
	}
	if err = os.Chdir(output_dir); err != nil {
		exit(err)
	}
	package_name = filepath.Base(output_dir)
	simd_arches := []Arch{AMD64, ARM64}
	a := make([]string, len(simd_arches))
	for i, arch := range simd_arches {
		a[i] = string(arch)
	}
	no_simd_build_tag := fmt.Sprintf("!(%s)", strings.Join(a, "||"))

	for _, bits := range []int{128, 256} {
		for _, arch := range simd_arches {
			s := NewState(create_isa(arch, bits))
			fmt.Fprintf(&s.StubOutput, "const HasSIMD%dCode = %#v\n", bits, s.ISA.HasSIMD)
			do_one(s)
		}
		s := NewState(CreateAMD64ISA(bits), no_simd_build_tag)
		s.ISA.HasSIMD = false
		fmt.Fprintf(&s.StubOutput, "const HasSIMD%dCode = false\n", bits)
		s.Generate()
		write_file(fmt.Sprintf("asm_other_%d_generated.go", bits), s.StubOutput.String())
		write_file(fmt.Sprintf("asm_other_%d_generated_test.go", bits), s.TestStubOutput.String())
	}
}

// }}}
