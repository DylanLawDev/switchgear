import json

import respx

from switchgear.config import Settings
from switchgear.gateway import Gateway
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.http_fetch import make_http_fetch_tool
from switchgear.tools.llm_tool import make_llm_tool
from switchgear.tools.storage_tool import make_storage_tool


@respx.mock
async def test_http_fetch_json():
    respx.get("https://api.test/x").respond(json={"ok": 1})
    out = await make_http_fetch_tool().handler(url="https://api.test/x")
    assert out["status"] == 200 and out["body"] == {"ok": 1}


@respx.mock
async def test_http_fetch_caps_oversized_json():
    from switchgear.tools.http_fetch import MAX_BODY

    big = '{"data": "' + "x" * MAX_BODY + '"}'
    respx.get("https://api.test/big").respond(
        200, content=big, headers={"content-type": "application/json"})
    out = await make_http_fetch_tool().handler(url="https://api.test/big")
    assert out["truncated"] is True
    assert isinstance(out["body"], str) and len(out["body"]) == MAX_BODY


async def test_http_fetch_blocks_gcp_metadata_hostname():
    out = await make_http_fetch_tool().handler(url="http://metadata.google.internal/x")
    assert out == {"error": "blocked host"}


async def test_http_fetch_blocks_metadata_goog_hostname():
    out = await make_http_fetch_tool().handler(url="http://metadata.goog/x")
    assert out == {"error": "blocked host"}


async def test_http_fetch_blocks_link_local_metadata_ip():
    out = await make_http_fetch_tool().handler(url="http://169.254.169.254/latest/meta-data")
    assert out == {"error": "blocked host"}


async def test_http_fetch_blocks_loopback():
    out = await make_http_fetch_tool().handler(url="http://127.0.0.1:8080/")
    assert out == {"error": "blocked host"}


async def test_http_fetch_blocks_private_range():
    out = await make_http_fetch_tool().handler(url="http://10.0.0.1/")
    assert out == {"error": "blocked host"}


@respx.mock
async def test_http_fetch_strips_sensitive_headers():
    route = respx.get("https://api.test/echo").respond(json={"ok": 1})
    out = await make_http_fetch_tool().handler(
        url="https://api.test/echo",
        headers={"Metadata-Flavor": "Google", "Authorization": "Bearer secret",
                 "X-Fine": "keep"})
    assert out["status"] == 200
    sent = route.calls.last.request.headers
    assert "metadata-flavor" not in sent
    assert "authorization" not in sent
    assert sent["x-fine"] == "keep"


async def test_storage_tool_roundtrip():
    t = make_storage_tool(MemoryStorage())
    assert await t.handler(op="put", collection="c", key="k", doc={"v": 1}) == {"ok": True}
    assert (await t.handler(op="get", collection="c", key="k"))["v"] == 1
    assert (await t.handler(op="query", collection="c", where={"v": 1}))[0]["_id"] == "k"


async def test_storage_tool_blocks_put_on_protected_collections():
    t = make_storage_tool(MemoryStorage())
    for collection in ("resources", "memories", "audit", "resource-settings",
                       "resource-pending", "skill-pending", "app-settings"):
        out = await t.handler(op="put", collection=collection, key="k", doc={"v": 1})
        assert out == {
            "error": f"collection '{collection}' is owner-managed and read-only for this tool"}


async def test_storage_tool_blocks_delete_on_protected_collections():
    storage = MemoryStorage()
    t = make_storage_tool(storage)
    await storage.put("resources", "k", {"v": 1})
    out = await t.handler(op="delete", collection="resources", key="k")
    assert out == {
        "error": "collection 'resources' is owner-managed and read-only for this tool"}
    assert await storage.get("resources", "k") == {"v": 1}


async def test_storage_tool_blocks_write_on_resource_settings():
    storage = MemoryStorage()
    t = make_storage_tool(storage)
    out = await t.handler(op="put", collection="resource-settings", key="resources",
                          doc={"write_mode": "full"})
    assert out == {"error": "collection 'resource-settings' is owner-managed and "
                             "read-only for this tool"}
    assert await storage.get("resource-settings", "resources") is None

    await storage.put("resource-settings", "resources", {"write_mode": "prompt"})
    out = await t.handler(op="delete", collection="resource-settings", key="resources")
    assert out == {"error": "collection 'resource-settings' is owner-managed and "
                             "read-only for this tool"}
    assert await storage.get("resource-settings", "resources") == {
        "write_mode": "prompt"}


