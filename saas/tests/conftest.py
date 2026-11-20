import os

# Tests build their own app with an in-memory database; do not create the default one on import.
os.environ["SAAS_AUTOSTART"] = "0"
