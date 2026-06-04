import os
import sys

import isa
from isa import Opcode

DATA_STACK_BASE = 0xD000
RETURN_STACK_BASE = 0xE000

INPUT_CHAR_ADDR = 0xFF00
INPUT_READY_ADDR = 0xFF01
OUTPUT_CHAR_ADDR = 0xFF02
INPUT_ACK_ADDR = 0xFF04

FETCH_OPCODE = "FETCH_OPCODE"
FETCH_ARGUMENT = "FETCH_ARGUMENT"
EXECUTE = "EXECUTE"
MEM_READ = "MEM_READ"
WRITEBACK = "WRITEBACK"
FETCH_PUSHN_VALUE = "FETCH_PUSHN_VALUE"
EXECUTE_PUSHN_VALUE = "EXECUTE_PUSHN_VALUE"
INTERRUPT = "INTERRUPT"


class MachineError(Exception):
    pass


class DataPath:
    def __init__(self, data_words=None):
        self.data_memory = [0] * isa.DATA_MEMORY_SIZE
        if data_words is not None:
            for address, word in enumerate(data_words):
                self.data_memory[address] = isa.word_to_signed(word)

        self.data_stack = []
        self.return_stack = []
        self.output_buffer = []

        self.input_char = 0
        self.input_ready = False
        self.read_data = 0
        self.alu_result = 0

        self.flags = {"Z": 0, "N": 0, "C": 0, "V": 0, "IE": 0, "INT": 0}
        self.tos = 0
        self.nos = 0
        self.sp = DATA_STACK_BASE - 1
        self.rp = RETURN_STACK_BASE - 1
        self.signal_refresh_stack_registers()

    def signal_refresh_stack_registers(self):
        self.tos = self.data_stack[-1] if self.data_stack else 0
        self.nos = self.data_stack[-2] if len(self.data_stack) > 1 else 0
        self.sp = DATA_STACK_BASE + len(self.data_stack) - 1
        self.rp = RETURN_STACK_BASE + len(self.return_stack) - 1

    def _push_data(self, value):
        self.data_stack.append(isa.word_to_signed(value))
        self.signal_refresh_stack_registers()

    def _pop_data(self):
        if not self.data_stack:
            raise MachineError("data stack underflow")
        value = self.data_stack.pop()
        self.signal_refresh_stack_registers()
        return value

    def _push_return(self, value):
        self.return_stack.append(isa.word_to_signed(value))
        self.signal_refresh_stack_registers()

    def _pop_return(self):
        if not self.return_stack:
            raise MachineError("return stack underflow")
        value = self.return_stack.pop()
        self.signal_refresh_stack_registers()
        return value

    def _peek_return(self):
        if not self.return_stack:
            raise MachineError("return stack underflow")
        return self.return_stack[-1]

    def _read_data_memory_or_mmio(self, address):
        address = address & 0xFFFF
        if address == INPUT_CHAR_ADDR:
            value = self.input_char if self.input_ready else 0
            self.input_ready = False
            return value
        if address == INPUT_READY_ADDR:
            return 1 if self.input_ready else 0
        return self.data_memory[address]

    def _write_data_memory_or_mmio(self, address, value):
        address = address & 0xFFFF
        value = isa.word_to_signed(value)
        if address == OUTPUT_CHAR_ADDR:
            self.output_buffer.append(chr(value & 0xFF))
            return
        if address == INPUT_ACK_ADDR:
            self.input_ready = False
            return
        self.data_memory[address] = value

    def signal_input_char(self, char):
        if isinstance(char, int):
            self.input_char = char & 0xFF
        else:
            self.input_char = ord(char[0]) if char else 0
        self.input_ready = True

    def signal_stack_push(self, value):
        self._push_data(value)

    def signal_stack_drop(self):
        self._pop_data()

    def signal_stack_drop_two(self):
        self._pop_data()
        self._pop_data()

    def signal_stack_swap(self):
        if len(self.data_stack) < 2:
            raise MachineError("data stack underflow")
        self.data_stack[-1], self.data_stack[-2] = self.data_stack[-2], self.data_stack[-1]
        self.signal_refresh_stack_registers()

    def signal_stack_over(self):
        if len(self.data_stack) < 2:
            raise MachineError("data stack underflow")
        self._push_data(self.data_stack[-2])

    def signal_stack_replace_tos(self, value):
        self._pop_data()
        self._push_data(value)

    def signal_stack_binary_alu(self, alu_op):
        b = self._pop_data()
        a = self._pop_data()
        result, carry, overflow = self.signal_alu(alu_op, a, b)
        self.alu_result = result
        self._push_data(result)
        self.signal_latch_flags(result, carry, overflow)

    def signal_return_push(self, value):
        self._push_return(value)

    def signal_return_pop(self):
        return self._pop_return()

    def signal_return_read(self):
        self.read_data = isa.word_to_signed(self._peek_return())
        return self.read_data

    def signal_data_to_return(self):
        self._push_return(self._pop_data())

    def signal_mem_read(self, address):
        self.read_data = isa.word_to_signed(self._read_data_memory_or_mmio(address))
        return self.read_data

    def signal_mem_write(self, address, value):
        self._write_data_memory_or_mmio(address, value)

    def signal_load_writeback(self):
        self.signal_stack_replace_tos(self.read_data)

    def signal_loada_writeback(self):
        self.signal_stack_push(self.read_data)

    def signal_store(self):
        address = self.tos
        value = self.nos
        self.signal_mem_write(address, value)
        self.signal_stack_drop_two()

    def signal_storea(self, address):
        self.signal_mem_write(address, self.tos)
        self.signal_stack_drop()

    def signal_memory_alu_writeback(self, alu_op):
        a = self._pop_data()
        result, carry, overflow = self.signal_alu(alu_op, a, self.read_data)
        self.alu_result = result
        self._push_data(result)
        self.signal_latch_flags(result, carry, overflow)

    def signal_return_to_data_writeback(self):
        self._pop_return()
        self._push_data(self.read_data)

    def signal_return_peek_to_data_writeback(self):
        self._push_data(self.read_data)

    def signal_latch_flags(self, result=None, carry=0, overflow=0, flags_ctrl="ALU_FLAGS"):
        if flags_ctrl == "ALU_FLAGS":
            result = isa.word_to_signed(result)
            self.flags["Z"] = 1 if result == 0 else 0
            self.flags["N"] = 1 if result < 0 else 0
            self.flags["C"] = 1 if carry else 0
            self.flags["V"] = 1 if overflow else 0
            return
        if flags_ctrl == "SET_IE":
            self.flags["IE"] = 1
            return
        if flags_ctrl == "CLEAR_IE":
            self.flags["IE"] = 0
            return
        if flags_ctrl == "CLEAR_INT":
            self.flags["INT"] = 0
            return
        raise MachineError(f"unsupported flags_ctrl: {flags_ctrl}")

    def signal_alu(self, alu_op, a, b=None):
        carry = 0
        overflow = 0

        if alu_op is Opcode.ADD:
            self._require_binary_operand(alu_op, b)
            unsigned = (a & isa.WORD_MASK) + (b & isa.WORD_MASK)
            result = isa.word_to_signed(unsigned)
            carry = unsigned > isa.WORD_MASK
            overflow = (a >= 0 and b >= 0 and result < 0) or (a < 0 and b < 0 and result >= 0)
        elif alu_op is Opcode.SUB:
            self._require_binary_operand(alu_op, b)
            unsigned = (a & isa.WORD_MASK) - (b & isa.WORD_MASK)
            result = isa.word_to_signed(unsigned)
            carry = unsigned < 0
            overflow = (a >= 0 and b < 0 and result < 0) or (a < 0 and b >= 0 and result >= 0)
        elif alu_op is Opcode.MUL:
            self._require_binary_operand(alu_op, b)
            result = isa.word_to_signed(a * b)
        elif alu_op is Opcode.DIV:
            self._require_binary_operand(alu_op, b)
            result = int(a / b)
        elif alu_op is Opcode.MOD:
            self._require_binary_operand(alu_op, b)
            quotient = int(a / b)
            result = a - quotient * b
        elif alu_op is Opcode.EQ:
            self._require_binary_operand(alu_op, b)
            result = 1 if a == b else 0
        elif alu_op is Opcode.LT:
            self._require_binary_operand(alu_op, b)
            result = 1 if a < b else 0
        elif alu_op is Opcode.GT:
            self._require_binary_operand(alu_op, b)
            result = 1 if a > b else 0
        else:
            raise MachineError(f"unsupported ALU op: {alu_op.mnemonic}")

        return isa.word_to_signed(result), carry, overflow

    def _require_binary_operand(self, alu_op, b):
        if b is None:
            raise MachineError(f"ALU op requires two operands: {alu_op.mnemonic}")


