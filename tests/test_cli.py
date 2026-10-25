from convertall.cli import main


def test_list(png, capsys):
    assert main([str(png), "--list"]) == 0
    out = capsys.readouterr().out
    assert "Image" in out and "jpg" in out and "Archive" in out


def test_convert_and_wildcards(png, tmp_path, capsys):
    (tmp_path / "second.png").write_bytes(png.read_bytes())
    assert main([str(tmp_path / "*.png"), "--to", "jpeg", "-o", str(tmp_path / "out")]) == 0
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["pic.jpg", "second.jpg"]


def test_extract(png, tmp_path):
    assert main([str(png), "--to", "zip"]) == 0
    assert main([str(tmp_path / "pic.zip"), "--extract", "-o", str(tmp_path / "x")]) == 0
    assert (tmp_path / "x" / "pic.png").exists()


def test_missing_engine_without_tty_does_not_install(tmp_path, without_engine, monkeypatch, capsys):
    without_engine("ffmpeg")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    assert main([str(wav), "--to", "mp3"]) == 1  # the autouse fixture fails the test if install runs
    assert "-y" in capsys.readouterr().err


def test_bad_input(tmp_path, capsys):
    assert main([str(tmp_path / "nope.png"), "--to", "jpg"]) == 2
    f = tmp_path / "song.mp3"
    f.write_bytes(b"")
    assert main([str(f), "--to", "docx"]) == 1
    assert "Can't convert MP3 to DOCX" in capsys.readouterr().err
