"""Reject malformed network identities before they can enter semantic artifacts."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backtest.domain.chain import SOLANA_MAINNET_NETWORK_ID
from backtest.domain.identifiers import NetworkId

# Base58 RPC contract: https://solana.com/docs/rpc/http/getgenesishash.
# Known full spelling and canonical leading-zero encodings are all preserved verbatim.
_VALID_GENESIS_REFERENCES = (
    SOLANA_MAINNET_NETWORK_ID.chain_reference,
    "GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC",
    # These exact 32-byte encodings cover entirely zero and mostly zero hash bytes.
    "1" * 32,
    "1" * 31 + "2",
)

# Length alone is insufficient: these alphabet-valid values decode to the wrong width.
_WRONG_WIDTH_REFERENCES = (
    "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "1" * 31,
    "1" * 33,
    "2" * 32,
    # A 44-character base58 number can exceed 256 bits; padding adds actual zero bytes.
    "z" * 44,
    "1" + SOLANA_MAINNET_NETWORK_ID.chain_reference,
)


@pytest.mark.parametrize("chain_reference", _VALID_GENESIS_REFERENCES)
def test_complete_genesis_hashes_preserve_the_exact_identity(chain_reference: str) -> None:
    """Validation must never normalize, shorten or replace an accepted chain reference."""
    value = f"solana:{chain_reference}"
    network = NetworkId(value)
    assert network.value == str(network) == value
    assert network.family == "solana"
    assert network.chain_reference == chain_reference


@pytest.mark.parametrize("chain_reference", _WRONG_WIDTH_REFERENCES)
def test_truncated_or_wrong_width_genesis_hashes_fail_closed(chain_reference: str) -> None:
    """A display prefix or malformed byte width cannot become a Solana identity."""
    value = f"solana:{chain_reference}"
    with pytest.raises(ValueError, match="genesis") as captured:
        NetworkId(value)
    assert value not in str(captured.value)


@pytest.mark.parametrize("invalid_character", ("0", "O", "I", "l", "é", "\uff11"))
def test_genesis_hash_requires_the_ascii_base58_alphabet(invalid_character: str) -> None:
    """Ambiguous ASCII glyphs and Unicode lookalikes must not form alternate identities."""
    value = f"solana:{'1' * 31}{invalid_character}"
    with pytest.raises(ValueError, match="base58") as captured:
        NetworkId(value)
    assert value not in str(captured.value)


@pytest.mark.parametrize(
    "chain_reference",
    (
        "https://rpc.invalid/mainnet",
        "user:invalid-password@rpc.invalid",
        # URI query/fragment and both path separators must remain operational values.
        "genesis?token=invalid",
        "genesis#fragment",
        # Filesystem spellings must not leak a deployment path into network identity.
        "relative/path",
        "relative\\path",
    ),
)
def test_generic_network_reference_rejects_endpoint_and_credential_shapes(
    chain_reference: str,
) -> None:
    """The generic envelope also rejects endpoint delimiters without disclosing input."""
    value = f"reference:{chain_reference}"
    with pytest.raises(ValueError, match="endpoint or credentials") as captured:
        NetworkId(value)
    assert value not in str(captured.value)
    assert chain_reference not in str(captured.value)


def test_generic_opaque_immutable_reference_keeps_its_existing_contract() -> None:
    """The syntax correction introduces no network registry or new admission policy."""
    value = "reference:immutable-chain-uuid-00000000-0000-0000-0000-000000000001"
    assert NetworkId(value).value == value


@given(st.binary(min_size=32, max_size=32))
def test_every_canonical_32_byte_genesis_encoding_is_accepted(raw_hash: bytes) -> None:
    """An independent division-based encoder covers every byte value and leading zeros."""
    chain_reference = _encode_base58(raw_hash)
    assert NetworkId(f"solana:{chain_reference}").chain_reference == chain_reference


def _encode_base58(raw_hash: bytes) -> str:
    """Create canonical test inputs independently of the production multiply/add decoder."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(raw_hash, "big")
    encoded = ""
    # Repeated division emits the least significant digit first, then prepends it.
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    # Preserve every leading zero byte, including the entirely zero 32-byte hash.
    return "1" * (len(raw_hash) - len(raw_hash.lstrip(b"\x00"))) + encoded
