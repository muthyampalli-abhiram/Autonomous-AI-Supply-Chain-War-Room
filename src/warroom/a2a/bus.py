"""In-process A2A (Agent-to-Agent) message bus and task lifecycle engine."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from warroom.a2a.models import A2AMessage, A2ATask, AgentCard


class A2ABus:
    """Synchronous in-process communication bus coordinating agents and human escalations."""

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._messages: list[A2AMessage] = []
        self._msg_counter: int = 1
        self._task_counter: int = 1

    def register(self, card: AgentCard) -> None:
        """Register an agent capability card on the bus."""
        self._cards[card.agent_id] = card

    def discover(self, skill: str | None = None) -> list[AgentCard]:
        """Discover registered agent cards, optionally filtering by skill keyword."""
        if skill is None:
            return list(self._cards.values())
        return [c for c in self._cards.values() if skill in c.skills]

    def _validate_endpoint(self, endpoint: str, allow_all: bool = False) -> None:
        if allow_all and endpoint == "all":
            return
        if endpoint not in self._cards:
            raise ValueError(
                f"Unknown endpoint '{endpoint}'. Registered cards: {list(self._cards.keys())}"
            )

    def _next_message_id(self) -> str:
        mid = f"MSG-{self._msg_counter:04d}"
        self._msg_counter += 1
        return mid

    def _next_task_id(self) -> str:
        tid = f"TASK-{self._task_counter:04d}"
        self._task_counter += 1
        return tid

    def _log_message(
        self,
        sender: str,
        recipient: str,
        msg_type: str,
        task_id: str | None = None,
        text: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> A2AMessage:
        parts: list[dict[str, Any]] = []
        if text is not None:
            parts.append({"kind": "text", "text": text})
        if data is not None:
            parts.append({"kind": "data", "data": data})

        msg = A2AMessage(
            message_id=self._next_message_id(),
            task_id=task_id,
            sender=sender,
            recipient=recipient,
            msg_type=msg_type,  # type: ignore[arg-type]
            parts=parts,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        self._messages.append(msg)
        return msg

    def send_task(
        self,
        sender: str,
        recipient: str,
        text: str,
        data: dict[str, Any] | None = None,
    ) -> A2ATask:
        """Create and submit a task, logging a task_request message."""
        self._validate_endpoint(sender)
        self._validate_endpoint(recipient)

        task_id = self._next_task_id()
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task = A2ATask(
            task_id=task_id,
            sender=sender,
            recipient=recipient,
            state="submitted",
            state_history=[{"state": "submitted", "timestamp": ts}],
        )
        self._tasks[task_id] = task

        self._log_message(
            sender=sender,
            recipient=recipient,
            msg_type="task_request",
            task_id=task_id,
            text=text,
            data=data,
        )
        return task

    def update_task(
        self, task_id: str, state: str, text: str | None = None
    ) -> A2ATask:
        """Update task state following legal transition rules: submitted -> working -> completed/failed."""
        if task_id not in self._tasks:
            raise ValueError(f"Task '{task_id}' not found")

        task = self._tasks[task_id]
        current_state = task.state

        # Validate legal transition
        is_legal = False
        if current_state == "submitted" and state == "working":
            is_legal = True
        elif current_state == "working" and state in ("completed", "failed"):
            is_legal = True

        if not is_legal:
            raise ValueError(
                f"Illegal state transition from '{current_state}' to '{state}' for task {task_id}"
            )

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task.state = state  # type: ignore[assignment]
        task.state_history.append({"state": state, "timestamp": ts})

        self._log_message(
            sender=task.recipient,
            recipient=task.sender,
            msg_type="status_update",
            task_id=task_id,
            text=text or f"Task {task_id} transitioned to {state}",
        )
        return task

    def complete_task(
        self, task_id: str, artifact: dict[str, Any], text: str | None = None
    ) -> A2ATask:
        """Mark task completed with an artifact containing only agent status and summary."""
        if task_id not in self._tasks:
            raise ValueError(f"Task '{task_id}' not found")

        task = self._tasks[task_id]
        if task.state != "working":
            self.update_task(task_id, "working")

        # Legal transition to completed
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task.state = "completed"
        task.state_history.append({"state": "completed", "timestamp": ts})
        task.artifact = artifact

        self._log_message(
            sender=task.recipient,
            recipient=task.sender,
            msg_type="task_result",
            task_id=task_id,
            text=text or f"Task {task_id} completed successfully",
            data=artifact,
        )
        return task

    def fail_task(self, task_id: str, error: str, text: str | None = None) -> A2ATask:
        """Mark task as failed with an error message."""
        if task_id not in self._tasks:
            raise ValueError(f"Task '{task_id}' not found")

        task = self._tasks[task_id]
        if task.state != "working":
            # Transition to working first if still in submitted
            ts_work = datetime.datetime.now(datetime.timezone.utc).isoformat()
            task.state = "working"
            task.state_history.append({"state": "working", "timestamp": ts_work})

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task.state = "failed"
        task.state_history.append({"state": "failed", "timestamp": ts})
        task.error = error

        self._log_message(
            sender=task.recipient,
            recipient=task.sender,
            msg_type="task_result",
            task_id=task_id,
            text=text or f"Task {task_id} failed: {error}",
            data={"error": error},
        )
        return task

    def broadcast(
        self, sender: str, text: str, data: dict[str, Any] | None = None
    ) -> A2AMessage:
        """Send a broadcast announcement to 'all'."""
        self._validate_endpoint(sender)
        return self._log_message(
            sender=sender,
            recipient="all",
            msg_type="broadcast",
            text=text,
            data=data,
        )

    def escalate(
        self,
        sender: str,
        recipient: str,
        text: str,
        data: dict[str, Any] | None = None,
    ) -> A2AMessage:
        """Send an escalation message to a designated recipient or human approver."""
        self._validate_endpoint(sender)
        self._validate_endpoint(recipient)
        return self._log_message(
            sender=sender,
            recipient=recipient,
            msg_type="escalation",
            text=text,
            data=data,
        )

    @property
    def log(self) -> list[dict[str, Any]]:
        """Return serialized list of all messages exchanged on the bus in order."""
        return [m.model_dump() for m in self._messages]

    @property
    def tasks(self) -> dict[str, A2ATask]:
        """Return all tracked tasks."""
        return self._tasks

    def export_jsonl(self, path: str | Path) -> None:
        """Write bus log messages to a JSONL file, one line per JSON object."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            for entry in self.log:
                f.write(json.dumps(entry, default=str) + "\n")
