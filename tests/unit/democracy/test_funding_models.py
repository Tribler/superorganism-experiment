from __future__ import annotations

from uuid import UUID

import pytest

from democracy.funding import models as funding_models_module
from democracy.funding.models import FundingCampaign, FundingPledge, _length_prefix


# =========================================================
# _length_prefix()
# =========================================================
def test_length_prefix_prefixes_empty_bytes_with_zero_length() -> None:
    assert _length_prefix(b"") == b"\x00\x00\x00\x00"


def test_length_prefix_prefixes_non_empty_bytes_with_big_endian_length() -> None:
    assert _length_prefix(b"abc") == b"\x00\x00\x00\x03abc"


def test_length_prefix_preserves_original_bytes_after_prefix() -> None:
    value = bytes(range(10))

    result = _length_prefix(value)

    assert result[:4] == len(value).to_bytes(4, "big", signed=False)
    assert result[4:] == value


# =========================================================
# FundingCampaign
# =========================================================
@pytest.mark.parametrize("asking_price_sats", [0, -1, -100])
def test_funding_campaign_rejects_non_positive_asking_price_sats(
    asking_price_sats: int,
) -> None:
    with pytest.raises(ValueError, match="asking_price_sats must be positive"):
        FundingCampaign(
            solution_id=UUID("00000000-0000-0000-0000-000000000002"),
            solution_hash="not-validated-yet",
            developer_payout_address="bcrt1qexampleaddress",
            asking_price_sats=asking_price_sats,
            deadline_height=20,
        )


@pytest.mark.parametrize("deadline_height", [0, -1, -100])
def test_funding_campaign_rejects_non_positive_deadline_height(
    deadline_height: int,
) -> None:
    with pytest.raises(ValueError, match="deadline_height must be positive"):
        FundingCampaign(
            solution_id=UUID("00000000-0000-0000-0000-000000000002"),
            solution_hash="not-validated-yet",
            developer_payout_address="bcrt1qexampleaddress",
            asking_price_sats=10,
            deadline_height=deadline_height,
        )


# =========================================================
# FundingCampaign.compute_campaign_commitment_hex()
# =========================================================
def test_compute_campaign_commitment_hex_binds_issue_and_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        funding_models_module,
        "FUNDING_PROTOCOL_LABEL",
        b"superorganism-funding-v1",
    )

    campaign = FundingCampaign(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        solution_id=UUID("00000000-0000-0000-0000-000000000002"),
        solution_hash="ab" * 32,
        developer_payout_address="bcrt1qexampleaddress",
        asking_price_sats=10,
        deadline_height=20,
    )

    expected = "44c099b3ec859e25670779fbbb5b9d703d376faf722735a66a2fe05a6a147429"

    assert campaign.compute_campaign_commitment_hex(b"regtest") == expected


def test_compute_campaign_commitment_hex_rejects_empty_network_id() -> None:
    campaign = FundingCampaign(
        solution_id=UUID("00000000-0000-0000-0000-000000000002"),
        solution_hash="ab" * 32,
        developer_payout_address="bcrt1qexampleaddress",
        asking_price_sats=10,
        deadline_height=20,
    )

    with pytest.raises(ValueError, match="network_id must be non-empty bytes"):
        campaign.compute_campaign_commitment_hex(b"")


# =========================================================
# FundingPledge
# =========================================================
def test_funding_pledge_normalizes_txid_and_signed_pledge_psbt() -> None:
    pledge = FundingPledge(
        campaign_id=UUID("00000000-0000-0000-0000-000000000001"),
        pledger_id=UUID("00000000-0000-0000-0000-000000000002"),
        txid=f"  {'ab' * 32}  ",
        vout=0,
        value_sats=1,
        signed_pledge_psbt="  cHNidP8BAAoCAAAAAQ==  ",
    )

    assert pledge.txid == "ab" * 32
    assert pledge.signed_pledge_psbt == "cHNidP8BAAoCAAAAAQ=="


@pytest.mark.parametrize("txid", ["", "   ", "ab", "g" * 64])
def test_funding_pledge_rejects_invalid_txid(txid: str) -> None:
    with pytest.raises(ValueError, match="txid"):
        FundingPledge(
            campaign_id=UUID("00000000-0000-0000-0000-000000000001"),
            pledger_id=UUID("00000000-0000-0000-0000-000000000002"),
            txid=txid,
            vout=0,
            value_sats=1,
            signed_pledge_psbt="cHNidP8BAAoCAAAAAQ==",
        )


@pytest.mark.parametrize("signed_pledge_psbt", ["", "   ", "zz", "not-base64!"])
def test_funding_pledge_rejects_invalid_signed_pledge_psbt(
    signed_pledge_psbt: str,
) -> None:
    with pytest.raises(ValueError, match="psbt_base64"):
        FundingPledge(
            campaign_id=UUID("00000000-0000-0000-0000-000000000001"),
            pledger_id=UUID("00000000-0000-0000-0000-000000000002"),
            txid="ab" * 32,
            vout=0,
            value_sats=1,
            signed_pledge_psbt=signed_pledge_psbt,
        )
