from __future__ import annotations

import pytest

from democracy.funding import service as funding_service_module
from democracy.funding.service import FundingService


# =========================================================
# _build_pledge_intputs()
# =========================================================
def test_build_pledge_inputs_returns_expected_single_input_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        funding_service_module,
        "PLEDGE_INPUT_SEQUENCE",
        123456,
    )

    inputs = FundingService._build_pledge_inputs("ab" * 32, 7)

    assert inputs == [
        {
            "txid": "ab" * 32,
            "vout": 7,
            "sequence": 123456,
        }
    ]
