"""Pure manifests for exact source-bound code bundles and dependency closure."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self, cast

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import canonicalize_job_payload
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import BundleId, ContentDigest

if TYPE_CHECKING:
    from backtest.application.run_specs import ResolvedComponent


# Keep the code bundle integrity error contract and validation rules together.
class CodeBundleIntegrityError(ValueError):
    """An exact bundle manifest or its transitive closure is inconsistent."""


@dataclass(frozen=True, slots=True)
class PinnedCodeBundleIdentity:
    """One composition-pinned bundle ID with an optional live source verifier.

    Production composition supplies ``resolve_current`` from an allowlisted
    installed-source registry.  The explicit unit-test constructor deliberately
    has no filesystem authority and exists only to keep isolated adapter tests
    small.
    """

    role: str
    bundle_id: BundleId
    _resolve_current: Callable[[], BundleId] | None = field(
        default=None,
        repr=False,
        # Pass compare explicitly into field within pinned code bundle identity.
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_role(self.role)

    @classmethod
    # Define pinned code bundle identity for unit tests as one focused operation with an
    # explicit boundary.
    def for_unit_tests(cls, role: str, bundle_id: BundleId) -> Self:
        """Create a fixed non-production identity for an isolated unit test."""

        return cls(role, bundle_id)

    @property
    def is_source_bound(self) -> bool:
        return self._resolve_current is not None

    def require_current(self) -> None:
        """Fail closed if installed relevant bytes changed since composition."""

        if self._resolve_current is None:
            return
        if self._resolve_current() != self.bundle_id:
            # Handle the pinned code bundle identity require current bundle id and resolve
            # current condition as a distinct block.
            raise CodeBundleIntegrityError(
                f"installed exact source bytes changed for bundle role {self.role}"
            )


@dataclass(frozen=True, slots=True)
class PinnedCodeBundleSet:
    """Canonical role-indexed physical tool identities for one composition cut."""

    identities: tuple[PinnedCodeBundleIdentity, ...]

    def __post_init__(self) -> None:
        # Execute the pinned code bundle set post init workflow in explicit, reviewable
        # steps.
        roles = tuple(item.role for item in self.identities)
        if not roles or roles != tuple(sorted(set(roles))):
            # Handle the pinned code bundle set post init roles and sorted condition as a
            # distinct block.
            raise CodeBundleIntegrityError(
                "pinned code bundle identities must be sorted, unique and non-empty"
            )

    def identity_for(self, role: str) -> PinnedCodeBundleIdentity:
        # Execute the pinned code bundle set identity for workflow in explicit, reviewable
        # steps.
        _require_role(role)
        try:
            return next(item for item in self.identities if item.role == role)
        except StopIteration as error:
            # Translate the StopIteration failure through the pinned code bundle set
            # identity for boundary.
            raise CodeBundleIntegrityError(
                f"no pinned code bundle identity for role {role}"
            ) from error

    def require_current(self, role: str) -> BundleId:
        # Execute the pinned code bundle set require current workflow in explicit,
        # reviewable steps.
        identity = self.identity_for(role)
        identity.require_current()
        return identity.bundle_id


@dataclass(frozen=True, slots=True, order=True)
class CodeSourceFile:
    """One package-relative regular file captured by exact physical bytes."""

    path: str
    sha256: ContentDigest
    size_bytes: int

    def __post_init__(self) -> None:
        # Execute the code source file post init workflow in explicit, reviewable steps.
        parts = self.path.split("/")
        if (
            not self.path
            or self.path.startswith("/")
            or "\\" in self.path
            # Keep any visible while evaluating the path, startswith and part guard.
            or any(part in {"", ".", ".."} for part in parts)
            or "\x00" in self.path
        ):
            # Handle the code source file post init path, startswith and part condition as
            # a distinct block.
            raise CodeBundleIntegrityError(
                "code source path must be normalized, package-relative and traversal-free"
            )
        if (
            isinstance(self.size_bytes, bool)
            # Keep isinstance visible while evaluating the isinstance and size bytes
            # guard.
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise CodeBundleIntegrityError("code source size must be a non-negative integer")

    def document(self) -> dict[str, object]:
        # Execute the code source file document workflow in explicit, reviewable steps.
        return {
            "path": self.path,
            "sha256": self.sha256.hex,
            "size_bytes": self.size_bytes,
        }


# Apply dataclass semantics to the following code bundle dependency contract.
@dataclass(frozen=True, slots=True, order=True)
class CodeBundleDependency:
    """One exact direct dependency edge in a code bundle manifest."""

    role: str
    bundle_id: BundleId
    api_version: int

    def __post_init__(self) -> None:
        # Execute the code bundle dependency post init workflow in explicit, reviewable
        # steps.
        _require_role(self.role)
        if (
            isinstance(self.api_version, bool)
            or not isinstance(self.api_version, int)
            or self.api_version <= 0
            # Evaluate the complete code bundle dependency post init isinstance and api
            # version condition before guarded effects.
        ):
            raise CodeBundleIntegrityError("bundle dependency API version must be positive")

    def document(self) -> dict[str, object]:
        # Execute the code bundle dependency document workflow in explicit, reviewable
        # steps.
        return {
            "api_version": self.api_version,
            "bundle_id": self.bundle_id.hex,
            "role": self.role,
        }


# Apply dataclass semantics to the following exact code bundle manifest contract.
@dataclass(frozen=True, slots=True)
class ExactCodeBundleManifest:
    """Canonical code/package identity with exact files and dependency edges."""

    bundle_id: BundleId
    role: str
    api_version: int
    package_name: str
    contract_digest: ContentDigest
    # Declare code digest explicitly in the exact code bundle manifest contract.
    code_digest: ContentDigest
    source_files: tuple[CodeSourceFile, ...]
    direct_dependencies: tuple[CodeBundleDependency, ...]

    def __post_init__(self) -> None:
        # Execute the exact code bundle manifest post init workflow in explicit,
        # reviewable steps.
        _require_role(self.role)
        if (
            isinstance(self.api_version, bool)
            or not isinstance(self.api_version, int)
            or self.api_version <= 0
            # Evaluate the complete exact code bundle manifest post init isinstance and api
            # version condition before guarded effects.
        ):
            raise CodeBundleIntegrityError("bundle API version must be positive")
        if (
            not self.package_name
            or self.package_name != self.package_name.strip()
            # Keep x00 visible while evaluating the package name and strip guard.
            or "\x00" in self.package_name
        ):
            raise CodeBundleIntegrityError("bundle package name must be non-empty and trimmed")
        files = tuple(sorted(self.source_files, key=lambda item: item.path))
        if files != self.source_files or len({item.path for item in files}) != len(files):
            # Fail the exact code bundle manifest post init path with
            # CodeBundleIntegrityError for bundle source files must be sorted and unique
            # when files, source files and path is true; do not continue ambiguously.
            raise CodeBundleIntegrityError("bundle source files must be sorted and unique")
        dependencies = tuple(sorted(self.direct_dependencies, key=lambda item: item.role))
        if dependencies != self.direct_dependencies or len(
            {item.role for item in dependencies}
        ) != len(dependencies):
            # Fail the exact code bundle manifest post init path with
            # CodeBundleIntegrityError for bundle dependencies must be sorted and unique
            # when dependencies, direct dependencies and role is true; do not continue
            # ambiguously.
            raise CodeBundleIntegrityError("bundle dependencies must be sorted and unique")
        if any(item.role == self.role for item in dependencies):
            raise CodeBundleIntegrityError("bundle cannot depend directly on itself")
        expected_code = _code_digest(files)
        if expected_code != self.code_digest:
            # Fail the exact code bundle manifest post init path with
            # CodeBundleIntegrityError for bundle code digest differs from exact source
            # files when expected code and code digest is true; do not continue
            # ambiguously.
            raise CodeBundleIntegrityError("bundle code digest differs from exact source files")
        expected_bundle = domain_digest("backtest.exact-code-bundle.v1", self.identity_document())
        if expected_bundle.hex != self.bundle_id.hex:
            raise CodeBundleIntegrityError("bundle ID differs from its exact manifest")

    @classmethod
    # Define exact code bundle manifest create as one focused operation with an explicit
    # boundary.
    def create(
        cls,
        *,
        role: str,
        api_version: int,
        # Keep the package name input explicit in the create contract.
        package_name: str,
        contract_digest: ContentDigest,
        source_files: tuple[CodeSourceFile, ...],
        direct_dependencies: tuple[CodeBundleDependency, ...] = (),
    ) -> Self:
        # Execute the exact code bundle manifest create workflow in explicit, reviewable
        # steps.
        files = tuple(sorted(source_files, key=lambda item: item.path))
        dependencies = tuple(sorted(direct_dependencies, key=lambda item: item.role))
        code_digest = _code_digest(files)
        provisional = cls.__new__(cls)
        object.__setattr__(provisional, "bundle_id", BundleId("0" * 64))
        # Invoke __setattr__ for role and provisional as a visible exact code bundle
        # manifest create step.
        object.__setattr__(provisional, "role", role)
        object.__setattr__(provisional, "api_version", api_version)
        object.__setattr__(provisional, "package_name", package_name)
        object.__setattr__(provisional, "contract_digest", contract_digest)
        object.__setattr__(provisional, "code_digest", code_digest)
        # Invoke __setattr__ for source files and provisional as a visible exact code
        # bundle manifest create step.
        object.__setattr__(provisional, "source_files", files)
        object.__setattr__(provisional, "direct_dependencies", dependencies)
        bundle_id = BundleId(
            domain_digest("backtest.exact-code-bundle.v1", provisional.identity_document()).hex
        )
        # Return the completed exact code bundle manifest create result without a hidden
        # fallback.
        return cls(
            bundle_id=bundle_id,
            role=role,
            api_version=api_version,
            package_name=package_name,
            # Pass contract digest explicitly so cls receives a reviewable bundle id and
            # role input in exact code bundle manifest create.
            contract_digest=contract_digest,
            code_digest=code_digest,
            source_files=files,
            direct_dependencies=dependencies,
        )

    # Define exact code bundle manifest identity document as one focused operation with an
    # explicit boundary.
    def identity_document(self) -> dict[str, object]:
        # Execute the exact code bundle manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "api_version": self.api_version,
            "code_digest": self.code_digest.hex,
            "contract_digest": self.contract_digest.hex,
            "direct_dependencies": [item.document() for item in self.direct_dependencies],
            # Include package name in the completed exact code bundle manifest identity
            # document result.
            "package_name": self.package_name,
            "role": self.role,
            "source_files": [item.document() for item in self.source_files],
        }

    def document(self) -> dict[str, object]:
        # Execute the exact code bundle manifest document workflow in explicit, reviewable
        # steps.
        return {
            "artifact_schema": "exact-code-bundle/v1",
            "bundle_id": self.bundle_id.hex,
            **self.identity_document(),
        }

    # Define exact code bundle manifest manifest bytes as one focused operation with an
    # explicit boundary.
    def manifest_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


@dataclass(frozen=True, slots=True)
class ExactCodeBundleClosure:
    """A complete, acyclic and exact set of code bundle manifests."""

    manifests: tuple[ExactCodeBundleManifest, ...]

    def __post_init__(self) -> None:
        # Execute the exact code bundle closure post init workflow in explicit, reviewable
        # steps.
        ordered = tuple(sorted(self.manifests, key=lambda item: item.role))
        if not ordered or ordered != self.manifests:
            raise CodeBundleIntegrityError("bundle closure must be non-empty and sorted by role")
        by_role = {item.role: item for item in ordered}
        if len(by_role) != len(ordered):
            # Fail the exact code bundle closure post init path with
            # CodeBundleIntegrityError for bundle closure contains duplicate roles when by
            # role and ordered is true; do not continue ambiguously.
            raise CodeBundleIntegrityError("bundle closure contains duplicate roles")
        for manifest in ordered:
            # Process ordered inside the bounded exact code bundle closure post init loop.
            for dependency in manifest.direct_dependencies:
                # Process manifest.direct_dependencies inside the bounded exact code
                # bundle closure post init loop.
                target = by_role.get(dependency.role)
                if target is None:
                    # Handle the exact code bundle closure post init target is None branch
                    # as a distinct logical block.
                    raise CodeBundleIntegrityError(
                        f"bundle {manifest.role} has an unresolved dependency {dependency.role}"
                    )
                if (
                    target.bundle_id != dependency.bundle_id
                    # Keep target visible while evaluating the bundle id, api version and
                    # target guard.
                    or target.api_version != dependency.api_version
                ):
                    # Handle the exact code bundle closure post init bundle id, api
                    # version and target condition as a distinct block.
                    raise CodeBundleIntegrityError(
                        f"bundle {manifest.role} dependency {dependency.role} is inexact"
                    )
        _require_acyclic(by_role)

    def manifest_for(self, role: str) -> ExactCodeBundleManifest:
        # Execute the exact code bundle closure manifest for workflow in explicit,
        # reviewable steps.
        try:
            return next(item for item in self.manifests if item.role == role)
        except StopIteration as error:
            raise CodeBundleIntegrityError(f"bundle closure has no role {role}") from error

    def require_components(
        # Keep the remaining require components inputs visible at the exact code bundle
        # closure require components boundary.
        self,
        components: tuple[ResolvedComponent, ...],
        dependency_merkle_root: ContentDigest,
    ) -> None:
        """Prove an exact ResolvedRunSpec leaf set against this fresh closure."""

        from backtest.application.run_specs import dependency_merkle_root as compute_merkle

        expected_roles = tuple(item.role for item in self.manifests)
        actual_roles = tuple(item.role for item in components)
        if actual_roles != expected_roles:
            # Handle the exact code bundle closure require components actual_roles !=
            # expected_roles branch as a distinct logical block.
            raise CodeBundleIntegrityError(
                "resolved component roles differ from the exact code bundle closure"
            )
        for component, manifest in zip(components, self.manifests, strict=True):
            # Process components and manifests inside the bounded exact code bundle
            # closure require components loop.
            if (
                component.bundle_id != manifest.bundle_id
                or component.api_version != manifest.api_version
            ):
                # Handle the exact code bundle closure require components bundle id, api
                # version and component condition as a distinct block.
                raise CodeBundleIntegrityError(
                    f"resolved component {component.role} differs from the exact code bundle"
                )
        if compute_merkle(components) != dependency_merkle_root:
            raise CodeBundleIntegrityError("resolved dependency Merkle root is inconsistent")


# Define exact code bundle manifest from bytes as one focused operation with an explicit
# boundary.
def exact_code_bundle_manifest_from_bytes(payload: bytes) -> ExactCodeBundleManifest:
    """Decode and recompute an untrusted canonical exact-code manifest."""

    canonical = canonicalize_job_payload(payload)
    if canonical != payload:
        raise CodeBundleIntegrityError("code bundle manifest must be canonical JSON")
    value = json.loads(canonical)
    if not isinstance(value, dict):
        # Fail the exact code bundle manifest from bytes path with
        # CodeBundleIntegrityError for code bundle manifest must be an object when
        # isinstance and value is true; do not continue ambiguously.
        raise CodeBundleIntegrityError("code bundle manifest must be an object")
    document = cast(dict[str, Any], value)
    expected_keys = {
        "api_version",
        "artifact_schema",
        # Keep the bundle id component named inside the expected keys contract.
        "bundle_id",
        "code_digest",
        "contract_digest",
        "direct_dependencies",
        "package_name",
        # Keep the role component named inside the expected keys contract.
        "role",
        "source_files",
    }
    if set(document) != expected_keys or document["artifact_schema"] != "exact-code-bundle/v1":
        raise CodeBundleIntegrityError("code bundle manifest schema is invalid")
    # Assemble files value once so the exact code bundle manifest from bytes workflow
    # shares one value.
    files_value = document["source_files"]
    dependencies_value = document["direct_dependencies"]
    if not isinstance(files_value, list) or not isinstance(dependencies_value, list):
        raise CodeBundleIntegrityError("code bundle files and dependencies must be lists")
    files = tuple(_source_file_from_document(item) for item in files_value)
    # Assemble dependencies once so the exact code bundle manifest from bytes workflow
    # shares one value.
    dependencies = tuple(_dependency_from_document(item) for item in dependencies_value)
    result = ExactCodeBundleManifest(
        bundle_id=BundleId(_string(document, "bundle_id")),
        role=_string(document, "role"),
        api_version=_integer(document["api_version"], "api_version"),
        # Keep the document _string step visible while building result.
        package_name=_string(document, "package_name"),
        contract_digest=ContentDigest(_string(document, "contract_digest")),
        code_digest=ContentDigest(_string(document, "code_digest")),
        source_files=files,
        direct_dependencies=dependencies,
        # Complete ExactCodeBundleManifest only after its bundle id and role inputs are
        # visible in exact code bundle manifest from bytes.
    )
    if result.document() != document:
        raise CodeBundleIntegrityError("code bundle manifest is not in exact canonical form")
    return result


def _source_file_from_document(value: object) -> CodeSourceFile:
    # Execute the source file from document workflow in explicit, reviewable steps.
    if not isinstance(value, dict):
        raise CodeBundleIntegrityError("code source entry must be an object")
    document = cast(dict[str, object], value)
    if set(document) != {"path", "sha256", "size_bytes"}:
        raise CodeBundleIntegrityError("code source entry schema is invalid")
    # Return the completed source file from document result without a hidden fallback.
    return CodeSourceFile(
        path=_string(document, "path"),
        sha256=ContentDigest(_string(document, "sha256")),
        size_bytes=_integer(document["size_bytes"], "size_bytes", minimum=0),
    )


# Define dependency from document as one focused operation with an explicit boundary.
def _dependency_from_document(value: object) -> CodeBundleDependency:
    # Execute the dependency from document workflow in explicit, reviewable steps.
    if not isinstance(value, dict):
        raise CodeBundleIntegrityError("code dependency entry must be an object")
    document = cast(dict[str, object], value)
    if set(document) != {"api_version", "bundle_id", "role"}:
        raise CodeBundleIntegrityError("code dependency entry schema is invalid")
    # Return the completed dependency from document result without a hidden fallback.
    return CodeBundleDependency(
        role=_string(document, "role"),
        bundle_id=BundleId(_string(document, "bundle_id")),
        api_version=_integer(document["api_version"], "api_version"),
    )


# Define code digest as one focused operation with an explicit boundary.
def _code_digest(files: tuple[CodeSourceFile, ...]) -> ContentDigest:
    return domain_digest("backtest.exact-code-files.v1", [item.document() for item in files])


def _require_acyclic(by_role: dict[str, ExactCodeBundleManifest]) -> None:
    # Execute the require acyclic workflow in explicit, reviewable steps.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(role: str) -> None:
        # Execute the visit workflow in explicit, reviewable steps.
        if role in visiting:
            raise CodeBundleIntegrityError("bundle closure contains a dependency cycle")
        if role in visited:
            return
        visiting.add(role)
        # Traverse by_role[role].direct_dependencies explicitly so each visit iteration
        # remains traceable.
        for dependency in by_role[role].direct_dependencies:
            visit(dependency.role)
        visiting.remove(role)
        visited.add(role)

    for role in sorted(by_role):
        # Invoke visit for role as a visible require acyclic step.
        visit(role)


def _require_role(value: str) -> None:
    # Execute the require role workflow in explicit, reviewable steps.
    if not value or value != value.strip() or "\x00" in value:
        raise CodeBundleIntegrityError("bundle role must be non-empty, trimmed and NUL-free")


def _string(document: dict[str, object], field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = document[field]
    if not isinstance(value, str) or not value or value != value.strip():
        raise CodeBundleIntegrityError(f"{field} must be a non-empty trimmed string")
    return value


def _integer(value: object, field: str, *, minimum: int = 1) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CodeBundleIntegrityError(f"{field} must be an integer >= {minimum}")
    return value


__all__ = [
    "CodeBundleDependency",
    # Keep the code bundle integrity error component named inside the all contract.
    "CodeBundleIntegrityError",
    "CodeSourceFile",
    "ExactCodeBundleClosure",
    "ExactCodeBundleManifest",
    "PinnedCodeBundleIdentity",
    # Keep the pinned code bundle set component named inside the all contract.
    "PinnedCodeBundleSet",
    "exact_code_bundle_manifest_from_bytes",
]
