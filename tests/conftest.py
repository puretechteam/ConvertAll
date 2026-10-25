import pytest
from PIL import Image

from convertall import engines


def pytest_addoption(parser):
    parser.addoption("--e2e", action="store_true", help="convert every sample to every format it can reach")


@pytest.fixture(autouse=True)
def no_installs(monkeypatch):
    """Tests must never install software on the machine."""
    def refuse(key, log=None):
        raise AssertionError(f"test tried to install {key}")
    monkeypatch.setattr(engines, "install", refuse)


@pytest.fixture
def without_engine(monkeypatch):
    """Pretend an engine isn't installed: without_engine('ffmpeg')."""
    def hide(*keys):
        real = engines.find

        def fake(key):
            return None if key in keys else real(key)
        monkeypatch.setattr(engines, "find", fake)
    return hide


def needs(engine: str):
    return pytest.mark.skipif(not engines.available(engine), reason=f"{engine} not installed")


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "pic.png"
    img = Image.new("RGBA", (120, 80), (30, 120, 220, 255))
    img.paste((255, 0, 0, 0), (0, 0, 40, 40))  # transparent corner
    img.save(path)
    return path
