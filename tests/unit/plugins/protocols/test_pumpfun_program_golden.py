# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json

# Import shutil at the visible module dependency boundary.
import shutil
from pathlib import Path
from typing import Any

import pytest
from pumpfun_program_golden_support import (
    # Include golden fixture error so the pumpfun program golden support dependency
    # remains explicit.
    GoldenFixtureError,
    GoldenTree,
    canonical_json_sha256,
    decode_raw_event,
    decode_raw_events,
    exact_file_sha256,
    # Include load verified tree so the pumpfun program golden support dependency remains
    # explicit.
    load_verified_tree,
)

from backtest.plugins.protocols.pumpfun import (
    PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
    PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1,
    # Include pump sell exact token in formula v1 so the pumpfun dependency remains
    # explicit.
    PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
    PUMP_STATIC_PROGRAM_CONTRACT_V1,
    PumpCreatorFeeRoute,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    # Include pump fee profile so the pumpfun dependency remains explicit.
    PumpFeeProfile,
    PumpMode,
    PumpProtocolFeeRoute,
    PumpQuoteError,
    PumpQuoteErrorCode,
    # Include pump token program so the pumpfun dependency remains explicit.
    PumpTokenProgram,
    buy_quote,
    sell_quote,
)

_TESTS_ROOT = Path(__file__).resolve().parents[3]
# Bind golden root once as an explicit module-level contract.
_GOLDEN_ROOT = _TESTS_ROOT / "golden" / "pumpfun" / "program-v1"
_DECODER_PATH = Path(__file__).with_name("pumpfun_program_golden_support.py")
_THIRD_PARTY_NOTICES_PATH = _TESTS_ROOT.parent / "THIRD_PARTY_NOTICES.md"

_NETWORK_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_SOL_QUOTE_MINT = "11111111111111111111111111111111"
# Bind legacy token program once as an explicit module-level contract.
_LEGACY_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
_TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

_EXPECTED_PACKAGE_IDENTITIES = {
    "pump-current-2026-07-15": ("crates.io", "pump-rust-client", "0.1.10"),
    "pump-historical-2025-05-08": ("npm", "@pump-fun/pump-sdk", "1.2.0"),
}
# Pin the complete reviewed records so URL, archive, IDL, license, publisher,
# projection or equivalence-reference drift requires an explicit test update.
_EXPECTED_SOURCE_PIN_SHA256 = {
    "pump-current-2026-07-15": ("898b04ee1eae335fd4eb36afeb93797ba96cadec1d5facd3413a9fb18b6e028c"),
    "pump-historical-2025-05-08": (
        "897e18a5a88f4ed7afbc0fa3e77268327ea5789bab719614da9ffa3dba0cd259"
    ),
}
_EXPECTED_TRADE_SIGNATURES = {
    "2Qa2ZHAKAzs6KWayPmobYP4YNkJfbnJ3m6oSQjNRNBo57Z7KgZBm22TPBmCcEawXthWfpTLBZVdMWWbf3Trspreo",
    "2RxiEtuGbTd8bWUdzxBZasVgymreRmquDt6NmJq6ec7EMMfM2DTixwv6ECb3nagFfwRiprNbr8ekSYqMSEkAYBjN",
    # Keep the go th ri xfmr6crz mfa t2g b9 twiiz nhd1 q2 f8 yzee pgr rz2 nd2 uyfh
    # qv17uam9 qq2bz h8 mnz zs y28x5 kq5fj arz57 component named inside the expected trade
    # signatures contract.
    "4goThRiXfmr6crzMfaT2gB9TWiizNHD1Q2F8YzeePgrRz2Nd2UyfhQv17uam9Qq2bzH8MnzZsY28x5Kq5fjARz57",
    "53SFCxXQkWff1s3n4Yf6oNFiPs3zVZMYAAVuoWLkC6WhbnsNjgEbg4J9RuawHtdp8Q6yEz7465pzhG4iK8EWfjsq",
    "5At5itU6139EwphTWbM4RZp3peq4X4yn3mDTf1Pe5fG7JQUw5AN8zFCjkyEE5gfwbtrjQVrQvHrZiKSEZvWDtnf5",
    "5frph8gBFyX7ayBmqntvwpTPwzZ8aF4kdfJAvC52Li2iDnnaRwtmcZP839Cm4YQUFx7GzsUUStCfAy3hAG69ir4u",
    "Qm2xtttvDYvSuQfXkKywcPfE4P22Pokn47jBx4x9h4DZPDhtGpjpjmyeUfCskoHnutUPBjwGuwgr9GQ7SYxpnZB",
    # Keep the wub pbya9 limxqhrbmf mcgz4i whqy mt h78po dhh k7 cf5bb dfy8as cb ubtt6h
    # dxpuvhrjnm dfbrka wle hib rz4 ke w component named inside the expected trade
    # signatures contract.
    "wubPBYa9LimxqhrbmfMCGz4iWHqyMtH78poDhhK7Cf5bbDFy8asCbUBtt6hDXPUVhrjnmDfbrkaWLeHibRz4KeW",
}
_EXPECTED_MATRIX = {
    ("CASHBACK", "TOKEN_2022", "BUY"),
    ("CASHBACK", "TOKEN_2022", "SELL"),
    # Keep the mayhem component named inside the expected matrix contract.
    ("MAYHEM", "TOKEN_2022", "BUY"),
    ("MAYHEM", "TOKEN_2022", "SELL"),
    ("NORMAL", "LEGACY_SPL_TOKEN", "BUY"),
    ("NORMAL", "LEGACY_SPL_TOKEN", "SELL"),
    ("TOKEN_2022", "TOKEN_2022", "BUY"),
    # Keep the token 2022 component named inside the expected matrix contract.
    ("TOKEN_2022", "TOKEN_2022", "SELL"),
}


@pytest.fixture(scope="module")
def golden_tree() -> GoldenTree:
    return load_verified_tree(_GOLDEN_ROOT)


