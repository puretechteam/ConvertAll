import json

from convertall import engines
from convertall.cli import main
from convertall.errors import ConversionError


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


def test_view_refuses_what_isnt_a_model(png, capsys):
    assert main(["view", str(png)]) == 2
    assert "isn't a 3D model" in capsys.readouterr().err


def test_engines_install_never_crashes(monkeypatch, capsys):
    assert main(["engines", "--install", "winrar"]) == 2  # hidden: never offered
    assert "Unknown engine" in capsys.readouterr().err

    def no_winget(key, log=None):
        raise ConversionError("winget isn't available; install App Installer from the Microsoft Store")
    monkeypatch.setattr(engines, "install", no_winget)
    assert main(["engines", "--install", "pandoc"]) == 1
    assert "winget isn't available" in capsys.readouterr().err


def test_default_preset_is_a_real_preset(png, capsys):
    assert main(["presets"]) == 0
    assert "Default" in capsys.readouterr().out
    assert main([str(png), "--to", "jpg", "--preset", "default", "--plan"]) == 0
    assert "PNG → JPG" in capsys.readouterr().out  # same arrow as --json and the reports


def test_list_json(png, capsys):
    assert main([str(png), "--list", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["source_format"] == "png" and got["suggested"]
    jpg = next(t for t in got["targets"] if t["format"] == "jpg")
    assert jpg["route"] == "PNG → JPG" and jpg["category"] == "Image"


def test_piped_json_is_utf8(tmp_path):
    import subprocess
    import sys

    from PIL import Image
    src = tmp_path / "café.png"
    Image.new("RGB", (4, 4)).save(src)
    out = subprocess.run([sys.executable, "-m", "convertall", str(src), "--to", "jpg", "--plan", "--json"],
                         capture_output=True, check=True).stdout
    got = json.loads(out.decode("utf-8"))  # a script reading the pipe gets UTF-8, whatever the console uses
    assert got["source"] == str(src) and got["route"] == "PNG → JPG"


def test_install_question_keeps_json_output_clean(monkeypatch, capsys):
    from convertall import cli
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert cli._ask_install(["ffmpeg"], assume_yes=False) is False
    out, err = capsys.readouterr()
    assert out == "" and "Install it now?" in err


def test_plan_on_a_file_that_cant_be_read_says_so(png, monkeypatch, capsys):
    from convertall import cli

    def locked(path):
        raise PermissionError(13, "The file is in use by another program", str(path))
    monkeypatch.setattr(cli, "detect", locked)
    assert main([str(png), "--to", "jpg", "--plan", "--json"]) != 0
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["source"].endswith("pic.png") and "in use" in line["error"]


def test_view_without_the_window_app_says_so(tmp_path, monkeypatch, capsys):
    from convertall import cli
    model = tmp_path / "cube.obj"
    model.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    monkeypatch.setattr(cli.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli.sys, "executable", str(tmp_path / "convertall-cli.exe"))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError(a)))
    assert cli.cmd_view([model]) == 1
    assert "ConvertAll.exe" in capsys.readouterr().err


def test_a_damaged_archive_extracts_to_a_message(tmp_path, monkeypatch):
    from convertall import pipeline
    from convertall.converters import archives
    src = tmp_path / "a.zip"
    src.write_bytes(b"PK\x03\x04broken")
    monkeypatch.setattr(archives, "extract_to", lambda *a, **k: (_ for _ in ()).throw(KeyError("odd")))
    try:
        pipeline.extract(src, tmp_path / "x", "zip")
    except ConversionError as exc:
        assert "Couldn't extract a.zip" in str(exc)
    else:
        raise AssertionError("no error")
