"""Pure tests for the CSV row parser used by /leads/import-csv."""
from app.routers.leads import _row_to_lead_dict


def test_minimal_valid_row():
    data, err = _row_to_lead_dict({"email": "alex@example.com"})
    assert err is None
    assert data["email"] == "alex@example.com"
    # Every optional column is None when not provided
    for col in ("first_name", "last_name", "company", "domain", "title",
                "linkedin_url", "persona", "company_size", "state", "growth_stage"):
        assert data[col] is None
    assert data["tech_stack"] is None


def test_email_lowercased_and_trimmed():
    data, err = _row_to_lead_dict({"email": "  Alex@Example.COM  "})
    assert err is None
    assert data["email"] == "alex@example.com"


def test_missing_email_is_error():
    data, err = _row_to_lead_dict({"email": "", "first_name": "Alex"})
    assert data is None
    assert err == "missing email"


def test_email_completely_absent_is_error():
    data, err = _row_to_lead_dict({"first_name": "Alex"})
    assert data is None
    assert err == "missing email"


def test_invalid_email_format_is_error():
    for bad in ["bad@", "@bad.com", "no-at-sign", "spaces in@email.com", "trailing@"]:
        data, err = _row_to_lead_dict({"email": bad})
        assert data is None, f"{bad!r} should fail"
        assert err == "invalid email format", f"{bad!r}: {err}"


def test_tech_stack_split_on_commas():
    data, err = _row_to_lead_dict({
        "email": "x@y.com",
        "tech_stack": "Salesforce, HubSpot, AMS360",
    })
    assert err is None
    assert data["tech_stack"] == ["Salesforce", "HubSpot", "AMS360"]


def test_tech_stack_handles_extra_whitespace_and_empty_chunks():
    data, err = _row_to_lead_dict({
        "email": "x@y.com",
        "tech_stack": "Salesforce,  ,HubSpot ,",
    })
    assert err is None
    assert data["tech_stack"] == ["Salesforce", "HubSpot"]


def test_empty_tech_stack_is_none():
    data, err = _row_to_lead_dict({"email": "x@y.com", "tech_stack": "   "})
    assert err is None
    assert data["tech_stack"] is None


def test_empty_string_columns_become_none():
    """A blank cell shouldn't overwrite an existing field as empty string —
    callers rely on None-detection to skip the update."""
    data, err = _row_to_lead_dict({
        "email": "x@y.com",
        "first_name": "",
        "company": "  ",
    })
    assert err is None
    assert data["first_name"] is None
    assert data["company"] is None


def test_unknown_columns_silently_ignored():
    data, err = _row_to_lead_dict({
        "email": "x@y.com",
        "unrecognized_field": "garbage",
        "another_one": "foo",
    })
    assert err is None
    assert "unrecognized_field" not in data
    assert "another_one" not in data


def test_full_row_round_trip():
    data, err = _row_to_lead_dict({
        "email": "alex@acme.com",
        "first_name": "Alex",
        "last_name": "Chen",
        "company": "Acme",
        "domain": "acme.com",
        "title": "Insurance Agent",
        "linkedin_url": "https://linkedin.com/in/alex",
        "persona": "insurance_agent",
        "company_size": "11-50",
        "state": "CA",
        "growth_stage": "growth",
        "tech_stack": "Salesforce, AMS360",
    })
    assert err is None
    assert data == {
        "email": "alex@acme.com",
        "first_name": "Alex",
        "last_name": "Chen",
        "company": "Acme",
        "domain": "acme.com",
        "title": "Insurance Agent",
        "linkedin_url": "https://linkedin.com/in/alex",
        "persona": "insurance_agent",
        "company_size": "11-50",
        "state": "CA",
        "growth_stage": "growth",
        "tech_stack": ["Salesforce", "AMS360"],
    }
