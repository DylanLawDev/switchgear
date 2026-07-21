from switchgear.prompts import system_prompt

# 1751328000.0 == 2025-07-01T00:00:00Z — pins the gmtime date formatting.
JULY_1 = 1751328000.0


def test_prompt_lists_active_skills():
    p = system_prompt("me@example.com", skills=[
        {"name": "job-search", "description": "Find jobs"}])
    assert "## Skills" in p
    assert "- job-search: Find jobs" in p
    assert "read_skill" in p


def test_prompt_without_skills_has_no_skill_section():
    assert "## Skills" not in system_prompt("me@example.com")


def test_prompt_carries_resource_subagent_guidance():
    # Phase 1 coverage, preserved through this file's replacement.
    p = system_prompt("me@example.com")
    assert "curated data banks" in p
    assert "subagent" in p
    assert "me@example.com" in p


def test_prompt_renders_core_memories_section():
    p = system_prompt("me@example.com", core_memories="- Always sign off with -D")
    assert "## Standing instructions (memories)" in p
    assert "- Always sign off with -D" in p


def test_prompt_renders_recalled_section_with_save_dates():
    p = system_prompt("me@example.com", recalled=[
        {"text": "The dog is named Biscuit", "created_at": JULY_1}])
    assert "## Possibly relevant memories" in p
    assert "ignore any that don't apply" in p
    assert "- The dog is named Biscuit (saved 2025-07-01)" in p


def test_prompt_without_memories_has_neither_memory_header():
    p = system_prompt("me@example.com")
    assert "## Standing instructions (memories)" not in p
    assert "## Possibly relevant memories" not in p


def test_empty_recalled_list_renders_no_header():
    p = system_prompt("me@example.com", core_memories="", recalled=[])
    assert "## Standing instructions (memories)" not in p
    assert "## Possibly relevant memories" not in p


def test_base_carries_the_save_memory_refinement_clause():
    assert "call save_memory before finishing your reply." in system_prompt("me@example.com")


def test_sections_ordered_skills_then_core_then_recalled():
    p = system_prompt("me@example.com",
                      skills=[{"name": "s", "description": "d"}],
                      core_memories="- core rule",
                      recalled=[{"text": "a fact", "created_at": JULY_1}])
    assert (p.index("## Skills")
            < p.index("## Standing instructions (memories)")
            < p.index("## Possibly relevant memories"))


def test_base_swaps_owner_only_email_rule_for_channel_clause():
    p = system_prompt("me@example.com")
    assert "Never email anyone but your owner." not in p
    assert "Email your owner freely via send_email." in p
    assert "channel_send functions" in p