async def test_storage_tool_blocks_write_on_resource_pending():
    storage = MemoryStorage()
    t = make_storage_tool(storage)
    out = await t.handler(op="put", collection="resource-pending", key="p1",
                          doc={"status": "approved"})
    assert out == {"error": "collection 'resource-pending' is owner-managed and "
                             "read-only for this tool"}
    assert await storage.get("resource-pending", "p1") is None

    await storage.put("resource-pending", "p1", {"status": "pending"})
    out = await t.handler(op="delete", collection="resource-pending", key="p1")
    assert out == {"error": "collection 'resource-pending' is owner-managed and "
                             "read-only for this tool"}
    assert await storage.get("resource-pending", "p1") == {"status": "pending"}


async def test_storage_tool_allows_put_on_settings_collection():
    # Regression: "settings" (distinct from "resource-settings") stays
    # agent-writable — fetch_jobs/score_jobs depend on settings/watchlist and
    # settings/career_summary.
    storage = MemoryStorage()
    t = make_storage_tool(storage)
    out = await t.handler(op="put", collection="settings", key="watchlist",
                          doc={"companies": ["acme"]})
    assert out == {"ok": True}
    assert await storage.get("settings", "watchlist") == {"companies": ["acme"]}


async def test_storage_tool_allows_reads_on_protected_collections():
    storage = MemoryStorage()
    await storage.put("resources", "k", {"v": 1})
    t = make_storage_tool(storage)
    assert (await t.handler(op="get", collection="resources", key="k"))["v"] == 1
    assert (await t.handler(op="query", collection="resources"))[0]["v"] == 1


async def test_storage_tool_strips_embedding_from_protected_get():
    storage = MemoryStorage()
    await storage.put("memories", "mem-1", {
        "key": "mem-1", "text": "prefers tabs", "status": "active",
        "embedding": [0.1, 0.2, 0.3]})
    t = make_storage_tool(storage)
    out = await t.handler(op="get", collection="memories", key="mem-1")
    assert out["text"] == "prefers tabs"
    assert "embedding" not in out


async def test_storage_tool_strips_embedding_from_protected_query():
    storage = MemoryStorage()
    await storage.put("memories", "mem-1", {
        "key": "mem-1", "text": "prefers tabs", "status": "active",
        "embedding": [0.1, 0.2, 0.3]})
    await storage.put("memories", "mem-2", {
        "key": "mem-2", "text": "inactive one", "status": "archived",
        "embedding": [0.4, 0.5, 0.6]})
    t = make_storage_tool(storage)
    out = await t.handler(op="query", collection="memories")
    assert len(out) == 2
    assert all("embedding" not in doc for doc in out)
    assert {doc["text"] for doc in out} == {"prefers tabs", "inactive one"}


async def test_storage_tool_query_unaffected_on_normal_collections():
    storage = MemoryStorage()
    await storage.put("scratch", "k", {"v": 1, "embedding": [0.1, 0.2]})
    t = make_storage_tool(storage)
    out = await t.handler(op="query", collection="scratch")
    assert out[0]["embedding"] == [0.1, 0.2]
    got = await t.handler(op="get", collection="scratch", key="k")
    assert got["embedding"] == [0.1, 0.2]


async def test_storage_tool_allows_put_on_normal_collections():
    t = make_storage_tool(MemoryStorage())
    out = await t.handler(op="put", collection="scratch", key="k", doc={"v": 1})
    assert out == {"ok": True}


async def test_storage_tool_description_mentions_protected_collections():
    t = make_storage_tool(MemoryStorage())
    assert "owner-managed" in t.description or "read-only" in t.description


@respx.mock
async def test_llm_tool_uses_tier():
    s = Settings(_env_file=None, gateway_base_url="https://gw.test/v1", model_bulk="m-bulk")
    respx.post("https://gw.test/v1/chat/completions").respond(json={
        "choices": [{"message": {"role": "assistant", "content": "out"}}],
        "usage": {"total_tokens": 5}})
    out = await make_llm_tool(Gateway(s)).handler(tier="bulk", prompt="p", system="sys")
    assert out == {"text": "out", "usage": 5}
    req = json.loads(respx.calls.last.request.content)
    assert req["model"] == "m-bulk"
    assert req["messages"][0] == {"role": "system", "content": "sys"}
