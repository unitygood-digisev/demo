import base64
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcedraft import web
from sourcedraft.auth import Authenticator, check_password, hash_password
from sourcedraft.pipeline import ReplayLLM

EX = Path(__file__).resolve().parent.parent / "examples" / "q12_training"


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


@pytest.fixture
def client(tmp_path):
    web.app.state.work_dir = tmp_path
    web.app.state.auth = Authenticator({"amy": hash_password("correct horse", iterations=1000)})
    web.app.state.allow_no_auth = False
    web.app.state.llm_factory = lambda: ReplayLLM(
        json.loads((EX / "reference_step1.json").read_text(encoding="utf-8")),
        {m: (EX / f"reference_draft_{m}.md").read_text(encoding="utf-8") for m in ("internal", "client")})
    with TestClient(web.app) as c:
        yield c


def _wait(client, url, headers):
    for _ in range(50):
        r = client.get(url, headers=headers)
        if "產出中" not in r.text and "排隊中" not in r.text:
            return r
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_password_hash():
    h = hash_password("abc12345678", iterations=1000)
    assert check_password("abc12345678", h) and not check_password("wrong", h)


def test_login_required(client):
    assert client.get("/").status_code == 401
    assert client.get("/", headers=_basic("amy", "wrong")).status_code == 401
    assert client.get("/", headers=_basic("amy", "correct horse")).status_code == 200
    assert client.get("/healthz").status_code == 200


def test_no_accounts_refuses(client):
    web.app.state.auth = Authenticator({})
    assert client.get("/").status_code == 503


def test_upload_runs_as_job(client, tmp_path):
    h = _basic("amy", "correct horse")
    data = json.loads((EX / "input.json").read_text(encoding="utf-8"))
    files = [("past", ("past.md", data["past_year_final_section"].encode(), "text/markdown")),
             ("survey", ("survey.txt", data["current_year_survey_data"].encode(), "text/plain"))]
    r = client.post("/run", headers=h, files=files, follow_redirects=False,
                    data={"client": "範例", "year": "2025", "chapter": "3.2", "mode": "both",
                          "instructions": data["special_instructions"]})
    assert r.status_code == 303
    url = r.headers["location"]
    page = _wait(client, url, h)
    assert "internal 版" in page.text and "client 版" in page.text and "amy" in page.text
    job = url.rsplit("/", 1)[1]
    meta = json.loads((tmp_path / job / "job.json").read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    docx = meta["drafts"][0]["files"]["docx"]
    assert client.get(f"/files/{job}/{docx}", headers=h).status_code == 200
    assert client.get(f"/files/{job}/..%2Fjob.json", headers=h).status_code == 404
    assert "範例" in client.get("/", headers=h).text  # shows in shared history


def test_failed_job_is_reported(client):
    h = _basic("amy", "correct horse")

    class Boom:
        def extract(self, *a):
            from sourcedraft.llm import LLMError
            raise LLMError("找不到 Claude API 憑證")

    web.app.state.llm_factory = Boom
    files = [("past", ("p.md", b"x", "text/markdown")), ("survey", ("s.md", b"y", "text/markdown"))]
    r = client.post("/run", headers=h, files=files, follow_redirects=False,
                    data={"client": "a", "year": "1", "chapter": "c", "mode": "internal"})
    page = _wait(client, r.headers["location"], h)
    assert "產出失敗" in page.text and "憑證" in page.text
