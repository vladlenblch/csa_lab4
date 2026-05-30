import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

import machine
import translator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_DIR = os.path.join(ROOT, "golden")


def read_text(filename):
    with open(filename, encoding="utf-8") as file:
        return file.read()


def read_manifest(case_dir):
    with open(os.path.join(case_dir, "case.toml"), "rb") as file:
        return tomllib.load(file)


def case_dirs():
    for name in sorted(os.listdir(GOLDEN_DIR)):
        path = os.path.join(GOLDEN_DIR, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "source.fth")):
            yield name, path


def data_target_name(target):
    if target.endswith(".bin"):
        return target[:-4] + ".data.bin"
    return target + ".data"


class GoldenTest(unittest.TestCase):
    def test_golden_cases(self):
        for case_name, case_dir in case_dirs():
            with self.subTest(case=case_name):
                self.run_case(case_dir)

    def run_case(self, case_dir):
        source = os.path.join(case_dir, "source.fth")
        manifest_file = os.path.join(case_dir, "case.toml")
        self.assertTrue(
            os.path.exists(manifest_file),
            f"missing golden manifest for {case_dir}",
        )
        manifest = read_manifest(case_dir)
        expected = manifest["expected"]
        limit = str(manifest.get("limit", 10000))

        with tempfile.TemporaryDirectory() as tmpdirname:
            target = os.path.join(tmpdirname, "program.bin")
            data_target = data_target_name(target)
            schedule_target = os.path.join(tmpdirname, "input.schedule")

            with open(schedule_target, "w", encoding="utf-8") as file:
                file.write(manifest.get("input", ""))

            subprocess.run(
                [sys.executable, "translator.py", source, target],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            machine_result = subprocess.run(
                [sys.executable, "machine.py", target, data_target, schedule_target, limit],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(machine_result.stdout, expected["stdout"])
            self.assertEqual(read_text(target + ".hex"), expected["code_hex"])
            self.assertEqual(read_text(data_target + ".hex"), expected["data_hex"])
            self.assertEqual(read_text(target + ".interrupts"), expected["interrupts"])

        translated = translator.translate(read_text(source))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as schedule_file:
            schedule_file.write(manifest.get("input", ""))
            schedule_file.flush()
            schedule_data = machine.load_input_schedule(schedule_file.name)
        sim = machine.simulation(
            translated["code"],
            data_words=translated["data"],
            limit=int(limit),
            interrupts=translated["interrupts"],
            input_schedule=schedule_data,
        )
        log_lines = int(manifest.get("log_lines", 25))
        log_head = "\n".join(sim["log"][:log_lines])
        if log_head:
            log_head += "\n"
        self.assertEqual(log_head, expected["log_head"])


if __name__ == "__main__":
    unittest.main()
