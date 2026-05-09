from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

import asyncpg

from .models import Edge, GraphSubset, Node, ReasoningLog
from .storage_security import FieldCrypto


def utcnow() -> datetime:
    return datetime.now(UTC)


class GraphStore(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def create_reasoning_log(self, trigger: str) -> ReasoningLog: ...

    @abstractmethod
    async def append_reasoning_step(self, log_id: UUID, step: dict[str, Any]) -> None: ...

    @abstractmethod
    async def finish_reasoning_log(self, log_id: UUID, conclusion: str) -> None: ...

    @abstractmethod
    async def list_reasoning_logs(self) -> list[ReasoningLog]: ...

    @abstractmethod
    async def get_reasoning_log(self, log_id: UUID) -> ReasoningLog | None: ...

    @abstractmethod
    async def create_node(
        self,
        type: str,
        payload: dict[str, Any],
        created_by: str,
        reasoning_log_id: UUID | None = None,
        status: str = "pending_review",
        id: UUID | None = None,
    ) -> Node: ...

    @abstractmethod
    async def create_node_with_edge(
        self,
        type: str,
        payload: dict[str, Any],
        created_by: str,
        reasoning_log_id: UUID | None,
        status: str,
        node_id: UUID,
        to_node: UUID,
        edge_type: str,
    ) -> tuple[Node, Edge]: ...

    @abstractmethod
    async def create_edge(self, from_node: UUID, to_node: UUID, edge_type: str) -> Edge: ...

    @abstractmethod
    async def list_nodes(self, patient_id: str | None = None, node_types: list[str] | None = None) -> list[Node]: ...

    @abstractmethod
    async def list_edges(self) -> list[Edge]: ...

    @abstractmethod
    async def get_node(self, node_id: UUID) -> Node | None: ...

    @abstractmethod
    async def update_node_status(self, node_id: UUID, status: str) -> Node | None: ...

    @abstractmethod
    async def update_node_payload(self, node_id: UUID, payload: dict[str, Any], status: str) -> Node | None: ...

    @abstractmethod
    async def get_system_state(self, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def set_system_state(self, key: str, value: dict[str, Any], locked_until: datetime | None = None) -> dict[str, Any]: ...

    @abstractmethod
    async def acquire_system_lock(self, key: str, ttl_seconds: int) -> bool: ...

    async def graph_subset(self, patient_id: str, node_types: list[str] | None = None) -> GraphSubset:
        nodes = await self.list_nodes(patient_id, node_types)
        node_ids = {node.id for node in nodes}
        edges = [edge for edge in await self.list_edges() if edge.from_node in node_ids or edge.to_node in node_ids]
        return GraphSubset(nodes=nodes, edges=edges)


class MemoryGraphStore(GraphStore):
    def __init__(self, encryption_key: str | None = None) -> None:
        self.nodes: dict[UUID, Node] = {}
        self.edges: dict[UUID, Edge] = {}
        self.logs: dict[UUID, ReasoningLog] = {}
        self.system_state: dict[str, dict[str, Any]] = {}
        self.crypto = FieldCrypto(encryption_key)

    async def init(self) -> None:
        return None

    async def create_reasoning_log(self, trigger: str) -> ReasoningLog:
        log = ReasoningLog(id=uuid4(), trigger=trigger, steps=[], conclusion=None, created_at=utcnow())
        self.logs[log.id] = log
        return log

    async def append_reasoning_step(self, log_id: UUID, step: dict[str, Any]) -> None:
        log = self.logs[log_id]
        log.steps.append({"at": utcnow().isoformat(), **step})

    async def finish_reasoning_log(self, log_id: UUID, conclusion: str) -> None:
        log = self.logs[log_id]
        self.logs[log_id] = log.model_copy(update={"conclusion": conclusion})

    async def list_reasoning_logs(self) -> list[ReasoningLog]:
        return sorted(self.logs.values(), key=lambda item: item.created_at, reverse=True)

    async def get_reasoning_log(self, log_id: UUID) -> ReasoningLog | None:
        return self.logs.get(log_id)

    async def create_node(
        self,
        type: str,
        payload: dict[str, Any],
        created_by: str,
        reasoning_log_id: UUID | None = None,
        status: str = "pending_review",
        id: UUID | None = None,
    ) -> Node:
        node = Node(
            id=id or uuid4(),
            type=type,
            payload=self.crypto.encrypt_payload(payload),
            created_by=created_by,
            created_at=utcnow(),
            reasoning_log_id=reasoning_log_id,
            status=status,
        )
        self.nodes[node.id] = node
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)})

    async def create_edge(self, from_node: UUID, to_node: UUID, edge_type: str) -> Edge:
        edge = Edge(id=uuid4(), from_node=from_node, to_node=to_node, type=edge_type, created_at=utcnow())
        self.edges[edge.id] = edge
        return edge

    async def create_node_with_edge(
        self,
        type: str,
        payload: dict[str, Any],
        created_by: str,
        reasoning_log_id: UUID | None,
        status: str,
        node_id: UUID,
        to_node: UUID,
        edge_type: str,
    ) -> tuple[Node, Edge]:
        node = await self.create_node(type, payload, created_by, reasoning_log_id, status, id=node_id)
        edge = await self.create_edge(node.id, to_node, edge_type)
        return node, edge

    async def list_nodes(self, patient_id: str | None = None, node_types: list[str] | None = None) -> list[Node]:
        rows = [node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}) for node in self.nodes.values()]
        if patient_id:
            rows = [node for node in rows if node.payload.get("patient_id") == patient_id]
        if node_types:
            rows = [node for node in rows if node.type in node_types]
        return sorted(rows, key=lambda item: item.created_at, reverse=True)

    async def list_edges(self) -> list[Edge]:
        return list(self.edges.values())

    async def get_node(self, node_id: UUID) -> Node | None:
        node = self.nodes.get(node_id)
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}) if node else None

    async def update_node_status(self, node_id: UUID, status: str) -> Node | None:
        node = self.nodes.get(node_id)
        if not node:
            return None
        updated = node.model_copy(update={"status": status})
        self.nodes[node_id] = updated
        return updated.model_copy(update={"payload": self.crypto.decrypt_payload(updated.payload)})

    async def update_node_payload(self, node_id: UUID, payload: dict[str, Any], status: str) -> Node | None:
        node = self.nodes.get(node_id)
        if not node:
            return None
        decrypted_payload = self.crypto.decrypt_payload(node.payload)
        updated = node.model_copy(update={"payload": self.crypto.encrypt_payload({**decrypted_payload, **payload}), "status": status})
        self.nodes[node_id] = updated
        return updated.model_copy(update={"payload": self.crypto.decrypt_payload(updated.payload)})

    async def get_system_state(self, key: str) -> dict[str, Any] | None:
        item = self.system_state.get(key)
        return dict(item) if item else None

    async def set_system_state(self, key: str, value: dict[str, Any], locked_until: datetime | None = None) -> dict[str, Any]:
        item = {
            "key": key,
            "value": value,
            "locked_until": locked_until,
            "updated_at": utcnow(),
        }
        self.system_state[key] = item
        return dict(item)

    async def acquire_system_lock(self, key: str, ttl_seconds: int) -> bool:
        now = utcnow()
        item = self.system_state.get(key)
        locked_until = item.get("locked_until") if item else None
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until and locked_until > now:
            return False
        value = dict(item.get("value", {})) if item else {}
        await self.set_system_state(key, value, now + timedelta(seconds=ttl_seconds))
        return True


