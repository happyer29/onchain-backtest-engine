"""Independent offline reader for the checked-in Pump program golden evidence.

This module intentionally has no dependency on ``backtest``.  It decodes the
literal Anchor event bytes through the pinned IDL extract so a production
projector or quote implementation cannot manufacture its own expected values.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_FULL_NETWORK_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
# Bind pump program id once as an explicit module-level contract.
_PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_HEX_DIGEST_LENGTH = 64

# Keep every licensed source pin closed so a future edit cannot silently turn an
# equivalence-only reference back into the redistribution source.
_SOURCE_PIN_KEYS = {
    "registry",
    "package",
    "version",
    "metadata_url",
    # Archive identity binds the exact registry payload independently of its URL.
    "archive_url",
    "archive_size_bytes",
    "archive_sha256",
    "registry_integrity",
    # The selected IDL is separately pinned inside the registry archive.
    "idl_path",
    "idl_size_bytes",
    "idl_sha256",
    "license",
    # Publisher, projection and equivalence evidence have distinct roles.
    "publisher_evidence",
    "projection",
    "equivalence_reference",
}
_EQUIVALENCE_REFERENCE_KEYS = {
    "purpose",
    "repository",
    "commit",
    "path",
    # Raw identity proves equivalence but is explicitly not a license basis.
    "raw_url",
    "raw_size_bytes",
    "raw_sha256",
    "redistribution_basis",
}
# Bind the complete reviewed source records, not only user-editable package labels.
_EXPECTED_SOURCE_PIN_SHA256 = {
    "pump-current-2026-07-15": ("898b04ee1eae335fd4eb36afeb93797ba96cadec1d5facd3413a9fb18b6e028c"),
    "pump-historical-2025-05-08": (
        "897e18a5a88f4ed7afbc0fa3e77268327ea5789bab719614da9ffa3dba0cd259"
    ),
}


class GoldenFixtureError(AssertionError):
    """The checked-in evidence is missing, corrupt, or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class DecodedEvent:
    name: str
    fields: dict[str, object]
    payload: bytes


# Keep the golden tree contract and validation rules together.
@dataclass(frozen=True, slots=True)
class GoldenTree:
    root: Path
    provenance: dict[str, Any]
    event_schema: dict[str, Any]
    # Declare event schemas explicitly in the golden tree contract.
    event_schemas: dict[str, dict[str, Any]]
    vectors: dict[str, Any]
    lifecycle: dict[str, Any]
    mint_accounts: dict[str, Any]

    def raw_document(self, relative_path: str) -> dict[str, Any]:
        # Return the completed golden tree raw document result without a hidden fallback.
        return load_json_object(_safe_member(self.root, relative_path))

    def schema_for_pin(self, name: str) -> dict[str, Any]:
        # Execute the golden tree schema for pin workflow in explicit, reviewable steps.
        try:
            return self.event_schemas[name]
        except KeyError as error:
            raise GoldenFixtureError(f"event schema pin is absent: {name}") from error


def load_json_object(path: Path) -> dict[str, Any]:
    # Execute the load json object workflow in explicit, reviewable steps.
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoldenFixtureError(f"invalid JSON fixture: {path.name}") from error
    if not isinstance(value, dict):
        # Fail the load json object path with GoldenFixtureError for fixture root must be
        # an object: and name when isinstance and value is true; do not continue
        # ambiguously.
        raise GoldenFixtureError(f"fixture root must be an object: {path.name}")
    return value


def canonical_json_sha256(value: object) -> str:
    # Execute the canonical json sha256 workflow in explicit, reviewable steps.
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        # Complete encode only after its declared inputs are visible in canonical json sha256.
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def exact_file_sha256(path: Path) -> str:
    # Execute the exact file sha256 workflow in explicit, reviewable steps.
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise GoldenFixtureError(f"fixture cannot be read: {path.name}") from error
    return hashlib.sha256(payload).hexdigest()


