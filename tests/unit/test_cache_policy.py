from open_dota_mcp.cache.policy import classify_freshness


def test_freshness_policy_is_explicit_and_boolean_safe() -> None:
    assert classify_freshness("get_heroes", []).ttl_seconds == 86_400
    assert classify_freshness("get_patches", []).category == "long"
    assert classify_freshness("get_match", {"version": 1}).category == "long"
    for value in [None, True, False, 0, -1, "1"]:
        assert classify_freshness("get_match", {"version": value}).ttl_seconds == 900
    assert classify_freshness("future_operation", {}).category == "short"
