"""The profile: declared intent (#8).

Most of these are about one failure: a profile that loads with a field quietly
missing produces a filter that passes everything, and a shortlist of noise looks
exactly like a shortlist that works. So every invalid case here has to fail, and
fail with the field named -- a message saying "invalid profile" would leave the
user reading YAML by eye.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobagent.core.profile import (
    CURRENT_SCHEMA_VERSION,
    Profile,
    Weights,
    load,
    load_file,
)
from jobagent.core.profile import store as store_profile
from jobagent.core.storage import SecretLeakError, Storage
from jobagent.core.vocabulary import Seniority

EXAMPLE = Path(__file__).resolve().parents[1] / "profile.example.yaml"


def _valid() -> dict[str, object]:
    """The smallest profile that should load. Optional fields left out on purpose."""
    return {
        "target_titles": ["Data Analyst"],
        "target_seniority": ["intern"],
        "locations": ["Toronto"],
        "work_arrangements": ["hybrid"],
        "must_have_skills": ["SQL"],
        "work_authorization": {"authorized_in": ["CA"], "needs_sponsorship": False},
    }


# -- the example ---------------------------------------------------------------


def test_the_example_profile_is_valid() -> None:
    """Checked in CI so the file people copy cannot rot into a broken template."""
    profile = load_file(EXAMPLE)
    assert profile.schema_version == CURRENT_SCHEMA_VERSION
    assert profile.target_titles
    assert Seniority.INTERN in profile.target_seniority


# -- round trip ----------------------------------------------------------------


def test_a_profile_round_trips_through_storage(store: Storage) -> None:
    original = load_file(EXAMPLE)
    store_profile(store, original)
    assert load(store) == original


def test_no_profile_stored_is_a_normal_state(store: Storage) -> None:
    """Day one has no profile. That is the caller's problem to report, not a crash."""
    assert load(store) is None


def test_storing_a_profile_is_audited_without_its_contents(store: Storage) -> None:
    store_profile(store, load_file(EXAMPLE))
    entry = store.audit_entries(limit=1)[0]
    assert entry["action"] == "profile.set"
    # The audit trail records that intent changed, not what the intent is: the
    # log is itself a dossier artefact and does not need a second copy.
    assert entry["detail"] == {"schema_version": CURRENT_SCHEMA_VERSION}


# -- invalid input, each naming its field --------------------------------------


def test_a_missing_required_field_names_it() -> None:
    data = _valid()
    del data["work_authorization"]
    with pytest.raises(ValidationError, match="work_authorization"):
        Profile.model_validate(data)


def test_a_wrong_type_names_the_field() -> None:
    data = _valid()
    data["target_titles"] = "Data Analyst"  # a string, not a list
    with pytest.raises(ValidationError, match="target_titles"):
        Profile.model_validate(data)


def test_an_empty_required_list_is_refused() -> None:
    """The bug this catches: an empty filter passes everything, silently."""
    data = _valid()
    data["must_have_skills"] = []
    with pytest.raises(ValidationError, match="must_have_skills"):
        Profile.model_validate(data)


def test_a_list_of_blanks_is_as_empty_as_an_empty_list() -> None:
    data = _valid()
    data["locations"] = ["  ", ""]
    with pytest.raises(ValidationError, match="locations"):
        Profile.model_validate(data)


def test_a_negative_compensation_floor_is_refused() -> None:
    data = _valid()
    data["compensation"] = {"floor": -5, "currency": "CAD"}
    with pytest.raises(ValidationError, match="floor"):
        Profile.model_validate(data)


def test_an_undisclosed_compensation_floor_is_fine() -> None:
    """Most postings disclose nothing. A profile need not either."""
    profile = Profile.model_validate(_valid())
    assert profile.compensation.floor is None
    assert profile.compensation.currency == "CAD"


def test_an_unknown_work_arrangement_names_the_allowed_set() -> None:
    data = _valid()
    data["work_arrangements"] = ["in the metaverse"]
    with pytest.raises(ValidationError, match="work_arrangements"):
        Profile.model_validate(data)


def test_an_unknown_seniority_rung_is_refused() -> None:
    """Caught here rather than in the scorer, where it would be a silent zero."""
    data = _valid()
    data["target_seniority"] = ["seniour"]
    with pytest.raises(ValidationError, match="target_seniority"):
        Profile.model_validate(data)


def test_a_country_that_is_not_a_code_is_refused() -> None:
    data = _valid()
    data["work_authorization"] = {"authorized_in": ["Canada"], "needs_sponsorship": False}
    with pytest.raises(ValidationError, match="authorized_in"):
        Profile.model_validate(data)


# -- credentials ---------------------------------------------------------------


