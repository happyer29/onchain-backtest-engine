"""Build a closed, synthetic, read-only demo corpus through real use cases and API DTOs."""

import hashlib
import importlib
import json
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi.testclient import TestClient

from backtest.adapters.replay.factory import LocalReplaySourceFactory
from backtest.adapters.results.parquet import LocalParquetRunOutputStore
from backtest.application.copy_run_contract import copy_draft_from_spec
from backtest.application.research import (
    SOL_QUOTE,
    ResearchMode,
    ResearchTokenMode,
    TokenMode,
    WalletObservation,
)
from backtest.application.run_drafts import PumpfunCopyBuyRunDraft
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.use_cases.prepare_dataset import PrepareDatasetRequest
from backtest.application.use_cases.run_backtest import RunBacktest, RunBacktestRequest
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.config import load_settings
from backtest.bootstrap.container import build_runtime_container
from backtest.bootstrap.copy_run_resolver import PumpfunCopyBuyRunSpecResolver
from backtest.bootstrap.copy_runtime import PumpfunCopyRuntimeResolver
from backtest.bootstrap.runtime_plugins import ReferenceRuntimeComponentsResolver
from backtest.domain.copytrading import CopyBuyPolicy
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import ArtifactId, ContentDigest, RuntimeLockId
from backtest.domain.time import BlockRange
from backtest.engine import ReferenceBacktestEngine
from backtest.interfaces.api import create_app

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests/unit/bootstrap")]
fixtures = importlib.import_module("tests.support.research")
DIGEST, NETWORK = fixtures.DIGEST, fixtures.NETWORK
configuration, dataset, key = fixtures.configuration, fixtures.dataset, fixtures.key

SCHEMA = "backtest.static-demo/v1"
RECIPE = "synthetic-wallet-groups-and-copy-outcomes/v1"
MAX_RESPONSE = 2 * 1024**2
MAX_TOTAL = 16 * 1024**2
MAX_RECORDS = 2048


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def route_key(path):
    parsed = urlsplit(path)
    assert not parsed.scheme and not parsed.netloc and not parsed.fragment
    assert parsed.path.startswith("/api/v1/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return parsed.path + ("?" + query if query else "")


def copy_runs(directory):
    """Reuse bounded source proofs and run both reference modes without a live source."""
    source_fixture = importlib.import_module("test_pumpfun_copy_source")
    profiles = importlib.import_module("test_sniping_runtime")._draft()
    plan, prepare, artifacts, source = source_fixture.planned_fixture(
        directory / "data", decision_start=10, initial_transactions=4
    )
    prepared = prepare.execute(PrepareDatasetRequest(plan))
    tools, runtime = BuildToolBundleRegistry().pin(), RuntimeLockId("7" * 64)
    resolver = PumpfunCopyBuyRunSpecResolver(
        artifacts,
        runtime,
        parquet_memory_limit_mb=256,
        threads=1,
        expected_projector_bundle_id=source.projector.bundle_id,
        build_tools=tools,
    )
    runner = RunBacktest(
        LocalReplaySourceFactory(
            artifacts,
            parquet_memory_limit_mb=256,
            expected_projector_bundle_id=source.projector.bundle_id,
            build_tools=tools,
        ),
        ReferenceRuntimeComponentsResolver(runtime),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, directory / "outputs"),
        copy_components=PumpfunCopyRuntimeResolver(runtime),
        required_threads=1,
    )
    results = []
    for i, mode in enumerate(
        (ExecutionMode.EXOGENOUS_REPLAY, ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT)
    ):
        draft = PumpfunCopyBuyRunDraft(
            prepared.dataset_revision_id,
            prepared.snapshot_id,
            None,
            source.selection.signing_wallets,
            1_000_000_000,
            CopyBuyPolicy(100_000_000, 2000, 1, 4, 0, 1, 1, 100, 100),
            mode,
            profiles.wallet_account_profile,
            profiles.pump_fee_profile,
            profiles.buy_solana_fee_profile,
            profiles.sell_solana_fee_profile,
            7,
        )
        spec = resolver.resolve(draft)
        assert copy_draft_from_spec(spec) == draft
        result = runner.execute(
            RunBacktestRequest(
                spec,
                ContentDigest(str(i + 1) * 64),
                RunPhysicalSettings(RunBackend.REFERENCE_PUMPFUN_COPY_BUY, 256, 1, 1, 1),
            )
        )
        results.append(
            {
                "id": result.artifact.artifact_id.hex,
                "mode": mode.value,
                "title": "Copy Buy · " + ("strict replay" if i == 0 else "virtual settlement"),
            }
        )
    return results


