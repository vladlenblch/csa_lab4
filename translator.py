import os
import sys

import isa
from isa import Opcode

INPUT_CHAR_ADDR = 0xFF00
INPUT_READY_ADDR = 0xFF01
OUTPUT_CHAR_ADDR = 0xFF02


class TranslationError(Exception):
    pass


def is_integer(token):
    if token == "":
        return False
    if token[0] == "-":
        return token[1:].isdigit()
    return token.isdigit()


def tokenize(text):
    tokens = []
    for line_num, line in enumerate(text.splitlines(), 1):
        pos = 0
        while pos < len(line):
            char = line[pos]
            if char == "\\":
                break
            if char.isspace():
                pos += 1
                continue
            if char == "s" and pos + 1 < len(line) and line[pos + 1] == '"':
                pos += 2
                value = []
                while pos < len(line) and line[pos] != '"':
                    value.append(line[pos])
                    pos += 1
                if pos >= len(line):
                    raise TranslationError(f"unterminated string at line {line_num}")
                tokens.append(
                    {
                        "kind": "string",
                        "value": "".join(value),
                    }
                )
                pos += 1
                continue

            start = pos
            while pos < len(line) and not line[pos].isspace() and line[pos] != "\\":
                pos += 1
            value = line[start:pos]
            tokens.append(
                {
                    "kind": "word",
                    "value": value,
                }
            )
    return tokens


def parse_program(tokens):
    definitions = []
    variables = []
    constants = {}
    top_level = []
    pos = 0

    while pos < len(tokens):
        token = tokens[pos]
        value = token["value"]

        if value in (":", ":interrupt"):
            interrupt = value == ":interrupt"
            name_token = _require_token(tokens, pos + 1, "word name")
            name = name_token["value"]
            body, pos = _take_until_semicolon(tokens, pos + 2)
            definitions.append({"name": name, "body": body, "interrupt": interrupt})
            continue

        if value == "variable":
            name_token = _require_token(tokens, pos + 1, "variable name")
            variables.append(name_token["value"])
            pos += 2
            continue

        if is_integer(value) and pos + 2 < len(tokens) and tokens[pos + 1]["value"] == "constant":
            constants[tokens[pos + 2]["value"]] = int(value)
            pos += 3
            continue

        top_level.append(token)
        pos += 1

    return definitions, variables, constants, top_level


def _require_token(tokens, pos, description):
    if pos >= len(tokens):
        raise TranslationError(f"expected {description}")
    return tokens[pos]


def _take_until_semicolon(tokens, pos):
    body = []
    while pos < len(tokens):
        if tokens[pos]["value"] == ";":
            return body, pos + 1
        body.append(tokens[pos])
        pos += 1
    raise TranslationError("definition is missing ';'")


