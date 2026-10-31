"""Saved presets: hand edits survive, names are one per spelling, settings read the way people type."""

import json
import os

import pytest

from convertall import options


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "presets.json"
    monkeypatch.setenv("CONVERTALL_PRESETS", str(path))
    return path


def test_saving_keeps_presets_it_cant_read(store):
    """A hand-edited preset with a value this version doesn't take is skipped, not deleted."""
    store.write_text(json.dumps({"Mine": {"quality": 500}, "Later": {"sharpness": 3}, "Ok": {"quality": 60}}))
    assert set(options.user_presets()) == {"Ok"}
    options.save_preset("New", {"quality": 70})
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["Mine"] == {"quality": 500} and saved["Later"] == {"sharpness": 3}
    assert saved["New"] == {"quality": 70} and saved["Ok"] == {"quality": 60}
    options.delete_preset("Ok")
    assert set(json.loads(store.read_text(encoding="utf-8"))) == {"Mine", "Later", "New"}


def test_a_file_that_isnt_json_is_kept_aside(store):
    store.write_text("{not json", encoding="utf-8")
    options.save_preset("New", {"quality": 70})
    assert json.loads(store.read_text(encoding="utf-8")) == {"New": {"quality": 70}}
    assert store.with_suffix(".unreadable.json").read_text(encoding="utf-8") == "{not json"


def test_names_ignore_case(store):
    options.save_preset("Web", {"quality": 70})
    options.save_preset("web ", {"quality": 60})
    assert options.user_presets() == {"web": {"quality": 60}}
    for builtin in ("default", "BEST QUALITY"):
        with pytest.raises(ValueError, match="built-in"):
            options.save_preset(builtin, {"quality": 1})
    options.delete_preset("WEB")
    assert options.user_presets() == {}


@pytest.mark.parametrize("typed", ["1920", "1920 px", "1920px", "1920PX", " 1920 Px "])
def test_numbers_take_their_unit_spaced_or_not(typed):
    assert options.SETTINGS["max_size"].check(typed) == 1920


def test_quick_saves_are_never_read_stale(store):
    """Saves a moment apart can share a timestamp (pinned here), and these have the same length."""
    for value in range(10, 30):
        options.save_preset("Web", {"quality": value})
        os.utime(store, ns=(1_700_000_000_000_000_000,) * 2)
        assert options.user_presets() == {"Web": {"quality": value}}