# Define load verified tree as one focused operation with an explicit boundary.
def load_verified_tree(root: Path) -> GoldenTree:
    """Verify the closed file set and return parsed fixture documents."""

    root = root.resolve(strict=True)
    provenance = load_json_object(root / "provenance.json")
    _require_equal(
        provenance.get("schema"),
        "pumpfun-program-v1-golden-provenance/v2",
        # Pass provenance schema explicitly so _require_equal receives a reviewable schema
        # and pumpfun-program-v1-golden-provenance/v2 input in load verified tree.
        "provenance schema",
    )
    network = _object(provenance.get("network"), "provenance.network")
    _require_equal(network.get("network_id"), _FULL_NETWORK_ID, "full NetworkId")
    _require_equal(
        # Pass network explicitly to _require_equal for genesis hash and solana:.
        network.get("genesis_hash"),
        _FULL_NETWORK_ID.removeprefix("solana:"),
        "genesis hash",
    )
    _require_equal(provenance.get("program_id"), _PUMP_PROGRAM_ID, "Pump program id")
    _verify_licensing(provenance)

    # Assemble rpc once so the load verified tree workflow shares one value.
    rpc = _object(provenance.get("rpc"), "provenance.rpc")
    _require_equal(rpc.get("transaction_method"), "getTransaction", "RPC method")
    rpc_config = _object(rpc.get("transaction_config"), "RPC transaction config")
    _require_equal(rpc_config.get("commitment"), "finalized", "RPC commitment")

    files = _object(provenance.get("files"), "provenance.files")
    # Assemble expected paths once so the load verified tree workflow shares one value.
    expected_paths = set(files)
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "provenance.json"
        # Complete the actual paths group only after its semantic components are visible.
    }
    _require_equal(actual_paths, expected_paths, "closed fixture file set")
    for relative_path, expected_digest in files.items():
        # Process files.items() inside the bounded load verified tree loop.
        if not isinstance(relative_path, str):
            raise GoldenFixtureError("fixture manifest path must be a string")
        _require_hex_digest(expected_digest, f"digest for {relative_path}")
        fixture_path = _safe_member(root, relative_path)
        _require_equal(
            # Pass exact file sha256 explicitly to _require_equal for physical sha-256 for
            # and exact file sha256.
            exact_file_sha256(fixture_path),
            expected_digest,
            f"physical SHA-256 for {relative_path}",
        )

    vectors = load_json_object(_safe_member(root, "vectors.json"))
    # Assemble event schema once so the load verified tree workflow shares one value.
    event_schema = load_json_object(_safe_member(root, "upstream/pump-events.schema.json"))
    _verify_schema_pins(provenance, event_schema)
    raw_schema_paths = _object(vectors.get("event_schema_paths"), "vectors.event_schema_paths")
    event_schemas = {
        name: load_json_object(_safe_member(root, path))
        # Keep the items and raw schema paths items step visible while building event
        # schemas.
        for name, path in raw_schema_paths.items()
        if isinstance(name, str) and isinstance(path, str)
    }
    _require_equal(set(event_schemas), set(raw_schema_paths), "event schema path types")
    _verify_standard_event_schemas(event_schema, event_schemas)
    # Assemble lifecycle once so the load verified tree workflow shares one value.
    lifecycle = load_json_object(_safe_member(root, "lifecycle.json"))
    mint_accounts = load_json_object(_safe_member(root, "raw/mint-accounts.json"))
    return GoldenTree(
        root,
        provenance,
        # Pass event schema explicitly so GoldenTree receives a reviewable root and
        # provenance input in load verified tree.
        event_schema,
        event_schemas,
        vectors,
        lifecycle,
        mint_accounts,
        # Complete GoldenTree only after its root and provenance inputs are visible in load
        # verified tree.
    )


def decode_raw_event(raw: dict[str, Any], event_schema: dict[str, Any]) -> DecodedEvent:
    """Decode one literal ``Program data`` line without production code."""

    events = decode_raw_events(raw, event_schema)
    if len(events) != 1:
        raise GoldenFixtureError("raw excerpt does not contain exactly one event")
    return events[0]


def decode_raw_events(
    # Keep the raw input explicit in the decode raw events contract.
    raw: dict[str, Any],
    event_schema: dict[str, Any],
) -> tuple[DecodedEvent, ...]:
    """Decode every literal event retained from one finalized transaction."""

    if raw.get("schema") not in {
        "solana-finalized-pump-event-excerpt/v1",
        "solana-finalized-pump-events-excerpt/v1",
    }:
        raise GoldenFixtureError("raw schema mismatch")
    # Invoke _require_equal for network id and raw network id as a visible decode raw
    # events step.
    _require_equal(raw.get("network_id"), _FULL_NETWORK_ID, "raw NetworkId")
    rpc = _object(raw.get("rpc"), "raw.rpc")
    _require_equal(rpc.get("method"), "getTransaction", "raw RPC method")
    rpc_config = _object(rpc.get("config"), "raw.rpc.config")
    _require_equal(rpc_config.get("commitment"), "finalized", "raw RPC commitment")
    # Invoke _require_hex_digest for full result canonical sha256 and full rpc result
    # digest as a visible decode raw events step.
    _require_hex_digest(rpc.get("full_result_canonical_sha256"), "full RPC result digest")

    transaction = _object(raw.get("transaction"), "raw.transaction")
    _require_equal(transaction.get("meta_err"), None, "successful transaction status")
    for field in ("slot", "block_time", "transaction_index", "fee_lamports"):
        _decimal_integer(transaction.get(field), f"transaction.{field}", signed=False)

    # Assemble instruction once so the decode raw events workflow shares one value.
    instruction = _object(raw.get("instruction"), "raw.instruction")
    _require_equal(instruction.get("program_id"), _PUMP_PROGRAM_ID, "instruction program")
    _decimal_integer(instruction.get("outer_index"), "instruction.outer_index", signed=False)
    inner_index = instruction.get("inner_index")
    if inner_index is not None:
        # Invoke _decimal_integer for inner index as a visible decode raw events step.
        _decimal_integer(inner_index, "instruction.inner_index", signed=False)

    raw_program_data = raw.get("program_data")
    if isinstance(raw_program_data, list):
        program_data_items = [_object(item, "raw.program_data item") for item in raw_program_data]
    else:
        # Register raw program data through _object so the program data items table
        # remains scannable.
        program_data_items = [_object(raw_program_data, "raw.program_data")]
    if not program_data_items:
        raise GoldenFixtureError("raw excerpt contains no program-data events")

    if event_schema.get("schema") == "pumpfun-official-package-idl-event-subset/v1":
        pin = event_schema
    # Route all remaining cases through the explicit alternative branch.
    else:
        pin = _schema_pin(event_schema, _string(raw.get("event_schema_pin"), "event schema pin"))
    return tuple(_decode_program_data(item, pin) for item in program_data_items)


