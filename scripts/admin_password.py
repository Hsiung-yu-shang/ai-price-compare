"""Create a one-repository admin password without storing its plaintext."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import tempfile
from pathlib import Path


SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if not password or len(password) > 256:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, int(n), int(r), int(p)) != ("scrypt", SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt),
            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32,
        )
        return secrets.compare_digest(digest, bytes.fromhex(expected))
    except (TypeError, ValueError):
        return False


def write_password_file(path: Path, rotate: bool = False) -> str | None:
    """Return a new one-time password, or None when keeping an existing hash."""
    if path.is_symlink():
        raise ValueError("管理員設定檔不得為符號連結")
    if path.exists() and not rotate:
        return None

    password = secrets.token_urlsafe(24)
    content = f"ADMIN_PASSWORD_HASH={hash_password(password)}\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".aiprice-admin-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if rotate:
            os.replace(temporary, path)
        else:
            os.link(temporary, path, follow_symlinks=False)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="建立或輪替管理員密碼")
    parser.add_argument("--file", type=Path, default=Path("/etc/ai-price-compare-admin.env"))
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args()

    password = write_password_file(args.file, rotate=args.rotate)
    if password is None:
        print("管理員密碼維持原設定。")
    else:
        print("管理員密碼（只顯示這一次，請存入密碼管理器）：" + password)
        if args.rotate:
            print("請執行 systemctl restart ai-price-compare.service 使新密碼生效。")


if __name__ == "__main__":
    main()
