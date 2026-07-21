import subprocess
import sys
import os


def test_default_application_modules_do_not_import_google_packages():
    code = "import switchgear.main,sys; print(any(x == 'google' or x.startswith('google.') for x in sys.modules))"
    env = {**os.environ, "SWITCHGEAR_OWNER_EMAIL": "owner@example.com",
           "SWITCHGEAR_LOCAL_PASSWORD_HASH": "scrypt:16384:8:1:bad:bad",
           "SWITCHGEAR_SESSION_SECRET": "a-secure-test-secret-that-is-long-enough",
           "SWITCHGEAR_COOKIE_SECURE": "false"}
    result = subprocess.run([sys.executable, "-c", code], check=True, env=env,
                            capture_output=True, text=True)
    assert result.stdout.strip() == "False"
