"""
core/services/shortcut_service.py
==================================
Native Windows desktop shortcut (.lnk) dispatcher.
Invokes PowerShell with WScript.Shell COM automation to create or update
OpenPOS.lnk on the user's desktop with custom or fallback icon metadata.
"""

import os
import subprocess
import logging
from typing import Optional

from core.config import Config

logger = logging.getLogger(__name__)

DEFAULT_SHELL_ICON = r"C:\Windows\System32\shell32.dll,264"


def create_desktop_shortcut(
    base_dir: Optional[str] = None,
    upload_dir: Optional[str] = None
) -> bool:
    """
    Creates or updates the Windows desktop shortcut (OpenPOS.lnk) pointing to Open_POS.vbs.

    Shortcut Properties:
      - TargetPath: <base_dir>/Open_POS.vbs
      - WorkingDirectory: <base_dir>
      - IconLocation: <upload_dir>/store_icon.ico,0 if it exists;
                      otherwise fallback to C:\\Windows\\System32\\shell32.dll,264
      - Description: OpenPOS - Point of Sale & System Manager

    Args:
        base_dir: Root directory of Open-POS repository. Defaults to Config.BASE_DIR.
        upload_dir: Uploads directory for custom icon. Defaults to Config.UPLOAD_DIR.

    Returns:
        bool: True if shortcut was verified on disk, False otherwise.
    """
    if base_dir is None:
        try:
            base_dir = Config.BASE_DIR
        except Exception:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

    if upload_dir is None:
        try:
            upload_dir = Config.UPLOAD_DIR
        except Exception:
            upload_dir = os.path.join(base_dir, 'data', 'uploads')

    try:
        desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not os.path.isdir(desktop):
            os.makedirs(desktop, exist_ok=True)

        shortcut_path = os.path.join(desktop, 'OpenPOS.lnk')
        target_vbs = os.path.join(base_dir, 'Open_POS.vbs')

        # Determine icon path
        custom_ico = os.path.join(upload_dir, 'store_icon.ico')
        if os.path.isfile(custom_ico):
            icon_location = f"{custom_ico},0"
        else:
            icon_location = DEFAULT_SHELL_ICON

        ps_cmd = f'''
        $WshShell = New-Object -ComObject WScript.Shell;
        $Shortcut = $WshShell.CreateShortcut('{shortcut_path}');
        $Shortcut.TargetPath = '{target_vbs}';
        $Shortcut.WorkingDirectory = '{base_dir}';
        $Shortcut.IconLocation = '{icon_location}';
        $Shortcut.Description = 'OpenPOS - Point of Sale & System Manager';
        $Shortcut.Save();
        '''

        creation_flag = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
            creationflags=creation_flag
        )

        logger.info(f"[SHORTCUT] Created desktop shortcut at {shortcut_path} (Icon: {icon_location})")
        return os.path.isfile(shortcut_path)
    except Exception as exc:
        logger.warning(f"[SHORTCUT] Failed to create desktop shortcut: {exc}")
        return False