class Translator:
    def __init__(self):
        self.code = []
        self.labels = {}
        self.label_counter = 0
        self.constants = {}
        self.variables = {}
        self.definitions = []
        self.word_labels = {}
        self.data = [0]

    def translate(self, text):
        tokens = tokenize(text)
        definitions, variables, constants, top_level = parse_program(tokens)

        self.constants = constants
        self.definitions = definitions
        for name in variables:
            self.variables[name] = len(self.data)
            self.data.append(0)
        for definition in definitions:
            self.word_labels[definition["name"]] = self._word_label(definition["name"])

        has_main = "main" in self.word_labels
        if top_level and has_main:
            raise TranslationError("top-level statements cannot be mixed with explicit main")
        if top_level and not has_main:
            self.word_labels["main"] = self._word_label("main")
            self.definitions.append({"name": "main", "body": top_level, "interrupt": False})
            has_main = True
        if not has_main:
            self.word_labels["main"] = self._word_label("main")
            self.definitions.append({"name": "main", "body": [], "interrupt": False})

        self.emit_call(self.word_labels["main"])
        self.emit(isa.op(Opcode.HALT))

        for definition in self.definitions:
            self._compile_definition(definition)

        code, symbols = self.resolve_labels()
        interrupts = {}
        for definition in self.definitions:
            if definition["interrupt"]:
                label = self.word_labels[definition["name"]]
                interrupts[definition["name"]] = symbols[label]
        return {"code": code, "data": self.data, "symbols": symbols, "interrupts": interrupts}

    def _word_label(self, name):
        return f"word:{name}"

    def new_label(self, prefix):
        label = f"{prefix}_{self.label_counter}"
        self.label_counter += 1
        return label

    def mark(self, label):
        self.labels[label] = len(self.code)

    def emit(self, instruction):
        self.code.append(instruction)

    def emit_many(self, *instructions):
        for instruction in instructions:
            self.emit(instruction)

    def emit_branch(self, opcode, target):
        instruction = isa.i16(opcode, 0)
        instruction["target"] = target
        self.emit(instruction)

    def emit_call(self, target):
        self.emit_branch(Opcode.CALL, target)

    def emit_address(self, target):
        instruction = isa.i32(Opcode.PUSHI32, 0)
        instruction["target_addr"] = target
        self.emit(instruction)

    def resolve_labels(self):
        addresses = isa.instruction_addresses(self.code)
        end_address = isa.code_size(self.code)
        label_addresses = {}

        for label, index in self.labels.items():
            if index == len(self.code):
                label_addresses[label] = end_address
            else:
                label_addresses[label] = addresses[index]

        for index, instruction in enumerate(self.code):
            if "target" in instruction:
                target = instruction.pop("target")
                source_address = addresses[index]
                target_address = label_addresses[target]
                instruction["arg"] = isa.relative_offset(
                    source_address,
                    isa.instruction_size(instruction),
                    target_address,
                )
            if "target_addr" in instruction:
                target = instruction.pop("target_addr")
                instruction["arg"] = label_addresses[target]

        return self.code, label_addresses

    def _compile_definition(self, definition):
        name = definition["name"]
        self.mark(self.word_labels[name])
        pos, stop = self._compile_block(definition["body"], 0, set())
        if pos != len(definition["body"]) or stop is not None:
            raise TranslationError(f"unexpected token in definition {name}: {stop}")
        if definition["interrupt"]:
            self.emit(isa.op(Opcode.IRET))
        else:
            self.emit(isa.op(Opcode.RET))

    def _compile_block(self, tokens, pos, stop_words):
        while pos < len(tokens):
            token = tokens[pos]
            value = token["value"]

            if value in stop_words:
                return pos, value
            if value in {"else", "then", "until", "loop"}:
                raise TranslationError(f"unexpected control token: {value}")

            if token["kind"] == "string":
                self._compile_string(token)
                pos += 1
                continue

            if is_integer(value):
                self.emit(isa.i32(Opcode.PUSHI32, int(value)))
                pos += 1
                continue

            if value == "if":
                pos = self._compile_if(tokens, pos + 1)
                continue
            if value == "begin":
                pos = self._compile_begin_until(tokens, pos + 1)
                continue
            if value == "do":
                pos = self._compile_do_loop(tokens, pos + 1)
                continue
            if value == "'":
                pos = self._compile_execution_token(tokens, pos + 1)
                continue
            if value == "pushn":
                pos = self._compile_pushn(tokens, pos + 1)
                continue

            self._compile_word(value, token)
            pos += 1

        if stop_words:
            expected = "/".join(sorted(stop_words))
            raise TranslationError(f"expected control token: {expected}")
        return pos, None

    def _compile_string(self, token):
        text = token["value"]
        address = len(self.data)
        self.data.append(len(text))
        for char in text:
            self.data.append(ord(char))
        self.emit(isa.i32(Opcode.PUSHI32, address))

    def _compile_execution_token(self, tokens, pos):
        token = _require_token(tokens, pos, "word after execution-token quote")
        name = token["value"]
        if name not in self.word_labels:
            self.word_labels[name] = self._word_label(name)
        self.emit_address(self.word_labels[name])
        return pos + 1

    def _compile_pushn(self, tokens, pos):
        count_token = _require_token(tokens, pos, "pushn count")
        if not is_integer(count_token["value"]):
            raise TranslationError("pushn count must be integer")

        count = int(count_token["value"])
        if count < 0:
            raise TranslationError("pushn count must be non-negative")

        values = []
        for offset in range(count):
            value_token = _require_token(tokens, pos + 1 + offset, "pushn value")
            if not is_integer(value_token["value"]):
                raise TranslationError("pushn value must be integer")
            values.append(int(value_token["value"]))

        self.emit(isa.pushn(values))
        return pos + 1 + count

    def _compile_if(self, tokens, pos):
        false_label = self.new_label("if_false")
        end_label = self.new_label("if_end")

        self.emit_branch(Opcode.JZ, false_label)
        pos, stop = self._compile_block(tokens, pos, {"else", "then"})

        if stop == "else":
            self.emit_branch(Opcode.JMP, end_label)
            self.mark(false_label)
            pos, stop = self._compile_block(tokens, pos + 1, {"then"})
            if stop != "then":
                raise TranslationError("expected then after else")
            self.mark(end_label)
            return pos + 1

        if stop == "then":
            self.mark(false_label)
            self.mark(end_label)
            return pos + 1

        raise TranslationError("expected else or then")

    def _compile_begin_until(self, tokens, pos):
        begin_label = self.new_label("begin")
        self.mark(begin_label)
        pos, stop = self._compile_block(tokens, pos, {"until"})
        if stop != "until":
            raise TranslationError("expected until")
        self.emit_branch(Opcode.JZ, begin_label)
        return pos + 1

    def _compile_do_loop(self, tokens, pos):
        loop_start = self.new_label("do_start")
        loop_exit = self.new_label("do_exit")
        skip_init = self.new_label("do_skip")
        after_loop = self.new_label("do_after")

        self.emit_many(
            isa.op(Opcode.OVER),
            isa.op(Opcode.OVER),
            isa.op(Opcode.SWAP),
            isa.op(Opcode.LT),
        )
        self.emit_branch(Opcode.JZ, skip_init)
        self.emit_many(isa.op(Opcode.SWAP), isa.op(Opcode.TOR), isa.op(Opcode.TOR))

        self.mark(loop_start)
        pos, stop = self._compile_block(tokens, pos, {"loop"})
        if stop != "loop":
            raise TranslationError("expected loop")

        self.emit_many(
            isa.op(Opcode.FROMR),
            isa.i32(Opcode.PUSHI32, 1),
            isa.op(Opcode.ADD),
            isa.op(Opcode.DUP),
            isa.op(Opcode.RPEEK),
            isa.op(Opcode.LT),
        )
        self.emit_branch(Opcode.JZ, loop_exit)
        self.emit(isa.op(Opcode.TOR))
        self.emit_branch(Opcode.JMP, loop_start)

        self.mark(loop_exit)
        self.emit_many(isa.op(Opcode.DROP), isa.op(Opcode.FROMR), isa.op(Opcode.DROP))
        self.emit_branch(Opcode.JMP, after_loop)

        self.mark(skip_init)
        self.emit_many(isa.op(Opcode.DROP), isa.op(Opcode.DROP))

        self.mark(after_loop)
        return pos + 1

    def _compile_word(self, word, token):
        if word in self.constants:
            self.emit(isa.i32(Opcode.PUSHI32, self.constants[word]))
            return
        if word in self.variables:
            self.emit(isa.i32(Opcode.PUSHI32, self.variables[word]))
            return
        if self._compile_builtin(word):
            return
        if word not in self.word_labels:
            self.word_labels[word] = self._word_label(word)
        self.emit_call(self.word_labels[word])

    def _compile_builtin(self, word):
        direct = {
            "+": Opcode.ADD,
            "-": Opcode.SUB,
            "*": Opcode.MUL,
            "/": Opcode.DIV,
            "mod": Opcode.MOD,
            "=": Opcode.EQ,
            "<": Opcode.LT,
            ">": Opcode.GT,
            "dup": Opcode.DUP,
            "drop": Opcode.DROP,
            "swap": Opcode.SWAP,
            "over": Opcode.OVER,
            "load": Opcode.LOAD,
            "store": Opcode.STORE,
            "execute": Opcode.CALLXT,
            "halt": Opcode.HALT,
            "i": Opcode.RPEEK,
            "ei": Opcode.EI,
            "di": Opcode.DI,
            "get-carry": Opcode.GET_CARRY,
        }

        if word in direct:
            self.emit(isa.op(direct[word]))
            return True
        if word == "read-char":
            self.emit(isa.u16(Opcode.LOADA, INPUT_CHAR_ADDR))
            return True
        if word == "input-ready?":
            self.emit(isa.u16(Opcode.LOADA, INPUT_READY_ADDR))
            return True
        if word == "write-char":
            self.emit(isa.u16(Opcode.STOREA, OUTPUT_CHAR_ADDR))
            return True
        return False


