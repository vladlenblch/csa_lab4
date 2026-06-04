from collections import namedtuple
from enum import IntEnum

COMMAND_MEMORY_SIZE = 1 << 16
DATA_MEMORY_SIZE = 1 << 16

WORD_BITS = 32
WORD_BYTES = WORD_BITS // 8
WORD_MASK = (1 << WORD_BITS) - 1

FORMAT_OP = "op"
FORMAT_U16 = "u16"
FORMAT_I16 = "i16"
FORMAT_I32 = "i32"
FORMAT_PUSHN = "pushn"


class Opcode(IntEnum):
    HALT = 0x00
    DUP = 0x01
    DROP = 0x02
    SWAP = 0x03
    OVER = 0x04
    LOAD = 0x05
    STORE = 0x06
    ADD = 0x07
    SUB = 0x08
    MUL = 0x09
    DIV = 0x0A
    MOD = 0x0B
    EQ = 0x0C
    LT = 0x0D
    GT = 0x0E
    AND = 0x0F
    OR = 0x10
    NOT = 0x11
    RET = 0x12
    CALLXT = 0x13
    TOR = 0x14
    FROMR = 0x15
    RPEEK = 0x16
    EI = 0x17
    DI = 0x18
    IRET = 0x19
    GET_CARRY = 0x1A
    LOADA = 0x1B
    STOREA = 0x1C
    ADDM = 0x1D
    MULM = 0x1E
    JMP = 0x1F
    JZ = 0x20
    CALL = 0x21
    PUSHI32 = 0x22
    PUSHN = 0x23

    @property
    def mnemonic(self):
        return self.name

    @classmethod
    def from_mnemonic(cls, mnemonic):
        normalized = mnemonic.replace("-", "_").upper()
        try:
            return cls[normalized]
        except KeyError as exc:
            raise ValueError(f"unknown opcode mnemonic: {mnemonic}") from exc


class Term(namedtuple("Term", "line pos symbol")):
    pass


opcode_to_format = {
    Opcode.HALT: FORMAT_OP,
    Opcode.DUP: FORMAT_OP,
    Opcode.DROP: FORMAT_OP,
    Opcode.SWAP: FORMAT_OP,
    Opcode.OVER: FORMAT_OP,
    Opcode.LOAD: FORMAT_OP,
    Opcode.STORE: FORMAT_OP,
    Opcode.ADD: FORMAT_OP,
    Opcode.SUB: FORMAT_OP,
    Opcode.MUL: FORMAT_OP,
    Opcode.DIV: FORMAT_OP,
    Opcode.MOD: FORMAT_OP,
    Opcode.EQ: FORMAT_OP,
    Opcode.LT: FORMAT_OP,
    Opcode.GT: FORMAT_OP,
    Opcode.AND: FORMAT_OP,
    Opcode.OR: FORMAT_OP,
    Opcode.NOT: FORMAT_OP,
    Opcode.RET: FORMAT_OP,
    Opcode.CALLXT: FORMAT_OP,
    Opcode.TOR: FORMAT_OP,
    Opcode.FROMR: FORMAT_OP,
    Opcode.RPEEK: FORMAT_OP,
    Opcode.EI: FORMAT_OP,
    Opcode.DI: FORMAT_OP,
    Opcode.IRET: FORMAT_OP,
    Opcode.GET_CARRY: FORMAT_OP,
    Opcode.LOADA: FORMAT_U16,
    Opcode.STOREA: FORMAT_U16,
    Opcode.ADDM: FORMAT_U16,
    Opcode.MULM: FORMAT_U16,
    Opcode.JMP: FORMAT_I16,
    Opcode.JZ: FORMAT_I16,
    Opcode.CALL: FORMAT_I16,
    Opcode.PUSHI32: FORMAT_I32,
    Opcode.PUSHN: FORMAT_PUSHN,
}

opcode_to_binary = {opcode: int(opcode) for opcode in Opcode}
binary_to_opcode = {int(opcode): opcode for opcode in Opcode}


