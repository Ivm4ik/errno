import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from config_loader import ROOT

GENESIS = "0" * 64
KEY_PATH = ROOT / "device_key.pem"


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_key() -> Ed25519PrivateKey:
    if KEY_PATH.exists():
        return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
    key = Ed25519PrivateKey.generate()
    KEY_PATH.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key


def link(prev_hash: str, ts: float, kind: str, payload) -> tuple[str, str]:
    raw = prev_hash + canonical({"ts": ts, "kind": kind, "payload": payload})
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return digest, raw


def sign(key: Ed25519PrivateKey, digest: str) -> str:
    return base64.b64encode(key.sign(digest.encode())).decode()


def verify_rows(rows: list[dict], public_key) -> dict:
    prev = GENESIS
    for index, row in enumerate(rows, start=1):
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        digest, _ = link(prev, row["ts"], row["kind"], payload)
        if digest != row["hash"] or row["prev_hash"] != prev:
            return {"ok": False, "broken_at": index, "total": len(rows)}
        try:
            public_key.verify(base64.b64decode(row["sig"]), digest.encode())
        except Exception:
            return {"ok": False, "broken_at": index, "total": len(rows)}
        prev = digest
    return {"ok": True, "broken_at": None, "total": len(rows)}


def public_from(key: Ed25519PrivateKey):
    return key.public_key()
