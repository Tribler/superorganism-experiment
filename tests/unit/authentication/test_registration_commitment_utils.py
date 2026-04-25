from __future__ import annotations

from authentication.registration_commitment_utils import compute_registration_commitment


# =========================================================
# compute_registration_commitment()
# =========================================================
def test_compute_registration_commitment_returns_expected_digest_for_known_key() -> (
    None
):
    public_key_bytes = bytes.fromhex("11" * 32)

    result = compute_registration_commitment(public_key_bytes)

    assert result == "0be3b47653ec2e43ca79beb221c78e998823df03b41284501eceedb94610f58c"


def test_compute_registration_commitment_returns_different_digest_for_different_key() -> (
    None
):
    first_public_key_bytes = bytes.fromhex("11" * 32)
    second_public_key_bytes = bytes.fromhex("22" * 32)

    first_result = compute_registration_commitment(first_public_key_bytes)
    second_result = compute_registration_commitment(second_public_key_bytes)

    assert first_result != second_result