def _normalize_opcode(opcode):
    if isinstance(opcode, Opcode):
        return opcode
    if isinstance(opcode, str):
        return Opcode.from_mnemonic(opcode)
    return Opcode(opcode)


def instruction_format(opcode):
    return opcode_to_format[_normalize_opcode(opcode)]


def op(opcode, term=None):
    return _instruction(opcode, term=term)


def u16(opcode, arg, term=None):
    return _instruction(opcode, arg=arg, term=term)


def i16(opcode, arg, term=None):
    return _instruction(opcode, arg=arg, term=term)


def i32(opcode, arg, term=None):
    return _instruction(opcode, arg=arg, term=term)


def pushn(values, term=None):
    return _instruction(Opcode.PUSHN, values=tuple(values), term=term)


def _instruction(opcode, arg=None, values=(), term=None):
    instruction = {"opcode": _normalize_opcode(opcode)}
    if arg is not None:
        instruction["arg"] = arg
    if values:
        instruction["values"] = tuple(values)
    if term is not None:
        instruction["term"] = term
    return instruction


def instruction_size(instruction):
    fmt = instruction_format(instruction["opcode"])
    if fmt == FORMAT_OP:
        return 1
    if fmt in (FORMAT_U16, FORMAT_I16):
        return 3
    if fmt == FORMAT_I32:
        return 5
    if fmt == FORMAT_PUSHN:
        return 2 + WORD_BYTES * len(instruction.get("values", ()))
    raise ValueError(f"unsupported instruction format: {fmt}")


def word_to_unsigned(value):
    return value & WORD_MASK


def word_to_signed(value):
    unsigned = value & WORD_MASK
    if unsigned > WORD_MASK >> 1:
        return unsigned - (1 << WORD_BITS)
    return unsigned


def encode_u16(value):
    return (value & 0xFFFF).to_bytes(2, byteorder="big", signed=False)


def decode_u16(payload):
    if len(payload) != 2:
        raise ValueError(f"uint16 payload must contain 2 bytes, got {len(payload)}")
    return int.from_bytes(payload, byteorder="big", signed=False)


def encode_i16(value):
    return (value & 0xFFFF).to_bytes(2, byteorder="big", signed=False)


def decode_i16(payload):
    if len(payload) != 2:
        raise ValueError(f"int16 payload must contain 2 bytes, got {len(payload)}")
    return int.from_bytes(payload, byteorder="big", signed=True)


def encode_i32(value):
    return word_to_unsigned(value).to_bytes(WORD_BYTES, byteorder="big", signed=False)


def decode_i32(payload):
    if len(payload) != WORD_BYTES:
        raise ValueError(f"int32 payload must contain {WORD_BYTES} bytes, got {len(payload)}")
    return word_to_signed(int.from_bytes(payload, byteorder="big", signed=False))


def encode_word(value):
    return encode_i32(value)


def decode_word(payload):
    return decode_i32(payload)


def encode_instruction(instruction):
    opcode = _normalize_opcode(instruction["opcode"])
    fmt = instruction_format(opcode)
    encoded = bytearray([opcode_to_binary[opcode]])

    if fmt == FORMAT_OP:
        return bytes(encoded)
    if fmt == FORMAT_U16:
        encoded.extend(encode_u16(instruction["arg"]))
        return bytes(encoded)
    if fmt == FORMAT_I16:
        encoded.extend(encode_i16(instruction["arg"]))
        return bytes(encoded)
    if fmt == FORMAT_I32:
        encoded.extend(encode_i32(instruction["arg"]))
        return bytes(encoded)
    if fmt == FORMAT_PUSHN:
        values = instruction.get("values", ())
        encoded.append(len(values))
        for value in values:
            encoded.extend(encode_i32(value))
        return bytes(encoded)
    raise ValueError(f"unsupported instruction format: {fmt}")