def research_examples(service):
    """Sixty synthetic signers form four dense groups with sparse cross-group pairs."""
    events = []

    def buys(wallets, mint, start):
        events.extend((start + i * 2, wallet, mint, "BUY") for i, wallet in enumerate(wallets))

    for group in range(4):
        wallets = list(range(1 + 15 * group, 16 + 15 * group))
        for token in range(3):
            buys(wallets, 100 + group * 3 + token, 1000 + group * 1000 + token * 100)
        # A later repeat is an observed trade, but cannot add another first-purchase vote.
        buys(wallets[:2], 100 + group * 3, 1400 + group * 1000)
    for group in range(3):
        for token in range(2):
            buys(
                (1 + group * 15, 16 + group * 15),
                120 + group * 2 + token,
                6000 + group * 200 + token * 60,
            )
    for mint in (130, 131):
        buys((2, 17, 32), mint, 7000 + (mint - 130) * 100)
    buys((3, 18), 132, 7300)  # Missing creation signature: visible warning, excluded in both modes.
    buys((4, 19), 133, 7500)  # Unknown mode: included only in ALL.
    events.append((8000, 5, 100, "SELL"))
    rows = tuple(
        WalletObservation(
            100 + i // 10,
            i % 10,
            0,
            key(i + 1, 64),
            1_700_000_000 + seconds,
            key(mint),
            SOL_QUOTE,
            side,
            100_000 + i,
            100_000_000 + i * 1300,
            key(wallet),
            key(70),
        )
        for i, (seconds, wallet, mint, side) in enumerate(sorted(events))
    )
    assert len(rows) <= 5000 and len({r.signing_wallet for r in rows}) == 60

    def classify(mints):
        return tuple(
            ResearchTokenMode(
                mint,
                TokenMode.MAYHEM
                if mint in (key(130), key(131))
                else TokenMode.UNKNOWN
                if mint == key(133)
                else TokenMode.NON_MAYHEM,
                None if mint == key(133) else (90, 1, 0, "" if mint == key(132) else key(90, 64)),
                0 if mint == key(133) else 1,
                "MISSING_CREATION_SIGNATURE" if mint == key(132) else "",
            )
            for mint in mints
        )

    spec = replace(
        dataset(),
        block_range=BlockRange(NETWORK, dataset().block_range.position_schema_id, 100, 500),
    )
    snapshot = service.store.publish_snapshot(spec, DIGEST, iter((rows,)), classify=classify)
    results = []
    for mode in (ResearchMode.NON_MAYHEM, ResearchMode.ALL):
        command = service.resolve_analysis(snapshot.artifact_id, window_seconds=60, mode=mode)
        result = service.store.analyze(command)
        results.append({"id": result.artifact_id.hex, "mode": mode.value})
    return snapshot.artifact_id.hex, results


class Exporter:
    def __init__(self, client, output):
        self.client, self.output, self.records, self.total = client, output, {}, 0
        (output / "responses").mkdir()

    def get(self, path):
        response = self.client.get(path)
        if response.status_code != 200:
            raise RuntimeError(
                f"Demo export rejected: {urlsplit(path).path} ({response.status_code})"
            )
        value = response.json()
        raw = canonical(value)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("Demo response limit exceeded")
        selected = route_key(path)
        if selected not in self.records:
            self.total += len(raw)
            if len(self.records) >= MAX_RECORDS or self.total > MAX_TOTAL:
                raise ValueError("Demo corpus limit exceeded")
            digest = hashlib.sha256(raw).hexdigest()
            filename = f"responses/{digest}.json"
            (self.output / filename).write_bytes(raw)
            self.records[selected] = {"file": filename, "bytes": len(raw), "sha256": digest}
        return value

    def pages(self, artifact, table, limit=25, pair=None):
        rows, cursor = [], None
        for _ in range(250):
            query = {"limit": str(limit)}
            if pair is not None:
                query["pair"] = str(pair)
            if cursor:
                query["cursor"] = cursor
            page = self.get(f"/api/v1/research/{artifact}/rows/{table}?{urlencode(query)}")
            rows.extend(page["rows"])
            cursor = page["next_cursor"]
            if not cursor:
                return rows
        raise ValueError("Demo pagination did not terminate")


