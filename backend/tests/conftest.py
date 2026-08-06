import os
import tempfile

# Must be set before anything under app/ is imported: db.py opens the database
# and config.py caches the settings at import time.
_tmp = tempfile.mkdtemp(prefix="timeme-test-")
os.environ.setdefault("TIMEME_DB_PATH", os.path.join(_tmp, "test.db"))
os.environ.setdefault("TIMEME_SECRET_KEY", "test-secret")
os.environ.setdefault("TIMEME_TIMEZONE", "Europe/Berlin")
os.environ.setdefault("TIMEME_COOKIE_SECURE", "false")
os.environ.setdefault("TIMEME_STATIC_DIR", "")