def test_corpus_is_closed_and_pins_authoritative_program_sources(
    golden_tree: GoldenTree,
) -> None:
    """Pin the corpus to its network, upstream packages, and complete file closure."""
    provenance = golden_tree.provenance
    schema_evidence = _object(provenance["schema_evidence"])
    sources = _object(schema_evidence["sources"])
    # The program and quote asset must belong to the corpus's exact chain identity.
    assert provenance["program_id"] == _PROGRAM_ID
    assert provenance["quote_mint"] == _SOL_QUOTE_MINT
    assert _object(provenance["network"])["network_id"] == _NETWORK_ID
    assert _object(provenance["network"])["genesis_hash"] == _NETWORK_ID.removeprefix("solana:")

    # The aggregate schema and each projected layout retain identical upstream pins.
    aggregate_sources = {
        _text(pin["name"]): _object(pin["source_pin"])
        for pin in _objects(golden_tree.event_schema["pins"])
    }
    # Resolve individual projections separately to catch inconsistent source attribution.
    standard_sources = {
        name: _object(schema["source_pin"]) for name, schema in golden_tree.event_schemas.items()
    }
    # All three checked-in representations must carry the same complete source records.
    assert sources == aggregate_sources == standard_sources
    assert {
        name: canonical_json_sha256(source) for name, source in sources.items()
    } == _EXPECTED_SOURCE_PIN_SHA256
    # Content hashes alone do not identify the expected registry package and version.
    assert {
        name: (_text(source["registry"]), _text(source["package"]), _text(source["version"]))
        for name, source in sources.items()
    } == _EXPECTED_PACKAGE_IDENTITIES

    # Retain the precise package-level licensing basis and attribution path.
    licensing = _object(provenance["licensing"])
    assert licensing["redistribution_basis"] == "official-package-level-SPDX-declarations"
    assert licensing["notice_path"] == _THIRD_PARTY_NOTICES_PATH.name
    # Package metadata must not be presented as an archive-level copyright notice.
    assert (
        "Neither pinned archive contains a standalone license file or copyright-holder notice"
        in (_text(licensing["residual_caveat"]))
    )
    # Redistributed fixture attribution must also be visible in the public notice.
    notice = _THIRD_PARTY_NOTICES_PATH.read_text(encoding="utf-8")
    assert "pump-rust-client 0.1.10" in notice
    assert "@pump-fun/pump-sdk 1.2.0" in notice
    assert "non-redistribution equivalence" in notice.lower()

    # Unlisted files would escape the fixture's content-verification boundary.
    assert set(_object(provenance["files"])) == {
        path.relative_to(_GOLDEN_ROOT).as_posix()
        for path in _GOLDEN_ROOT.rglob("*")
        if path.is_file() and path.name != "provenance.json"
    }


