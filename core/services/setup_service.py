"""
core/services/setup_service.py
==============================
First-run setup engine, security provisioning, and setup immunity service.

Ensures that while data/config/.setup_complete does NOT exist, setup routes
and initial provisioning are exempt from admin PIN verification and lockouts.
"""

import os
from typing import Dict, Any

from core.config import Config
from core.setup.wizard import (
    SETUP_MARKER_PATH,
    AUTH_CONFIG_PATH,
    PIN_HASH_PATH,
    ENV_CONFIG_PATH,
    get_pin_hash_path,
    is_setup_complete as _is_setup_complete,
    check_existing_installation as _check_existing_installation,
    save_setup_configuration as _save_setup_configuration,
    mark_setup_complete as _mark_setup_complete,
    generate_crypto_keys,
    test_crypto_roundtrip,
    check_prerequisites
)


def is_setup_complete() -> bool:
    """Returns True if first-run setup is fully finished and locked."""
    return _is_setup_complete()


def check_existing_installation() -> Dict[str, Any]:
    """Inspects private data dir for existing credentials or keys."""
    return _check_existing_installation()


def is_exempt_from_pin_auth() -> bool:
    """
    While data/config/.setup_complete does NOT exist, exempt setup endpoints
    from Admin PIN verification.
    """
    return not is_setup_complete()


def save_setup_configuration(data: Dict[str, Any]) -> Dict[str, Any]:
    """Saves initial configuration, generates keys, and runs verification roundtrips."""
    return _save_setup_configuration(data)


def mark_setup_complete(data: Dict[str, Any] = None) -> bool:
    """Creates data/config/.setup_complete upon final user completion (Step 7)."""
    return _mark_setup_complete(data or {})