def _decode_program_data(program_data: dict[str, Any], schema_pin: dict[str, Any]) -> DecodedEvent:
    # Execute the decode program data workflow in explicit, reviewable steps.
    log_line = program_data.get("log_line")
    if not isinstance(log_line, str) or not log_line.startswith("Program data: "):
        raise GoldenFixtureError("program-data log line is missing")
    encoded = log_line.removeprefix("Program data: ")
    try:
        # Assemble payload once so the decode program data workflow shares one value.
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise GoldenFixtureError("program-data payload is not canonical base64") from error
    _require_equal(base64.b64encode(payload).decode(), encoded, "canonical base64 payload")
    _require_equal(
        # Pass len explicitly to _require_equal for raw size and raw size bytes.
        len(payload),
        _decimal_integer(program_data.get("raw_size_bytes"), "raw size"),
        "raw size",
    )
    _require_equal(
        # Pass hashlib explicitly to _require_equal for decoded bytes sha256 and program-
        # data sha-256.
        hashlib.sha256(payload).hexdigest(),
        program_data.get("decoded_bytes_sha256"),
        # Pass program-data sha-256 explicitly so _require_equal receives a reviewable
        # decoded bytes sha256 and program-data sha-256 input in decode program data.
        "program-data SHA-256",
    )
    _require_equal(program_data.get("trailing_bytes"), "0", "declared trailing bytes")

    decoded = decode_event(payload, schema_pin)
    _require_equal(decoded.name, program_data.get("event_name"), "event name")
    # Assemble expected fields once so the decode program data workflow shares one value.
    expected_fields = _object(program_data.get("fields"), "program_data.fields")
    _require_equal(
        _decimalize(decoded.fields),
        expected_fields,
        f"independently decoded {decoded.name} fields",
        # Complete _require_equal only after its independently decoded and fields inputs are
        # visible in decode program data.
    )
    return decoded


def decode_event(payload: bytes, schema_pin: dict[str, Any]) -> DecodedEvent:
    """Decode an Anchor event using only the checked-in IDL field layout."""

    if len(payload) < 8:
        raise GoldenFixtureError("event payload is shorter than its discriminator")
    discriminator = list(payload[:8])
    events = _array(schema_pin.get("events"), "schema pin events")
    matches = [
        # Keep the event component named inside the matches contract.
        event
        for event in events
        if isinstance(event, dict) and event.get("discriminator") == discriminator
    ]
    if len(matches) != 1:
        # Fail the decode event path with GoldenFixtureError for event discriminator is
        # absent or ambiguous in pinned schema when matches is true; do not continue
        # ambiguously.
        raise GoldenFixtureError("event discriminator is absent or ambiguous in pinned schema")
    event = matches[0]
    event_name = _string(event.get("name"), "event name")
    definitions = {
        _string(item.get("name"), "defined type name"): item
        # Keep the array and get _array step visible while building definitions.
        for item in _array(schema_pin.get("types", []), "schema pin types")
        if isinstance(item, dict)
    }
    cursor = _BorshCursor(payload[8:])
    raw_fields = event.get("fields")
    # Guard this path with raw_fields is None before applying effects.
    if raw_fields is None:
        # Handle the decode event raw_fields is None branch as a distinct logical block.
        try:
            event_definition = definitions[event_name]
        except KeyError as error:
            raise GoldenFixtureError(f"event has no defined field layout: {event_name}") from error
        raw_type = _object(event_definition.get("type"), f"event type {event_name}")
        # Invoke _require_equal for kind and struct as a visible decode event step.
        _require_equal(raw_type.get("kind"), "struct", f"event type {event_name} kind")
        raw_fields = raw_type.get("fields")
    fields = _decode_struct_fields(raw_fields, cursor, definitions)
    if cursor.remaining:
        raise GoldenFixtureError(f"{event_name} leaves {cursor.remaining} trailing bytes")
    # Return the completed decode event result without a hidden fallback.
    return DecodedEvent(event_name, fields, payload)


def normalized_decoded_fields(event: DecodedEvent) -> dict[str, object]:
    """Return the JSON representation used by raw fixture excerpts."""

    value = _decimalize(event.fields)
    if not isinstance(value, dict):
        raise GoldenFixtureError("decoded event fields must normalize to an object")
    return value