def test_independent_decoder_has_no_production_import() -> None:
    # Execute the test independent decoder has no production import workflow in explicit,
    # reviewable steps.
    syntax = ast.parse(_DECODER_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(syntax):
        # Process ast.walk(syntax) inside the bounded test independent decoder has no
        # production import loop.
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        # Handle the test independent decoder has no production import complement of
        # isinstance(node, ast.Import) explicitly.
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
    assert not any(
        module == "backtest" or module.startswith("backtest.") for module in imported_modules
    )


# Define test all trade program data decodes and cross links to rpc evidence as one
# focused operation with an explicit boundary.
def test_all_trade_program_data_decodes_and_cross_links_to_rpc_evidence(
    golden_tree: GoldenTree,
) -> None:
    # Execute the test all trade program data decodes and cross links to rpc evidence
    # workflow in explicit, reviewable steps.
    vectors = _vectors(golden_tree)
    for vector in vectors:
        _verify_trade_vector(golden_tree, vector)


def test_mode_side_matrix_and_dual_token_program_evidence_are_exact(
    golden_tree: GoldenTree,
    # Close the test mode side matrix and dual token program evidence are exact signature
    # after its explicit inputs.
) -> None:
    # Execute the test mode side matrix and dual token program evidence are exact workflow
    # in explicit, reviewable steps.
    vectors = _vectors(golden_tree)
    _verify_mode_matrix(golden_tree, vectors)


def test_curve_transitions_fee_rounding_and_literal_outputs_are_independent(
    golden_tree: GoldenTree,
) -> None:
    # Execute the test curve transitions fee rounding and literal outputs are independent
    # workflow in explicit, reviewable steps.
    protocol_round_up_witnesses = 0
    creator_round_up_witnesses = 0
    sell_curve_floor_witnesses = 0
    modern_minus_one_witnesses = 0
    legacy_full_net_witnesses = 0
    # Assemble gross budget adjustment witnesses once so the test curve transitions fee
    # rounding and literal outputs are independent workflow shares one value.
    gross_budget_adjustment_witnesses = 0

    for vector in _vectors(golden_tree):
        # Process _vectors(golden_tree) inside the bounded test curve transitions fee
        # rounding and literal outputs are independent loop.
        event = _verify_trade_vector(golden_tree, vector)
        witnesses = _verify_independent_economics(vector, event)
        protocol_round_up_witnesses += witnesses["protocol_round_up"]
        creator_round_up_witnesses += witnesses["creator_round_up"]
        sell_curve_floor_witnesses += witnesses["sell_curve_floor"]
        # Assemble modern minus one witnesses once so the test curve transitions fee
        # rounding and literal outputs are independent workflow shares one value.
        modern_minus_one_witnesses += witnesses["modern_minus_one"]
        legacy_full_net_witnesses += witnesses["legacy_full_net"]
        gross_budget_adjustment_witnesses += witnesses["gross_budget_adjustment"]

    assert protocol_round_up_witnesses > 0
    assert creator_round_up_witnesses > 0
    # Verify sell_curve_floor_witnesses > 0 before this scenario is accepted.
    assert sell_curve_floor_witnesses > 0
    assert modern_minus_one_witnesses > 0
    assert legacy_full_net_witnesses == 1
    assert gross_budget_adjustment_witnesses > 0


def test_production_quotes_match_all_eight_decoded_program_vectors_exactly(
    # Keep the golden tree input explicit in the test production quotes match all eight
    # decoded program vectors exactly contract.
    golden_tree: GoldenTree,
) -> None:
    # Execute the test production quotes match all eight decoded program vectors exactly
    # workflow in explicit, reviewable steps.
    proofs = _mint_proofs(golden_tree)
    for vector in _vectors(golden_tree):
        # Process _vectors(golden_tree) inside the bounded test production quotes match
        # all eight decoded program vectors exactly loop.
        event = _verify_trade_vector(golden_tree, vector)
        _verify_production_quote(vector, event, proofs[_text(vector["mint"])])


def test_historical_formula_is_explicit_and_modern_formula_does_not_mask_it(
    golden_tree: GoldenTree,
) -> None:
    # Execute the test historical formula is explicit and modern formula does not mask it
    # workflow in explicit, reviewable steps.
    vector = next(
        vector for vector in _vectors(golden_tree) if vector["id"] == "legacy-normal-buy-v1"
    )
    event = _verify_trade_vector(golden_tree, vector)
    profile, state = _profile_and_state(
        # Keep the golden tree _mint_proofs step visible while building (profile, state).
        vector,
        event,
        _mint_proofs(golden_tree)[_text(vector["mint"])],
    )
    gross_budget = _integer(_object(vector["trade"])["gross_wallet_quote_debit_atomic"])

    # Assemble selected once so the test historical formula is explicit and modern formula
    # does not mask it workflow shares one value.
    selected = buy_quote(
        state,
        # Pass spendable gross sol lamports explicitly so buy_quote receives a reviewable
        # block time and integer input in test historical formula is explicit and modern
        # formula does not mask it.
        spendable_gross_sol_lamports=gross_budget,
        fee_profile=profile,
        effective_at_unix_s=_integer(vector["block_time"]),
    )
    modern = buy_quote(
        # Pass state explicitly so buy_quote receives a reviewable golden-modern-negative-
        # control-v1 and block time input in test historical formula is explicit and
        # modern formula does not mask it.
        state,
        spendable_gross_sol_lamports=gross_budget,
        fee_profile=PumpFeeProfile(
            profile_id="golden-modern-negative-control-v1",
            program_version=profile.program_version,
            # Pass buy formula version explicitly so PumpFeeProfile receives a reviewable
            # golden-modern-negative-control-v1 and program version input in test
            # historical formula is explicit and modern formula does not mask it.
            buy_formula_version=PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
            sell_formula_version=profile.sell_formula_version,
            effective_from_unix_s=profile.effective_from_unix_s,
            effective_until_unix_s=profile.effective_until_unix_s,
            protocol_fee_bps=profile.protocol_fee_bps,
            # Pass creator fee bps explicitly so PumpFeeProfile receives a reviewable
            # golden-modern-negative-control-v1 and program version input in test
            # historical formula is explicit and modern formula does not mask it.
            creator_fee_bps=profile.creator_fee_bps,
        ),
        effective_at_unix_s=_integer(vector["block_time"]),
    )

    assert selected.formula_version == PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1
    # Verify the tokens out atomic, selected and integer relationship before this scenario
    # is accepted.
    assert selected.tokens_out_atomic == _integer(_object(vector["trade"])["output_amount_atomic"])
    assert modern.tokens_out_atomic != selected.tokens_out_atomic

    with pytest.raises(PumpQuoteError) as unsupported:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # historical formula is explicit and modern formula does not mask it operation.
        buy_quote(
            state,
            spendable_gross_sol_lamports=gross_budget,
            fee_profile=PumpFeeProfile(
                profile_id="golden-unknown-formula-negative-control-v1",
                # Pass program version explicitly so PumpFeeProfile receives a reviewable
                # golden-unknown-formula-negative-control-v1 and pump-buy-unproven-v999
                # input in test historical formula is explicit and modern formula does not
                # mask it.
                program_version=profile.program_version,
                buy_formula_version="pump-buy-unproven-v999",
                sell_formula_version=profile.sell_formula_version,
                effective_from_unix_s=profile.effective_from_unix_s,
                effective_until_unix_s=profile.effective_until_unix_s,
                # Pass protocol fee bps explicitly so PumpFeeProfile receives a reviewable
                # golden-unknown-formula-negative-control-v1 and pump-buy-unproven-v999
                # input in test historical formula is explicit and modern formula does not
                # mask it.
                protocol_fee_bps=profile.protocol_fee_bps,
                creator_fee_bps=profile.creator_fee_bps,
            ),
            effective_at_unix_s=_integer(vector["block_time"]),
        )
    # Verify the code, unsupported formula version and value relationship before this
    # scenario is accepted.
    assert unsupported.value.code is PumpQuoteErrorCode.UNSUPPORTED_FORMULA_VERSION


def test_completion_and_migration_decode_in_causal_order(golden_tree: GoldenTree) -> None:
    # Execute the test completion and migration decode in causal order workflow in
    # explicit, reviewable steps.
    lifecycle = golden_tree.lifecycle
    assert lifecycle["schema"] == "pumpfun-program-v1-lifecycle-golden-v1"
    assert lifecycle["network_id"] == _NETWORK_ID
    assert lifecycle["program_id"] == _PROGRAM_ID
    rows = _objects(lifecycle["events"])
    # Verify the complete event, complete pump amm migration event and row relationship
    # before this scenario is accepted.
    assert [row["event"] for row in rows] == [
        "CompleteEvent",
        "CompletePumpAmmMigrationEvent",
    ]
    assert {row["signature"] for row in rows} == {
        # Keep the qhkq jrm w4 mpz2 abruzmktz v72a rkn9k xm1 bjmq gyxf mrbys7vf97c32 hwj
        # as lr ln s1vbjoz5 wvjycx eod8q prk expectation tied to row, signature and rows
        # in this scenario.
        "31QhkqJrmW4MPZ2ABRUZMKtzV72aRKn9kXM1BJMqGyxfMRbys7vf97c32HWjAsLrLnS1vbjoz5WVJycxEod8qPRK",
        "49mdxJ2sLHzVhQe52gUQQV9DfeDqEHohji5uqVK2RC62wbxDXht6nnvc9w3o8bEk2wUA45T53hZbAcpJSozqFjL6",
    }

    decoded_by_name: dict[str, tuple[dict[str, Any], dict[str, object]]] = {}
    for row in rows:
        # Process rows inside the bounded test completion and migration decode in causal
        # order loop.
        raw_ref = _object(row["raw"])
        raw = golden_tree.raw_document(_text(raw_ref["path"]))
        schema = golden_tree.schema_for_pin(_text(raw["event_schema_pin"]))
        decoded = decode_raw_events(raw, schema)
        program_data = raw["program_data"]
        # Assemble items once so the test completion and migration decode in causal order
        # workflow shares one value.
        items = (
            _objects(program_data) if isinstance(program_data, list) else [_object(program_data)]
        )
        selected = [
            (item, event.fields)
            # Keep the items zip step visible while building selected.
            for item, event in zip(items, decoded, strict=True)
            if event.name == row["event"]
        ]
        assert len(selected) == 1
        program_item, fields = selected[0]
        # Register text and row through _text so the decoded by name[ text(row['event'])]
        # table remains scannable.
        decoded_by_name[_text(row["event"])] = (raw, fields)
        assert (
            exact_file_sha256(golden_tree.root / _text(raw_ref["path"])) == raw_ref["file_sha256"]
        )
        assert program_item["decoded_bytes_sha256"] == raw_ref["program_data_sha256"]
        # Verify the signature, row and object relationship before this scenario is
        # accepted.
        assert _object(raw["transaction"])["signature"] == row["signature"]
        assert _object(raw["transaction"])["slot"] == row["slot"]
        assert _object(raw["transaction"])["transaction_index"] == row["transaction_index"]
        assert _object(raw["transaction"])["block_time"] == row["block_time"]
        assert program_item["log_index"] == row["event_log_index"]

    # Assemble (completion raw, completion) once so the test completion and migration
    # decode in causal order workflow shares one value.
    completion_raw, completion = decoded_by_name["CompleteEvent"]
    migration_raw, migration = decoded_by_name["CompletePumpAmmMigrationEvent"]
    assert completion["mint"] == migration["mint"] == lifecycle["mint"]
    assert completion["bonding_curve"] == migration["bonding_curve"] == lifecycle["bonding_curve"]
    assert completion["quote_mint"] == migration["quote_mint"] == _SOL_QUOTE_MINT
    # Verify the integer, slot and object relationship before this scenario is accepted.
    assert _integer(_object(completion_raw["transaction"])["slot"]) < _integer(
        _object(migration_raw["transaction"])["slot"]
    )

    completion_events = decode_raw_events(
        completion_raw,
        # Keep the schema for pin and golden tree schema_for_pin step visible while
        # building completion events.
        golden_tree.schema_for_pin(_text(completion_raw["event_schema_pin"])),
    )
    terminal_trade = next(event for event in completion_events if event.name == "TradeEvent")
    assert terminal_trade.fields["real_token_reserves"] == 0
    assert _integer(rows[0]["terminal_real_token_reserves_atomic"]) == 0
    # Verify the integer, terminal trade log index and event log index relationship before
    # this scenario is accepted.
    assert _integer(rows[0]["terminal_trade_log_index"]) < _integer(rows[0]["event_log_index"])
    assert migration["mint_amount"] == _integer(rows[1]["mint_amount_atomic"])
    assert migration["sol_amount"] == _integer(rows[1]["sol_amount_lamports"])
    assert migration["pool_migration_fee"] == _integer(rows[1]["pool_migration_fee_lamports"])
    assert migration["pool"] == rows[1]["pool"]


# Define test physical and semantic tampering fail closed as one focused operation with an
# explicit boundary.
def test_physical_and_semantic_tampering_fail_closed(
    golden_tree: GoldenTree,
    tmp_path: Path,
) -> None:
    # Execute the test physical and semantic tampering fail closed workflow in explicit,
    # reviewable steps.
    copied_root = tmp_path / "program-v1"
    shutil.copytree(golden_tree.root, copied_root)
    first_vector = _vectors(golden_tree)[0]
    raw_path = copied_root / _text(_object(first_vector["raw"])["path"])
    raw_path.write_bytes(raw_path.read_bytes() + b" ")
    # Acquire raises, golden fixture error and pytest at an explicit test physical and
    # semantic tampering fail closed context boundary so cleanup remains scoped.
    with pytest.raises(GoldenFixtureError, match="physical SHA-256"):
        load_verified_tree(copied_root)

    source_root = tmp_path / "source-program-v1"
    shutil.copytree(golden_tree.root, source_root)
    provenance_path = source_root / "provenance.json"
    aggregate_path = source_root / "upstream" / "pump-events.schema.json"
    standard_path = source_root / "upstream" / "pump-current.events.idl.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    standard = json.loads(standard_path.read_text(encoding="utf-8"))

    source_name = "pump-current-2026-07-15"
    provenance_source = _object(_object(provenance["schema_evidence"])["sources"])[source_name]
    aggregate_source = next(
        pin["source_pin"] for pin in _objects(aggregate["pins"]) if pin["name"] == source_name
    )
    standard_source = _object(standard["source_pin"])
    for source in (provenance_source, aggregate_source, standard_source):
        # A coordinated but unreviewed metadata rewrite must still fail closed.
        _object(_object(source)["publisher_evidence"])["identity"] = "unreviewed-publisher"

    for path, document in ((aggregate_path, aggregate), (standard_path, standard)):
        # Recompute physical hashes to prove the semantic source pin remains independently bound.
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = _object(provenance["files"])
    files["upstream/pump-events.schema.json"] = exact_file_sha256(aggregate_path)
    files["upstream/pump-current.events.idl.json"] = exact_file_sha256(standard_path)
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GoldenFixtureError, match="reviewed source pin SHA-256"):
        load_verified_tree(source_root)

    raw = copy.deepcopy(golden_tree.raw_document(_text(_object(first_vector["raw"])["path"])))
    program_data = _object(raw["program_data"])
    encoded = _text(program_data["log_line"]).removeprefix("Program data: ")
    # Assemble payload once so the test physical and semantic tampering fail closed
    # workflow shares one value.
    payload = bytearray(base64.b64decode(encoded, validate=True))
    payload[-1] ^= 1
    program_data["log_line"] = "Program data: " + base64.b64encode(payload).decode()
    program_data["decoded_bytes_sha256"] = hashlib.sha256(payload).hexdigest()
    schema = golden_tree.schema_for_pin(_text(raw["event_schema_pin"]))
    # Acquire raises, golden fixture error and pytest at an explicit test physical and
    # semantic tampering fail closed context boundary so cleanup remains scoped.
    with pytest.raises(GoldenFixtureError, match="independently decoded"):
        decode_raw_event(raw, schema)

    tampered_vector = copy.deepcopy(first_vector)
    trade = _object(tampered_vector["trade"])
    trade["output_amount_atomic"] = str(_integer(trade["output_amount_atomic"]) + 1)
    # Acquire raises, golden fixture error and pytest at an explicit test physical and
    # semantic tampering fail closed context boundary so cleanup remains scoped.
    with pytest.raises(GoldenFixtureError, match="output amount"):
        _verify_trade_vector(golden_tree, tampered_vector)

    with pytest.raises(GoldenFixtureError, match="four-by-two"):
        _verify_mode_matrix(golden_tree, _vectors(golden_tree)[:-1])