def translate(text):
    return Translator().translate(text)


def _data_target_name(target):
    if target.endswith(".bin"):
        return target[:-4] + ".data.bin"
    return target + ".data"


def main(source, target):
    with open(source, encoding="utf-8") as file:
        source_text = file.read()

    result = translate(source_text)
    code = result["code"]
    data = result["data"]
    binary_code = isa.to_bytes(code)
    hex_code = isa.to_hex(code)
    data_binary = isa.data_to_bytes(data)
    data_hex = isa.data_to_hex(data)
    symbols = result["symbols"]
    interrupts = result["interrupts"]

    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    data_target = _data_target_name(target)
    with open(target, "wb") as file:
        file.write(binary_code)
    with open(target + ".hex", "w", encoding="utf-8") as file:
        file.write(hex_code)
    with open(data_target, "wb") as file:
        file.write(data_binary)
    with open(data_target + ".hex", "w", encoding="utf-8") as file:
        file.write(data_hex)
    with open(target + ".symbols", "w", encoding="utf-8") as file:
        for name in sorted(symbols):
            file.write(f"{name} {symbols[name]}\n")
    with open(target + ".interrupts", "w", encoding="utf-8") as file:
        for name in sorted(interrupts):
            file.write(f"{name} {interrupts[name]}\n")

    print(
        "source LoC:",
        len(source_text.splitlines()),
        "code instr:",
        len(code),
        "code bytes:",
        len(binary_code),
        "data words:",
        len(data),
    )


if __name__ == "__main__":
    assert len(sys.argv) == 3, "Wrong arguments: translator.py <input_file> <target_file>"
    _, source, target = sys.argv
    main(source, target)
