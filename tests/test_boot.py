import pytest
from app import create_app
from core.boot import run_boot_sequence

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_run_boot_sequence():
    """Asserts that the boot sequence executes all 5 phases and reports monotonically increasing progress."""
    progress_history = []

    def on_progress(percent: int, message: str):
        progress_history.append((percent, message))

    # Run with 0s buffer to execute fast in unit tests
    boot_summary = run_boot_sequence(
        progress_callback=on_progress,
        buffer_seconds=0.0,
        check_git_remote=False
    )

    assert boot_summary["status"] == "success"
    assert "environment" in boot_summary
    assert "updates" in boot_summary
    assert "database" in boot_summary
    assert "addons" in boot_summary

    # Verify progress notifications
    assert len(progress_history) >= 5
    percentages = [p[0] for p in progress_history]
    assert percentages[0] <= 10
    assert percentages[-1] == 100
    # Ensure progress increases
    assert percentages == sorted(percentages)

    # Verify status messages
    messages = [p[1] for p in progress_history]
    assert any("environment" in m.lower() for m in messages)
    assert any("update" in m.lower() for m in messages)
    assert any("database" in m.lower() for m in messages)
    assert any("addon" in m.lower() or "plugin" in m.lower() for m in messages)
    assert any("finishing" in m.lower() for m in messages)

def test_splash_view_route(client):
    """Asserts that GET /manager/splash renders the splash template."""
    res = client.get("/manager/splash")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Open-POS System Startup" in html
    assert "splash-frame" in html
    assert "progressBar" in html
    assert "statusLabel" in html
    assert "updateProgress" in html

def test_splash_image_route(client):
    """Asserts that GET /manager/splash_image returns the splash graphic."""
    res = client.get("/manager/splash_image")
    assert res.status_code == 200
    assert res.content_type == "image/png"
    assert len(res.data) > 1000
