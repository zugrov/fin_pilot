from tests.synthetic_polygon.expectations import (
    ORACLE,
    assert_oracle_matches_profiles,
    expectation_for,
    group_rollup,
)
from tests.synthetic_polygon.profiles import ALL_PROFILES


def test_polygon_oracle_matches_profile_aggregates() -> None:
    assert_oracle_matches_profiles()


def test_polygon_group_rollup() -> None:
    rollup = group_rollup()
    assert rollup["cash_total"] == "117500.00"
    assert rollup["revenue"] == "46000.00"


def test_each_profile_has_oracle_entry() -> None:
    for profile in ALL_PROFILES:
        assert profile.slug in ORACLE
        assert expectation_for(profile) == ORACLE[profile.slug]
