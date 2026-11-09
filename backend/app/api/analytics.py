"""Analytics API routes (DOC3 §12.5 and §12.5A)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter

from app.analytics.service import AnalyticsService
from app.api.graph import get_graph as get_graph_snapshot
from app.contracts.analytics import AnalyticsRequest, AnalyticsResult, ShortestPathResult
from app.contracts.errors import InternalError, ValidationError

router = APIRouter(prefix="/analytics", tags=["analytics"])

_DATASETS = frozenset({"synthetic_demo", "live_public"})
_CENTRALITY_ALGORITHMS = ("degree", "betweenness", "pagerank", "community")
_analytics_service = AnalyticsService()


def _validate_scope(dataset: str, as_of: Optional[str]) -> None:
    if dataset not in _DATASETS:
        raise ValidationError("dataset must be 'synthetic_demo' or 'live_public'")
    if as_of is not None:
        try:
            datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationError("as_of must be an ISO-8601 timestamp") from exc


def _parse_algorithms(value: Optional[str]) -> list[str]:
    if value is None:
        return list(_CENTRALITY_ALGORITHMS)

    tokens = [token.strip() for token in value.split(",")]
    if not tokens or any(not token for token in tokens):
        raise ValidationError("algorithms must be a comma-separated list of supported algorithms")

    unsupported = sorted(set(tokens) - set(_CENTRALITY_ALGORITHMS))
    if unsupported:
        raise ValidationError(
            "GET /analytics supports only degree, betweenness, pagerank, and community",
            details={"unsupported_algorithms": unsupported},
        )
    return list(dict.fromkeys(tokens))


async def _graph_inputs(dataset: str, as_of: Optional[str]):
    """Use C6's dataset/as_of-filtered graph response as D1's graph input."""
    snapshot = await get_graph_snapshot(dataset=dataset, as_of=as_of)
    relationships = snapshot["relationships"]
    nodes = [entity.entity_id for entity in snapshot["entities"]]
    return relationships, nodes


@router.get("", response_model=AnalyticsResult)
async def get_analytics(
    dataset: str = "synthetic_demo",
    as_of: Optional[str] = None,
    algorithms: Optional[str] = None,
) -> AnalyticsResult:
    """Return centrality/community analytics; shortest path is a separate route."""
    _validate_scope(dataset, as_of)
    requested_algorithms = _parse_algorithms(algorithms)
    relationships, nodes = await _graph_inputs(dataset, as_of)
    request = AnalyticsRequest(
        dataset=dataset,
        as_of=as_of,
        algorithms=requested_algorithms,
    )
    result, shortest_path = _analytics_service.compute(
        request,
        relationships=relationships,
        nodes=nodes,
    )
    if shortest_path is not None:
        raise InternalError("D1 returned a shortest path for a non-shortest-path request")
    return result


@router.get("/shortest-path", response_model=ShortestPathResult)
async def get_shortest_path(
    dataset: str = "synthetic_demo",
    as_of: Optional[str] = None,
    shortest_path_from: Optional[str] = None,
    shortest_path_to: Optional[str] = None,
) -> ShortestPathResult:
    """Return D1's shortest path for two entities in one graph snapshot."""
    _validate_scope(dataset, as_of)
    if not shortest_path_from or not shortest_path_to:
        raise ValidationError(
            "shortest_path_from and shortest_path_to are required non-empty entity IDs"
        )

    relationships, nodes = await _graph_inputs(dataset, as_of)
    request = AnalyticsRequest(
        dataset=dataset,
        as_of=as_of,
        algorithms=["shortest_path"],
        shortest_path_from=shortest_path_from,
        shortest_path_to=shortest_path_to,
    )
    _, shortest_path = _analytics_service.compute(
        request,
        relationships=relationships,
        nodes=nodes,
    )
    if shortest_path is None:
        raise InternalError("D1 did not return a shortest-path result")
    return shortest_path
