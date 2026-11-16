"""Print a new identity signing key (SIGNING_PRIVATE_KEY): base64url of a 32-byte Ed25519 seed.

    python tools/gen_signing_key.py

Put the value in the server's env file (never in Git). To ROTATE: restart identity with a new value; the
old public key stays published as 'retiring' until the tokens it signed have expired.
"""

import base64
import secrets

print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))
