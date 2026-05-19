from __future__ import annotations

import sqlite3

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from bitcoin.rpc_client import BitcoinRpcClient
from bitcoin.rpc_errors import BitcoinRpcError
from bitcoin.utils import btc_value_to_sats, sats_to_btc_string, validate_txid
from democracy.funding.bitcoin_tx import combine_anyonecanpay_pledges
from democracy.funding.models import FundingCampaign, FundingPledge
from democracy.models.solution import Solution
from democracy.storage.repository import DemocracyRepository

PLEDGE_SIGHASH_TYPE = "ALL|ANYONECANPAY"
PLEDGE_INPUT_SEQUENCE = 0xFFFFFFFD
PLEDGE_LOCKTIME = 0


@dataclass(frozen=True)
class PledgeRequest:
    """
    Wallet-facing pledge request.

    The PSBT is the object that should be signed by the user's external wallet. The
    remaining fields are application context used by the UI and by later pledge
    submission.
    """

    campaign_id: UUID
    pledger_id: UUID
    txid: str
    vout: int
    value_sats: int
    psbt_base64: str
    sighash_type: str
    campaign_commitment_hex: str
    developer_payout_address: str
    asking_price_sats: int
    deadline_height: int


@dataclass(frozen=True)
class PledgeValidationResult:
    valid: bool
    reason: str | None = None


@dataclass(frozen=True)
class FundingStatus:
    campaign_id: UUID
    asking_price_sats: int
    valid_pledge_total_sats: int
    required_total_sats: int
    valid_pledge_count: int
    is_expired: bool
    is_fundable: bool


@dataclass(frozen=True)
class PreparedPledge:
    pledge: FundingPledge
    finalized_raw_tx_hex: str


@dataclass(frozen=True)
class FinalTransactionPlan:
    campaign_id: UUID
    selected_pledges: list[FundingPledge]
    selected_total_sats: int
    required_total_sats: int
    final_raw_tx_hex: str


class CampaignNotFoundError(LookupError):
    pass


