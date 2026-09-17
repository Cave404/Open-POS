"""
core/services/branding_service.py
==================================
Multi-resolution ICO converter and dynamic branding asset processor.
Converts uploaded store logo imagery into Windows-compatible multi-resolution
icon (.ico) files preserving alpha transparency across standard mipmaps.
"""

import os
import logging
from typing import Optional, List, Tuple
from PIL import Image

from core.config import Config

logger = logging.getLogger(__name__)

DEFAULT_ICO_SIZES: List[Tuple[int, int]] = [
    (16, 16),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256)
]


def generate_store_ico(
    source_image_path: str,
    output_ico_path: Optional[str] = None,
    sizes: Optional[List[Tuple[int, int]]] = None
) -> Optional[str]:
    """
    Converts a source raster image (PNG, JPG, WebP) into a Windows-standard
    multi-resolution .ico asset with mipmaps:
    [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)].

    Preserves alpha channel transparency and applies center square cropping
    to avoid aspect distortion.

    Args:
        source_image_path: Absolute or relative path to the uploaded logo file.
        output_ico_path: Destination path for the .ico file. Defaults to
                         data/uploads/store_icon.ico.
        sizes: Optional list of (width, height) tuples for mipmaps.

    Returns:
        The destination path if successful, or None if conversion failed.
    """
    if not source_image_path or not os.path.isfile(source_image_path):
        logger.warning(f"[BRANDING] Source image does not exist: {source_image_path}")
        return None

    if output_ico_path is None:
        upload_dir = getattr(Config, 'UPLOAD_DIR', os.path.join(Config.DATA_DIR, 'uploads'))
        os.makedirs(upload_dir, exist_ok=True)
        output_ico_path = os.path.join(upload_dir, 'store_icon.ico')

    if sizes is None:
        sizes = DEFAULT_ICO_SIZES

    try:
        with Image.open(source_image_path) as img:
            # Preserve RGBA transparency
            img = img.convert('RGBA')

            # Crop to square centered on original canvas
            w, h = img.size
            min_dim = min(w, h)
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            right = left + min_dim
            bottom = top + min_dim

            square_img = img.crop((left, top, right, bottom))

            dirname = os.path.dirname(output_ico_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            square_img.save(output_ico_path, format='ICO', sizes=sizes)

        logger.info(f"[BRANDING] Successfully generated multi-resolution ICO at {output_ico_path}")
        return output_ico_path
    except Exception as exc:
        logger.error(f"[BRANDING] Failed to generate store ICO from {source_image_path}: {exc}", exc_info=True)
        return None
