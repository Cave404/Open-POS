import socket
import logging

logger = logging.getLogger("openpos.network")


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """
    Checks whether a TCP port is free to bind on localhost.
    Performs connection probe and verifies actual socket binding capability
    to prevent Errno 10048 (address already in use).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return False
    except Exception:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def resolve_server_port(preferred_port: int = 5050, max_attempts: int = 50, host: str = "127.0.0.1") -> int:
    """
    Returns preferred_port if available; otherwise scans sequentially
    until a free port is found to prevent collisions with existing POS software.
    """
    if is_port_available(preferred_port, host):
        logger.info(f"Primary port {preferred_port} is available.")
        return preferred_port

    logger.warning(f"Port {preferred_port} is occupied. Scanning for available fallback...")
    for offset in range(1, max_attempts + 1):
        candidate = preferred_port + offset
        if is_port_available(candidate, host):
            logger.info(f"Resolved available fallback port: {candidate}")
            return candidate

    raise RuntimeError(f"Unable to find an open port in range {preferred_port}-{preferred_port + max_attempts}")