def _vectors(tree: GoldenTree) -> list[dict[str, Any]]:
    # Execute the vectors workflow in explicit, reviewable steps.
    document = tree.vectors
    _ensure(document.get("schema") == "pumpfun-program-v1-trade-golden-v1", "vector schema")
    _ensure(document.get("network_id") == _NETWORK_ID, "vector NetworkId")
    _ensure(document.get("program_id") == _PROGRAM_ID, "vector program id")
    _ensure(document.get("quote_mint") == _SOL_QUOTE_MINT, "vector quote mint")
    # Assemble vectors once so the vectors workflow shares one value.
    vectors = _objects(document.get("vectors"))
    _ensure(_integer(document.get("vector_count")) == len(vectors), "vector count")
    _ensure(
        {vector.get("signature") for vector in vectors} == _EXPECTED_TRADE_SIGNATURES,
        "signatures",
        # Complete _ensure only after its signature and signatures inputs are visible in
        # vectors.
    )
    _ensure(len({vector.get("id") for vector in vectors}) == len(vectors), "unique vector ids")
    return vectors


def _verify_trade_vector(tree: GoldenTree, vector: dict[str, Any]) -> dict[str, object]:
    # Execute the verify trade vector workflow in explicit, reviewable steps.
    raw_ref = _object(vector.get("raw"))
    raw_path = _text(raw_ref.get("path"))
    raw = tree.raw_document(raw_path)
    schema_pin = _text(vector.get("event_schema_pin"))
    _ensure(raw.get("event_schema_pin") == schema_pin, "event schema pin")
    # Assemble event once so the verify trade vector workflow shares one value.
    event = decode_raw_event(raw, tree.schema_for_pin(schema_pin))
    _ensure(event.name == "TradeEvent", "trade event type")
    fields = event.fields

    transaction = _object(raw.get("transaction"))
    instruction = _object(raw.get("instruction"))
    # Assemble position once so the verify trade vector workflow shares one value.
    position = _object(vector.get("position"))
    program_data = _object(raw.get("program_data"))
    fees = _object(vector.get("fees"))
    trade = _object(vector.get("trade"))

    _ensure(transaction.get("signature") == vector.get("signature"), "signature")
    # Invoke _ensure for slot and get as a visible verify trade vector step.
    _ensure(transaction.get("slot") == position.get("slot"), "slot")
    _ensure(transaction.get("transaction_index") == position.get("transaction_index"), "tx index")
    _ensure(transaction.get("block_time") == vector.get("block_time"), "block time")
    _ensure(transaction.get("fee_lamports") == fees.get("network_fee_lamports"), "network fee")
    _ensure(instruction.get("outer_index") == position.get("instruction_outer_index"), "outer ix")
    # Invoke _ensure for inner index and instruction inner index as a visible verify trade
    # vector step.
    _ensure(instruction.get("inner_index") == position.get("instruction_inner_index"), "inner ix")
    _ensure(program_data.get("log_index") == position.get("event_log_index"), "event log index")
    _ensure(instruction.get("mint_account") == vector.get("mint"), "instruction mint")
    _ensure(instruction.get("user_account") == vector.get("user"), "instruction user")
    _ensure(instruction.get("quote_mint_account") == _SOL_QUOTE_MINT, "instruction quote mint")

    # Invoke _ensure for mint and event mint as a visible verify trade vector step.
    _ensure(fields["mint"] == vector.get("mint"), "event mint")
    _ensure(fields["creator"] == vector.get("creator"), "event creator")
    _ensure(fields["user"] == vector.get("user"), "event user")
    _ensure(fields["timestamp"] == _integer(vector.get("block_time")), "event timestamp")
    _ensure(fields["is_buy"] is (vector.get("side") == "BUY"), "event side")
    # Invoke _ensure for sol amount and quote amount atomic as a visible verify trade
    # vector step.
    _ensure(fields["sol_amount"] == _integer(trade.get("quote_amount_atomic")), "quote amount")
    _ensure(fields["token_amount"] == _integer(trade.get("token_amount_atomic")), "token amount")
    _ensure(fields["fee_basis_points"] == _integer(fees.get("protocol_bps")), "protocol bps")
    _ensure(fields["fee"] == _integer(fees.get("protocol_fee_atomic")), "protocol fee")
    _ensure(fields["creator_fee_basis_points"] == _integer(fees.get("creator_bps")), "creator bps")
    # Invoke _ensure for creator fee and creator fee atomic as a visible verify trade
    # vector step.
    _ensure(fields["creator_fee"] == _integer(fees.get("creator_fee_atomic")), "creator fee")
    _ensure(
        _event_integer(fields, "cashback_fee_basis_points") == _integer(fees.get("cashback_bps")),
        "cashback bps",
    )
    # Invoke _ensure for cashback and cashback atomic as a visible verify trade vector
    # step.
    _ensure(_event_integer(fields, "cashback") == _integer(fees.get("cashback_atomic")), "cashback")
    _ensure(
        _event_integer(fields, "buyback_fee_basis_points") == _integer(fees.get("buyback_bps")),
        "buyback bps",
    )
    # Invoke _ensure for buyback fee and buyback atomic as a visible verify trade vector
    # step.
    _ensure(
        _event_integer(fields, "buyback_fee") == _integer(fees.get("buyback_atomic")),
        "buyback",
    )

    expected_output = (
        # Keep the integer and get _integer step visible while building expected output.
        _integer(trade.get("token_amount_atomic"))
        if vector.get("side") == "BUY"
        else _integer(trade.get("net_wallet_quote_credit_atomic"))
    )
    _ensure(_integer(trade.get("output_amount_atomic")) == expected_output, "output amount")
    # Invoke _ensure for file sha256 and raw file digest as a visible verify trade vector
    # step.
    _ensure(
        exact_file_sha256(tree.root / raw_path) == raw_ref.get("file_sha256"),
        "raw file digest",
    )
    _ensure(
        # Pass program data explicitly to _ensure for decoded bytes sha256 and program
        # data sha256.
        program_data.get("decoded_bytes_sha256") == raw_ref.get("program_data_sha256"),
        "program-data digest",
    )
    return fields


