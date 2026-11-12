"""Gera ícones PNG simples do PWA sem dependências externas."""
import struct
import zlib
from pathlib import Path


def png(size: int) -> bytes:
    raw = b"".join(b"\0" + bytes((79, 70, 229, 255)) * size for _ in range(size))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


output = Path("app/static/icons")
output.mkdir(parents=True, exist_ok=True)
for size in (192, 512):
    (output / f"icon-{size}.png").write_bytes(png(size))
