from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    UNKNOWN = "unknown"


class EdgeKind(str, Enum):
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    DEFINES = "DEFINES"


class Confidence(str, Enum):
    CERTAIN = "certain"
    INFERRED = "inferred"


class SourceSpan(BaseModel):
    start_line: int
    start_col: int
    end_line: int
    end_col: int


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    name: str
    file_path: str = Field(alias="filePath")
    span: SourceSpan | None = None
    confidence: Confidence = Confidence.CERTAIN
    is_async: bool = Field(default=False, alias="isAsync")
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: EdgeKind
    confidence: Confidence = Confidence.CERTAIN
    label: str | None = None

    model_config = {"populate_by_name": True}


class GraphPayload(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AnalyzeRequest(BaseModel):
    root_path: str = Field(alias="rootPath")
    include_patterns: list[str] | None = None

    model_config = {"populate_by_name": True}


class TraceRequest(BaseModel):
    entry_node_id: str = Field(alias="entryNodeId")
    max_depth: int = Field(default=20, ge=1, le=200)

    model_config = {"populate_by_name": True}


class TraceResponse(BaseModel):
    paths: list[list[str]]
    truncated: bool
    cycles_skipped: int = Field(alias="cyclesSkipped")

    model_config = {"populate_by_name": True}


class ImpactRequest(BaseModel):
    node_id: str = Field(alias="nodeId")

    model_config = {"populate_by_name": True}


class ImpactResponse(BaseModel):
    impacted_node_ids: list[str] = Field(alias="impactedNodeIds")
    ordered_by_distance: list[str] = Field(alias="orderedByDistance")

    model_config = {"populate_by_name": True}


class NLQueryRequest(BaseModel):
    question: str
    node_id: str | None = Field(default=None, alias="nodeId")
    include_impact: bool = Field(default=True, alias="includeImpact")

    model_config = {"populate_by_name": True}


class NLQueryResponse(BaseModel):
    answer: str
    structured_context: dict[str, Any] = Field(alias="structuredContext")

    model_config = {"populate_by_name": True}


class ReactFlowNode(BaseModel):
    id: str
    type: Literal["symbol"] = "symbol"
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: dict[str, Any] = Field(default_factory=dict)


class ReactFlowEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ReactFlowGraph(BaseModel):
    nodes: list[ReactFlowNode]
    edges: list[ReactFlowEdge]
