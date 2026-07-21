from switchgear.career.bank import load_bank
from switchgear.resume.render import extract_jd_terms, keyword_report, render_html


def _bank(tmp_path):
    (tmp_path / "profile.yaml").write_text(
        "name: Jane Doe\n"
        "email: jane@example.com\n"
        'phone: "555-1234"\n'
        "location: Remote\n"
        "links: [https://github.com/janedoe]\n"
        "headline: Software engineer\n"
        "summary: Builds reliable systems.\n"
        "education:\n"
        "  - school: Example University\n"
        "    degree: BSc Computer Science\n"
        '    year: "2020"\n'
    )
    (tmp_path / "skills.yaml").write_text(
        "skills:\n"
        "  - {name: Python, years: 5}\n"
        "  - {name: Go, years: 2}\n"
        "  - {name: Latency, years: 1}\n"
        "  - {name: Kubernetes, years: 1}\n"
    )
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "acme.yaml").write_text(
        'company: "<Evil & Co>"\n'
        "title: Senior Engineer\n"
        "start: 2022-01\n"
        "end: present\n"
        "facts:\n"
        "  - id: cut-latency\n"
        '    text: "Cut checkout p99 latency 40% by rewriting the cart service in Python"\n'
        "    skills: [python, performance]\n"
        '    metric: "40% p99 reduction"\n'
        "  - id: led-migration\n"
        '    text: "Led migration to a new billing platform"\n'
        "    skills: [python]\n"
    )
    return load_bank(str(tmp_path))


def _profile(bank, **overrides):
    profile = dict(bank.profile)
    profile.update(overrides)
    return profile


def _selection(bullets, *, company="<Evil & Co>", title="Senior Engineer", dates="2022-01 - present"):
    entry = {"bullets": bullets}
    if company is not None:
        entry["company"] = company
    if title is not None:
        entry["title"] = title
    if dates is not None:
        entry["dates"] = dates
    return {
        "summary": "A concise summary.",
        "sections": [
            {"heading": "Experience", "entries": [entry]},
        ],
    }


def _bullet(bank, fact_id, text=None):
    fact = bank.facts[fact_id]
    return {
        "fact_id": fact_id,
        "text": text,
        "source_text": fact["text"],
        "rephrased": text is not None and text.strip() != fact["text"].strip(),
    }


# ---------- render_html ----------