def generate(output):
    with tempfile.TemporaryDirectory(prefix="backtest-static-demo-") as temporary:
        directory = Path(temporary)
        runs = copy_runs(directory)
        config = configuration(directory / "demo.toml", directory / "data")
        container = build_runtime_container(load_settings(config), profile="synthetic-static-demo")
        service = container.control.research
        assert service is not None
        snapshot, results = research_examples(service)
        # Register only the verified transitive closure of the selected test results.
        indexed = set()

        def index(artifact):
            if artifact in indexed:
                return
            assert len(indexed) < 128
            with container.artifacts.open_committed(ArtifactId(artifact)) as handle:
                descriptor = handle.descriptor
            for dependency in descriptor.input_artifact_ids:
                index(dependency.hex)
            container.catalog.index_committed(descriptor)
            indexed.add(artifact)

        for artifact in (snapshot, *(r["id"] for r in results), *(r["id"] for r in runs)):
            index(artifact)
        app = create_app(container.control, control_plane_id=ContentDigest("d" * 64))
        with TestClient(app, base_url="http://127.0.0.1") as client:
            export = Exporter(client, output)
            export.get(f"/api/v1/research/{snapshot}")
            export.pages(snapshot, "observations")
            export.pages(snapshot, "token_modes")
            export.pages(snapshot, "data_issues")
            for result in results:
                artifact = result["id"]
                summary = export.get(f"/api/v1/research/{artifact}")
                result["counts"] = summary["counts"]
                pairs = export.pages(artifact, "pairs")
                assert 0 < len(pairs) == int(summary["counts"]["pairs"]) <= 1000
                assert export.pages(artifact, "pairs", 200) == pairs
                export.pages(artifact, "activity")
                export.pages(artifact, "data_issues")
                for pair in pairs:
                    evidence = export.pages(artifact, "evidence", pair=pair["row_id"])
                    assert len(evidence) == int(pair["shared_mints"])
            for run in runs:
                prefix = f"/api/v1/run-artifacts/{run['id']}"
                run["summary"] = export.get(prefix + "/strategy-summary")
                dashboard = export.get(prefix + "/strategy-dashboard?limit=25")
                entries = export.get(prefix + "/entries?limit=25")
                assert dashboard["entries"] == entries and len(entries["items"]) == 1
                export.get(prefix + "/analytics")
                for entry in entries["items"]:
                    if entry["chart_availability"] == "AVAILABLE":
                        export.get(
                            prefix
                            + f"/entries/{entry['entry_id']}/chart"
                            + f"?boundary_ordinal={entry['boundary_ordinal']}"
                        )
            # Lineage DTOs expose only bounded IDs/relationships, never executable manifest bodies.
            pending = {snapshot, *(r["id"] for r in results), *(r["id"] for r in runs)}
            done = set()
            while pending:
                artifact = pending.pop()
                lineage = export.get(f"/api/v1/lineage/{artifact}")
                done.add(artifact)
                pending.update(
                    item["artifact_id"]
                    for item in lineage["artifacts"]
                    if item["artifact_id"] not in done
                )
                assert len(done | pending) <= 128
            manifest = {
                "schema": SCHEMA,
                "recipe": RECIPE,
                "synthetic": True,
                "wallets": 60,
                "snapshot": snapshot,
                "research": results,
                "runs": runs,
                "response_bytes": export.total,
                "responses": export.records,
            }
            raw = canonical(manifest)
            assert len(raw) <= 1024**2
            (output / "manifest.json").write_bytes(raw)
            (output / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
            print(
                f"Demo prepared: 60 wallets, {[r['counts']['pairs'] for r in results]} pairs, "
                f"2 runs, {len(export.records)} responses, {export.total} bytes."
            )


def main():
    output = ROOT / "frontend/demo-data"
    with tempfile.TemporaryDirectory(prefix=".demo-export-", dir=output.parent) as staging:
        with patch(
            "socket.socket.connect",
            side_effect=RuntimeError("Demo preparation forbids network access."),
        ):
            generate(Path(staging))
        if output.exists():
            assert json.loads((output / "manifest.json").read_text())["schema"] == SCHEMA
            shutil.rmtree(output)
        shutil.copytree(staging, output)


if __name__ == "__main__":
    main()