class ControlUnit:
    def __init__(self, command_memory, data_path, interrupt_vector=None, input_schedule=None):
        self.command_memory = self._load_command_memory(command_memory)
        self.data_path = data_path
        self.interrupt_vector = interrupt_vector
        self.input_schedule = sorted(input_schedule or [], key=lambda item: item[0])
        self.pending_input = []

        self.pc = 0
        self.ir = None
        self.arg = 0
        self.current_instruction = None
        self.fetch_address = 0

        self.state = FETCH_OPCODE
        self._tick = 0
        self.halted = False
        self.log = []

        self.pushn_remaining = 0

    def _load_command_memory(self, command_memory):
        payload = bytes(command_memory)
        if len(payload) > isa.COMMAND_MEMORY_SIZE:
            raise MachineError("command memory image is too large")
        return payload + bytes(isa.COMMAND_MEMORY_SIZE - len(payload))

    def current_tick(self):
        return self._tick

    def tick(self, stage, detail=""):
        self._tick += 1
        self.log.append(self.format_state(stage, detail))

    def process_next_tick(self):
        if self.halted:
            raise StopIteration()

        self.deliver_input_tokens()
        if self.state == FETCH_OPCODE and self.interrupt_requested():
            self.signal_enter_interrupt()
            self.tick(INTERRUPT, f"vector={self.interrupt_vector}")
            return

        if self.state == FETCH_OPCODE:
            self.fetch_address = self.pc
            self.signal_latch_ir()
            if isa.instruction_format(self.ir) == isa.FORMAT_OP:
                self.state = EXECUTE
            else:
                self.state = FETCH_ARGUMENT
            self.tick(FETCH_OPCODE, f"instr_addr={self.fetch_address}")
            return

        if self.state == FETCH_ARGUMENT:
            self.signal_latch_arg()
            self.state = EXECUTE
            self.tick(FETCH_ARGUMENT, self.current_instruction_mnemonic())
            return

        if self.state == MEM_READ:
            self.signal_mem_read_stage()
            return

        if self.state == WRITEBACK:
            self.signal_writeback_stage()
            return

        if self.state == FETCH_PUSHN_VALUE:
            self.signal_pushn_latch_value()
            self.state = EXECUTE_PUSHN_VALUE
            self.tick(FETCH_PUSHN_VALUE, f"value={self.arg}")
            return

        if self.state == EXECUTE_PUSHN_VALUE:
            self.signal_pushn_push_value()
            self.tick(EXECUTE_PUSHN_VALUE, f"value={self.data_path.tos}")
            return

        if self.state == EXECUTE:
            self.decode_and_execute()
            return

        raise MachineError(f"unknown control state: {self.state}")

    def deliver_input_tokens(self):
        next_tick = self._tick + 1
        while self.input_schedule and self.input_schedule[0][0] <= next_tick:
            _, char = self.input_schedule.pop(0)
            self.pending_input.append(char)

        if not self.data_path.input_ready and self.pending_input:
            self.data_path.signal_input_char(self.pending_input.pop(0))

    def interrupt_requested(self):
        flags = self.data_path.flags
        return flags["IE"] == 1 and flags["INT"] == 0 and self.data_path.input_ready

    def signal_enter_interrupt(self):
        if self.interrupt_vector is None:
            raise MachineError("input interrupt requested but no interrupt vector configured")
        self.data_path.signal_return_push(self.pc)
        self.data_path.flags["INT"] = 1
        self.signal_latch_pc(self.interrupt_vector)
        self.state = FETCH_OPCODE

    def signal_latch_ir(self):
        if self.pc >= len(self.command_memory):
            raise MachineError(f"instruction address is outside code: {self.pc}")

        opcode_byte = self.command_memory[self.pc]
        try:
            self.ir = isa.binary_to_opcode[opcode_byte]
        except KeyError as exc:
            raise MachineError(f"unknown opcode 0x{opcode_byte:02X} at address {self.pc}") from exc

        self.arg = 0
        self.current_instruction = isa.op(self.ir)
        self.signal_latch_pc(step=1)

    def signal_latch_arg(self):
        fmt = isa.instruction_format(self.ir)

        if fmt == isa.FORMAT_OP:
            self.arg = 0
            self.current_instruction = isa.op(self.ir)
            return

        if fmt == isa.FORMAT_U16:
            self.arg = isa.decode_u16(self.read_command_bytes(2))
            self.current_instruction = isa.u16(self.ir, self.arg)
            return

        if fmt == isa.FORMAT_I16:
            self.arg = isa.decode_i16(self.read_command_bytes(2))
            self.current_instruction = isa.i16(self.ir, self.arg)
            return

        if fmt == isa.FORMAT_I32:
            self.arg = isa.decode_i32(self.read_command_bytes(4))
            self.current_instruction = isa.i32(self.ir, self.arg)
            return

        if fmt == isa.FORMAT_PUSHN:
            payload = self.read_command_bytes(1)
            self.arg = payload[0]
            self.current_instruction = isa.pushn(())
            return

        raise MachineError(f"unsupported instruction format: {fmt}")

    def read_command_bytes(self, count):
        end = self.pc + count
        if end > len(self.command_memory):
            raise MachineError(f"truncated instruction at address {self.fetch_address}")
        payload = self.command_memory[self.pc : end]
        self.signal_latch_pc(step=count)
        return payload

    def signal_latch_pc(self, target=None, step=0):
        if target is None:
            self.pc += step
        else:
            self.pc = target

    def current_instruction_mnemonic(self):
        if self.ir is Opcode.PUSHN:
            return f"PUSHN count={self.arg}"
        return isa.instruction_to_mnemonic(self.current_instruction)

    def signal_finish_execute(self):
        self.state = FETCH_OPCODE

    def signal_mem_read_stage(self):
        opcode = self.ir

        if opcode is Opcode.LOAD:
            self.data_path.signal_mem_read(self.data_path.tos)
            self.state = WRITEBACK
            self.tick(MEM_READ, f"addr={self.data_path.tos}")
            return
        if opcode in {Opcode.LOADA, Opcode.ADDM}:
            self.data_path.signal_mem_read(self.arg)
            self.state = WRITEBACK
            self.tick(MEM_READ, f"addr={self.arg}")
            return
        if opcode in {Opcode.RET, Opcode.FROMR, Opcode.RPEEK, Opcode.IRET}:
            self.data_path.signal_return_read()
            self.state = WRITEBACK
            self.tick(MEM_READ, f"rp={self.data_path.rp:04X}")
            return

        raise MachineError(f"opcode does not use MEM_READ: {opcode.mnemonic}")

    def signal_writeback_stage(self):
        opcode = self.ir
        stage = WRITEBACK
        detail = opcode.mnemonic

        if opcode is Opcode.LOAD:
            self.data_path.signal_load_writeback()
        elif opcode is Opcode.LOADA:
            self.data_path.signal_loada_writeback()
        elif opcode is Opcode.ADDM:
            self.data_path.signal_memory_alu_writeback(Opcode.ADD)
            stage = EXECUTE
        elif opcode is Opcode.RET:
            ret_addr = self.data_path.read_data
            self.data_path.signal_return_pop()
            self.signal_latch_pc(ret_addr)
            stage = EXECUTE
        elif opcode is Opcode.FROMR:
            self.data_path.signal_return_to_data_writeback()
        elif opcode is Opcode.RPEEK:
            self.data_path.signal_return_peek_to_data_writeback()
        elif opcode is Opcode.IRET:
            ret_addr = self.data_path.read_data
            self.data_path.signal_return_pop()
            self.data_path.signal_latch_flags(flags_ctrl="CLEAR_INT")
            self.signal_latch_pc(ret_addr)
            stage = EXECUTE
        else:
            raise MachineError(f"opcode does not use WRITEBACK: {opcode.mnemonic}")

        self.signal_finish_execute()
        self.tick(stage, detail)

    def decode_and_execute(self):
        opcode = self.ir
        detail = opcode.mnemonic

        if opcode is Opcode.HALT:
            self.halted = True
            self.tick(EXECUTE, detail)
            raise StopIteration()

        if opcode is Opcode.PUSHI32:
            self.data_path.signal_stack_push(self.arg)
        elif opcode is Opcode.PUSHN:
            self.signal_pushn_start()
            self.tick("EXECUTE_PUSHN_START", f"count={self.pushn_remaining}")
            return
        elif opcode in {
            Opcode.ADD,
            Opcode.SUB,
            Opcode.MUL,
            Opcode.DIV,
            Opcode.MOD,
            Opcode.EQ,
            Opcode.LT,
            Opcode.GT,
        }:
            self.data_path.signal_stack_binary_alu(opcode)
        elif opcode is Opcode.DUP:
            self.data_path.signal_stack_push(self.data_path.tos)
        elif opcode is Opcode.DROP:
            self.data_path.signal_stack_drop()
        elif opcode is Opcode.SWAP:
            self.data_path.signal_stack_swap()
        elif opcode is Opcode.OVER:
            self.data_path.signal_stack_over()
        elif opcode is Opcode.LOAD:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.LOADA:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.STORE:
            self.data_path.signal_store()
        elif opcode is Opcode.STOREA:
            self.data_path.signal_storea(self.arg)
        elif opcode is Opcode.ADDM:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.JMP:
            self.signal_latch_pc(self.pc + self.arg)
        elif opcode is Opcode.JZ:
            flag = self.data_path.tos
            self.data_path.signal_stack_drop()
            if flag == 0:
                self.signal_latch_pc(self.pc + self.arg)
            detail = f"JZ flag={flag}"
        elif opcode is Opcode.CALL:
            self.data_path.signal_return_push(self.pc)
            self.signal_latch_pc(self.pc + self.arg)
        elif opcode is Opcode.CALLXT:
            target = self.data_path.tos
            self.data_path.signal_return_push(self.pc)
            self.signal_latch_pc(target)
            self.data_path.signal_stack_drop()
        elif opcode is Opcode.RET:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.TOR:
            self.data_path.signal_data_to_return()
        elif opcode is Opcode.FROMR:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.RPEEK:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.EI:
            self.data_path.signal_latch_flags(flags_ctrl="SET_IE")
        elif opcode is Opcode.DI:
            self.data_path.signal_latch_flags(flags_ctrl="CLEAR_IE")
        elif opcode is Opcode.IRET:
            self.state = MEM_READ
            self.signal_mem_read_stage()
            return
        elif opcode is Opcode.GET_CARRY:
            self.data_path.signal_stack_push(self.data_path.flags["C"])
        else:
            raise MachineError(f"unsupported opcode in first machine version: {opcode.mnemonic}")

        self.signal_finish_execute()
        self.tick(EXECUTE, detail)

    def signal_pushn_start(self):
        self.pushn_remaining = self.arg
        if self.pushn_remaining:
            self.state = FETCH_PUSHN_VALUE
        else:
            self.signal_finish_execute()

    def signal_pushn_latch_value(self):
        value = isa.decode_i32(self.read_command_bytes(isa.WORD_BYTES))
        self.arg = value

    def signal_pushn_push_value(self):
        self.data_path.signal_stack_push(self.arg)
        self.pushn_remaining -= 1

        if self.pushn_remaining == 0:
            self.signal_finish_execute()
        else:
            self.state = FETCH_PUSHN_VALUE

    def format_state(self, stage, detail):
        dp = self.data_path
        ir = self.ir.mnemonic if self.ir is not None else "-"
        flags = "".join(name if dp.flags[name] else name.lower() for name in ("Z", "N", "C", "V", "IE", "INT"))
        mode = "interrupt" if dp.flags["INT"] else "main"
        input_state = f"input={dp.input_char:02X}" if dp.input_ready else "input=--"
        return (
            f"tick={self._tick:05d} state={stage:<20} pc={self.pc:04X} "
            f"ir={ir:<9} arg={self.arg:>11} tos={dp.tos:>11} nos={dp.nos:>11} "
            f"sp={dp.sp:04X} rp={dp.rp:04X} flags={flags} mode={mode:<9} {input_state} {detail}"
        )

    def __repr__(self):
        if not self.log:
            return self.format_state("RESET", "")
        return self.log[-1]


