import os
import unittest

from backend.config import Config
from backend.gemini_manager import _attempt_model
from google.genai import types


@unittest.skipUnless(os.getenv("COOKMATE_RUN_GEMINI_INTEGRATION") == "1", "set COOKMATE_RUN_GEMINI_INTEGRATION=1 to use live Gemini quota")
class GeminiLiveIntegrationTests(unittest.TestCase):
    def test_primary_and_fallback_models_accept_generate_content(self):
        contents = [types.Content(role="user", parts=[types.Part.from_text(text="Say only: CookMate ready")])]
        instruction = "Reply with the short test phrase only."
        for model, fallback in ((Config.GEMINI_PRIMARY_MODEL, False), (Config.GEMINI_FALLBACK_MODEL, True)):
            with self.subTest(model=model):
                _, text = _attempt_model(model, contents, instruction, fallback=fallback)
                self.assertTrue(text.strip())


if __name__ == "__main__":
    unittest.main()
