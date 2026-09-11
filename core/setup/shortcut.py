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

logger = logging.getLogger(__name__)


def create_desktop_shortcut(base_dir=None) -> bool:
    """
    Creates an OpenPOS.lnk shortcut on the current user's Desktop pointing to Open_POS.vbs.
    
    Args:
        base_dir: Root directory of Open-POS installation (defaults to Config.BASE_DIR).
        
    Returns:
        bool: True if shortcut created successfully, False otherwise.
    """
    if base_dir is None:
        try:
            from core.config import Config
            base_dir = Config.BASE_DIR
        except Exception:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

    try:
        desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not os.path.isdir(desktop):
            os.makedirs(desktop, exist_ok=True)

        shortcut_path = os.path.join(desktop, 'OpenPOS.lnk')
        target_vbs = os.path.join(base_dir, 'Open_POS.vbs')
        icon_path = os.path.join(base_dir, 'manager', 'open_pos_splash.png')

        # PowerShell script utilizing WScript.Shell COM object
        ps_cmd = f'''
        $WshShell = New-Object -ComObject WScript.Shell;
        $Shortcut = $WshShell.CreateShortcut('{shortcut_path}');
        $Shortcut.TargetPath = '{target_vbs}';
        $Shortcut.WorkingDirectory = '{base_dir}';
        $Shortcut.Description = 'OpenPOS - Point of Sale & System Manager';
        $Shortcut.Save();
        '''

        creation_flag = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
            creationflags=creation_flag
        )
        logger.info(f"[SHORTCUT] Created desktop shortcut at {shortcut_path}")
        return os.path.isfile(shortcut_path)
    except Exception as e:
        logger.warning(f"[SHORTCUT] Failed to create desktop shortcut: {e}")
        return False
