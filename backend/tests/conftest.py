import os
import tempfile
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_PATH"] = str(_db)
os.environ["RUN_DRIVERS"] = "false"
os.environ["DEV_NO_AUTH"] = "true"
os.environ["DEMO_MODE"] = "true"
os.environ["DEVICE_TOKENS"] = "gw-1:secret,sim-gw-1:secret"
os.environ["FLUSH_SECONDS"] = "0.05"
os.environ["SIGNAL_DELAY_SEC"] = "0"
os.environ["SEED_PASSWORD_DOCTOR"] = "doctor-pass"
os.environ["SEED_PASSWORD_OFFICER"] = "officer-pass"
os.environ["SEED_PASSWORD_ASTRONAUT"] = "astronaut-pass"