# Keep the borsh cursor contract and validation rules together.
class _BorshCursor:
    def __init__(self, payload: bytes) -> None:
        # Execute the borsh cursor init workflow in explicit, reviewable steps.
        self._payload = payload
        self._offset = 0

    @property
    def remaining(self) -> int:
        return len(self._payload) - self._offset

    # Define borsh cursor take as one focused operation with an explicit boundary.
    def take(self, size: int) -> bytes:
        # Execute the borsh cursor take workflow in explicit, reviewable steps.
        if size < 0 or self._offset + size > len(self._payload):
            raise GoldenFixtureError("Borsh payload is truncated")
        start = self._offset
        self._offset += size
        return self._payload[start : start + size]

    # Define borsh cursor integer as one focused operation with an explicit boundary.
    def integer(self, size: int, *, signed: bool = False) -> int:
        return int.from_bytes(self.take(size), byteorder="little", signed=signed)


def _decode_struct_fields(
    raw_fields: object,
    cursor: _BorshCursor,
    # Keep the definitions input explicit in the decode struct fields contract.
    definitions: dict[str, dict[str, Any]],
) -> dict[str, object]:
    # Execute the decode struct fields workflow in explicit, reviewable steps.
    result: dict[str, object] = {}
    for raw_field in _array(raw_fields, "struct fields"):
        # Process _array(raw_fields, 'struct fields') inside the bounded decode struct
        # fields loop.
        if isinstance(raw_field, list) and len(raw_field) == 2:
            raw_name, field_type = raw_field
        # Handle the decode struct fields complement of isinstance and raw field
        # explicitly.
        elif isinstance(raw_field, dict):
            raw_name, field_type = raw_field.get("name"), raw_field.get("type")
        else:
            raise GoldenFixtureError("IDL field must be a pair or Anchor field object")
        name = _string(raw_name, "field name")
        # Guard this path with name in result before applying effects.
        if name in result:
            raise GoldenFixtureError(f"duplicate field in IDL layout: {name}")
        result[name] = _decode_type(field_type, cursor, definitions)
    return result


def _decode_type(
    # Keep the field type input explicit in the decode type contract.
    field_type: object,
    cursor: _BorshCursor,
    definitions: dict[str, dict[str, Any]],
) -> object:
    # Execute the decode type workflow in explicit, reviewable steps.
    if isinstance(field_type, str):
        # Handle the decode type isinstance(field_type, str) branch as a distinct logical
        # block.
        integer_types = {
            "u8": (1, False),
            "u16": (2, False),
            "u32": (4, False),
            "u64": (8, False),
            # Keep the u128 component named inside the integer types contract.
            "u128": (16, False),
            "i8": (1, True),
            "i16": (2, True),
            "i32": (4, True),
            "i64": (8, True),
            # Keep the i128 component named inside the integer types contract.
            "i128": (16, True),
        }
        if field_type in integer_types:
            # Handle the decode type field_type in integer_types branch as a distinct
            # logical block.
            size, signed = integer_types[field_type]
            return cursor.integer(size, signed=signed)
        if field_type == "bool":
            # Handle the decode type field_type == 'bool' branch as a distinct logical
            # block.
            value = cursor.integer(1)
            if value not in (0, 1):
                raise GoldenFixtureError("Borsh bool is not zero or one")
            return bool(value)
        if field_type == "pubkey":
            # Return the completed decode type result without a hidden fallback.
            return _base58_encode(cursor.take(32))
        if field_type == "string":
            # Handle the decode type field_type == 'string' branch as a distinct logical
            # block.
            size = cursor.integer(4)
            try:
                return cursor.take(size).decode("utf-8")
            except UnicodeDecodeError as error:
                raise GoldenFixtureError("Borsh string is not UTF-8") from error
        # Fail the decode type path with GoldenFixtureError for unsupported primitive idl
        # Detail: type: and field type when field type str type is true; do not continue
        # ambiguously.
        raise GoldenFixtureError(f"unsupported primitive IDL type: {field_type}")

    if not isinstance(field_type, dict) or len(field_type) != 1:
        raise GoldenFixtureError("unsupported composite IDL type")
    kind, argument = next(iter(field_type.items()))
    if kind == "vec":
        # Handle the decode type kind == 'vec' branch as a distinct logical block.
        size = cursor.integer(4)
        return [_decode_type(argument, cursor, definitions) for _ in range(size)]
    if kind == "option":
        # Handle the decode type kind == 'option' branch as a distinct logical block.
        present = cursor.integer(1)
        if present == 0:
            return None
        if present != 1:
            raise GoldenFixtureError("Borsh option tag is not zero or one")
        # Return the completed decode type result without a hidden fallback.
        return _decode_type(argument, cursor, definitions)
    if kind == "array":
        # Handle the decode type kind == 'array' branch as a distinct logical block.
        parts = _array(argument, "array type")
        if len(parts) != 2 or isinstance(parts[1], bool) or not isinstance(parts[1], int):
            raise GoldenFixtureError("IDL array type has an invalid length")
        return [_decode_type(parts[0], cursor, definitions) for _ in range(parts[1])]
    if kind == "defined":
        # Handle the decode type kind == 'defined' branch as a distinct logical block.
        if isinstance(argument, dict):
            argument = argument.get("name")
        name = _string(argument, "defined type")
        try:
            definition = definitions[name]
        # Translate key error through the decode type boundary without hiding other
        # errors.
        except KeyError as error:
            raise GoldenFixtureError(f"undefined IDL type: {name}") from error
        raw_type = definition.get("type")
        if isinstance(raw_type, dict):
            # Handle the decode type isinstance(raw_type, dict) branch as a distinct
            # logical block.
            _require_equal(raw_type.get("kind"), "struct", f"defined type {name} kind")
            raw_fields = raw_type.get("fields")
        else:
            raw_fields = definition.get("fields")
        return _decode_struct_fields(raw_fields, cursor, definitions)
    # Fail the decode type path with GoldenFixtureError for unsupported composite idl
    # Detail: type: and kind; do not continue ambiguously.
    raise GoldenFixtureError(f"unsupported composite IDL type: {kind}")


