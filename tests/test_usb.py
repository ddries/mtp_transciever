import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from usb import read_file_from_usb


class ReadFileFromUsb(unittest.TestCase):
    def stick(self, files: dict[str, int]) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name, size in files.items():
            (root / name).write_bytes(b"x" * size)
        return root

    def test_skips_windows_and_mac_leftovers(self):
        # A stick used on Windows: lock files, Word temp files, desktop.ini sort before "test.txt"
        root = self.stick({"desktop.ini": 82, "~$Trabajo.pptx": 165, "~WRL3792.tmp": 626279,
                           ".DS_Store": 10, "._test.txt": 4096, "test.txt": 35149})
        self.assertEqual(read_file_from_usb(str(root)).name, "test.txt")

    def test_largest_txt_wins(self):
        root = self.stick({"a.txt": 10, "b.TXT": 500, "c.txt": 20, "notes.docx": 9999})
        self.assertEqual(read_file_from_usb(str(root)).name, "b.TXT")

    def test_no_txt_falls_back_to_first_file(self):
        root = self.stick({"b.bin": 1, "a.bin": 2})
        self.assertEqual(read_file_from_usb(str(root)).name, "a.bin")

    def test_empty_or_only_leftovers(self):
        self.assertIsNone(read_file_from_usb(str(self.stick({}))))
        self.assertIsNone(read_file_from_usb(str(self.stick({"desktop.ini": 1, "~$x.docx": 1}))))
        self.assertIsNone(read_file_from_usb("/nonexistent/stick"))


if __name__ == "__main__":
    unittest.main()