def _command_memory_from_code(code):
    if isinstance(code, (bytes, bytearray)):
        return bytes(code)
    return isa.to_bytes(code)


def _interrupt_vector_from(interrupts):
    if interrupts is None:
        return None
    if isinstance(interrupts, int):
        return interrupts
    if not interrupts:
        return None
    if "on-input" in interrupts:
        return interrupts["on-input"]
    name = sorted(interrupts)[0]
    return interrupts[name]


def simulation(code, data_words=None, limit=10000, interrupts=None, input_schedule=None):
    data_path = DataPath(data_words)
    control_unit = ControlUnit(
        _command_memory_from_code(code),
        data_path,
        interrupt_vector=_interrupt_vector_from(interrupts),
        input_schedule=input_schedule,
    )

    try:
        while control_unit.current_tick() < limit and not control_unit.halted:
            control_unit.process_next_tick()
    except StopIteration:
        pass

    if not control_unit.halted and control_unit.current_tick() >= limit:
        raise MachineError("tick limit exceeded")

    return {
        "output": "".join(data_path.output_buffer),
        "ticks": control_unit.current_tick(),
        "data_stack": list(data_path.data_stack),
        "return_stack": list(data_path.return_stack),
        "log": list(control_unit.log),
        "control_unit": control_unit,
        "data_path": data_path,
    }


