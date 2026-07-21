from switchgear.jobs.model import (
    canonical_url,
    fuzzy_key,
    job_key,
    make_job,
    normalize_ashby,
    normalize_greenhouse,
    normalize_jsearch,
    normalize_lever,
    normalize_remoteok,
    normalize_remotive,
    strip_html,
)

CANONICAL_FIELDS = {
    "score": None,
    "rationale": None,
    "scored_at": None,
}


def _pop_first_seen(job: dict) -> float:
    first_seen = job.pop("first_seen")
    assert isinstance(first_seen, float)
    return first_seen


# --- canonical_url ---------------------------------------------------------


def test_canonical_url_lowercases_scheme_and_host_preserves_path_case():
    assert canonical_url("HTTPS://Example.COM/Jobs/SWE") == "https://example.com/Jobs/SWE"


def test_canonical_url_drops_fragment():
    assert canonical_url("https://example.com/jobs/1#section") == "https://example.com/jobs/1"


def test_canonical_url_strips_trailing_slash():
    assert canonical_url("https://example.com/jobs/1/") == "https://example.com/jobs/1"


def test_canonical_url_drops_utm_ref_source_keeps_other_params():
    url = "https://example.com/jobs/1?utm_source=x&utm_campaign=y&ref=z&source=w&foo=bar"
    assert canonical_url(url) == "https://example.com/jobs/1?foo=bar"


def test_canonical_url_variants_are_equal():
    base = "https://example.com/jobs/123"
    variant = "HTTPS://EXAMPLE.com/jobs/123/?utm_campaign=abc&ref=xyz&source=foo#section"
    assert canonical_url(base) == canonical_url(variant)


# --- job_key -----------------------------------------------------------------


def test_job_key_is_sha1_hex_of_canonical_url():
    url = "https://example.com/jobs/123"
    key = job_key(url)
    assert len(key) == 40
    assert int(key, 16) >= 0  # valid hex


def test_job_key_stable_across_url_variants():
    base = "https://example.com/jobs/123"
    variant = "HTTPS://EXAMPLE.com/jobs/123/?utm_campaign=abc&ref=xyz&source=foo#section"
    assert job_key(base) == job_key(variant)


def test_job_key_differs_for_different_urls():
    assert job_key("https://example.com/jobs/1") != job_key("https://example.com/jobs/2")


# --- fuzzy_key -----------------------------------------------------------------


def test_fuzzy_key_ignores_case_and_punctuation():
    a = fuzzy_key("Acme, Inc.", "Senior SWE!")
    b = fuzzy_key("acme inc", "senior swe")
    assert a == b


def test_fuzzy_key_differs_for_different_titles():
    assert fuzzy_key("Acme", "Engineer") != fuzzy_key("Acme", "Manager")


# --- strip_html -----------------------------------------------------------------


def test_strip_html_removes_tags_unescapes_and_collapses_whitespace():
    raw = "<p>Hello &amp; welcome to <b>Acme</b>!</p>\n\n   Extra   spaces."
    assert strip_html(raw) == "Hello & welcome to Acme ! Extra spaces."


def test_strip_html_empty_string():
    assert strip_html("") == ""


# --- make_job -----------------------------------------------------------------


def test_make_job_builds_canonical_schema():
    job = make_job(
        url="https://example.com/jobs/1",
        title="Software Engineer",
        company="Acme",
        location="Remote",
        remote=True,
        comp="$100k",
        description="<p>Build things.</p>",
        source="greenhouse",
    )
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://example.com/jobs/1"),
        "url": "https://example.com/jobs/1",
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Remote",
        "remote": True,
        "comp": "$100k",
        "description": "Build things.",
        "source": "greenhouse",
        **CANONICAL_FIELDS,
    }


def test_make_job_defaults():
    job = make_job(
        url="https://example.com/jobs/2",
        title="Analyst",
        company="Acme",
        source="lever",
    )
    _pop_first_seen(job)
    assert job["location"] == ""
    assert job["remote"] is False
    assert job["comp"] == ""
    assert job["description"] == ""


def test_make_job_truncates_description_after_strip_html():
    long_html = "<p>" + ("x" * 20050) + "</p>"
    job = make_job(
        url="https://example.com/jobs/3",
        title="Engineer",
        company="Acme",
        description=long_html,
        source="lever",
    )
    assert len(job["description"]) == 20_000
    assert job["description"] == "x" * 20_000


# --- normalize_greenhouse -----------------------------------------------------


def test_normalize_greenhouse():
    data = {
        "jobs": [
            {
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "title": "Software Engineer",
                "location": {"name": "Remote - US"},
                "content": "<p>Build cool stuff.</p>",
            },
            {"title": "Missing URL"},
            {"absolute_url": "https://boards.greenhouse.io/acme/jobs/999"},
        ]
    }
    result = normalize_greenhouse(data, "Acme")
    assert len(result) == 1
    job = result[0]
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://boards.greenhouse.io/acme/jobs/123"),
        "url": "https://boards.greenhouse.io/acme/jobs/123",
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Remote - US",
        "remote": False,
        "comp": "",
        "description": "Build cool stuff.",
        "source": "greenhouse",
        **CANONICAL_FIELDS,
    }


# --- normalize_lever -----------------------------------------------------------