def _verify_mode_matrix(tree: GoldenTree, vectors: list[dict[str, Any]]) -> None:
    # Execute the verify mode matrix workflow in explicit, reviewable steps.
    cells = {
        (
            _text(vector.get("mode")),
            _text(vector.get("token_program_family")),
            _text(vector.get("side")),
            # Complete the cells group only after its semantic components are visible.
        )
        for vector in vectors
    }
    _ensure(len(vectors) == 8 and cells == _EXPECTED_MATRIX, "four-by-two mode/side matrix")
    declared = {
        # Keep the mode component named inside the declared contract.
        (mode, family, side)
        for raw_key, raw_sides in _object(tree.vectors.get("matrix")).items()
        for mode, family in [_text(raw_key).split(":", maxsplit=1)]
        for side in _strings(raw_sides)
    }
    # Invoke _ensure for declared four-by-two mode/side matrix and declared as a visible
    # verify mode matrix step.
    _ensure(declared == _EXPECTED_MATRIX, "declared four-by-two mode/side matrix")

    proofs = _mint_proofs(tree)
    for vector in vectors:
        # Process vectors inside the bounded verify mode matrix loop.
        fields = _verify_trade_vector(tree, vector)
        mode = _text(vector.get("mode"))
        family = _text(vector.get("token_program_family"))
        evidence = _object(vector.get("mode_evidence"))
        expected_program = (
            # Keep the family component named inside the expected program contract.
            _LEGACY_TOKEN_PROGRAM if family == "LEGACY_SPL_TOKEN" else _TOKEN_2022_PROGRAM
        )
        _ensure(evidence.get("token_program") == expected_program, "declared token program")
        raw = tree.raw_document(_text(_object(vector.get("raw"))["path"]))
        _ensure(
            # Pass object explicitly to _ensure for token program account and instruction.
            _object(raw["instruction"]).get("token_program_account") == expected_program,
            "instruction token program",
        )
        proof = proofs[_text(vector.get("mint"))]
        _ensure(proof.get("owner") == expected_program, "mint owner token program")

        # Guard this path with mode == 'NORMAL' before applying effects.
        if mode == "NORMAL":
            # Handle the verify mode matrix mode == 'NORMAL' branch as a distinct logical
            # block.
            _ensure(family == "LEGACY_SPL_TOKEN", "legacy normal family")
            _ensure(
                evidence.get("historical_idl_has_explicit_mode_fields") is False,
                "legacy mode evidence",
            )
        # Route all remaining cases through the explicit alternative branch.
        else:
            # Handle the verify mode matrix complement of mode == 'NORMAL' explicitly.
            _ensure(family == "TOKEN_2022", "current mode token family")
            mayhem = bool(fields["mayhem_mode"])
            cashback_bps = _event_integer(fields, "cashback_fee_basis_points")
            if mode == "TOKEN_2022":
                _ensure(not mayhem and cashback_bps == 0, "plain Token-2022 mode")
            # Handle the verify mode matrix complement of mode == 'TOKEN_2022' explicitly.
            elif mode == "CASHBACK":
                _ensure(not mayhem and cashback_bps > 0, "cashback mode")
            # Handle the verify mode matrix complement of mode == 'CASHBACK' explicitly.
            elif mode == "MAYHEM":
                # Handle the verify mode matrix mode == 'MAYHEM' branch as a distinct
                # logical block.
                _ensure(mayhem and cashback_bps == 0, "Mayhem mode")
                _ensure(evidence.get("is_fee_exempt_agent_trade") is False, "Mayhem user trade")
                _ensure(
                    vector.get("user") != evidence.get("documented_fee_exempt_agent"),
                    "Mayhem agent exclusion",
                    # Complete _ensure only after its user and documented fee exempt agent
                    # inputs are visible in verify mode matrix.
                )
            else:
                raise GoldenFixtureError(f"unsupported golden mode: {mode}")


