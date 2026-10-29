"""Tests für Passwort-Hashing und Migration alter SHA-256-Hashes (config.py)."""

import hashlib

from config import hash_password, password_needs_rehash, verify_password


def test_hash_roundtrip():
    stored = hash_password("geheim123")
    assert stored.startswith("scrypt$")
    assert verify_password("geheim123", stored)
    assert not verify_password("geheim124", stored)


def test_hash_is_salted():
    assert hash_password("geheim123") != hash_password("geheim123")


def test_empty_hash_never_matches():
    assert not verify_password("", "")
    assert not verify_password("irgendwas", "")


def test_legacy_sha256_still_verifies_and_needs_rehash():
    legacy = hashlib.sha256(b"altes-passwort").hexdigest()
    assert verify_password("altes-passwort", legacy)
    assert not verify_password("falsch", legacy)
    assert password_needs_rehash(legacy)


def test_current_hash_needs_no_rehash():
    assert not password_needs_rehash(hash_password("x"))


def test_outdated_scrypt_parameters_need_rehash():
    stored = hash_password("x").replace("scrypt$16384$", "scrypt$1024$", 1)
    assert password_needs_rehash(stored)


def test_malformed_scrypt_hash_is_rejected():
    assert not verify_password("x", "scrypt$kaputt")
    assert not verify_password("x", "scrypt$16384$8$1$zz$00")
