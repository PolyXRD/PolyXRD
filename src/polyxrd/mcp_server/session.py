"""
Session state management for PolyXRD MCP Server.

Holds all intermediate analysis results (loaded data, peaks, phases,
refinement results) so that multiple MCP tool calls can share state
within a single session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from polyxrd.models.peak import PeakList, FitResult
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.models.refinement import RefinementResult


@dataclass
class MCPSession:
    """Holds session-level state across MCP tool calls.

    The session stores the "current" data at each stage of the XRD
    analysis pipeline so that downstream tools (e.g. peak detection)
    can automatically pick up upstream results (e.g. loaded data)
    without the AI model having to pass raw arrays back and forth.
    """

    # Pipeline data slots
    raw_data: Optional[XRDData] = None       # original loaded data
    processed_data: Optional[XRDData] = None  # after preprocessing
    peak_list: Optional[PeakList] = None       # detected peaks
    fit_results: list[FitResult] = field(default_factory=list)
    phase_matches: list[PhaseMatchResult] = field(default_factory=list)
    selected_phases: list[Phase] = field(default_factory=list)
    refinement_result: Optional[RefinementResult] = None

    # File tracking
    source_file: Optional[str] = None
    project_file: Optional[str] = None

    @property
    def current_data(self) -> Optional[XRDData]:
        """Get the most recent data in the pipeline."""
        return self.processed_data or self.raw_data

    def reset(self) -> None:
        """Clear all session state."""
        self.raw_data = None
        self.processed_data = None
        self.peak_list = None
        self.fit_results.clear()
        self.phase_matches.clear()
        self.selected_phases.clear()
        self.refinement_result = None
        self.source_file = None
        self.project_file = None


# Global singleton session
_session = MCPSession()


def get_session() -> MCPSession:
    """Get the global MCP session instance."""
    return _session