def test_normalize_lever():
    data = [
        {
            "hostedUrl": "https://jobs.lever.co/acme/abc123",
            "text": "Backend Engineer",
            "categories": {"location": "San Francisco, Remote", "commitment": "Full-time"},
            "descriptionPlain": "Join our team.\nWe build things.",
            "country": "US",
        },
        {"text": "No URL"},
        {"hostedUrl": "https://jobs.lever.co/acme/999"},
    ]
    result = normalize_lever(data, "Acme")
    assert len(result) == 1
    job = result[0]
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://jobs.lever.co/acme/abc123"),
        "url": "https://jobs.lever.co/acme/abc123",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "San Francisco, Remote",
        "remote": True,
        "comp": "",
        "description": "Join our team. We build things.",
        "source": "lever",
        **CANONICAL_FIELDS,
    }


def test_normalize_lever_remote_detection_case_insensitive():
    data = [
        {
            "hostedUrl": "https://jobs.lever.co/acme/xyz",
            "text": "Support Engineer",
            "categories": {"location": "REMOTE"},
            "descriptionPlain": "Help customers.",
        }
    ]
    result = normalize_lever(data, "Acme")
    assert result[0]["remote"] is True


# --- normalize_ashby -----------------------------------------------------------


def test_normalize_ashby():
    data = {
        "jobs": [
            {
                "title": "Product Manager",
                "location": "New York, NY",
                "jobUrl": "https://jobs.ashbyhq.com/acme/pm-123",
                "isRemote": False,
                "descriptionHtml": "<div>Own the roadmap.</div>",
                "compensation": "$150k-$180k",
            },
            {"location": "Remote", "isRemote": True},
            {"title": "Has title no url", "isRemote": True},
        ]
    }
    result = normalize_ashby(data, "Acme")
    assert len(result) == 1
    job = result[0]
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://jobs.ashbyhq.com/acme/pm-123"),
        "url": "https://jobs.ashbyhq.com/acme/pm-123",
        "title": "Product Manager",
        "company": "Acme",
        "location": "New York, NY",
        "remote": False,
        "comp": "$150k-$180k",
        "description": "Own the roadmap.",
        "source": "ashby",
        **CANONICAL_FIELDS,
    }


# --- normalize_remotive -----------------------------------------------------------


def test_normalize_remotive():
    data = {
        "jobs": [
            {
                "url": "https://remotive.com/remote-jobs/123",
                "title": "Data Scientist",
                "company_name": "Remoteco",
                "candidate_required_location": "Worldwide",
                "salary": "$100k-$130k",
                "description": "<p>Crunch numbers.</p>",
            },
            {"title": "No url"},
            {"url": "https://remotive.com/remote-jobs/999"},
        ]
    }
    result = normalize_remotive(data)
    assert len(result) == 1
    job = result[0]
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://remotive.com/remote-jobs/123"),
        "url": "https://remotive.com/remote-jobs/123",
        "title": "Data Scientist",
        "company": "Remoteco",
        "location": "Worldwide",
        "remote": True,
        "comp": "$100k-$130k",
        "description": "Crunch numbers.",
        "source": "remotive",
        **CANONICAL_FIELDS,
    }


# --- normalize_remoteok -----------------------------------------------------------


def test_normalize_remoteok_skips_metadata_head_and_missing_fields():
    data = [
        {"legal": "notice", "id": "meta"},
        {
            "position": "Frontend Engineer",
            "company": "Okco",
            "location": "Anywhere",
            "url": "https://remoteok.com/remote-jobs/123",
            "description": "<p>Build UI.</p>",
        },
        {"company": "No position field"},
        {"position": "No URL"},
    ]
    result = normalize_remoteok(data)
    assert len(result) == 1
    job = result[0]
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://remoteok.com/remote-jobs/123"),
        "url": "https://remoteok.com/remote-jobs/123",
        "title": "Frontend Engineer",
        "company": "Okco",
        "location": "Anywhere",
        "remote": True,
        "comp": "",
        "description": "Build UI.",
        "source": "remoteok",
        **CANONICAL_FIELDS,
    }


# --- normalize_jsearch -----------------------------------------------------------


def test_normalize_jsearch():
    data = {
        "data": [
            {
                "job_title": "DevOps Engineer",
                "employer_name": "Cloudify",
                "job_city": "Austin",
                "job_country": "US",
                "job_is_remote": True,
                "job_apply_link": "https://jsearch.example.com/jobs/123",
                "job_description": "<p>Automate everything.</p>",
                "job_min_salary": 120000,
                "job_max_salary": 150000,
            },
            {"employer_name": "No title"},
            {"job_title": "No URL", "employer_name": "X"},
        ]
    }
    result = normalize_jsearch(data)
    assert len(result) == 1
    job = result[0]
    _pop_first_seen(job)
    assert job == {
        "key": job_key("https://jsearch.example.com/jobs/123"),
        "url": "https://jsearch.example.com/jobs/123",
        "title": "DevOps Engineer",
        "company": "Cloudify",
        "location": "Austin, US",
        "remote": True,
        "comp": "120000-150000",
        "description": "Automate everything.",
        "source": "jsearch",
        **CANONICAL_FIELDS,
    }


def test_normalize_jsearch_missing_one_salary_yields_empty_comp():
    data = {
        "data": [
            {
                "job_title": "Analyst",
                "employer_name": "Cloudify",
                "job_apply_link": "https://jsearch.example.com/jobs/456",
                "job_description": "",
                "job_min_salary": 90000,
            }
        ]
    }
    result = normalize_jsearch(data)
    assert result[0]["comp"] == ""
    assert result[0]["location"] == ""
    assert result[0]["remote"] is False
