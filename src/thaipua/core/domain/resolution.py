"""Resolution commands: the single entry point for slot decisions."""

from pydantic import BaseModel, ConfigDict

from thaipua.core.domain.cluster import ThaiCluster
from thaipua.core.domain.layout import LayoutEngine


class OverrideApproval(BaseModel):
    """Approve overwriting one locked slot in one font session."""

    model_config = ConfigDict(frozen=True)

    font_id: str
    codepoint: int


class OverrideRevocation(BaseModel):
    """Revoke one session's overwrite approval for a slot."""

    model_config = ConfigDict(frozen=True)

    font_id: str
    codepoint: int


class RelocatePin(BaseModel):
    """Pin one cluster to an absolute codepoint."""

    model_config = ConfigDict(frozen=True)

    cluster: ThaiCluster
    codepoint: int


ResolveCommand = OverrideApproval | OverrideRevocation | RelocatePin


def resolve(engine: LayoutEngine, command: ResolveCommand) -> LayoutEngine:
    """Apply one resolution command, returning the new engine."""
    if isinstance(command, OverrideApproval):
        return engine.with_override(command.font_id, command.codepoint)
    if isinstance(command, OverrideRevocation):
        return engine.without_override(command.font_id, command.codepoint)
    return engine.with_relocation(command.cluster, command.codepoint)
