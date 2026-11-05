import atexit
import os
import shutil
import tempfile

# Must run before anything imports backend.app.config: the real .env holds Docker's /app
# paths, and the suite must neither break on them nor touch the real data directory.
_tmp = tempfile.mkdtemp(prefix="piop-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/app.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)