def _schema_pin(event_schema: dict[str, Any], name: str) -> dict[str, Any]:
    # Execute the schema pin workflow in explicit, reviewable steps.
    pins = [
        pin
        for pin in _array(event_schema.get("pins"), "event schema pins")
        if isinstance(pin, dict) and pin.get("name") == name
    ]
    # Guard this path with len(pins) != 1 before applying effects.
    if len(pins) != 1:
        raise GoldenFixtureError(f"event schema pin is absent or ambiguous: {name}")
    return pins[0]


def _verify_licensing(provenance: dict[str, Any]) -> None:
    """Validate the package license basis, attribution path, and archive limitations."""

    licensing = _object(provenance.get("licensing"), "provenance licensing")
    # A closed metadata schema prevents unverified licensing claims from being accepted.
    _require_exact_keys(
        licensing,
        {"redistribution_basis", "notice_path", "residual_caveat"},
        "provenance licensing",
    )
    # Package declarations are the attribution basis; the archives contain no separate notice.
    _require_equal(
        licensing.get("redistribution_basis"),
        "official-package-level-SPDX-declarations",
        "schema redistribution basis",
    )
    # Require both the public notice reference and the package's documented limitation.
    _require_equal(licensing.get("notice_path"), "THIRD_PARTY_NOTICES.md", "notice path")
    _string(licensing.get("residual_caveat"), "licensing residual caveat")


def _verify_schema_evidence_paths(schema_evidence: dict[str, Any]) -> None:
    """Keep source policy and checked-in decoder paths versioned and unambiguous."""

    _require_exact_keys(
        schema_evidence,
        {
            "source_policy",
            "schema_extract",
            "current_decoder_idl_subset",
            # Historical decoding remains a separate exact layout contract.
            "historical_decoder_idl_subset",
            "sources",
        },
        "schema evidence",
    )
    _require_equal(
        schema_evidence.get("source_policy"),
        "Checked-in event layouts are projected from pinned official packages that declare MIT; "
        "unlicensed pump-public-docs revisions are retained only as non-redistribution "
        "equivalence references.",
        "schema source policy",
    )
    # Bind provenance to the exact three files consumed by the independent decoder.
    _require_equal(
        schema_evidence.get("schema_extract"),
        "upstream/pump-events.schema.json",
        "aggregate schema path",
    )
    _require_equal(
        schema_evidence.get("current_decoder_idl_subset"),
        "upstream/pump-current.events.idl.json",
        "current decoder schema path",
    )
    _require_equal(
        schema_evidence.get("historical_decoder_idl_subset"),
        "upstream/pump-historical.events.idl.json",
        "historical decoder schema path",
    )


def _named_source_pins(raw_pins: list[Any]) -> dict[str, dict[str, Any]]:
    """Return aggregate source pins while rejecting omissions, extras and duplicates."""

    result: dict[str, dict[str, Any]] = {}
    for raw_pin in raw_pins:
        # Aggregate pins may carry defined types only when their layouts require them.
        pin = _object(raw_pin, "aggregate schema pin")
        keys = set(pin)
        if (
            not {"name", "source_pin", "events"}
            <= keys
            <= {
                "name",
                "source_pin",
                "events",
                "types",
            }
        ):
            raise GoldenFixtureError("aggregate schema pin keys mismatch")

        name = _string(pin.get("name"), "aggregate schema pin name")
        if name in result:
            raise GoldenFixtureError("duplicate aggregate schema pin name")
        # Copy only the source contract; event layouts are checked against standard files.
        result[name] = _object(pin.get("source_pin"), f"source pin for {name}")
    return result


