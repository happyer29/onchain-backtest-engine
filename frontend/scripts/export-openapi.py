"""Export transport schemas without constructing repositories, secrets or a controller."""

import json
from pathlib import Path

from backtest.domain.identifiers import ContentDigest
from backtest.interfaces.api.app import ControlUseCases, create_app

# Route registration is declarative; this export never invokes a use case or lifespan.
services = object.__new__(ControlUseCases)
app = create_app(services, control_plane_id=ContentDigest("0" * 64))
output = Path(__file__).parents[1] / "src/generated/openapi.json"
output.write_text(json.dumps(app.openapi(), ensure_ascii=False), encoding="utf-8")