class PostgresGraphStore(GraphStore):
    def __init__(self, database_url: str, schema_path: Path, encryption_key: str | None = None) -> None:
        self.database_url = database_url
        self.schema_path = schema_path
        self.pool: asyncpg.Pool | None = None
        self.crypto = FieldCrypto(encryption_key)

    async def init(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self.pool.acquire() as conn:
            await conn.execute(self.schema_path.read_text(encoding="utf-8"))

    def _conn(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("PostgresGraphStore not initialized")
        return self.pool

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        async with self._conn().acquire() as conn:
            async with conn.transaction():
                yield conn

    async def create_reasoning_log(self, trigger: str) -> ReasoningLog:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow(
                "insert into reasoning_logs (id, trigger, steps) values ($1, $2, '[]'::jsonb) returning *",
                uuid4(),
                trigger,
            )
        return _log(row)

    async def append_reasoning_step(self, log_id: UUID, step: dict[str, Any]) -> None:
        async with self._conn().acquire() as conn:
            await conn.execute(
                """
                update reasoning_logs
                set steps = steps || $2::jsonb
                where id = $1
                """,
                log_id,
                json.dumps([{"at": utcnow().isoformat(), **step}]),
            )

    async def finish_reasoning_log(self, log_id: UUID, conclusion: str) -> None:
        async with self._conn().acquire() as conn:
            await conn.execute("update reasoning_logs set conclusion = $2 where id = $1", log_id, conclusion)

    async def list_reasoning_logs(self) -> list[ReasoningLog]:
        async with self._conn().acquire() as conn:
            rows = await conn.fetch("select * from reasoning_logs order by created_at desc")
        return [_log(row) for row in rows]

    async def get_reasoning_log(self, log_id: UUID) -> ReasoningLog | None:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow("select * from reasoning_logs where id = $1", log_id)
        return _log(row) if row else None

    async def create_node(
        self,
        type: str,
        payload: dict[str, Any],
        created_by: str,
        reasoning_log_id: UUID | None = None,
        status: str = "pending_review",
        id: UUID | None = None,
    ) -> Node:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into nodes (id, type, payload, created_by, reasoning_log_id, status)
                values ($1, $2, $3::jsonb, $4, $5, $6)
                returning *
                """,
                id or uuid4(),
                type,
                json.dumps(self.crypto.encrypt_payload(payload)),
                created_by,
                reasoning_log_id,
                status,
            )
        node = _node(row)
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)})

    async def create_edge(self, from_node: UUID, to_node: UUID, edge_type: str) -> Edge:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow(
                "insert into edges (id, from_node, to_node, type) values ($1, $2, $3, $4) returning *",
                uuid4(),
                from_node,
                to_node,
                edge_type,
            )
        return _edge(row)

    async def create_node_with_edge(
        self,
        type: str,
        payload: dict[str, Any],
        created_by: str,
        reasoning_log_id: UUID | None,
        status: str,
        node_id: UUID,
        to_node: UUID,
        edge_type: str,
    ) -> tuple[Node, Edge]:
        async with self.transaction() as conn:
            node_row = await conn.fetchrow(
                """
                insert into nodes (id, type, payload, created_by, reasoning_log_id, status)
                values ($1, $2, $3::jsonb, $4, $5, $6)
                returning *
                """,
                node_id,
                type,
                json.dumps(payload),
                created_by,
                reasoning_log_id,
                status,
            )
            edge_row = await conn.fetchrow(
                "insert into edges (id, from_node, to_node, type) values ($1, $2, $3, $4) returning *",
                uuid4(),
                node_id,
                to_node,
                edge_type,
            )
        node = _node(node_row)
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}), _edge(edge_row)

    async def list_nodes(self, patient_id: str | None = None, node_types: list[str] | None = None) -> list[Node]:
        conditions: list[str] = []
        args: list[Any] = []
        if patient_id:
            args.append(patient_id)
            conditions.append(f"payload->>'patient_id' = ${len(args)}")
        if node_types:
            args.append(node_types)
            conditions.append(f"type = any(${len(args)}::text[])")
        where = f"where {' and '.join(conditions)}" if conditions else ""
        async with self._conn().acquire() as conn:
            rows = await conn.fetch(f"select * from nodes {where} order by created_at desc", *args)
        return [node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}) for node in (_node(row) for row in rows)]

    async def list_edges(self) -> list[Edge]:
        async with self._conn().acquire() as conn:
            rows = await conn.fetch("select * from edges")
        return [_edge(row) for row in rows]

    async def get_node(self, node_id: UUID) -> Node | None:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow("select * from nodes where id = $1", node_id)
        node = _node(row) if row else None
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}) if node else None

    async def update_node_status(self, node_id: UUID, status: str) -> Node | None:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow("update nodes set status = $2 where id = $1 returning *", node_id, status)
        node = _node(row) if row else None
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}) if node else None

    async def update_node_payload(self, node_id: UUID, payload: dict[str, Any], status: str) -> Node | None:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow(
                """
                update nodes
                set payload = payload || $2::jsonb, status = $3
                where id = $1
                returning *
                """,
                node_id,
                json.dumps(self.crypto.encrypt_payload(payload)),
                status,
            )
        node = _node(row) if row else None
        return node.model_copy(update={"payload": self.crypto.decrypt_payload(node.payload)}) if node else None

    async def get_system_state(self, key: str) -> dict[str, Any] | None:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow("select * from system_state where key = $1", key)
        return _state(row) if row else None

    async def set_system_state(self, key: str, value: dict[str, Any], locked_until: datetime | None = None) -> dict[str, Any]:
        async with self._conn().acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into system_state (key, value, locked_until, updated_at)
                values ($1, $2::jsonb, $3, now())
                on conflict (key) do update
                set value = excluded.value,
                    locked_until = excluded.locked_until,
                    updated_at = now()
                returning *
                """,
                key,
                json.dumps(value),
                locked_until,
            )
        return _state(row)

    async def acquire_system_lock(self, key: str, ttl_seconds: int) -> bool:
        async with self.transaction() as conn:
            row = await conn.fetchrow(
                """
                insert into system_state (key, value, locked_until, updated_at)
                values ($1, '{}'::jsonb, now() + make_interval(secs => $2), now())
                on conflict (key) do update
                set locked_until = now() + make_interval(secs => $2),
                    updated_at = now()
                where system_state.locked_until is null or system_state.locked_until <= now()
                returning true as acquired
                """,
                key,
                ttl_seconds,
            )
        return bool(row and row["acquired"])


def _node(row: Any) -> Node:
    return Node(**dict(row))


def _edge(row: Any) -> Edge:
    return Edge(**dict(row))


def _log(row: Any) -> ReasoningLog:
    return ReasoningLog(**dict(row))


def _state(row: Any) -> dict[str, Any]:
    item = dict(row)
    return {
        "key": item["key"],
        "value": item["value"],
        "locked_until": item["locked_until"],
        "updated_at": item["updated_at"],
    }
