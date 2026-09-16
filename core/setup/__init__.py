"""
Open-POS Automated First-Run Setup Engine
"""
from core.setup.wizard import (
    is_setup_complete,
    mark_setup_complete,
    check_prerequisites,
    check_existing_installation,
    generate_crypto_keys,
    save_setup_configuration,
    get_recovery_key_text,
    SETUP_MARKER_PATH,
    PIN_HASH_PATH
)
from core.setup.checks import install_missing_requirements
from core.setup.shortcut import create_desktop_shortcut

__all__ = [
    "is_setup_complete",
    "mark_setup_complete",
    "check_prerequisites",
    "check_existing_installation",
    "install_missing_requirements",
    "create_desktop_shortcut",
    "generate_crypto_keys",
    "save_setup_configuration",
    "get_recovery_key_text",
    "SETUP_MARKER_PATH",
    "PIN_HASH_PATH"
]