def test_render_html_escapes_dangerous_company_name(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration")])
    html = render_html(bank.profile, selection)
    assert "<Evil & Co>" not in html
    assert "&lt;Evil &amp; Co&gt;" in html


def test_render_html_bullet_uses_rephrased_text_when_set(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection(
        [_bullet(bank, "cut-latency", text="Reduced checkout latency by 40%")]
    )
    html = render_html(bank.profile, selection)
    assert "Reduced checkout latency by 40%" in html
    assert "Cut checkout p99 latency" not in html


def test_render_html_bullet_falls_back_to_source_text_when_text_is_none(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration", text=None)])
    html = render_html(bank.profile, selection)
    assert "Led migration to a new billing platform" in html


def test_render_html_omits_empty_profile_fields(tmp_path):
    bank = _bank(tmp_path)
    profile = _profile(bank, phone="", location="", links=[])
    selection = _selection([_bullet(bank, "led-migration")])
    html = render_html(profile, selection)
    assert "555-1234" not in html
    assert "Remote" not in html
    assert "github.com/janedoe" not in html
    assert "jane@example.com" in html
    # no dangling separators around the lone contact value
    assert "· ·" not in html
    assert "·  ·" not in html


def test_render_html_includes_full_contact_line(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration")])
    html = render_html(bank.profile, selection)
    assert "jane@example.com" in html
    assert "555-1234" in html
    assert "Remote" in html
    assert "https://github.com/janedoe" in html


def test_render_html_includes_education_section(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration")])
    html = render_html(bank.profile, selection)
    assert "Example University" in html
    assert "BSc Computer Science" in html
    assert "2020" in html


def test_render_html_includes_selection_summary(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration")])
    selection["summary"] = "A tailored summary just for this job."
    html = render_html(bank.profile, selection)
    assert "A tailored summary just for this job." in html


def test_render_html_has_no_tables_images_or_forbidden_elements(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration")])
    html = render_html(bank.profile, selection)
    lowered = html.lower()
    assert "<table" not in lowered
    assert "<img" not in lowered


def test_render_html_is_deterministic(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([_bullet(bank, "led-migration")])
    first = render_html(bank.profile, selection)
    second = render_html(bank.profile, selection)
    assert first == second


def test_render_html_renders_section_heading_and_entry_without_company(tmp_path):
    bank = _bank(tmp_path)
    selection = {
        "summary": "S",
        "sections": [
            {
                "heading": "Skills",
                "entries": [{"bullets": [_bullet(bank, "led-migration")]}],
            }
        ],
    }
    html = render_html(bank.profile, selection)
    assert "<h2>Skills</h2>" in html


# ---------- extract_jd_terms ----------


def test_extract_jd_terms_word_boundary_excludes_substring_match(tmp_path):
    bank = _bank(tmp_path)
    jd_text = "We need experience with Google Cloud."
    terms = extract_jd_terms(jd_text, bank)
    assert "Go" not in terms


def test_extract_jd_terms_matches_standalone_word(tmp_path):
    bank = _bank(tmp_path)
    jd_text = "Experience with the Go programming language is a plus."
    terms = extract_jd_terms(jd_text, bank)
    assert "Go" in terms


def test_extract_jd_terms_is_sorted_case_insensitively(tmp_path):
    bank = _bank(tmp_path)
    jd_text = "Looking for Python, Kubernetes, and Latency-sensitive systems engineers."
    terms = extract_jd_terms(jd_text, bank)
    assert terms == sorted(terms, key=str.lower)
    assert "Python" in terms
    assert "Kubernetes" in terms
    assert "Latency" in terms


def test_extract_jd_terms_matches_plus_plus_punctuation(tmp_path):
    bank = _bank(tmp_path)
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: \"C++\", years: 5}\n"
    )
    bank = load_bank(str(tmp_path))
    jd_text = "We need someone skilled in C++."
    terms = extract_jd_terms(jd_text, bank)
    assert "C++" in terms


def test_extract_jd_terms_c_sharp_matches_without_matching_plain_c(tmp_path):
    bank = _bank(tmp_path)
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: \"C#\", years: 5}\n  - {name: \"C++\", years: 5}\n"
    )
    bank = load_bank(str(tmp_path))
    jd_text = "Looking for a C# developer with plain C experience."
    terms = extract_jd_terms(jd_text, bank)
    assert "C#" in terms
    assert "C++" not in terms


def test_extract_jd_terms_dot_net_matches(tmp_path):
    bank = _bank(tmp_path)
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: \".NET\", years: 5}\n"
    )
    bank = load_bank(str(tmp_path))
    jd_text = "Experience with .NET on the backend is a plus."
    terms = extract_jd_terms(jd_text, bank)
    assert ".NET" in terms


# ---------- keyword_report ----------


def test_keyword_report_hit_via_selected_fact_skills_tag(tmp_path):
    bank = _bank(tmp_path)
    jd_text = "We need a backend engineer with Python experience."
    selection = _selection(
        [
            _bullet(bank, "cut-latency"),
            _bullet(bank, "led-migration"),
        ]
    )
    report = keyword_report(jd_text, selection, bank)
    assert "Python" in report["hit"]
    assert "Python" not in report["missed"]


def test_keyword_report_hit_via_rendered_bullet_text(tmp_path):
    bank = _bank(tmp_path)
    jd_text = "Must have experience optimizing latency in production systems."
    selection = _selection(
        [
            _bullet(bank, "cut-latency"),
            _bullet(bank, "led-migration"),
        ]
    )
    report = keyword_report(jd_text, selection, bank)
    assert "Latency" in report["hit"]


def test_keyword_report_missed_when_selection_does_not_cover_term(tmp_path):
    bank = _bank(tmp_path)
    jd_text = "Strong Kubernetes experience required."
    selection = _selection(
        [
            _bullet(bank, "cut-latency"),
            _bullet(bank, "led-migration"),
        ]
    )
    report = keyword_report(jd_text, selection, bank)
    assert "Kubernetes" in report["missed"]
    assert "Kubernetes" not in report["hit"]


def test_keyword_report_hits_via_punctuated_skill_term(tmp_path):
    bank = _bank(tmp_path)
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: \"C++\", years: 5}\n"
    )
    exp_dir = tmp_path / "experience"
    (exp_dir / "acme.yaml").write_text(
        'company: "<Evil & Co>"\n'
        "title: Senior Engineer\n"
        "start: 2022-01\n"
        "end: present\n"
        "facts:\n"
        "  - id: cpp-service\n"
        '    text: "Built a high-throughput service in C++"\n'
        "    skills: [c++]\n"
    )
    bank = load_bank(str(tmp_path))
    jd_text = "Looking for engineers with C++ experience."
    selection = _selection([_bullet(bank, "cpp-service")])
    report = keyword_report(jd_text, selection, bank)
    assert "C++" in report["hit"]
    assert "C++" not in report["missed"]


def test_keyword_report_hit_and_missed_are_disjoint(tmp_path):
    bank = _bank(tmp_path)
    jd_text = (
        "We need a backend engineer with Python experience, deep knowledge of "
        "latency optimization, and Kubernetes."
    )
    selection = _selection(
        [
            _bullet(bank, "cut-latency"),
            _bullet(bank, "led-migration"),
        ]
    )
    report = keyword_report(jd_text, selection, bank)
    assert set(report["hit"]) & set(report["missed"]) == set()
    assert set(report["hit"]) | set(report["missed"]) == set(
        extract_jd_terms(jd_text, bank)
    )
