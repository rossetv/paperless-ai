"""An api-key expiry outside the representable UTC range is a validation error."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire.api_keys import CreateApiKeyRequest


@pytest.mark.parametrize(
    "value",
    ["9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+01:00"],
)
def test_expiry_at_the_datetime_edges_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        CreateApiKeyRequest(name="k", scopes=["api"], expires_at=value)


def test_a_normal_offset_expiry_is_still_normalised_to_utc() -> None:
    req = CreateApiKeyRequest(
        name="k", scopes=["api"], expires_at="2030-01-01T01:00:00+01:00"
    )
    assert req.expires_at == "2030-01-01T00:00:00+00:00"
