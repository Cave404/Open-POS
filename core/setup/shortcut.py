"""
=============================================================================
Open-POS Automated Desktop Shortcut Generator
=============================================================================
Generates a Windows desktop shortcut (OpenPOS.lnk) targeting Open_POS.vbs
via Windows Script Host (WScript.Shell) COM automation in PowerShell.
=============================================================================
"""

import os
import subprocess
import logging

from core.services.shortcut_service import create_desktop_shortcut, DEFAULT_SHELL_ICON

__all__ = ["create_desktop_shortcut", "DEFAULT_SHELL_ICON"]
