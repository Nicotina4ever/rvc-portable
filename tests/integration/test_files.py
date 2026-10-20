"""Test di integrazione per /api/files/dialog (Tk sempre mockato)."""

from __future__ import annotations

import sys
import types

import pytest

from app.api.routes import files as files_routes

pytestmark = pytest.mark.integration


def _patch_dialog(monkeypatch, result=None, error=None):
    calls = []

    def fake_dialog(kind, title, initial):
        calls.append({"kind": kind, "title": title, "initial": initial})
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(files_routes, "_open_dialog", fake_dialog)
    return calls


def test_dialog_returns_selected_path(client, auth, tmp_path, monkeypatch):
    selected = str(tmp_path / "voce.pth")
    calls = _patch_dialog(
        monkeypatch, result={"path": selected, "canceled": False}
    )
    response = client.post(
        "/api/files/dialog",
        json={"kind": "model", "title": "Scegli modello", "initial": str(tmp_path)},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"path": selected, "canceled": False}
    assert calls == [
        {"kind": "model", "title": "Scegli modello", "initial": str(tmp_path)}
    ]


def test_dialog_canceled(client, auth, monkeypatch):
    _patch_dialog(monkeypatch, result={"path": None, "canceled": True})
    response = client.post(
        "/api/files/dialog", json={"kind": "directory"}, headers=auth
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"path": None, "canceled": True}


def test_dialog_defaults_kind_and_title(client, auth, monkeypatch):
    calls = _patch_dialog(monkeypatch, result={"path": None, "canceled": True})
    response = client.post("/api/files/dialog", json={}, headers=auth)
    assert response.status_code == 200, response.text
    assert calls[0]["kind"] == "directory"
    assert calls[0]["title"] == files_routes.DEFAULT_TITLES["directory"]
    assert calls[0]["initial"] == ""


def test_dialog_headless_returns_503_with_hint(client, auth, monkeypatch):
    _patch_dialog(
        monkeypatch, error=files_routes.DialogUnavailable("no display: DISPLAY mancante")
    )
    response = client.post("/api/files/dialog", json={"kind": "audio"}, headers=auth)
    assert response.status_code == 503, response.text
    payload = response.json()["error"]
    assert payload["code"] == "validation_error"
    assert "usa il percorso manuale" in payload["message"]
    assert "DISPLAY" in payload["detail"]


def test_dialog_invalid_kind(client, auth, monkeypatch):
    _patch_dialog(monkeypatch, result={"path": None, "canceled": True})
    response = client.post("/api/files/dialog", json={"kind": "video"}, headers=auth)
    assert response.status_code == 422, response.text
    payload = response.json()["error"]
    assert payload["code"] == "validation_error"
    assert payload["params"]["allowed"] == list(files_routes.DIALOG_KINDS)


def test_dialog_filetypes_cover_expected_extensions():
    def patterns(kind):
        return " ".join(pattern for _, pattern in files_routes.FILETYPES[kind])

    assert "*.pth" in patterns("model")
    assert "*.index" in patterns("index")
    for extension in ("*.wav", "*.mp3", "*.ogg", "*.m4a", "*.flac"):
        assert extension in patterns("audio")
    assert "*.json" in patterns("config")
    assert "directory" not in files_routes.FILETYPES


def test_dialog_initial_path_helpers(tmp_path):
    model = tmp_path / "voce.pth"
    model.write_bytes(b"x")
    directory = tmp_path / "cartella"
    directory.mkdir()
    assert files_routes._initial_kwargs("") == {}
    assert files_routes._initial_kwargs(str(directory)) == {
        "initialdir": str(directory)
    }
    kwargs = files_routes._initial_kwargs(str(model))
    assert kwargs["initialdir"] == str(tmp_path)
    assert kwargs["initialfile"] == "voce.pth"
    assert files_routes._initial_kwargs(str(tmp_path / "fantasma")) == {}


def test_dialog_requires_token(client):
    response = client.post("/api/files/dialog", json={"kind": "directory"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# Ciclo di vita Tk (tkinter finto, nessuna finestra reale)
# ---------------------------------------------------------------------------


class FakeRoot:
    instances = []

    def __init__(self):
        self.withdrawn = False
        self.destroyed = False
        self.attributes_seen = []
        FakeRoot.instances.append(self)

    def withdraw(self):
        self.withdrawn = True

    def attributes(self, name, value):
        self.attributes_seen.append((name, value))

    def destroy(self):
        self.destroyed = True


def _install_fake_tk(monkeypatch, *, open_result="", open_error=None):
    calls = {}

    def askopenfilename(**kwargs):
        calls["open"] = kwargs
        if open_error is not None:
            raise open_error
        return open_result

    def askdirectory(**kwargs):
        calls["directory"] = kwargs
        return open_result

    fake_filedialog = types.ModuleType("tkinter.filedialog")
    fake_filedialog.askopenfilename = askopenfilename
    fake_filedialog.askdirectory = askdirectory
    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = FakeRoot
    fake_tk.filedialog = fake_filedialog
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog)
    FakeRoot.instances = []
    return calls


def test_open_dialog_creates_and_destroys_tk(monkeypatch, tmp_path):
    selected = str(tmp_path / "voce.pth")
    calls = _install_fake_tk(monkeypatch, open_result=selected)
    result = files_routes._open_dialog("model", "Scegli modello", str(tmp_path))
    assert result == {"path": selected, "canceled": False}
    root = FakeRoot.instances[-1]
    assert root.withdrawn is True
    assert root.destroyed is True
    assert ("-topmost", True) in root.attributes_seen
    assert calls["open"]["title"] == "Scegli modello"
    assert calls["open"]["initialdir"] == str(tmp_path)
    filetypes = [tuple(item) for item in calls["open"]["filetypes"]]
    assert ("Modelli RVC", "*.pth") in filetypes


def test_open_dialog_directory_has_no_filetypes(monkeypatch, tmp_path):
    calls = _install_fake_tk(monkeypatch, open_result=str(tmp_path))
    result = files_routes._open_dialog("directory", "Cartella", str(tmp_path))
    assert result == {"path": str(tmp_path), "canceled": False}
    assert "filetypes" not in calls["directory"]
    assert FakeRoot.instances[-1].destroyed is True


def test_open_dialog_cancel_returns_canceled(monkeypatch, tmp_path):
    _install_fake_tk(monkeypatch, open_result="")
    result = files_routes._open_dialog("audio", "Audio", "")
    assert result == {"path": None, "canceled": True}
    assert FakeRoot.instances[-1].destroyed is True


def test_open_dialog_failure_destroys_root_and_maps(monkeypatch):
    _install_fake_tk(monkeypatch, open_error=RuntimeError("Tk rotto"))
    with pytest.raises(files_routes.DialogUnavailable):
        files_routes._open_dialog("config", "Config", "")
    assert FakeRoot.instances[-1].destroyed is True


def test_dialog_headless_real_fallback(client, auth, monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    response = client.post("/api/files/dialog", json={"kind": "index"}, headers=auth)
    assert response.status_code == 503, response.text
    payload = response.json()["error"]
    assert payload["code"] == "validation_error"
    assert "usa il percorso manuale" in payload["message"]


