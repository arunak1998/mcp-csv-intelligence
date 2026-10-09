from csv_intelligence.ui.uploads import clear_uploads, save_upload


def test_save_upload_keeps_a_single_file(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    save_upload("first.csv", b"a\n1\n")
    second = save_upload("second.csv", b"a\n2\n")

    assert not (tmp_path / "uploads" / "first.csv").exists()
    assert second.read_bytes() == b"a\n2\n"


def test_save_upload_strips_directories_from_the_name(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    assert save_upload("../../evil.csv", b"a\n1\n") == tmp_path / "evil.csv"


def test_clear_uploads_removes_csvs(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    save_upload("x.csv", b"a\n1\n")
    clear_uploads()
    assert list(tmp_path.glob("*.csv")) == []
