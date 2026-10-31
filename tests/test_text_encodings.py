"""Text files saved in other encodings: Notepad's "Unicode" (UTF-16 with a BOM), UTF-8 with a BOM,
and old Windows files (cp1252). Every reader of text goes through textfile.decode."""

import json

import pytest

from convertall import convert
from convertall.converters import maps, models, notebooks, subtitles

ENCODINGS = [("utf-16", "utf-16"), ("utf-16-be", "utf-16-be-bom"), ("utf-8-sig", "utf-8-bom"),
             ("utf-8", "utf-8"), ("cp1252", "cp1252")]


def _write(path, text: str, encoding: str) -> None:
    data = text.encode(encoding)
    if encoding == "utf-16-be":
        data = b"\xfe\xff" + data  # Python's utf-16-be writes no BOM; Notepad's "Unicode big endian" does
    path.write_bytes(data)


SRT = "1\n00:00:01,000 --> 00:00:02,500\nCafé déjà vu\n\n2\n00:00:03,000 --> 00:00:04,000\nÉtè à Noël\n"


@pytest.mark.parametrize("encoding", [e for e, _ in ENCODINGS], ids=[i for _, i in ENCODINGS])
@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
def test_subtitles_in_any_encoding(tmp_path, encoding, fmt):
    src = tmp_path / "plain.srt"
    src.write_text(SRT, encoding="utf-8")
    if fmt != "srt":
        src = convert(src, fmt, out_dir=tmp_path / "made")
    text = src.read_text(encoding="utf-8-sig")
    encoded = tmp_path / f"encoded.{fmt}"
    _write(encoded, text, encoding)
    subs = subtitles._load(encoded, fmt)
    assert [e.plaintext for e in subs] == ["Café déjà vu", "Étè à Noël"]


GEOJSON = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Zürich Hauptbahnhof"},
     "geometry": {"type": "Point", "coordinates": [8.5402, 47.3782]}}]}


@pytest.mark.parametrize("encoding", [e for e, _ in ENCODINGS], ids=[i for _, i in ENCODINGS])
def test_geojson_in_any_encoding(tmp_path, encoding):
    src = tmp_path / "places.geojson"
    _write(src, json.dumps(GEOJSON, ensure_ascii=False), encoding)
    m = maps.read_map(src, "geojson")
    assert [p.name for p in m.points] == ["Zürich Hauptbahnhof"]


NOTEBOOK = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
    {"cell_type": "markdown", "metadata": {}, "source": ["# Résumé\n", "Grüße"]}]}


@pytest.mark.parametrize("encoding", [e for e, _ in ENCODINGS], ids=[i for _, i in ENCODINGS])
def test_notebooks_in_any_encoding(tmp_path, encoding):
    src = tmp_path / "nb.ipynb"
    _write(src, json.dumps(NOTEBOOK, ensure_ascii=False), encoding)
    cells, _ = notebooks._load(src)
    assert "".join(cells[0]["source"]) == "# Résumé\nGrüße"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "cp1252"])
def test_gltf_rig_check_reads_any_encoding(tmp_path, encoding):
    doc = {"asset": {"version": "2.0", "generator": "Ünïcode"}, "skins": [{"joints": [0]}], "nodes": [{}]}
    src = tmp_path / "rig.gltf"
    _write(src, json.dumps(doc, ensure_ascii=False), encoding)
    assert models._deforms(src, "gltf")