def _verify_source_pin(source_pin: dict[str, Any], label: str) -> None:
    """Validate one official package pin and its non-redistribution reference."""

    _require_exact_keys(source_pin, _SOURCE_PIN_KEYS, label)
    for field in ("registry", "package", "version", "metadata_url", "archive_url"):
        _string(source_pin.get(field), f"{label}.{field}")
    # Archive and embedded IDL bytes are independently content-addressed.
    _positive_decimal(source_pin.get("archive_size_bytes"), f"{label}.archive_size_bytes")
    _require_hex_digest(source_pin.get("archive_sha256"), f"{label}.archive_sha256")
    _string(source_pin.get("registry_integrity"), f"{label}.registry_integrity")
    _string(source_pin.get("idl_path"), f"{label}.idl_path")
    _positive_decimal(source_pin.get("idl_size_bytes"), f"{label}.idl_size_bytes")
    _require_hex_digest(source_pin.get("idl_sha256"), f"{label}.idl_sha256")

    # Package metadata is the declared license basis; no holder notice is fabricated.
    license_record = _object(source_pin.get("license"), f"{label}.license")
    _require_exact_keys(
        license_record,
        {"spdx_expression", "declaration_path", "standalone_notice_file"},
        f"{label}.license",
    )
    _require_equal(license_record.get("spdx_expression"), "MIT", f"{label}.license SPDX")
    _string(license_record.get("declaration_path"), f"{label}.license declaration")
    _require_equal(
        license_record.get("standalone_notice_file"),
        None,
        f"{label}.standalone license notice",
    )

    publisher = _object(source_pin.get("publisher_evidence"), f"{label}.publisher evidence")
    _require_exact_keys(
        publisher,
        {"kind", "identity", "url", "observed_utc_date"},
        f"{label}.publisher evidence",
    )
    for field in ("kind", "identity", "url", "observed_utc_date"):
        # Publisher evidence stays factual and separate from copyright ownership.
        _string(publisher.get(field), f"{label}.publisher evidence.{field}")

    projection = _object(source_pin.get("projection"), f"{label}.projection")
    _require_exact_keys(
        projection,
        {
            "schema",
            "selected_events",
            "selected_types",
            "omitted_object_keys",
            "layout_sha256",
        },
        f"{label}.projection",
    )
    _require_equal(
        projection.get("schema"),
        "pumpfun-idl-event-projection/v1",
        f"{label}.projection schema",
    )
    _string_array(projection.get("selected_events"), f"{label}.selected events")
    _string_array(projection.get("selected_types"), f"{label}.selected types")
    omitted = _string_array(projection.get("omitted_object_keys"), f"{label}.omitted keys")
    if any(key != "docs" for key in omitted):
        raise GoldenFixtureError(f"{label}.omitted keys contain unsupported values")
    _require_hex_digest(projection.get("layout_sha256"), f"{label}.layout SHA-256")

    equivalence = _object(
        source_pin.get("equivalence_reference"),
        f"{label}.equivalence reference",
    )
    _require_exact_keys(equivalence, _EQUIVALENCE_REFERENCE_KEYS, f"{label}.equivalence")
    _require_equal(
        equivalence.get("purpose"),
        "non-redistribution-equivalence-only",
        f"{label}.equivalence purpose",
    )
    _require_equal(
        equivalence.get("repository"),
        "https://github.com/pump-fun/pump-public-docs",
        f"{label}.equivalence repository",
    )
    _require_git_oid(equivalence.get("commit"), f"{label}.equivalence commit")
    for field in ("path", "raw_url"):
        _string(equivalence.get(field), f"{label}.equivalence {field}")
    # The reference proves matching semantics and must never become a license basis.
    _positive_decimal(equivalence.get("raw_size_bytes"), f"{label}.equivalence raw size")
    _require_hex_digest(equivalence.get("raw_sha256"), f"{label}.equivalence raw SHA-256")
    _require_equal(
        equivalence.get("redistribution_basis"),
        False,
        f"{label}.equivalence redistribution basis",
    )


def _verify_projected_layout(
    projection: dict[str, Any],
    raw_events: list[Any],
    raw_types: list[Any],
    name: str,
) -> None:
    """Bind checked-in ordered layouts to the package projection digest."""

    event_names = [
        _string(_object(event, "standard event").get("name"), "standard event name")
        for event in raw_events
    ]
    type_names = [
        _string(_object(item, "standard type").get("name"), "standard type name")
        for item in raw_types
    ]
    # Exact ordered selections prevent a smaller or rearranged decoder contract.
    _require_equal(event_names, projection.get("selected_events"), f"selected events for {name}")
    _require_equal(type_names, projection.get("selected_types"), f"selected types for {name}")
    _require_equal(len(event_names), len(set(event_names)), f"unique event names for {name}")
    _require_equal(len(type_names), len(set(type_names)), f"unique type names for {name}")

    layout = {"events": raw_events, "types": raw_types}
    _require_equal(
        canonical_json_sha256(layout),
        projection.get("layout_sha256"),
        f"projected layout SHA-256 for {name}",
    )


def _verify_schema_pins(provenance: dict[str, Any], event_schema: dict[str, Any]) -> None:
    # Execute the verify schema pins workflow in explicit, reviewable steps.
    _require_equal(
        event_schema.get("schema"),
        "pumpfun-official-package-event-schema-extract/v1",
        "event-schema extract version",
    )
    # Invoke _require_equal for program id and schema program id as a visible verify
    # schema pins step.
    _require_equal(event_schema.get("program_id"), _PUMP_PROGRAM_ID, "schema program id")
    schema_evidence = _object(provenance.get("schema_evidence"), "schema evidence")
    _verify_schema_evidence_paths(schema_evidence)
    expected = _object(schema_evidence.get("sources"), "licensed schema sources")

    # Preserve the array cardinality before building the name-keyed comparison.
    raw_pins = _array(event_schema.get("pins"), "event schema pins")
    actual = _named_source_pins(raw_pins)
    _require_equal(len(actual), len(raw_pins), "unique aggregate schema pin names")
    _require_equal(actual, expected, "licensed schema sources")
    _require_equal(set(actual), set(_EXPECTED_SOURCE_PIN_SHA256), "licensed source names")

    for name, source_pin in actual.items():
        # Validate every nested source contract after cross-file equality is established.
        _verify_source_pin(source_pin, f"source pin for {name}")
        _require_equal(
            canonical_json_sha256(source_pin),
            _EXPECTED_SOURCE_PIN_SHA256[name],
            f"reviewed source pin SHA-256 for {name}",
        )


