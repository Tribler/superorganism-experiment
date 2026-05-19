from __future__ import annotations

import hashlib

from dataclasses import dataclass
from io import BytesIO


class TxFormatError(ValueError):
    pass


@dataclass(frozen=True)
class TxInput:
    prev_txid_le: bytes
    vout: int
    script_sig: bytes
    sequence: int
    witness: list[bytes]

    def outpoint_key(self) -> tuple[str, int]:
        txid = self.prev_txid_le[::-1].hex()
        return txid, self.vout


@dataclass(frozen=True)
class TxOutput:
    value_sats: int
    script_pubkey: bytes


@dataclass(frozen=True)
class BitcoinTransaction:
    version: int
    inputs: list[TxInput]
    outputs: list[TxOutput]
    locktime: int

    def serialize(self) -> bytes:
        has_witness = any(txin.witness for txin in self.inputs)

        result = bytearray()
        result.extend(_uint32_le(self.version))

        if has_witness:
            result.extend(b"\x00\x01")

        result.extend(_encode_varint(len(self.inputs)))
        for txin in self.inputs:
            result.extend(txin.prev_txid_le)
            result.extend(_uint32_le(txin.vout))
            result.extend(_encode_varint(len(txin.script_sig)))
            result.extend(txin.script_sig)
            result.extend(_uint32_le(txin.sequence))

        result.extend(_encode_varint(len(self.outputs)))
        for txout in self.outputs:
            result.extend(_uint64_le(txout.value_sats))
            result.extend(_encode_varint(len(txout.script_pubkey)))
            result.extend(txout.script_pubkey)

        if has_witness:
            for txin in self.inputs:
                result.extend(_encode_varint(len(txin.witness)))
                for item in txin.witness:
                    result.extend(_encode_varint(len(item)))
                    result.extend(item)

        result.extend(_uint32_le(self.locktime))
        return bytes(result)

    def to_hex(self) -> str:
        return self.serialize().hex()

    def txid(self) -> str:
        raw_no_witness = self.serialize_without_witness()
        return (
            hashlib.sha256(hashlib.sha256(raw_no_witness).digest()).digest()[::-1].hex()
        )

    def serialize_without_witness(self) -> bytes:
        result = bytearray()
        result.extend(_uint32_le(self.version))

        result.extend(_encode_varint(len(self.inputs)))
        for txin in self.inputs:
            result.extend(txin.prev_txid_le)
            result.extend(_uint32_le(txin.vout))
            result.extend(_encode_varint(len(txin.script_sig)))
            result.extend(txin.script_sig)
            result.extend(_uint32_le(txin.sequence))

        result.extend(_encode_varint(len(self.outputs)))
        for txout in self.outputs:
            result.extend(_uint64_le(txout.value_sats))
            result.extend(_encode_varint(len(txout.script_pubkey)))
            result.extend(txout.script_pubkey)

        result.extend(_uint32_le(self.locktime))
        return bytes(result)


def parse_transaction(raw_tx_hex: str) -> BitcoinTransaction:
    try:
        raw = bytes.fromhex(raw_tx_hex)
    except ValueError as exc:
        raise TxFormatError("raw_tx_hex is not valid hex.") from exc

    stream = BytesIO(raw)

    version = _read_uint32_le(stream)

    marker_or_input_count = _read_varint(stream)
    has_witness = False

    if marker_or_input_count == 0:
        flag = _read_exact(stream, 1)
        if flag != b"\x01":
            raise TxFormatError("Invalid segwit transaction marker/flag.")
        has_witness = True
        input_count = _read_varint(stream)
    else:
        input_count = marker_or_input_count

    inputs: list[TxInput] = []
    for _ in range(input_count):
        prev_txid_le = _read_exact(stream, 32)
        vout = _read_uint32_le(stream)
        script_len = _read_varint(stream)
        script_sig = _read_exact(stream, script_len)
        sequence = _read_uint32_le(stream)

        inputs.append(
            TxInput(
                prev_txid_le=prev_txid_le,
                vout=vout,
                script_sig=script_sig,
                sequence=sequence,
                witness=[],
            )
        )

    output_count = _read_varint(stream)
    outputs: list[TxOutput] = []
    for _ in range(output_count):
        value_sats = _read_uint64_le(stream)
        script_len = _read_varint(stream)
        script_pubkey = _read_exact(stream, script_len)
        outputs.append(
            TxOutput(
                value_sats=value_sats,
                script_pubkey=script_pubkey,
            )
        )

    if has_witness:
        new_inputs: list[TxInput] = []
        for txin in inputs:
            item_count = _read_varint(stream)
            witness_items = []
            for _ in range(item_count):
                item_len = _read_varint(stream)
                witness_items.append(_read_exact(stream, item_len))

            new_inputs.append(
                TxInput(
                    prev_txid_le=txin.prev_txid_le,
                    vout=txin.vout,
                    script_sig=txin.script_sig,
                    sequence=txin.sequence,
                    witness=witness_items,
                )
            )
        inputs = new_inputs

    locktime = _read_uint32_le(stream)

    remaining = stream.read()
    if remaining:
        raise TxFormatError("Unexpected bytes after transaction end.")

    return BitcoinTransaction(
        version=version,
        inputs=inputs,
        outputs=outputs,
        locktime=locktime,
    )


