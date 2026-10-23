from starlette.testclient import TestClient

from rsna_knee_reader.server import create_http_app


def test_http_auth_and_modern_tool_call(setup_case):
    _, reader = setup_case
    with TestClient(create_http_app(reader, token="synthetic-test-only"), base_url="http://127.0.0.1") as client:
        assert client.get("/healthz").status_code == 401
        headers = {"Authorization": "Bearer synthetic-test-only",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call",
                   "Mcp-Name": "read_slices"}
        assert client.get("/healthz", headers=headers).json()["status"] == "ok"
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "read_slices", "arguments": {"case_id": "CASE0001", "series_id": "S01"},
            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                      "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                      "io.modelcontextprotocol/clientCapabilities": {}}}}
        response = client.post("/mcp", json=body, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["content"][1]["mimeType"] == "image/jpeg"
        assert "mcp-session-id" not in response.headers


def test_http_legacy_initialize_and_tools(setup_case):
    _, reader = setup_case
    with TestClient(create_http_app(reader), base_url="http://127.0.0.1") as client:
        headers = {"Accept": "application/json, text/event-stream"}
        initialized = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "legacy-test", "version": "1"}}})
        assert initialized.status_code == 200, initialized.text
        assert initialized.json()["result"]["protocolVersion"] == "2025-11-25"
        headers["MCP-Protocol-Version"] = "2025-11-25"
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2,
                                                               "method": "tools/list", "params": {}})
        assert response.status_code == 200, response.text
        assert len(response.json()["result"]["tools"]) == 3
