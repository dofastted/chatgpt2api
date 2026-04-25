from __future__ import annotations

import os
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="chatgpt2api-pytest-config-"))

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")
os.environ.setdefault("CHATGPT2API_ADMIN_AUTH_KEY", "test-admin-key")
os.environ.setdefault("CHATGPT2API_DATA_DIR", str(TEST_ROOT / "data"))
os.environ.setdefault("CHATGPT2API_USER_KEYS_FILE", str(TEST_ROOT / "user_keys.json"))
os.environ.setdefault("CHATGPT2API_REDEEM_CODES_FILE", str(TEST_ROOT / "redeem_codes.json"))

