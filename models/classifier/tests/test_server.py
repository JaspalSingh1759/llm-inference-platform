import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server

HERE = Path(__file__).parent / "fixtures"   # the B2 model, for tests only (not in the image)


def client_for(model_dir, monkeypatch):
    # The model is loaded at startup from server.MODEL_DIR (reloading the module would
    # register the Prometheus metrics twice).
    monkeypatch.setattr(server, "MODEL_DIR", Path(model_dir))
    return TestClient(server.app)


def test_classifies_a_claim(monkeypatch):
    with client_for(HERE, monkeypatch) as c:
        assert c.get("/readyz").status_code == 200
        r = c.post("/v1/classify", json={"texts": ["I was charged twice at BestElectro for $49.99"]})
        assert r.status_code == 200
        assert r.json()["predictions"][0]["label"] == "duplicate_charge"


def test_tampered_model_is_refused(monkeypatch, tmp_path):
    shutil.copy(HERE / "metadata.json", tmp_path)
    shutil.copy(HERE / "model.joblib", tmp_path)
    with open(tmp_path / "model.joblib", "ab") as f:
        f.write(b"tampered")
    with client_for(tmp_path, monkeypatch) as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert "checksum mismatch" in r.json()["detail"]
        assert c.post("/v1/classify", json={"texts": ["x"]}).status_code == 503


def test_unsupported_framework_is_refused(monkeypatch, tmp_path):
    shutil.copy(HERE / "model.joblib", tmp_path)
    metadata = json.loads((HERE / "metadata.json").read_text())
    (tmp_path / "metadata.json").write_text(json.dumps({**metadata, "framework": "pytorch"}))
    with client_for(tmp_path, monkeypatch) as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert "not supported" in r.json()["detail"]


@pytest.mark.parametrize("body", [{"texts": []}, {}])
def test_rejects_bad_input(monkeypatch, body):
    with client_for(HERE, monkeypatch) as c:
        assert c.post("/v1/classify", json=body).status_code == 422
