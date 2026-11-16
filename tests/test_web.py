import json

import pytest
from fastapi.testclient import TestClient

from conftest import FakeLLM, InProcessMcp
from csv_intelligence.web.app import create_app, effective_privacy_mode

BY_REGION = json.dumps({"sql": "SELECT region, SUM(revenue) AS total FROM self GROUP BY region"})
PEOPLE_CSV = b"Customer Name,email,amount\nAnn Lee,ann@example.com,10\nBo Chan,bo@example.org,20\n"


def client_for(*replies: str, llm_factory=None) -> TestClient:
    llm = FakeLLM(*replies)
    return TestClient(create_app(mcp=InProcessMcp(), llm_factory=llm_factory or (lambda: llm)))


def events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_status_without_a_dataset(upload_dir):
    with client_for() as client:
        status = client.get("/api/status").json()
    assert status == {
        "mcp_connected": True,
        "privacy_mode": "standard",
        "privacy_mode_locked": False,
        "dataset": None,
    }


def test_upload_review_then_ingest_with_masking(upload_dir):
    with client_for() as client:
        review = client.post("/api/upload", files={"file": ("people.csv", PEOPLE_CSV, "text/csv")}).json()
        assert review["row_count"] == 2
        assert {(f["column"], f["kind"]) for f in review["pii"]} == {
            ("Customer Name", "name"),
            ("email", "email"),
        }
        assert review["preview"][0] == ["Ann Lee", "ann@example.com", "10"]
        assert list(review["timings_ms"]) == ["read_csv", "pii_scan", "total"]

        profile = client.post(
            "/api/ingest",
            json={
                "upload_id": review["upload_id"],
                "choices": {"email": {"mask": True}, "Customer Name": {"rename": "buyer"}},
            },
        ).json()
        assert [c["name"] for c in profile["columns"]] == ["buyer", "email", "amount"]
        assert list(profile["timings_ms"]) == ["read_csv", "privacy", "write_parquet", "profile", "total"]
        assert client.get("/api/status").json()["dataset"]["dataset"] == "people"
    assert not (upload_dir / ".staging").exists()


def test_ingest_twice_or_with_a_bad_id_is_404(upload_dir):
    with client_for() as client:
        review = client.post("/api/upload", files={"file": ("a.csv", b"a\n1\n", "text/csv")}).json()
        assert client.post("/api/ingest", json={"upload_id": review["upload_id"]}).status_code == 200
        assert client.post("/api/ingest", json={"upload_id": review["upload_id"]}).status_code == 404
        assert client.post("/api/ingest", json={"upload_id": "../../etc"}).status_code == 404


def test_unreadable_upload_is_400(upload_dir):
    with client_for() as client:
        response = client.post("/api/upload", files={"file": ("bad.csv", b"a,b\n1\n2,3,4,5\n", "text/csv")})
    assert response.status_code == 400 and "Could not read bad.csv" in response.json()["detail"]


def test_chat_streams_table_before_insights(sales_dataset):
    with client_for(BY_REGION, "South leads.") as client:
        stream = events(client.post("/api/chat", json={"question": "Revenue by region?"}))
    types = [event["type"] for event in stream]
    assert types[:3] == ["sql", "table", "privacy"] and types[-1] == "done"
    assert "insight" in types
    assert stream[-1]["audit"][0]["step"] == "write_sql"


def test_chat_strict_mode_from_the_browser(sales_dataset):
    with client_for(BY_REGION) as client:
        stream = events(client.post("/api/chat", json={"question": "q", "privacy_mode": "strict"}))
    assert stream[2]["type"] == "privacy" and stream[2]["results_sent"] is False
    assert [event["type"] for event in stream][-2:] == ["summary", "done"]


def test_chat_reports_setup_errors_as_an_event(sales_dataset):
    def no_key():
        raise RuntimeError("Environment variable LLM_API_KEY is not set. See .env.example.")

    with client_for(llm_factory=no_key) as client:
        stream = events(client.post("/api/chat", json={"question": "q"}))
    assert stream == [
        {
            "type": "error",
            "message": "Environment variable LLM_API_KEY is not set. See .env.example.",
            "audit": [],
            "timings_ms": {},
        }
    ]


def test_dashboard_returns_rendered_html_and_audit(sales_dataset):
    plan = {
        "title": "Overview",
        "metrics": [{"title": "Orders", "chart": "kpi", "sql": "SELECT COUNT(*) AS n FROM self"}],
    }
    with client_for(json.dumps(plan)) as client:
        body = client.post("/api/dashboard", json={"question": "overview"}).json()
    assert "<title>Overview</title>" in body["html"] and ">120<" in body["html"]
    assert body["audit"][0]["step"] == "plan_dashboard"
    assert list(body["timings_ms"]) == ["load_dataset", "plan", "queries", "build_spec", "render", "total"]
    assert body["metric_timings"][0]["title"] == "Orders" and body["metric_timings"][0]["ok"] is True


def test_dashboard_without_a_dataset_is_400(upload_dir):
    with client_for("{}") as client:
        response = client.post("/api/dashboard", json={"question": "x"})
    assert response.status_code == 400 and "No file is loaded" in response.json()["detail"]


def test_remove_dataset(sales_dataset, upload_dir):
    with client_for() as client:
        assert client.delete("/api/dataset").json() == {"removed": True}
        assert client.get("/api/status").json()["dataset"] is None


@pytest.mark.parametrize(
    "requested, configured, expected",
    [(None, "standard", "standard"), ("strict", "standard", "strict"), ("standard", "strict", "strict")],
)
def test_strict_configuration_cannot_be_relaxed_from_the_browser(requested, configured, expected):
    assert effective_privacy_mode(requested, configured) == expected


def test_page_and_assets_are_served_locally(upload_dir):
    with client_for() as client:
        page = client.get("/")
        assert page.headers["content-type"].startswith("text/html")
        for asset in ("/static/app.js", "/static/app.css"):
            assert asset in page.text and client.get(asset).status_code == 200
    assert "https://" not in page.text  # no CDN: the UI works offline


def test_status_answers_fast_when_the_mcp_server_is_down(upload_dir, monkeypatch):
    import socket
    import time

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{dead_port}/mcp")

    with TestClient(create_app(llm_factory=FakeLLM)) as client:  # the real McpClient, nothing listening
        started = time.monotonic()
        status = client.get("/api/status").json()
        elapsed = time.monotonic() - started
    assert status["mcp_connected"] is False and status["dataset"] is None
    assert elapsed < 3
