from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChatGptPackTests(unittest.TestCase):
    def test_search_laws_module_imports(self):
        module = load_module(
            "chatgpt_pack_search_laws",
            ROOT / "chatgpt_pack" / "search_laws.py",
        )
        self.assertTrue(hasattr(module, "search_laws"))

    def test_export_chatgpt_pack_module_imports(self):
        module = load_module(
            "export_chatgpt_pack",
            ROOT / "tools" / "export_chatgpt_pack.py",
        )
        self.assertTrue(hasattr(module, "create_chatgpt_pack"))

    def test_create_chatgpt_pack_zip(self):
        module = load_module(
            "export_chatgpt_pack_for_zip_test",
            ROOT / "tools" / "export_chatgpt_pack.py",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = module.create_chatgpt_pack(Path(tmp_dir))

            self.assertTrue(zip_path.exists())
            self.assertEqual(zip_path.parent, Path(tmp_dir).resolve())

            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())

            self.assertIn("chatgpt_pack/search_laws.py", names)
            self.assertIn("chatgpt_pack/CHATGPT_INSTRUCTIONS.md", names)
            self.assertIn("chatgpt_pack/README.md", names)
            self.assertIn("data/laws.db", names)


if __name__ == "__main__":
    unittest.main()