def decode_instruction(code, address=0):
    if not 0 <= address < len(code):
        raise ValueError(f"instruction address is outside code: {address}")

    opcode_byte = code[address]
    try:
        opcode = binary_to_opcode[opcode_byte]
    except KeyError as exc:
        raise ValueError(f"unknown opcode 0x{opcode_byte:02X} at address {address}") from exc

    fmt = instruction_format(opcode)
    if fmt == FORMAT_OP:
        return op(opcode)
    if fmt == FORMAT_U16:
        end = address + 3
        _ensure_available(code, address, end)
        return u16(opcode, decode_u16(code[address + 1 : end]))
    if fmt == FORMAT_I16:
        end = address + 3
        _ensure_available(code, address, end)
        return i16(opcode, decode_i16(code[address + 1 : end]))
    if fmt == FORMAT_I32:
        end = address + 5
        _ensure_available(code, address, end)
        return i32(opcode, decode_i32(code[address + 1 : end]))
    if fmt == FORMAT_PUSHN:
        count_end = address + 2
        _ensure_available(code, address, count_end)
        count = code[address + 1]
        end = count_end + WORD_BYTES * count
        _ensure_available(code, address, end)
        values = tuple(decode_i32(code[offset : offset + WORD_BYTES]) for offset in range(count_end, end, WORD_BYTES))
        return pushn(values)
    raise ValueError(f"unsupported instruction format: {fmt}")


def _ensure_available(code, address, end):
    if len(code) < end:
        raise ValueError(
            f"truncated instruction at address {address}: need {end - address} bytes, have {len(code) - address}"
        )


def to_bytes(code):
    binary = bytearray()
    for instruction in code:
        binary.extend(encode_instruction(instruction))
    return bytes(binary)


def from_bytes(binary_code):
    code = []
    address = 0
    while address < len(binary_code):
        instruction = decode_instruction(binary_code, address)
        code.append(instruction)
        address += instruction_size(instruction)
    return code


def instruction_addresses(code, start=0):
    address = start
    addresses = []
    for instruction in code:
        addresses.append(address)
        address += instruction_size(instruction)
    return addresses


def code_size(code):
    return sum(instruction_size(instruction) for instruction in code)


def relative_offset(source_address, instruction_size, target_address):
    return target_address - (source_address + instruction_size)


def branch_target(source_address, instruction_size, rel16):
    return source_address + instruction_size + rel16


def instruction_to_hex(instruction):
    return encode_instruction(instruction).hex().upper()


def instruction_to_mnemonic(instruction):
    opcode = _normalize_opcode(instruction["opcode"])
    fmt = instruction_format(opcode)

    if fmt == FORMAT_PUSHN:
        values = " ".join(str(value) for value in instruction.get("values", ()))
        return f"{opcode.mnemonic} {values}".rstrip()
    if "arg" not in instruction:
        return opcode.mnemonic
    if fmt == FORMAT_U16:
        return f"{opcode.mnemonic} 0x{instruction['arg']:04X}"
    return f"{opcode.mnemonic} {instruction['arg']}"


def to_hex(code):
    lines = []
    address = 0
    for instruction in code:
        lines.append(f"{address} - {instruction_to_hex(instruction)} - {instruction_to_mnemonic(instruction)}")
        address += instruction_size(instruction)
    return "\n".join(lines)


def data_to_bytes(words):
    binary = bytearray()
    for word in words:
        binary.extend(encode_word(word))
    return bytes(binary)


def data_from_bytes(payload):
    if len(payload) % WORD_BYTES != 0:
        raise ValueError(f"data memory payload size must be a multiple of {WORD_BYTES}, got {len(payload)}")
    return [decode_word(payload[offset : offset + WORD_BYTES]) for offset in range(0, len(payload), WORD_BYTES)]


def data_to_hex(words, start=0):
    lines = []
    for offset, word in enumerate(words):
        address = start + offset
        encoded = encode_word(word).hex().upper()
        lines.append(f"{address} - {encoded} - {word}")
    return "\n".join(lines)