def _verify_independent_economics(
    vector: dict[str, Any],
    # Keep the event input explicit in the verify independent economics contract.
    event: dict[str, object],
    # Keep the dict input explicit in the verify independent economics contract.
) -> dict[str, int]:
    # Execute the verify independent economics workflow in explicit, reviewable steps.
    side = _text(vector.get("side"))
    formula = _text(vector.get("formula"))
    trade = _object(vector.get("trade"))
    fees = _object(vector.get("fees"))
    curve = _object(vector.get("curve"))
    # Assemble pre once so the verify independent economics workflow shares one value.
    pre = _integer_map(_object(curve.get("pre")))
    post = _integer_map(_object(curve.get("post")))
    sol_amount = _event_integer(event, "sol_amount")
    token_amount = _event_integer(event, "token_amount")

    _ensure(
        # Pass post explicitly to _ensure for virtual sol reserves lamports and virtual
        # sol reserves.
        post["virtual_sol_reserves_lamports"] == _event_integer(event, "virtual_sol_reserves"),
        "post virtual SOL",
    )
    _ensure(
        post["virtual_token_reserves_atomic"] == _event_integer(event, "virtual_token_reserves"),
        # Pass post virtual token explicitly so _ensure receives a reviewable virtual
        # token reserves atomic and virtual token reserves input in verify independent
        # economics.
        "post virtual token",
    )
    _ensure(
        post["real_sol_reserves_lamports"] == _event_integer(event, "real_sol_reserves"),
        "post real SOL",
        # Complete _ensure only after its real sol reserves lamports and real sol reserves
        # inputs are visible in verify independent economics.
    )
    _ensure(
        post["real_token_reserves_atomic"] == _event_integer(event, "real_token_reserves"),
        "post real token",
    )

    # Assemble protocol bps once so the verify independent economics workflow shares one
    # value.
    protocol_bps = _integer(fees.get("protocol_bps"))
    creator_bps = _integer(fees.get("creator_bps"))
    cashback_bps = _integer(fees.get("cashback_bps"))
    protocol_fee = _integer(fees.get("protocol_fee_atomic"))
    creator_fee = _integer(fees.get("creator_fee_atomic"))
    # Assemble cashback once so the verify independent economics workflow shares one
    # value.
    cashback = _integer(fees.get("cashback_atomic"))
    buyback_bps = _integer(fees.get("buyback_bps"))
    buyback = _integer(fees.get("buyback_atomic"))

    _ensure(protocol_fee == _ceil_bps(sol_amount, protocol_bps), "protocol fee rounding")
    _ensure(creator_fee == _ceil_bps(sol_amount, creator_bps), "creator fee rounding")
    # Invoke _ensure for cashback fee rounding and ceil bps as a visible verify
    # independent economics step.
    _ensure(cashback == _ceil_bps(sol_amount, cashback_bps), "cashback fee rounding")
    _ensure(not (creator_fee and cashback), "creator/cashback exclusivity")
    _ensure(buyback == protocol_fee * buyback_bps // 10_000, "buyback suballocation")

    witnesses = {
        "protocol_round_up": int(protocol_bps > 0 and sol_amount * protocol_bps % 10_000 != 0),
        # Register creator bps and cashback bps through int so the witnesses table remains
        # scannable.
        "creator_round_up": int(
            (creator_bps > 0 and sol_amount * creator_bps % 10_000 != 0)
            or (cashback_bps > 0 and sol_amount * cashback_bps % 10_000 != 0)
        ),
        "sell_curve_floor": 0,
        # Keep the modern minus one component named inside the witnesses contract.
        "modern_minus_one": 0,
        "legacy_full_net": 0,
        "gross_budget_adjustment": 0,
    }

    if side == "BUY":
        # Handle the verify independent economics side == 'BUY' branch as a distinct
        # logical block.
        _ensure(
            post["virtual_sol_reserves_lamports"]
            == pre["virtual_sol_reserves_lamports"] + sol_amount,
            "buy virtual SOL transition",
        )
        # Invoke _ensure for real sol reserves lamports and buy real sol transition as a
        # visible verify independent economics step.
        _ensure(
            post["real_sol_reserves_lamports"] == pre["real_sol_reserves_lamports"] + sol_amount,
            "buy real SOL transition",
        )
        _ensure(
            # Pass post explicitly so _ensure receives a reviewable virtual token reserves
            # atomic and buy virtual token transition input in verify independent
            # economics.
            post["virtual_token_reserves_atomic"]
            == pre["virtual_token_reserves_atomic"] - token_amount,
            "buy virtual token transition",
        )
        _ensure(
            # Pass post explicitly so _ensure receives a reviewable real token reserves
            # atomic and buy real token transition input in verify independent economics.
            post["real_token_reserves_atomic"] == pre["real_token_reserves_atomic"] - token_amount,
            "buy real token transition",
        )
        if formula == PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1:
            # Handle the verify independent economics formula and pump buy exact gross sol
            # formula v1 condition as a distinct block.
            curve_input = sol_amount - 1
            witnesses["modern_minus_one"] = int(_curve_buy_output(pre, sol_amount) != token_amount)
        # Handle the verify independent economics complement of formula and pump buy exact
        # gross sol formula v1 explicitly.
        elif formula == PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1:
            # Handle the verify independent economics formula and pump buy legacy exact
            # net sol formula v1 condition as a distinct block.
            curve_input = sol_amount
            _ensure(
                _curve_buy_output(pre, sol_amount - 1) != token_amount,
                "legacy no-minus-one witness",
            )
            # Assemble witnesses['legacy full net'] once so the verify independent
            # economics workflow shares one value.
            witnesses["legacy_full_net"] = 1
        else:
            raise GoldenFixtureError(f"unsupported buy golden formula: {formula}")
        expected_tokens = (
            curve_input
            # Keep the pre component named inside the expected tokens contract.
            * pre["virtual_token_reserves_atomic"]
            // (pre["virtual_sol_reserves_lamports"] + curve_input)
        )
        _ensure(expected_tokens == token_amount, "independent buy curve output")
        _ensure(
            # Pass integer explicitly to _ensure for net curve quote input atomic and buy
            # curve input.
            _integer(trade.get("net_curve_quote_input_atomic")) == sol_amount,
            "buy curve input",
        )
        gross = sol_amount + protocol_fee + creator_fee + cashback
        _ensure(_integer(trade.get("gross_wallet_quote_debit_atomic")) == gross, "buy gross debit")
        # Invoke _ensure for output amount atomic and buy output as a visible verify
        # independent economics step.
        _ensure(_integer(trade.get("output_amount_atomic")) == token_amount, "buy output")

        total_bps = protocol_bps + creator_bps + cashback_bps
        initial_net = gross * 10_000 // (10_000 + total_bps)
        before_adjustment = (
            initial_net
            # Keep the initial net _ceil_bps step visible while building before
            # adjustment.
            + _ceil_bps(initial_net, protocol_bps)
            + _ceil_bps(initial_net, creator_bps + cashback_bps)
        )
        excess = max(0, before_adjustment - gross)
        _ensure(initial_net - excess == sol_amount, "gross-budget net derivation")
        # Assemble witnesses['gross budget adjustment'] once so the verify independent
        # economics workflow shares one value.
        witnesses["gross_budget_adjustment"] = int(excess > 0)
    # Handle the verify independent economics complement of side == 'BUY' explicitly.
    elif side == "SELL":
        # Handle the verify independent economics side == 'SELL' branch as a distinct
        # logical block.
        _ensure(
            post["virtual_sol_reserves_lamports"]
            == pre["virtual_sol_reserves_lamports"] - sol_amount,
            "sell virtual SOL transition",
        )
        # Invoke _ensure for real sol reserves lamports and sell real sol transition as a
        # visible verify independent economics step.
        _ensure(
            post["real_sol_reserves_lamports"] == pre["real_sol_reserves_lamports"] - sol_amount,
            "sell real SOL transition",
        )
        _ensure(
            # Pass post explicitly so _ensure receives a reviewable virtual token reserves
            # atomic and sell virtual token transition input in verify independent
            # economics.
            post["virtual_token_reserves_atomic"]
            == pre["virtual_token_reserves_atomic"] + token_amount,
            "sell virtual token transition",
        )
        _ensure(
            # Pass post explicitly so _ensure receives a reviewable real token reserves
            # atomic and sell real token transition input in verify independent economics.
            post["real_token_reserves_atomic"] == pre["real_token_reserves_atomic"] + token_amount,
            "sell real token transition",
        )
        numerator = token_amount * pre["virtual_sol_reserves_lamports"]
        denominator = pre["virtual_token_reserves_atomic"] + token_amount
        # Invoke _ensure for independent sell curve output and sol amount as a visible
        # verify independent economics step.
        _ensure(numerator // denominator == sol_amount, "independent sell curve output")
        witnesses["sell_curve_floor"] = int(numerator % denominator != 0)
        net = sol_amount - protocol_fee - creator_fee - cashback
        _ensure(
            _integer(trade.get("gross_curve_quote_output_atomic")) == sol_amount,
            # Pass sell gross output explicitly so _ensure receives a reviewable gross
            # curve quote output atomic and sell gross output input in verify independent
            # economics.
            "sell gross output",
        )
        _ensure(_integer(trade.get("net_wallet_quote_credit_atomic")) == net, "sell net credit")
        _ensure(_integer(trade.get("output_amount_atomic")) == net, "sell output")
        _ensure(formula == PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1, "sell formula")
    # Route all remaining cases through the explicit alternative branch.
    else:
        raise GoldenFixtureError(f"unsupported side: {side}")
    return witnesses


def _verify_production_quote(
    vector: dict[str, Any],
    # Keep the event input explicit in the verify production quote contract.
    event: dict[str, object],
    mint_proof: dict[str, Any],
) -> None:
    # Execute the verify production quote workflow in explicit, reviewable steps.
    profile, state = _profile_and_state(vector, event, mint_proof)
    trade = _object(vector["trade"])
    fees = _object(vector["fees"])
    timestamp = _integer(vector["block_time"])
    protocol_fee = _integer(fees["protocol_fee_atomic"])
    # Assemble effective creator fee once so the verify production quote workflow shares
    # one value.
    effective_creator_fee = _integer(fees["creator_fee_atomic"]) + _integer(fees["cashback_atomic"])

    if vector["side"] == "BUY":
        # Handle the verify production quote vector['side'] == 'BUY' branch as a distinct
        # logical block.
        quote = buy_quote(
            state,
            spendable_gross_sol_lamports=_integer(trade["gross_wallet_quote_debit_atomic"]),
            fee_profile=profile,
            effective_at_unix_s=timestamp,
            # Complete buy_quote only after its gross wallet quote debit atomic and integer
            # inputs are visible in verify production quote.
        )
        _ensure(quote.formula_version == vector["formula"], "production buy formula")
        _ensure(
            quote.net_curve_sol_lamports == _integer(trade["net_curve_quote_input_atomic"]),
            "production buy curve input",
            # Complete _ensure only after its net curve quote input atomic and production buy
            # curve input inputs are visible in verify production quote.
        )
        _ensure(
            quote.tokens_out_atomic == _integer(trade["output_amount_atomic"]),
            "production buy output",
        )
        # Invoke _ensure for gross wallet quote debit atomic and production buy gross as a
        # visible verify production quote step.
        _ensure(
            quote.gross_sol_spent_lamports == _integer(trade["gross_wallet_quote_debit_atomic"]),
            "production buy gross",
        )
        _ensure(quote.unspent_sol_lamports == 0, "production buy unspent budget")
    # Route all remaining cases through the explicit alternative branch.
    else:
        # Handle the verify production quote complement of vector['side'] == 'BUY'
        # explicitly.
        quote = sell_quote(
            state,
            tokens_in_atomic=_integer(trade["token_amount_atomic"]),
            fee_profile=profile,
            effective_at_unix_s=timestamp,
            # Complete sell_quote only after its token amount atomic and integer inputs are
            # visible in verify production quote.
        )
        _ensure(quote.formula_version == vector["formula"], "production sell formula")
        _ensure(
            quote.gross_curve_sol_lamports == _integer(trade["gross_curve_quote_output_atomic"]),
            "production sell gross",
            # Complete _ensure only after its gross curve quote output atomic and production
            # sell gross inputs are visible in verify production quote.
        )
        _ensure(
            quote.sol_out_lamports == _integer(trade["output_amount_atomic"]),
            "production sell output",
        )

    # Invoke _ensure for production protocol fee and protocol fee lamports as a visible
    # verify production quote step.
    _ensure(quote.fees.protocol_fee_lamports == protocol_fee, "production protocol fee")
    _ensure(
        quote.fees.creator_fee_lamports == effective_creator_fee,
        "production creator/cashback component",
    )
    # Assemble cashback expected once so the verify production quote workflow shares one
    # value.
    cashback_expected = effective_creator_fee if vector["mode"] == "CASHBACK" else None
    _ensure(
        quote.fees.cashback_receivable_lamports == cashback_expected,
        "production cashback receivable",
    )

    # Assemble token program once so the verify production quote workflow shares one
    # value.
    token_program = (
        PumpTokenProgram.LEGACY_SPL_TOKEN
        if vector["token_program_family"] == "LEGACY_SPL_TOKEN"
        else PumpTokenProgram.TOKEN_2022
    )
    # Assemble protocol route once so the verify production quote workflow shares one
    # value.
    protocol_route = (
        PumpProtocolFeeRoute.MAYHEM_RECIPIENT
        if vector["mode"] == "MAYHEM"
        else PumpProtocolFeeRoute.NORMAL_RECIPIENT
    )
    # Assemble creator route once so the verify production quote workflow shares one
    # value.
    creator_route = (
        PumpCreatorFeeRoute.CASHBACK_RECEIVABLE
        if vector["mode"] == "CASHBACK"
        else PumpCreatorFeeRoute.CREATOR_VAULT
    )
    # Invoke _ensure for production token program and token program as a visible verify
    # production quote step.
    _ensure(quote.fees.routing.token_program is token_program, "production token program")
    _ensure(quote.fees.routing.protocol_fee_route is protocol_route, "production protocol route")
    _ensure(quote.fees.routing.creator_fee_route is creator_route, "production creator route")


def _profile_and_state(
    vector: dict[str, Any],
    # Keep the event input explicit in the profile and state contract.
    event: dict[str, object],
    mint_proof: dict[str, Any],
) -> tuple[PumpFeeProfile, PumpCurveStateV1]:
    # Execute the profile and state workflow in explicit, reviewable steps.
    fees = _object(vector["fees"])
    curve = _object(vector["curve"])
    pre = _integer_map(_object(curve["pre"]))
    timestamp = _integer(vector["block_time"])
    effective_creator_bps = _integer(fees["creator_bps"]) + _integer(fees["cashback_bps"])
    # Assemble formula once so the profile and state workflow shares one value.
    formula = _text(vector["formula"])
    profile = PumpFeeProfile(
        profile_id=f"{_text(vector['id'])}-golden-profile",
        program_version=PUMP_STATIC_PROGRAM_CONTRACT_V1,
        buy_formula_version=(
            # Pass formula explicitly so PumpFeeProfile receives a reviewable -golden-
            # profile and id input in profile and state.
            formula if vector["side"] == "BUY" else PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1
        ),
        sell_formula_version=(
            formula if vector["side"] == "SELL" else PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1
        ),
        # Pass effective from unix s explicitly so PumpFeeProfile receives a reviewable
        # -golden-profile and id input in profile and state.
        effective_from_unix_s=timestamp,
        effective_until_unix_s=timestamp + 1,
        protocol_fee_bps=_integer(fees["protocol_bps"]),
        creator_fee_bps=effective_creator_bps,
    )
    # Assemble state once so the profile and state workflow shares one value.
    state = PumpCurveStateV1(
        virtual_token_reserves_atomic=pre["virtual_token_reserves_atomic"],
        virtual_sol_reserves_lamports=pre["virtual_sol_reserves_lamports"],
        real_token_reserves_atomic=pre["real_token_reserves_atomic"],
        real_sol_reserves_lamports=pre["real_sol_reserves_lamports"],
        # Keep the integer and mint proof _integer step visible while building state.
        token_total_supply_atomic=_integer(mint_proof["supply_amount"]),
        lifecycle=PumpCurveLifecycle.ACTIVE,
        mode=PumpMode(_text(vector["mode"])),
    )
    _ensure(event["timestamp"] == timestamp, "profile effective timestamp")
    # Return the completed profile and state result without a hidden fallback.
    return profile, state


def _mint_proofs(tree: GoldenTree) -> dict[str, dict[str, Any]]:
    # Execute the mint proofs workflow in explicit, reviewable steps.
    document = tree.mint_accounts
    _ensure(
        document.get("schema") == "solana-finalized-mint-account-evidence/v1",
        "mint proof schema",
    )
    # Assemble network once so the mint proofs workflow shares one value.
    network = _object(document.get("network"))
    _ensure(network.get("network_id") == _NETWORK_ID, "mint proof NetworkId")
    _ensure(
        network.get("genesis_hash") == _NETWORK_ID.removeprefix("solana:"),
        "mint proof genesis",
        # Complete _ensure only after its genesis hash and solana: inputs are visible in mint
        # proofs.
    )
    rpc = _object(document.get("rpc"))
    _ensure(rpc.get("commitment") == "finalized", "mint proof commitment")
    proofs = {_text(proof.get("mint")): proof for proof in _objects(document.get("proofs"))}
    for proof in proofs.values():
        # Process proofs.values() inside the bounded mint proofs loop.
        payload = base64.b64decode(_text(proof.get("account_data_base64")), validate=True)
        _ensure(
            hashlib.sha256(payload).hexdigest() == proof.get("account_data_sha256"),
            "mint account digest",
        )
        # Invoke _ensure for space and mint account size as a visible mint proofs step.
        _ensure(len(payload) == _integer(proof.get("space")), "mint account size")
        _integer(proof.get("context_slot"))
        _integer(proof.get("supply_context_slot"))
        _integer(proof.get("supply_amount"))
    return proofs


# Define curve buy output as one focused operation with an explicit boundary.
def _curve_buy_output(pre: dict[str, int], curve_input: int) -> int:
    # Execute the curve buy output workflow in explicit, reviewable steps.
    return (
        curve_input
        * pre["virtual_token_reserves_atomic"]
        // (pre["virtual_sol_reserves_lamports"] + curve_input)
    )


# Define ceil bps as one focused operation with an explicit boundary.
def _ceil_bps(amount: int, basis_points: int) -> int:
    # Execute the ceil bps workflow in explicit, reviewable steps.
    if basis_points == 0:
        return 0
    return (amount * basis_points + 9_999) // 10_000


def _event_integer(fields: dict[str, object], name: str) -> int:
    # Execute the event integer workflow in explicit, reviewable steps.
    value = fields.get(name, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoldenFixtureError(f"decoded event field is not an integer: {name}")
    return value


def _integer_map(value: dict[str, Any]) -> dict[str, int]:
    # Return the completed integer map result without a hidden fallback.
    return {key: _integer(item) for key, item in value.items()}


def _integer(value: object) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or str(int(value)) != value:
        raise GoldenFixtureError("expected canonical decimal integer string")
    return int(value)


def _text(value: object) -> str:
    # Execute the text workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value:
        raise GoldenFixtureError("expected non-empty text")
    return value


def _object(value: object) -> dict[str, Any]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict):
        raise GoldenFixtureError("expected JSON object")
    return value


def _objects(value: object) -> list[dict[str, Any]]:
    # Execute the objects workflow in explicit, reviewable steps.
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise GoldenFixtureError("expected JSON object array")
    return value


def _strings(value: object) -> list[str]:
    # Execute the strings workflow in explicit, reviewable steps.
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GoldenFixtureError("expected string array")
    return value


def _ensure(condition: bool, label: str) -> None:
    # Execute the ensure workflow in explicit, reviewable steps.
    if not condition:
        raise GoldenFixtureError(f"{label} mismatch")
