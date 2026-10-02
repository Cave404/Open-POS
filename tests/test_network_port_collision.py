"""
tests/test_network_port_collision.py
====================================
Tests for dynamic port selection, collision detection, and persistence:
1. is_port_available accurately detects free and occupied ports.
2. resolve_server_port scans sequentially upon collision and finds available port.
3. Config.determine_runtime_port uses store_settings.json server_port if present.
"""

import socket
import json
import pytest
from core.network import is_port_available, resolve_server_port
from core.config import Config


def test_is_port_available_on_free_port():
    """Asserts that an unallocated port in safe high range is detected as free."""
    # Find a free port using OS ephemeral allocation
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        free_port = s.getsockname()[1]
    assert is_port_available(free_port) is True


def test_is_port_available_detects_occupied_port():
    """Asserts that a bound and listening socket is correctly identified as unavailable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert is_port_available(port) is False
    finally:
        sock.close()
    assert is_port_available(port) is True


def test_resolve_server_port_collision_fallback():
    """Asserts that resolve_server_port increments past an occupied port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    occupied_port = sock.getsockname()[1]
    try:
        resolved = resolve_server_port(preferred_port=occupied_port, max_attempts=5)
        assert resolved > occupied_port
        assert is_port_available(resolved) is True
    finally:
        sock.close()


def test_config_get_configured_port_and_determine_runtime_port(tmp_path, monkeypatch):
    """Asserts Config reads server_port from store_settings.json and determine_runtime_port sets ACTIVE_PORT."""
    test_config_dir = tmp_path / "config"
    test_config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = test_config_dir / "store_settings.json"
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump({"server_port": 5060}, f)

    monkeypatch.setattr(Config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.Config.DATA_DIR", str(tmp_path))

    configured = Config.get_configured_port()
    assert configured == 5060

    runtime_port = Config.determine_runtime_port()
    assert runtime_port == 5060
    assert Config.ACTIVE_PORT == 5060
    assert Config.PORT == 5060