def test_a_credential_in_any_field_is_refused_before_storage() -> None:
    """A profile is a config file, which is where an API key gets pasted.

    The field name here is innocent on purpose: the realistic accident is a key
    landing in `narrative`, not in one helpfully called `api_key`.
    """
    data = _valid()
    data["narrative"] = "Reach me via sk-abcdefghijklmnopqrstuvwxyz012345"
    with pytest.raises((SecretLeakError, ValidationError)):
        Profile.model_validate(data)


# -- weights -------------------------------------------------------------------


def test_weights_default_sensibly_when_omitted() -> None:
    profile = Profile.model_validate(_valid())
    shares = profile.weights.normalized()
    assert abs(sum(shares.values()) - 1.0) < 1e-9
    assert shares["skill_overlap"] > shares["freshness"]


def test_weights_are_relative_not_percentages() -> None:
    """Doubling every number says the same thing, so it must score the same."""
    once = Weights(skill_overlap=2, seniority_fit=1, domain_relevance=1, freshness=1)
    twice = Weights(skill_overlap=4, seniority_fit=2, domain_relevance=2, freshness=2)
    assert once.normalized() == twice.normalized()


def test_a_negative_weight_is_refused() -> None:
    with pytest.raises(ValidationError):
        Weights(freshness=-0.1)


def test_weights_that_all_sit_at_zero_are_refused() -> None:
    """Every posting scoring the same is not a ranking."""
    with pytest.raises(ValidationError, match="zero"):
        Weights(skill_overlap=0, seniority_fit=0, domain_relevance=0, freshness=0)


def test_a_semantic_fit_weight_is_refused_while_it_cannot_be_scored() -> None:
    """The point of the refusal: a weight that does nothing produces a score
    that looks complete. Better to fail with the reason than to rank on four
    components while the profile claims five."""
    with pytest.raises(ValidationError, match="semantic_fit") as caught:
        Weights(semantic_fit=0.25)
    # The message has to carry the reason and where the decision lives, or the
    # refusal reads as the tool being broken.
    assert "#31" in str(caught.value)
    assert "embedding model" in str(caught.value)


# -- schema version ------------------------------------------------------------


def test_a_profile_from_the_future_is_refused_rather_than_guessed_at() -> None:
    data = _valid()
    data["schema_version"] = CURRENT_SCHEMA_VERSION + 1
    with pytest.raises(ValidationError, match="schema_version"):
        Profile.model_validate(data)


def test_the_upgrade_chain_runs_even_with_nothing_to_do(
    monkeypatch: pytest.MonkeyPatch, store: Storage
) -> None:
    """The first time an upgrader matters is the worst time to find out the
    chain was never exercised, so a fake one is run end to end."""
    import jobagent.core.profile as profile_module

    def _v1_to_v2(payload: dict[str, object]) -> dict[str, object]:
        upgraded = dict(payload)
        upgraded["schema_version"] = 2
        upgraded["narrative"] = "added by the upgrade"
        return upgraded

    monkeypatch.setattr(profile_module, "CURRENT_SCHEMA_VERSION", 2)
    monkeypatch.setattr(profile_module, "_UPGRADES", {1: _v1_to_v2})
    monkeypatch.setattr(
        profile_module.Profile.model_fields["schema_version"], "default", 2, raising=False
    )

    stored = dict(_valid())
    stored["schema_version"] = 1
    store.put_singleton("profile", stored, 1)

    loaded = profile_module.load(store)
    assert loaded is not None
    assert loaded.schema_version == 2
    assert loaded.narrative == "added by the upgrade"


def test_a_version_with_no_upgrade_path_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, store: Storage
) -> None:
    import jobagent.core.profile as profile_module

    monkeypatch.setattr(profile_module, "CURRENT_SCHEMA_VERSION", 3)
    monkeypatch.setattr(profile_module, "_UPGRADES", {})

    stored = dict(_valid())
    stored["schema_version"] = 1
    store.put_singleton("profile", stored, 1)

    with pytest.raises(ValueError, match="no upgrade path"):
        profile_module.load(store)


# -- the file ------------------------------------------------------------------


def test_a_missing_file_says_where_it_looked(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="profile"):
        load_file(tmp_path / "nope.yaml")


def test_a_yaml_file_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "profile.yaml"
    target.write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        load_file(target)


def test_a_file_edit_does_not_change_what_the_agent_reads(tmp_path: Path, store: Storage) -> None:
    """The file is an import, not the store.

    Worth pinning because the opposite is the intuitive assumption, and someone
    editing YAML and wondering why filters did not change is the bug report.
    """
    target = tmp_path / "profile.yaml"
    data = _valid()
    target.write_text(yaml.safe_dump(data))
    store_profile(store, load_file(target))

    data["target_titles"] = ["Something Else Entirely"]
    target.write_text(yaml.safe_dump(data))

    stored = load(store)
    assert stored is not None
    assert stored.target_titles == ["Data Analyst"]
