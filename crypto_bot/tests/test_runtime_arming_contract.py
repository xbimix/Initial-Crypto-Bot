from runtime.arming_contract import evaluate_runtime_arming_contract


def test_contract_allows_local_mutations_with_token():
    result = evaluate_runtime_arming_contract(
        deployed_mode=False,
        execution_mode="paper",
        token_configured=True,
        strict_mutating_auth=False,
        deployed_mutations_enabled=False,
        deployed_live_arming_enabled=False,
    )
    assert result.mutating_allowed is True
    assert result.live_arming_allowed is True
    assert result.failures == ()


def test_contract_blocks_deployed_without_explicit_flags():
    result = evaluate_runtime_arming_contract(
        deployed_mode=True,
        execution_mode="paper",
        token_configured=True,
        strict_mutating_auth=False,
        deployed_mutations_enabled=False,
        deployed_live_arming_enabled=False,
    )
    assert result.mutating_allowed is False
    assert "strict_mutating_auth_disabled" in result.failures
    assert "deployed_mutations_not_enabled" in result.failures


def test_contract_requires_live_arming_flag_in_live_mode():
    blocked = evaluate_runtime_arming_contract(
        deployed_mode=True,
        execution_mode="live",
        token_configured=True,
        strict_mutating_auth=True,
        deployed_mutations_enabled=True,
        deployed_live_arming_enabled=False,
    )
    assert blocked.mutating_allowed is True
    assert blocked.live_arming_allowed is False
    assert "deployed_live_arming_not_enabled" in blocked.live_arming_failures

    allowed = evaluate_runtime_arming_contract(
        deployed_mode=True,
        execution_mode="live",
        token_configured=True,
        strict_mutating_auth=True,
        deployed_mutations_enabled=True,
        deployed_live_arming_enabled=True,
    )
    assert allowed.mutating_allowed is True
    assert allowed.live_arming_allowed is True

