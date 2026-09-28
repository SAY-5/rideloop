"""The integration fixture must never target AWS or another machine."""

import pytest

from tests import conftest


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "",
        "http://dynamodb.us-east-1.amazonaws.com:8000",
        "http://localhost:8000",
        "http://192.0.2.1:8000",
        "http://0.0.0.0:8000",
        "http://127.0.0.1",
        "http://user:pass@127.0.0.1:8000",
        "http://127.0.0.1:8000/other",
        "http://127.0.0.1:8000/?secret=x",
        "http://127.0.0.1:8000/#fragment",
        "https://127.0.0.1:8000",
    ],
)
def test_nonlocal_or_ambiguous_dynamo_endpoints_are_rejected(endpoint):
    # A missing guard is a security failure, not permission to fall back to the Moto store.
    validator = getattr(conftest, "local_dynamo_settings", None)
    assert validator is not None, "integration fixture must validate its endpoint before I/O"
    with pytest.raises(ValueError, match="TEST_DYNAMODB_ENDPOINT"):
        validator(endpoint)


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:8000", "http://[::1]:8000"])
def test_local_fixture_uses_fake_credentials_and_its_own_unique_table(endpoint):
    validator = getattr(conftest, "local_dynamo_settings", None)
    assert validator is not None, "integration fixture must validate its endpoint before I/O"
    first = validator(endpoint)
    second = validator(endpoint)
    assert first.dynamodb_endpoint == endpoint
    assert first.aws_access_key_id == first.aws_secret_access_key == "testing"
    assert first.driver_positions_table.startswith("rideloop-test-")
    assert len(first.driver_positions_table.removeprefix("rideloop-test-")) == 32
    assert first.driver_positions_table != second.driver_positions_table
