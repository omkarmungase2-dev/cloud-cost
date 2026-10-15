"""
PostgreSQL storage via SQLAlchemy 2.0 asyncpg.
Provides models: requests, runs, approvals.
Handles background writes, upserts on conflict, and query endpoints.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, func, case, text, select
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger("firewall.db")


class Base(DeclarativeBase):
    pass


class RequestRecord(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    feature: Mapped[str] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    action: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RunRecord(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100))
    feature: Mapped[str] = mapped_column(String(100))
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str] = mapped_column(String(100))
    feature: Mapped[str] = mapped_column(String(100))
    projected_cost: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(50))
    decided_by: Mapped[str] = mapped_column(String(100))
    new_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wait_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Database:
    """Async database client for PostgreSQL."""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.session_factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        self.name = "postgres"

    async def save(self, rec: Dict[str, Any]) -> None:
        """
        In one transaction:
        1. Insert a requests row
        2. Upsert runs table (adding cost and counts)
        Actions BLOCK, DENIED, TIMEOUT count as blocked (call_count +0, blocked_count +1).
        Catches and prints exceptions so proxy never breaks.
        """
        try:
            action = rec.get("action", "ALLOW")
            is_blocked = action in ("BLOCK", "DENIED", "TIMEOUT")
            actual_cost = float(rec.get("actual_cost", 0.0) or 0.0)
            now = datetime.now(timezone.utc)

            req_obj = RequestRecord(
                run_id=rec.get("run_id", "no-run"),
                user_id=rec.get("user_id", "unknown"),
                feature=rec.get("feature", "unknown"),
                model=rec.get("model", ""),
                input_tokens=int(rec.get("input_tokens", 0) or 0),
                output_tokens=int(rec.get("output_tokens", 0) or 0),
                estimated_cost=float(rec.get("estimated_cost", 0.0) or 0.0),
                actual_cost=actual_cost,
                latency_ms=float(rec.get("latency_ms", 0.0) or 0.0),
                action=action,
                reason=rec.get("reason", ""),
            )

            upsert_stmt = pg_insert(RunRecord).values(
                run_id=rec.get("run_id", "no-run"),
                user_id=rec.get("user_id", "unknown"),
                feature=rec.get("feature", "unknown"),
                total_cost=actual_cost,
                call_count=0 if is_blocked else 1,
                blocked_count=1 if is_blocked else 0,
                status="blocked" if is_blocked else "running",
                started_at=now,
                last_at=now,
            )

            upsert_stmt = upsert_stmt.on_conflict_do_update(
                index_elements=[RunRecord.run_id],
                set_={
                    "total_cost": RunRecord.total_cost + upsert_stmt.excluded.total_cost,
                    "call_count": RunRecord.call_count + upsert_stmt.excluded.call_count,
                    "blocked_count": RunRecord.blocked_count + upsert_stmt.excluded.blocked_count,
                    "status": case(
                        (upsert_stmt.excluded.status == "blocked", "blocked"),
                        else_=RunRecord.status,
                    ),
                    "last_at": upsert_stmt.excluded.last_at,
                },
            )

            async with self.session_factory() as session:
                async with session.begin():
                    session.add(req_obj)
                    await session.execute(upsert_stmt)

        except Exception as e:
            logger.error(f"[db] Failed to save record: {e}", exc_info=True)
            print(f"[db] ERROR: Failed to save record: {e}")

    async def save_approval(self, rec: Dict[str, Any]) -> None:
        """Save an approval decision record."""
        try:
            app_obj = ApprovalRecord(
                run_id=rec.get("run_id", "no-run"),
                user_id=rec.get("user_id", "unknown"),
                feature=rec.get("feature", "unknown"),
                projected_cost=float(rec.get("projected_cost", 0.0) or 0.0),
                decision=rec.get("decision", ""),
                decided_by=rec.get("decided_by", ""),
                new_cap=float(rec["new_cap"]) if rec.get("new_cap") is not None else None,
                wait_seconds=float(rec.get("wait_seconds", 0.0) or 0.0),
            )
            async with self.session_factory() as session:
                async with session.begin():
                    session.add(app_obj)
        except Exception as e:
            logger.error(f"[db] Failed to save approval: {e}", exc_info=True)
            print(f"[db] ERROR: Failed to save approval: {e}")

    async def reset(self) -> None:
        """Truncate all three tables."""
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE TABLE requests, runs, approvals RESTART IDENTITY"))
        except Exception as e:
            logger.error(f"[db] Reset failed: {e}")
            print(f"[db] ERROR: Reset failed: {e}")

    async def fetch(self, sql: str, **params) -> List[Dict[str, Any]]:
        """Execute a SQL query with parameters and return list of dicts."""
        async with self.session_factory() as session:
            res = await session.execute(text(sql), params)
            rows = res.fetchall()
            return [dict(r._mapping) for r in rows]

    async def close(self) -> None:
        await self.engine.dispose()


class NoopDatabase:
    """Fallback when Postgres is unavailable."""

    name = "off"

    async def save(self, rec: Dict[str, Any]) -> None:
        pass

    async def save_approval(self, rec: Dict[str, Any]) -> None:
        pass

    async def reset(self) -> None:
        pass

    async def fetch(self, sql: str, **params) -> List[Dict[str, Any]]:
        return []

    async def close(self) -> None:
        pass


async def create_db(database_url: str, retries: int = 5, retry_delay: float = 2.0):
    """
    Connect to PostgreSQL with retries (Docker container may still be starting).
    Creates tables if connected. Falls back to NoopDatabase if unreachable.
    """
    for attempt in range(1, retries + 1):
        try:
            print(f"[db] Attempting Postgres connection ({attempt}/{retries})...")
            engine = create_async_engine(
                database_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=5,
                connect_args={"timeout": 1.5},
            )
            # Test connection and create tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print(f"[db] PostgreSQL connected and tables initialized.")
            return Database(engine)
        except Exception as e:
            print(f"[db] Postgres attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                await asyncio.sleep(retry_delay)

    print("[db] WARNING: PostgreSQL unavailable — database features disabled (db: off).")
    return NoopDatabase()