class FundingService:
    def __init__(
        self,
        repository: DemocracyRepository,
        bitcoin_rpc: BitcoinRpcClient,
        network_id: bytes,
        min_confirmations: int,
    ) -> None:
        if not isinstance(network_id, bytes) or not network_id:
            raise ValueError("network_id must be non-empty bytes.")
        if min_confirmations < 0:
            raise ValueError("min_confirmations must be non-negative.")

        self.repository = repository
        self.bitcoin_rpc = bitcoin_rpc
        self.network_id = network_id
        self.min_confirmations = min_confirmations

    def create_campaign(
        self,
        solution: Solution,
        developer_payout_address: str,
        asking_price_sats: int,
        deadline_height_offset: int,
    ) -> FundingCampaign:
        """
        Create and store a funding campaign for a solution.

        Computes the campaign deadline from the current blockchain height and the given
        deadline offset, derives the solution hash from the solution, and stores the
        resulting campaign in the repository.

        :param solution: The solution for which to create a funding campaign.
        :param developer_payout_address: The Bitcoin address that receives the payout.
        :param asking_price_sats: The requested funding amount in satoshis.
        :param deadline_height_offset: The number of blocks from the current height
                                       until the campaign deadline.
        :returns: The created funding campaign.
        :raises ValueError: If deadline_height_offset is not positive, a campaign already
                            exists for the solution, or the solution is unknown to the
                            repository.
        """
        if deadline_height_offset <= 0:
            raise ValueError("deadline_height_offset must be positive.")

        current_height = self.bitcoin_rpc.get_block_count()
        deadline_height = current_height + deadline_height_offset

        campaign = FundingCampaign(
            solution_id=solution.id,
            solution_hash=solution.compute_hash(),
            developer_payout_address=developer_payout_address,
            asking_price_sats=asking_price_sats,
            deadline_height=deadline_height,
        )

        try:
            self.repository.add_campaign(campaign)
        except sqlite3.IntegrityError as exc:
            message = str(exc)
            if "UNIQUE constraint failed: funding_campaigns.solution_id" in message:
                raise ValueError(
                    f"Campaign already exists for solution: {solution.id}"
                ) from exc
            if "FOREIGN KEY constraint failed" in message:
                raise ValueError(
                    f"Cannot create campaign for unknown solution: {solution.id}"
                ) from exc
            raise

        return campaign

    def create_pledge_request(
        self,
        campaign_id: UUID,
        pledger_id: UUID,
        txid: str,
        vout: int,
    ) -> PledgeRequest:
        """
        Create an unsigned pledge transaction template for external signing.

        Validates the pledged transaction output, checks that the campaign exists and has
        not expired, verifies that the UTXO is unspent and sufficiently confirmed, and
        creates a PSBT that the pledger can sign.

        The returned request should be presented to a user or exported to a wallet
        provider. The wallet must sign unsigned_tx_hex using ALL|ANYONECANPAY.

        :param campaign_id: The campaign to which the pledge should be added.
        :param pledger_id: The participant creating the pledge.
        :param txid: The transaction ID containing the UTXO to pledge.
        :param vout: The zero-based output index of the UTXO to pledge.
        :returns: A pledge request containing the PSBT and campaign commitment details.
        :raises ValueError: If txid is invalid, the campaign does not exist, the campaign
                            has expired, the UTXO is spent or unknown, or the UTXO has too
                            few confirmations.
        """
        txid = validate_txid(txid)
        campaign = self._require_campaign(campaign_id)
        self._ensure_campaign_not_expired(campaign)

        utxo = self.bitcoin_rpc.get_tx_out(txid, vout, include_mempool=True)
        if utxo is None:
            raise ValueError("Cannot pledge a spent or unknown UTXO.")

        self._ensure_utxo_has_min_confirmations(utxo)

        value_sats = btc_value_to_sats(utxo["value"])
        campaign_commitment_hex = campaign.compute_campaign_commitment_hex(
            self.network_id
        )

        psbt_base64 = self.bitcoin_rpc.create_psbt(
            inputs=self._build_pledge_inputs(txid, vout),
            outputs=self._build_campaign_outputs(campaign, campaign_commitment_hex),
            locktime=PLEDGE_LOCKTIME,
            replaceable=True,
        )

        return PledgeRequest(
            campaign_id=campaign.id,
            pledger_id=pledger_id,
            txid=txid,
            vout=vout,
            value_sats=value_sats,
            psbt_base64=psbt_base64,
            sighash_type=PLEDGE_SIGHASH_TYPE,
            campaign_commitment_hex=campaign_commitment_hex,
            developer_payout_address=campaign.developer_payout_address,
            asking_price_sats=campaign.asking_price_sats,
            deadline_height=campaign.deadline_height,
        )

    def submit_signed_pledge(
        self,
        campaign_id: UUID,
        pledger_id: UUID,
        txid: str,
        vout: int,
        signed_pledge_psbt: str,
    ) -> FundingPledge:
        """
        Validate, finalize, and store a signed funding pledge.

        Checks that the campaign exists and has not expired, verifies that the pledged
        UTXO is still unspent and sufficiently confirmed, finalizes the signed PSBT to
        obtain the raw transaction hex, validates the resulting pledge transaction, and
        stores the pledge in the repository.

        :param campaign_id: The campaign to which the pledge belongs.
        :param pledger_id: The participant submitting the signed pledge.
        :param txid: The transaction ID containing the pledged UTXO.
        :param vout: The zero-based output index of the pledged UTXO.
        :param signed_pledge_psbt: The signed pledge transaction as a PSBT string.
        :returns: The stored funding pledge.
        :raises ValueError: If txid is invalid, the campaign does not exist, the campaign
                            has expired, the UTXO is spent or unknown, the UTXO has too
                            few confirmations, the signed pledge is invalid, the pledge
                            already exists, or the campaign is unknown to the repository.
        """
        txid = validate_txid(txid)
        campaign = self._require_campaign(campaign_id)
        self._ensure_campaign_not_expired(campaign)

        utxo = self.bitcoin_rpc.get_tx_out(txid, vout, include_mempool=True)
        if utxo is None:
            raise ValueError("Cannot submit pledge for a spent or unknown UTXO.")

        self._ensure_utxo_has_min_confirmations(utxo)

        value_sats = btc_value_to_sats(utxo["value"])
        finalized_raw_tx_hex = self.bitcoin_rpc.finalize_psbt_extract_tx_hex(
            signed_pledge_psbt
        )

        pledge = FundingPledge(
            campaign_id=campaign.id,
            pledger_id=pledger_id,
            txid=txid,
            vout=vout,
            value_sats=value_sats,
            signed_pledge_psbt=signed_pledge_psbt,
        )

        validation = self.validate_pledge(
            pledge,
            finalized_raw_tx_hex=finalized_raw_tx_hex,
        )
        if not validation.valid:
            raise ValueError(f"Invalid signed pledge: {validation.reason}")

        try:
            self.repository.add_pledge(pledge)
        except sqlite3.IntegrityError as exc:
            message = str(exc)
            if (
                "UNIQUE constraint failed: funding_pledges.campaign_id, "
                "funding_pledges.txid, funding_pledges.vout"
            ) in message:
                raise ValueError(
                    f"Pledge already exists for outpoint {pledge.txid}:{pledge.vout} "
                    f"in campaign {pledge.campaign_id}."
                ) from exc
            if "FOREIGN KEY constraint failed" in message:
                raise ValueError(
                    f"Cannot submit pledge for unknown campaign: {pledge.campaign_id}"
                ) from exc
            raise
        return pledge

    def validate_pledge(
        self,
        pledge: FundingPledge,
        finalized_raw_tx_hex: str | None = None,
    ) -> PledgeValidationResult:
        """
        Validate whether a funding pledge is currently usable for its campaign.

        The method first checks that the referenced campaign exists and that the pledged
        UTXO is still valid according to the current Bitcoin chain/mempool state. It then
        finalizes the signed pledge PSBT, unless a finalized raw transaction is already
        provided, decodes the resulting transaction, and verifies that it matches the
        expected pledge structure for the campaign.

        A pledge is considered valid only if it references a known campaign, its pledged
        UTXO is still unspent and satisfies the campaign's chain-level requirements, and
        the finalized transaction spends the claimed input while preserving the campaign's
        fixed funding outputs.

        The method does not call testmempoolaccept on the individual pledge transaction,
        because a single pledge usually does not contain enough input value to pay the
        full campaign output. Final signature and policy validity are therefore checked
        later, when enough pledges are combined into the final funding transaction.

        :param pledge: The pledge to validate.
        :param finalized_raw_tx_hex: Optional finalized raw transaction hex derived from
                                     the pledge PSBT. Supplying this avoids finalizing the
                                     same PSBT again when the caller has already done so.
        :return: A PledgeValidationResult indicating whether the pledge is valid. If
                 invalid, the result contains a human-readable reason.
        """
        campaign = self.repository.get_campaign(pledge.campaign_id)
        if campaign is None:
            return PledgeValidationResult(False, "Unknown campaign.")

        return self._validate_pledge_for_campaign(
            pledge,
            campaign,
            finalized_raw_tx_hex=finalized_raw_tx_hex,
        )

    def get_valid_pledges(self, campaign_id: UUID) -> list[FundingPledge]:
        """
        Retrieve all currently valid pledges for a funding campaign.

        The method loads the campaign, retrieves all locally stored pledges for it, and
        filters out pledges that are no longer valid. A pledge is considered valid only if
        it passes campaign-specific validation, including checks such as whether the
        pledged UTXO is still unspent and whether the signed pledge matches the campaign's
        expected transaction structure.

        Because pledge validity depends on the current Bitcoin chain and mempool state,
        the returned list is a snapshot and may become outdated if pledged UTXOs are spent
        afterward.

        :param campaign_id: The ID of the campaign whose valid pledges should be returned.
        :return: A list of currently valid funding pledges for the campaign.
        :raises ValueError: If the campaign does not exist.
        """
        campaign = self._require_campaign(campaign_id)
        prepared_pledges = self._prepare_valid_pledges_for_campaign(campaign)
        return [prepared.pledge for prepared in prepared_pledges]

    def _validate_pledge_for_campaign(
        self,
        pledge: FundingPledge,
        campaign: FundingCampaign,
        finalized_raw_tx_hex: str | None = None,
        decoded_pledge_tx: dict[str, Any] | None = None,
        current_height: int | None = None,
    ) -> PledgeValidationResult:
        """
        Validate a pledge against a known funding campaign.

        This helper performs the full pledge validation flow once the campaign has already
        been resolved by the caller. It first checks the chain-dependent pledge
        conditions, such as campaign expiry, UTXO availability, confirmation policy, and
        pledged value. It then finalizes the signed pledge PSBT, unless a finalized raw
        transaction was provided, decodes the resulting transaction, and verifies that the
        finalized transaction matches the expected pledge structure for the campaign.

        A pledge is valid only if its referenced UTXO is currently usable and its
        finalized transaction spends the claimed outpoint while preserving the campaign's
        fixed funding outputs and input sequence.

        The method does not call testmempoolaccept on the individual pledge transaction,
        because a single pledge will usually not cover the full campaign output by itself.
        Final signature and policy validity are checked later when enough pledge inputs
        are combined into the final funding transaction.

        :param pledge: The pledge to validate.
        :param campaign: The already resolved campaign the pledge belongs to.
        :param finalized_raw_tx_hex: Optional finalized raw transaction hex derived from
                                     the pledge PSBT. Supplying this avoids finalizing the
                                     same PSBT again.
        :param decoded_pledge_tx: Optional decoded finalized pledge transaction. Supplying
                                  this avoids decoding the same transaction again.
        :param current_height: Optional chain height snapshot to reuse across multiple
                               validations.
        :return: A PledgeValidationResult indicating whether the pledge is valid. If
                 invalid, the result contains a human-readable reason.
        """
        chain_validation = self._validate_pledge_against_chain(
            pledge,
            campaign,
            current_height=current_height,
        )
        if chain_validation is not None:
            return chain_validation

        try:
            raw_tx_hex = (
                finalized_raw_tx_hex
                or self.bitcoin_rpc.finalize_psbt_extract_tx_hex(
                    pledge.signed_pledge_psbt
                )
            )
            decoded = decoded_pledge_tx or self.bitcoin_rpc.decode_raw_transaction(
                raw_tx_hex
            )
        except (BitcoinRpcError, ValueError) as exc:
            return PledgeValidationResult(False, f"Cannot process pledge PSBT: {exc}")

        tx_validation = self._validate_finalized_pledge_transaction(
            pledge,
            campaign,
            decoded,
        )
        if tx_validation is not None:
            return tx_validation

        # We cannot reliably call testmempoolaccept on a single pledge transaction,
        # because an individual pledge usually does not fund the fixed campaign outputs.
        # Signature validity is therefore finally enforced when enough pledges are
        # combined and the final transaction is tested/broadcast.
        return PledgeValidationResult(True)

    def compute_funding_status(
        self,
        campaign_id: UUID,
        fee_buffer_sats: int,
    ) -> FundingStatus:
        """
        Compute a live funding snapshot for a campaign.

        This method is not a cheap repository read. It validates every locally stored
        pledge against the current Bitcoin chain and mempool state before computing the
        returned totals, so the result is a point-in-time snapshot that may become stale
        as chain state changes.

        Expired campaigns are reported explicitly through FundingStatus.is_expired and are
        never considered fundable.

        :param campaign_id: The ID of the campaign whose funding status should be
                            computed.
        :param fee_buffer_sats: Extra amount in satoshis required above the asking price
                                to cover the final funding transaction fee.
        :return: The current funding status of the campaign.
        :raises ValueError: If fee_buffer_sats is negative or if the campaign does not
                            exist.
        """
        if fee_buffer_sats < 0:
            raise ValueError("fee_buffer_sats must be non-negative.")

        campaign = self._require_campaign(campaign_id)
        current_height = self.bitcoin_rpc.get_block_count()
        is_expired = current_height > campaign.deadline_height
        required_total = campaign.asking_price_sats + fee_buffer_sats

        if is_expired:
            return FundingStatus(
                campaign_id=campaign.id,
                asking_price_sats=campaign.asking_price_sats,
                valid_pledge_total_sats=0,
                required_total_sats=required_total,
                valid_pledge_count=0,
                is_expired=True,
                is_fundable=False,
            )

        prepared_pledges = self._prepare_valid_pledges_for_campaign(
            campaign,
            current_height=current_height,
        )
        valid_total = sum(prepared.pledge.value_sats for prepared in prepared_pledges)

        return FundingStatus(
            campaign_id=campaign.id,
            asking_price_sats=campaign.asking_price_sats,
            valid_pledge_total_sats=valid_total,
            required_total_sats=required_total,
            valid_pledge_count=len(prepared_pledges),
            is_expired=False,
            is_fundable=valid_total >= required_total,
        )

    def prepare_final_transaction(
        self,
        campaign_id: UUID,
        fee_buffer_sats: int,
    ) -> FinalTransactionPlan:
        """
        Select valid pledges and build a final funding transaction plan.

        This method performs the live validation and selection work behind
        build_final_transaction(). It returns both the built raw transaction and the
        selected pledges so callers can inspect or display the chosen inputs.
        """
        if fee_buffer_sats < 0:
            raise ValueError("fee_buffer_sats must be non-negative.")

        campaign = self._require_campaign(campaign_id)
        current_height = self.bitcoin_rpc.get_block_count()

        prepared_pledges = self._prepare_valid_pledges_for_open_campaign(
            campaign,
            current_height=current_height,
        )
        selected = self._select_pledges(
            campaign=campaign,
            prepared_pledges=prepared_pledges,
            fee_buffer_sats=fee_buffer_sats,
        )

        final_raw_tx_hex = combine_anyonecanpay_pledges(
            [prepared.finalized_raw_tx_hex for prepared in selected]
        )
        selected_pledges = [prepared.pledge for prepared in selected]

        return FinalTransactionPlan(
            campaign_id=campaign.id,
            selected_pledges=selected_pledges,
            selected_total_sats=sum(pledge.value_sats for pledge in selected_pledges),
            required_total_sats=campaign.asking_price_sats + fee_buffer_sats,
            final_raw_tx_hex=final_raw_tx_hex,
        )

    def build_final_transaction(
        self,
        campaign_id: UUID,
        fee_buffer_sats: int,
    ) -> str:
        """
        Build the final raw transaction from enough valid pledges.

        This does not broadcast. Any peer can call this if it has the campaign and pledge
        objects. The resulting transaction should be checked with testmempoolaccept
        before broadcast.
        """
        return self.prepare_final_transaction(
            campaign_id=campaign_id,
            fee_buffer_sats=fee_buffer_sats,
        ).final_raw_tx_hex

    def broadcast_final_transaction(
        self,
        campaign_id: UUID,
        fee_buffer_sats: int,
    ) -> str:
        """
        Build, test, and broadcast the final funding transaction.

        Returns the Bitcoin txid.
        """
        final_raw_tx_hex = self.build_final_transaction(
            campaign_id=campaign_id,
            fee_buffer_sats=fee_buffer_sats,
        )

        acceptance = self.bitcoin_rpc.test_mempool_accept(final_raw_tx_hex)
        if not acceptance.get("allowed", False):
            reject_reason = acceptance.get("reject-reason", "unknown reason")
            raise ValueError(
                f"Final transaction rejected by mempool policy: {reject_reason}"
            )

        return self.bitcoin_rpc.send_raw_transaction(final_raw_tx_hex)

    def _select_pledges(
        self,
        campaign: FundingCampaign,
        prepared_pledges: list[PreparedPledge],
        fee_buffer_sats: int,
    ) -> list[PreparedPledge]:
        """
        Select prepared pledges for a final funding transaction.

        The heuristic prefers fewer inputs, because each additional pledge input increases
        transaction size and therefore fee pressure. When the remaining shortfall can be
        covered by one pledge, it chooses the smallest such pledge to limit overfunding.
        Otherwise, it chooses the largest remaining pledge to reduce the number of inputs.
        """
        if fee_buffer_sats < 0:
            raise ValueError("fee_buffer_sats must be non-negative.")

        required = campaign.asking_price_sats + fee_buffer_sats
        remaining = list(prepared_pledges)
        selected: list[PreparedPledge] = []
        total = 0

        while total < required and remaining:
            shortfall = required - total
            finishing = [
                prepared
                for prepared in remaining
                if prepared.pledge.value_sats >= shortfall
            ]
            if finishing:
                next_prepared = min(
                    finishing,
                    key=self._prepared_pledge_smallest_first_key,
                )
            else:
                next_prepared = min(
                    remaining,
                    key=self._prepared_pledge_largest_first_key,
                )

            remaining.remove(next_prepared)
            selected.append(next_prepared)
            total += next_prepared.pledge.value_sats

        if total < required:
            raise ValueError(
                f"Not enough valid pledges. Have {total} sats, need {required} sats."
            )

        return selected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_campaign(self, campaign_id: UUID) -> FundingCampaign:
        """
        Return an existing funding campaign.

        Looks up the campaign in the repository and raises an error if no campaign with
        the given identifier exists.

        :param campaign_id: The identifier of the campaign to retrieve.
        :returns: The matching funding campaign.
        :raises CampaignNotFoundError: If no campaign exists for campaign_id.
        """
        campaign = self.repository.get_campaign(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Unknown campaign: {campaign_id}")
        return campaign

    def _ensure_campaign_not_expired(self, campaign: FundingCampaign) -> None:
        """
        Ensure that a funding campaign has not expired.

        Checks the current blockchain height against the campaign deadline height.

        :param campaign: The funding campaign to check.
        :raises ValueError: If the current blockchain height is greater than the campaign
                            deadline height.
        """
        current_height = self.bitcoin_rpc.get_block_count()
        self._ensure_campaign_not_expired_at_height(campaign, current_height)

    def _ensure_campaign_not_expired_at_height(
        self,
        campaign: FundingCampaign,
        current_height: int,
    ) -> None:
        """
        Ensure that a funding campaign has not expired at a known chain height.

        :param campaign: The funding campaign to check.
        :param current_height: The chain height snapshot to compare to the deadline.
        :raises ValueError: If the campaign deadline has passed.
        """
        if current_height > campaign.deadline_height:
            raise ValueError(
                f"Campaign expired at height {campaign.deadline_height}; "
                f"current height is {current_height}."
            )

    def _validate_pledge_against_chain(
        self,
        pledge: FundingPledge,
        campaign: FundingCampaign,
        current_height: int | None = None,
    ) -> PledgeValidationResult | None:
        """
        Validate a pledge against the current Bitcoin chain and mempool state.

        This helper checks the chain-dependent conditions for a pledge: the campaign must
        still be open, the pledged outpoint must currently exist as an unspent transaction
        output, the UTXO must satisfy the required confirmation policy, and the value
        stored in the pledge must match the value reported by the Bitcoin node.

        The mempool is included when checking the pledged outpoint, so a pledge is treated
        as invalid as soon as the node observes another transaction spending the same
        UTXO, even before that transaction is confirmed.

        :param pledge: The pledge whose referenced UTXO should be checked.
        :param campaign: The campaign that defines the deadline and confirmation policy.
        :param current_height: Optional chain height snapshot to reuse across multiple
                               validations.
        :return: A PledgeValidationResult when validation fails, or None when all
                 chain-level checks pass.
        """
        if current_height is None:
            current_height = self.bitcoin_rpc.get_block_count()
        if current_height > campaign.deadline_height:
            return PledgeValidationResult(False, "Campaign deadline has passed.")

        utxo = self.bitcoin_rpc.get_tx_out(
            pledge.txid,
            pledge.vout,
            include_mempool=True,
        )
        if utxo is None:
            return PledgeValidationResult(False, "Pledged UTXO is spent or unknown.")

        try:
            self._ensure_utxo_has_min_confirmations(utxo)
        except ValueError:
            return PledgeValidationResult(
                False,
                "Pledged UTXO has too few confirmations.",
            )

        chain_value_sats = btc_value_to_sats(utxo["value"])
        if chain_value_sats != pledge.value_sats:
            return PledgeValidationResult(
                False,
                "Stored pledge value does not match UTXO.",
            )

        return None

    def _prepare_valid_pledges_for_campaign(
        self,
        campaign: FundingCampaign,
        *,
        current_height: int | None = None,
    ) -> list[PreparedPledge]:
        """
        Load, validate, and finalize all currently usable pledges for a campaign.

        The returned list is a live snapshot derived from current chain state. Each valid
        pledge is paired with the finalized raw transaction hex extracted from its signed
        PSBT so callers can reuse that work during final transaction assembly.

        Expired campaigns return an empty list because they no longer have any currently
        usable pledges.
        """
        if current_height is None:
            current_height = self.bitcoin_rpc.get_block_count()

        if current_height > campaign.deadline_height:
            return []

        prepared_pledges: list[PreparedPledge] = []
        for pledge in self.repository.get_pledges_for_campaign(campaign.id):
            try:
                finalized_raw_tx_hex = self.bitcoin_rpc.finalize_psbt_extract_tx_hex(
                    pledge.signed_pledge_psbt
                )
                decoded_pledge_tx = self.bitcoin_rpc.decode_raw_transaction(
                    finalized_raw_tx_hex
                )
            except BitcoinRpcError as exc:
                raise BitcoinRpcError(
                    method=exc.method,
                    code=exc.code,
                    rpc_message=(
                        f"Cannot process stored pledge {pledge.txid}:{pledge.vout} "
                        f"for campaign {campaign.id}: {exc.rpc_message}"
                    ),
                ) from exc
            except ValueError as exc:
                raise ValueError(
                    f"Cannot process stored pledge {pledge.txid}:{pledge.vout} "
                    f"for campaign {campaign.id}: {exc}"
                ) from exc

            validation = self._validate_pledge_for_campaign(
                pledge,
                campaign,
                finalized_raw_tx_hex=finalized_raw_tx_hex,
                decoded_pledge_tx=decoded_pledge_tx,
                current_height=current_height,
            )
            if validation.valid:
                prepared_pledges.append(
                    PreparedPledge(
                        pledge=pledge,
                        finalized_raw_tx_hex=finalized_raw_tx_hex,
                    )
                )

        return prepared_pledges

    def _prepare_valid_pledges_for_open_campaign(
        self,
        campaign: FundingCampaign,
        *,
        current_height: int | None = None,
    ) -> list[PreparedPledge]:
        """
        Load, validate, and finalize all currently usable pledges for a campaign that
        must still be open.

        :param campaign: The campaign whose pledges should be prepared.
        :param current_height: Optional chain height snapshot to reuse across the
                               preparation flow.
        :return: Prepared valid pledges for the campaign.
        :raises ValueError: If the campaign deadline has passed or if a stored pledge
                            cannot be processed.
        :raises BitcoinRpcError: If Bitcoin Core fails while processing a stored pledge.
        """
        if current_height is None:
            current_height = self.bitcoin_rpc.get_block_count()

        self._ensure_campaign_not_expired_at_height(campaign, current_height)
        return self._prepare_valid_pledges_for_campaign(
            campaign,
            current_height=current_height,
        )

    @staticmethod
    def _prepared_pledge_smallest_first_key(
        prepared_pledge: PreparedPledge,
    ) -> tuple[int, object, str, int]:
        pledge = prepared_pledge.pledge
        return (pledge.value_sats, pledge.created_at, pledge.txid, pledge.vout)

    @staticmethod
    def _prepared_pledge_largest_first_key(
        prepared_pledge: PreparedPledge,
    ) -> tuple[int, object, str, int]:
        pledge = prepared_pledge.pledge
        return (-pledge.value_sats, pledge.created_at, pledge.txid, pledge.vout)

    def _ensure_utxo_has_min_confirmations(self, utxo: dict[str, Any]) -> int:
        """
        Ensure that a UTXO satisfies the service-level confirmation policy.

        :param utxo: The decoded UTXO result returned by Bitcoin Core.
        :returns: The parsed confirmation count.
        :raises ValueError: If the UTXO has fewer confirmations than required.
        """
        confirmations = int(utxo.get("confirmations", 0))
        if confirmations < self.min_confirmations:
            raise ValueError(
                f"UTXO has {confirmations} confirmations, "
                f"requires {self.min_confirmations}."
            )

        return confirmations

    def _validate_finalized_pledge_transaction(
        self,
        pledge: FundingPledge,
        campaign: FundingCampaign,
        decoded_pledge_tx: dict[str, Any],
    ) -> PledgeValidationResult | None:
        """
        Validate the structure of a finalized pledge transaction.

        This helper checks that the finalized transaction extracted from a pledge PSBT has
        the expected one-input pledge shape. The transaction must spend the exact UTXO
        referenced by the pledge, preserve the campaign's fixed funding outputs, and use
        the same input sequence as the unsigned pledge template.

        The method validates the transaction structure and campaign binding, but it does
        not check whether the pledged UTXO is still unspent. Chain-level checks are
        handled separately by _validate_pledge_against_chain.

        :param pledge: The pledge whose finalized transaction is being validated.
        :param campaign: The campaign that defines the expected funding outputs.
        :param decoded_pledge_tx: Decoded raw transaction returned by Bitcoin RPC.
        :return: A PledgeValidationResult when validation fails, or None when the
                 finalized transaction matches the expected pledge structure.
        """
        vin = decoded_pledge_tx.get("vin")
        if not isinstance(vin, list) or len(vin) != 1:
            return PledgeValidationResult(
                False,
                "Pledge transaction must have exactly one input.",
            )

        input_txid = vin[0].get("txid")
        input_vout = vin[0].get("vout")

        if input_txid != pledge.txid or int(input_vout) != pledge.vout:
            return PledgeValidationResult(
                False,
                "Pledge transaction spends wrong UTXO.",
            )

        expected_raw = self._build_unsigned_pledge_transaction(
            campaign=campaign,
            txid=pledge.txid,
            vout=pledge.vout,
        )
        expected_decoded = self.bitcoin_rpc.decode_raw_transaction(expected_raw)

        if decoded_pledge_tx.get("vout") != expected_decoded.get("vout"):
            return PledgeValidationResult(
                False,
                "Pledge transaction has wrong outputs.",
            )

        expected_sequence = self._extract_single_input_sequence(expected_decoded)
        actual_sequence = self._extract_single_input_sequence(decoded_pledge_tx)
        if actual_sequence != expected_sequence:
            return PledgeValidationResult(
                False,
                "Pledge transaction uses wrong input sequence.",
            )

        return None

    def _build_unsigned_pledge_transaction(
        self,
        campaign: FundingCampaign,
        txid: str,
        vout: int,
    ) -> str:
        """
        Build the unsigned one-input pledge transaction template for a campaign.

        The transaction spends the pledged outpoint identified by txid and vout and uses
        the campaign's fixed funding outputs: the developer payout output and the
        OP_RETURN campaign commitment. This unsigned transaction is the template that the
        pledger signs externally with the required pledge sighash mode.

        The resulting raw transaction is not intended to be broadcast on its own. It is
        used to derive the exact transaction structure that each pledge must preserve so
        that the signed input can later be combined with other pledge inputs.

        :param campaign: The funding campaign that defines the payout terms.
        :param txid: The transaction ID of the pledged UTXO.
        :param vout: The output index of the pledged UTXO.
        :return: The unsigned raw transaction hex for the pledge template.
        """
        campaign_commitment_hex = campaign.compute_campaign_commitment_hex(
            self.network_id
        )
        return self.bitcoin_rpc.create_raw_transaction(
            inputs=self._build_pledge_inputs(txid, vout),
            outputs=self._build_campaign_outputs(campaign, campaign_commitment_hex),
            locktime=PLEDGE_LOCKTIME,
            replaceable=True,
        )

    @staticmethod
    def _build_pledge_inputs(txid: str, vout: int) -> list[dict[str, Any]]:
        """
        Build the Bitcoin RPC input list for a one-input pledge transaction.

        The returned input references the pledged UTXO identified by txid and vout and
        sets the fixed pledge sequence value. The same input structure is used when
        creating pledge PSBTs and when reconstructing the expected unsigned pledge
        transaction during validation.

        :param txid: The transaction ID of the pledged UTXO.
        :param vout: The output index of the pledged UTXO.
        :return: A Bitcoin Core-compatible input list for the pledge transaction template.
        """
        return [
            {
                "txid": txid,
                "vout": vout,
                "sequence": PLEDGE_INPUT_SEQUENCE,
            }
        ]

    @staticmethod
    def _build_campaign_outputs(
        campaign: FundingCampaign,
        campaign_commitment_hex: str,
    ) -> list[dict[str, Any]]:
        """
        Build the ordered Bitcoin Core RPC outputs for a funding campaign.

        The order is part of the pledge contract. Every unsigned pledge transaction and
        the final combined transaction must use exactly this output list. The outputs pay
        the campaign asking price to the developer and include an OP_RETURN commitment
        that links the transaction to the campaign.

        :param campaign: Campaign defining the payout address and asking price.
        :param campaign_commitment_hex: Hex-encoded campaign commitment for OP_RETURN.
        :return: Bitcoin Core-compatible output list for the campaign transaction.
        """
        return [
            {
                campaign.developer_payout_address: sats_to_btc_string(
                    campaign.asking_price_sats
                )
            },
            {"data": campaign_commitment_hex},
        ]

    @staticmethod
    def _extract_single_input_sequence(decoded_tx: dict[str, object]) -> int:
        """
        Extract the sequence number from a decoded one-input transaction.

        This helper is used when validating pledge transactions, which are expected to
        have exactly one input. The sequence value is part of the signed input data and
        must match the pledge template; otherwise, the pledged signature may not remain
        valid when the input is combined into the final funding transaction.

        :param decoded_tx: Decoded raw transaction returned by Bitcoin RPC.
        :return: The sequence number of the transaction's single input.
        :raises ValueError: If the transaction does not have exactly one input or if the
                            input does not contain an integer sequence value.
        """
        vin = decoded_tx.get("vin")
        if not isinstance(vin, list) or len(vin) != 1:
            raise ValueError("Transaction must have exactly one input.")

        sequence = vin[0].get("sequence")
        if not isinstance(sequence, int):
            raise ValueError("Transaction input does not contain an integer sequence.")

        return sequence
