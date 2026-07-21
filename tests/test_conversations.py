from switchgear.conversations import ConversationStore
from switchgear.storage.memory import MemoryStorage


async def test_load_save_list():
    cs = ConversationStore(MemoryStorage())
    assert await cs.load("c1") == []
    await cs.save("c1", [{"role": "user", "content": "hi"}], title="greeting")
    assert (await cs.load("c1"))[0]["content"] == "hi"
    listing = await cs.list()
    assert listing[0]["_id"] == "c1" and listing[0]["title"] == "greeting"


async def test_save_merges_into_existing_doc_preserving_out_of_band_fields():
    # Reflection (storage layer phase 3) persists reflection_cursor and
    # last_reflection_at onto the same "conversations" document. save() must
    # merge — a blind overwrite silently resets reflection's throttle state on
    # every following chat turn.
    db = MemoryStorage()
    cs = ConversationStore(db)
    await db.put("conversations", "c1", {
        "messages": [{"role": "user", "content": "old"}],
        "title": "old title", "updated_at": 1.0,
        "reflection_cursor": 3, "last_reflection_at": 123.0})

    new_messages = [{"role": "user", "content": "old"},
                    {"role": "assistant", "content": "new"}]
    await cs.save("c1", new_messages, title="new title")

    doc = await db.get("conversations", "c1")
    # out-of-band fields survive
    assert doc["reflection_cursor"] == 3
    assert doc["last_reflection_at"] == 123.0
    # save()'s own fields are overwritten
    assert doc["messages"] == new_messages
    assert doc["title"] == "new title"
    assert doc["updated_at"] > 1.0