def load_interrupts(filename):
    interrupts = {}
    if filename is None:
        return interrupts

    with open(filename, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, address = line.split(maxsplit=1)
            interrupts[name] = int(address, 0)
    return interrupts


def load_input_schedule(filename):
    if filename is None:
        return []

    escapes = {
        "\\0": "\0",
        "\\n": "\n",
        "\\r": "\r",
        "\\t": "\t",
    }
    schedule = []

    with open(filename, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tick_text, token = line.split(maxsplit=1)
            if token in escapes:
                char = escapes[token]
            elif token.startswith("\\x") and len(token) == 4:
                char = chr(int(token[2:], 16))
            else:
                char = token[0]
            schedule.append((int(tick_text, 0), char))

    return sorted(schedule, key=lambda item: item[0])


def default_interrupt_file(code_file):
    candidate = code_file + ".interrupts"
    if os.path.exists(candidate):
        return candidate
    return None


def main(code_file, data_file=None, interrupt_file=None, schedule_file=None, limit=10000):
    with open(code_file, "rb") as file:
        command_memory = file.read()

    if interrupt_file is None:
        interrupt_file = default_interrupt_file(code_file)

    data_words = None
    if data_file is not None:
        with open(data_file, "rb") as file:
            data_words = isa.data_from_bytes(file.read())

    result = simulation(
        command_memory,
        data_words=data_words,
        limit=int(limit),
        interrupts=load_interrupts(interrupt_file),
        input_schedule=load_input_schedule(schedule_file),
    )
    print(result["output"])
    print("ticks:", result["ticks"])


if __name__ == "__main__":
    assert 2 <= len(sys.argv) <= 5, "Wrong arguments: machine.py <code_file> [data_file] [schedule_file] [limit]"

    code_arg = sys.argv[1]
    data_arg = sys.argv[2] if len(sys.argv) >= 3 else None
    schedule_arg = sys.argv[3] if len(sys.argv) >= 4 else None
    limit_arg = sys.argv[4] if len(sys.argv) == 5 else 10000

    main(code_arg, data_arg, schedule_file=schedule_arg, limit=limit_arg)
