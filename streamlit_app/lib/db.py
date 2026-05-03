"""Cached SQLAlchemy engine for the Streamlit pages.

We intentionally do NOT use ``st.cache_resource`` for the engine itself
(connections become stale on Streamlit reruns). Instead we cache a
factory and let SQLAlchemy's connection pool handle reuse.
"""

from __future__ import annotations

import os

import streamlit as st
from sqlalchemy import Engine, create_engine


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    user = os.environ.get("POSTGRES_USER", "glrecon")
    password = os.environ.get("POSTGRES_PASSWORD", "glrecon")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "glrecon")
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
    return create_engine(dsn, future=True, pool_pre_ping=True)


@st.cache_data(ttl=60, show_spinner=False)
def query_df(sql: str, params: dict | None = None):
    """Run a SELECT and return a pandas DataFrame, cached for 60 seconds."""
    import pandas as pd

    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params=params or {})