def combine_anyonecanpay_pledges(
    signed_pledge_tx_hexes: list[str],
) -> str:
    """
    Combine one-input signed pledge transactions into one final transaction.

    Preconditions:
    - each pledge tx has exactly one input;
    - all pledge txs have exactly the same outputs;
    - each input was signed with ALL|ANYONECANPAY;
    - each input still references an unspent UTXO.

    This function does not verify the signatures. Verification is done by Bitcoin Core
    during mempool acceptance/broadcast.
    """
    if not signed_pledge_tx_hexes:
        raise ValueError("At least one pledge transaction is required.")

    parsed = [parse_transaction(raw) for raw in signed_pledge_tx_hexes]

    first = parsed[0]
    expected_outputs = first.outputs
    expected_locktime = first.locktime
    expected_version = first.version

    combined_inputs: list[TxInput] = []
    seen_outpoints: set[tuple[str, int]] = set()

    for tx in parsed:
        if len(tx.inputs) != 1:
            raise ValueError(
                "Each signed pledge transaction must have exactly one input."
            )

        if tx.outputs != expected_outputs:
            raise ValueError("All pledge transactions must have identical outputs.")

        if tx.locktime != expected_locktime:
            raise ValueError("All pledge transactions must use the same locktime.")

        if tx.version != expected_version:
            raise ValueError("All pledge transactions must use the same version.")

        txin = tx.inputs[0]
        outpoint = txin.outpoint_key()
        if outpoint in seen_outpoints:
            raise ValueError(f"Duplicate pledge input: {outpoint[0]}:{outpoint[1]}.")

        seen_outpoints.add(outpoint)
        combined_inputs.append(txin)

    final_tx = BitcoinTransaction(
        version=expected_version,
        inputs=combined_inputs,
        outputs=expected_outputs,
        locktime=expected_locktime,
    )

    return final_tx.to_hex()


def _read_exact(stream: BytesIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise TxFormatError("Unexpected end of transaction.")
    return value


def _read_uint32_le(stream: BytesIO) -> int:
    return int.from_bytes(_read_exact(stream, 4), "little")


def _read_uint64_le(stream: BytesIO) -> int:
    return int.from_bytes(_read_exact(stream, 8), "little")


def _uint32_le(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("uint32 out of range.")
    return value.to_bytes(4, "little")


def _uint64_le(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("uint64 out of range.")
    return value.to_bytes(8, "little")


def _read_varint(stream: BytesIO) -> int:
    prefix = _read_exact(stream, 1)[0]

    if prefix < 0xFD:
        return prefix

    if prefix == 0xFD:
        return int.from_bytes(_read_exact(stream, 2), "little")

    if prefix == 0xFE:
        return int.from_bytes(_read_exact(stream, 4), "little")

    return int.from_bytes(_read_exact(stream, 8), "little")


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint cannot be negative.")

    if value < 0xFD:
        return bytes([value])

    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")

    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")

    if value <= 0xFFFFFFFFFFFFFFFF:
        return b"\xff" + value.to_bytes(8, "little")

    raise ValueError("varint too large.")