def _verify_standard_event_schemas(
    aggregate: dict[str, Any], standards: dict[str, dict[str, Any]]
) -> None:
    # Execute the verify standard event schemas workflow in explicit, reviewable steps.
    aggregate_pins = {
        _string(pin.get("name"), "aggregate schema pin name"): pin
        for pin in _array(aggregate.get("pins"), "aggregate schema pins")
        if isinstance(pin, dict)
    }
    # Invoke _require_equal for standard event-schema pins and set as a visible verify
    # standard event schemas step.
    _require_equal(set(standards), set(aggregate_pins), "standard event-schema pins")
    for name, standard in standards.items():
        # Process standards.items() inside the bounded verify standard event schemas loop.
        _require_equal(
            standard.get("schema"),
            "pumpfun-official-package-idl-event-subset/v1",
            f"standard event schema version for {name}",
        )
        # Invoke _require_equal for address and idl address for as a visible verify
        # standard event schemas step.
        _require_equal(standard.get("address"), _PUMP_PROGRAM_ID, f"IDL address for {name}")
        aggregate_pin = aggregate_pins[name]
        source_pin = _object(standard.get("source_pin"), f"source pin for {name}")
        _require_equal(source_pin, aggregate_pin.get("source_pin"), f"source pin for {name}")

        # Bind the selected and ordered event/type names to the declared projection.
        projection = _object(source_pin.get("projection"), f"projection for {name}")
        raw_events = _array(standard.get("events"), f"standard events for {name}")
        raw_types = _array(standard.get("types"), f"standard types for {name}")
        _verify_projected_layout(projection, raw_events, raw_types, name)

        standard_events = {
            # Keep the string and get _string step visible while building standard events.
            _string(event.get("name"), "standard event name"): event
            for event in raw_events
            if isinstance(event, dict)
        }
        standard_types = {
            # Keep the string and get _string step visible while building standard types.
            _string(item.get("name"), "standard type name"): item
            for item in raw_types
            if isinstance(item, dict)
        }
        for aggregate_event in _array(aggregate_pin.get("events"), f"aggregate events for {name}"):
            # Process array, get and events inside the bounded verify standard event
            # schemas loop.
            aggregate_event = _object(aggregate_event, "aggregate event")
            event_name = _string(aggregate_event.get("name"), "aggregate event name")
            standard_event = standard_events.get(event_name)
            if standard_event is None:
                raise GoldenFixtureError(f"standard schema omits event: {event_name}")
            # Invoke _require_equal for discriminator and event discriminator for as a
            # visible verify standard event schemas step.
            _require_equal(
                standard_event.get("discriminator"),
                aggregate_event.get("discriminator"),
                f"event discriminator for {event_name}",
            )
            # Assemble standard type once so the verify standard event schemas workflow
            # shares one value.
            standard_type = _object(standard_types.get(event_name), f"event type {event_name}")
            type_body = _object(standard_type.get("type"), f"event type body {event_name}")
            _require_equal(type_body.get("kind"), "struct", f"event kind for {event_name}")
            _require_equal(
                _field_pairs(type_body.get("fields")),
                # Pass aggregate event explicitly to _require_equal for fields and event
                # layout for.
                aggregate_event.get("fields"),
                f"event layout for {event_name}",
            )
        for aggregate_type in _array(aggregate_pin.get("types", []), f"aggregate types for {name}"):
            # Process array, get and types inside the bounded verify standard event
            # schemas loop.
            aggregate_type = _object(aggregate_type, "aggregate defined type")
            type_name = _string(aggregate_type.get("name"), "aggregate defined type name")
            standard_type = _object(standard_types.get(type_name), f"defined type {type_name}")
            type_body = _object(standard_type.get("type"), f"defined type body {type_name}")
            _require_equal(type_body.get("kind"), "struct", f"defined kind for {type_name}")
            # Invoke _require_equal for fields and defined layout for as a visible verify
            # standard event schemas step.
            _require_equal(
                _field_pairs(type_body.get("fields")),
                aggregate_type.get("fields"),
                f"defined layout for {type_name}",
            )


# Define field pairs as one focused operation with an explicit boundary.
def _field_pairs(raw_fields: object) -> list[list[object]]:
    # Execute the field pairs workflow in explicit, reviewable steps.
    pairs: list[list[object]] = []
    for item in _array(raw_fields, "standard struct fields"):
        # Process array and raw fields inside the bounded field pairs loop.
        field = _object(item, "standard struct field")
        pairs.append([_string(field.get("name"), "standard field name"), field.get("type")])
    return pairs


