"""A record of exactly what was sent to the LLM, shown to the user as "What the AI saw"."""

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


@dataclass
class LlmAudit:
    calls: list[dict[str, str]] = field(default_factory=list)

    def messages(self, step: str, system: str, payload: dict[str, Any]) -> list[BaseMessage]:
        """Build the messages for one LLM call and record them; the recorded text is what is sent."""
        user = json.dumps(payload, indent=2, default=str)
        self.calls.append({"step": step, "system": system, "user": user})
        return [SystemMessage(content=system), HumanMessage(content=user)]
