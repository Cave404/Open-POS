"""
Open-POS Automated First-Run Setup Engine
"""
from core.setup.wizard import (
    is_setup_complete,
    mark_setup_complete,
    check_prerequisites,
    generate_crypto_keys,
    save_setup_configuration,
    get_recovery_key_text,
    SETUP_MARKER_PATH
)

__all__ = [
    "is_setup_complete",
    "mark_setup_complete",
    "check_prerequisites",
    "generate_crypto_keys",
    "save_setup_configuration",
    "get_recovery_key_text",
    "SETUP_MARKER_PATH"
]