def _safe_member(root: Path, relative_path: str) -> Path:
    # Execute the safe member workflow in explicit, reviewable steps.
    candidate_path = PurePosixPath(relative_path)
    if (
        not relative_path
        or candidate_path.is_absolute()
        or relative_path != candidate_path.as_posix()
        # Keep candidate path visible while evaluating the relative path, is absolute and
        # parts guard.
        or ".." in candidate_path.parts
        or "." in candidate_path.parts
    ):
        raise GoldenFixtureError(f"unsafe fixture path: {relative_path!r}")
    candidate = root.joinpath(*candidate_path.parts)
    # Keep expected failures inside the safe member error boundary.
    try:
        # Perform the protected safe member operation before explicit failure handling.
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise GoldenFixtureError(f"fixture path escapes or is missing: {relative_path}") from error
    if candidate.is_symlink() or not resolved.is_file():
        # Fail the safe member path with GoldenFixtureError for fixture path is not a
        # regular file: and relative path when is symlink, candidate and is file is true;
        # do not continue ambiguously.
        raise GoldenFixtureError(f"fixture path is not a regular file: {relative_path}")
    return resolved


def _base58_encode(payload: bytes) -> str:
    # Execute the base58 encode workflow in explicit, reviewable steps.
    zeroes = len(payload) - len(payload.lstrip(b"\0"))
    value = int.from_bytes(payload, "big")
    encoded = ""
    while value:
        # Keep the value loop body bounded within base58 encode.
        value, remainder = divmod(value, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    return "1" * zeroes + encoded


def _decimalize(value: object) -> object:
    # Execute the decimalize workflow in explicit, reviewable steps.
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        # Return the completed decimalize result without a hidden fallback.
        return [_decimalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _decimalize(item) for key, item in value.items()}
    raise GoldenFixtureError(f"decoded field has an unsupported value: {type(value).__name__}")


def _decimal_integer(value: object, label: str, *, signed: bool = True) -> int:
    # Execute the decimal integer workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip():
        raise GoldenFixtureError(f"{label} must be a canonical decimal string")
    if value.startswith("+") or (len(value) > 1 and value.startswith("0")):
        raise GoldenFixtureError(f"{label} must be a canonical decimal string")
    if value.startswith("-"):
        # Handle the decimal integer value.startswith('-') branch as a distinct logical
        # block.
        if not signed or value == "-0" or not value[1:].isdigit():
            raise GoldenFixtureError(f"{label} must be a canonical decimal string")
    # Handle the decimal integer complement of value.startswith('-') explicitly.
    elif not value.isdigit():
        raise GoldenFixtureError(f"{label} must be a canonical decimal string")
    return int(value)


def _positive_decimal(value: object, label: str) -> int:
    # Registry sizes are canonical decimal strings and cannot describe empty bytes.
    parsed = _decimal_integer(value, label, signed=False)
    if parsed <= 0:
        raise GoldenFixtureError(f"{label} must be positive")
    return parsed


def _string_array(value: object, label: str) -> list[str]:
    # Normalize only after every member is proven to be a non-empty string.
    values = [_string(item, f"{label} item") for item in _array(value, label)]
    if len(values) != len(set(values)):
        raise GoldenFixtureError(f"{label} must not contain duplicates")
    return values


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    # Closed metadata schemas make additions and omissions explicit version changes.
    if set(value) != expected:
        raise GoldenFixtureError(f"{label} keys mismatch")


def _require_hex_digest(value: object, label: str) -> str:
    # Execute the require hex digest workflow in explicit, reviewable steps.
    if (
        not isinstance(value, str)
        or len(value) != _HEX_DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        # Fail the require hex digest path with GoldenFixtureError for must be a lowercase
        # sha-256 digest and label when hex digest length, isinstance and value is true;
        # do not continue ambiguously.
        raise GoldenFixtureError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_git_oid(value: object, label: str) -> str:
    # Execute the require git oid workflow in explicit, reviewable steps.
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        # Fail the require git oid path with GoldenFixtureError for must be a lowercase
        # full sha-1 object id and label when isinstance, value and character is true; do
        # not continue ambiguously.
        raise GoldenFixtureError(f"{label} must be a lowercase full SHA-1 object id")
    return value


def _object(value: object, label: str) -> dict[str, Any]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise GoldenFixtureError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    # Execute the array workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise GoldenFixtureError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value:
        raise GoldenFixtureError(f"{label} must be a non-empty string")
    return value


def _require_equal(actual: object, expected: object, label: str) -> None:
    # Execute the require equal workflow in explicit, reviewable steps.
    if actual != expected:
        raise GoldenFixtureError(f"{label} mismatch")


__all__ = [
    "DecodedEvent",
    "GoldenFixtureError",
    # Keep the golden tree component named inside the all contract.
    "GoldenTree",
    "canonical_json_sha256",
    "decode_event",
    "decode_raw_event",
    "decode_raw_events",
    # Keep the exact file sha256 component named inside the all contract.
    "exact_file_sha256",
    "load_json_object",
    "load_verified_tree",
    "normalized_decoded_fields",
]
