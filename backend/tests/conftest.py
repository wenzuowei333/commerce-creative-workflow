import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Importing app.main creates the ASGI application used by Uvicorn. Keep that
# import-time application isolated from developer and production .env files.
_runtime_root = Path(tempfile.mkdtemp(prefix="image-studio-pytest-"))
atexit.register(shutil.rmtree, _runtime_root, True)

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "MEDIA_BACKEND": "local",
        "MEDIA_ROOT": str(_runtime_root / "media"),
    }
)
