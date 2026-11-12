"""Gera e imprime chaves VAPID para uso no .env."""
from py_vapid import Vapid
from py_vapid.utils import b64urlencode
from cryptography.hazmat.primitives import serialization

vapid = Vapid()
vapid.generate_keys()
public_key = vapid.public_key.public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
)
print(f"VAPID_PUBLIC_KEY={b64urlencode(public_key)}")
private_value = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
print(f"VAPID_PRIVATE_KEY={b64urlencode(private_value)}")
print("VAPID_CLAIM_EMAIL=mailto:admin@seudominio.com")
