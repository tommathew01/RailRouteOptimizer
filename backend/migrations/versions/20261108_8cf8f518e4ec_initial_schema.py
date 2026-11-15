"""initial schema

Revision ID: 8cf8f518e4ec
Revises:
Create Date: 2026-11-08 19:04:14.209093+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8cf8f518e4ec"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "availability_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("train_number", sa.String(length=5), nullable=False),
        sa.Column("train_start_date", sa.Date(), nullable=False),
        sa.Column("journey_date", sa.Date(), nullable=False),
        sa.Column("source_station_code", sa.String(length=8), nullable=False),
        sa.Column("destination_station_code", sa.String(length=8), nullable=False),
        sa.Column("travel_class", sa.String(length=4), nullable=False),
        sa.Column("quota", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("availability_text", sa.String(length=120), nullable=True),
        sa.Column("raw_status", sa.String(length=120), nullable=True),
        sa.Column("provider_status", sa.String(length=60), nullable=True),
        sa.Column("waitlist_type", sa.String(length=8), nullable=True),
        sa.Column("waitlist_number", sa.Integer(), nullable=True),
        sa.Column("rac_number", sa.Integer(), nullable=True),
        sa.Column("available_count", sa.Integer(), nullable=True),
        sa.Column("can_book", sa.Boolean(), nullable=True),
        sa.Column("prediction_text", sa.String(length=200), nullable=True),
        sa.Column("prediction_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("prediction_percentage_source", sa.String(length=8), nullable=True),
        sa.Column("fare_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("fare_basis", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anomalies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_observations")),
    )
    op.create_index(
        "ix_availability_observations_identity",
        "availability_observations",
        [
            "train_number",
            "journey_date",
            "source_station_code",
            "destination_station_code",
            "travel_class",
            "quota",
            sa.text("observed_at DESC"),
        ],
        unique=False,
    )
    op.create_index(
        "ix_availability_observations_observed_at",
        "availability_observations",
        ["observed_at"],
        unique=False,
    )
    op.create_table(
        "journey_searches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_station_code", sa.String(length=8), nullable=False),
        sa.Column("destination_station_code", sa.String(length=8), nullable=False),
        sa.Column("journey_date", sa.Date(), nullable=False),
        sa.Column("classes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quota", sa.String(length=4), server_default="GN", nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("train_numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("max_segments", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("search_completeness", sa.String(length=32), nullable=True),
        sa.Column("incomplete_reason", sa.String(length=64), nullable=True),
        sa.Column("request_budget", sa.Integer(), nullable=False),
        sa.Column("requests_made", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("result_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journey_searches")),
    )
    op.create_index(
        "ix_journey_searches_created_at_desc",
        "journey_searches",
        [sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index("ix_journey_searches_status", "journey_searches", ["status"], unique=False)
    op.create_table(
        "stations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stations")),
        sa.UniqueConstraint("code", name=op.f("uq_stations_code")),
    )
    op.create_table(
        "trains",
        sa.Column("train_number", sa.String(length=5), nullable=False),
        sa.Column("train_name", sa.String(length=160), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("train_number", name=op.f("pk_trains")),
    )
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("endpoint", sa.String(length=40), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("search_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["journey_searches.id"],
            name=op.f("fk_provider_usage_search_id_journey_searches"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_usage")),
    )
    op.create_index(
        "ix_provider_usage_provider_created",
        "provider_usage",
        ["provider", "created_at"],
        unique=False,
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("train_number", sa.String(length=5), nullable=False),
        sa.Column("train_name", sa.String(length=160), nullable=True),
        sa.Column("travel_class", sa.String(length=4), nullable=False),
        sa.Column("quota", sa.String(length=4), nullable=False),
        sa.Column("train_start_date", sa.Date(), nullable=False),
        sa.Column("segment_count", sa.SmallInteger(), nullable=False),
        sa.Column("status_tier", sa.SmallInteger(), nullable=False),
        sa.Column("ranking_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_fare", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("fare_complete", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["journey_searches.id"],
            name=op.f("fk_recommendations_search_id_journey_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
    )
    op.create_index(
        "ix_recommendations_search_rank", "recommendations", ["search_id", "rank"], unique=False
    )
    op.create_table(
        "segment_query_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_id", sa.Uuid(), nullable=True),
        sa.Column("train_number", sa.String(length=5), nullable=False),
        sa.Column("train_start_date", sa.Date(), nullable=False),
        sa.Column("journey_date", sa.Date(), nullable=False),
        sa.Column("source_station_code", sa.String(length=8), nullable=False),
        sa.Column("destination_station_code", sa.String(length=8), nullable=False),
        sa.Column("travel_class", sa.String(length=4), nullable=False),
        sa.Column("quota", sa.String(length=4), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("provider_latency_ms", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("observation_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["availability_observations.id"],
            name=op.f("fk_segment_query_runs_observation_id_availability_observations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["journey_searches.id"],
            name=op.f("fk_segment_query_runs_search_id_journey_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_segment_query_runs")),
    )
    op.create_index(
        "ix_segment_query_runs_search_outcome",
        "segment_query_runs",
        ["search_id", "outcome"],
        unique=False,
    )
    op.create_table(
        "train_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("train_number", sa.String(length=5), nullable=False),
        sa.Column("route_version", sa.String(length=64), nullable=False),
        sa.Column("journey_date", sa.Date(), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_verified", sa.Boolean(), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("classes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("running_days", sa.String(length=16), nullable=True),
        sa.Column("anomalies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["train_number"],
            ["trains.train_number"],
            name=op.f("fk_train_routes_train_number_trains"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_train_routes")),
        sa.UniqueConstraint(
            "train_number", "route_version", name=op.f("uq_train_routes_train_number_route_version")
        ),
    )
    op.create_table(
        "recommendation_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.SmallInteger(), nullable=False),
        sa.Column("availability_observation_id", sa.Uuid(), nullable=False),
        sa.Column("source_station_code", sa.String(length=8), nullable=False),
        sa.Column("destination_station_code", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(
            ["availability_observation_id"],
            ["availability_observations.id"],
            name=op.f(
                "fk_recommendation_segments_availability_observation_id_availability_observations"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            name=op.f("fk_recommendation_segments_recommendation_id_recommendations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_segments")),
        sa.UniqueConstraint(
            "recommendation_id",
            "sequence_index",
            name=op.f("uq_recommendation_segments_recommendation_id_sequence_index"),
        ),
    )
    op.create_table(
        "train_stops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("route_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("station_code", sa.String(length=8), nullable=False),
        sa.Column("station_name", sa.String(length=160), nullable=True),
        sa.Column("arrival_time", sa.Time(), nullable=True),
        sa.Column("departure_time", sa.Time(), nullable=True),
        sa.Column("day_offset", sa.SmallInteger(), nullable=True),
        sa.Column("halt_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("platform", sa.String(length=16), nullable=True),
        sa.Column("is_stoppage", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["train_routes.id"],
            name=op.f("fk_train_stops_route_id_train_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["station_code"], ["stations.code"], name=op.f("fk_train_stops_station_code_stations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_train_stops")),
        sa.UniqueConstraint(
            "route_id", "sequence_index", name=op.f("uq_train_stops_route_id_sequence_index")
        ),
    )


def downgrade() -> None:
    op.drop_table("train_stops")
    op.drop_table("recommendation_segments")
    op.drop_table("train_routes")
    op.drop_index("ix_segment_query_runs_search_outcome", table_name="segment_query_runs")
    op.drop_table("segment_query_runs")
    op.drop_index("ix_recommendations_search_rank", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_provider_usage_provider_created", table_name="provider_usage")
    op.drop_table("provider_usage")
    op.drop_table("trains")
    op.drop_table("stations")
    op.drop_index("ix_journey_searches_status", table_name="journey_searches")
    op.drop_index("ix_journey_searches_created_at_desc", table_name="journey_searches")
    op.drop_table("journey_searches")
    op.drop_index(
        "ix_availability_observations_observed_at", table_name="availability_observations"
    )
    op.drop_index("ix_availability_observations_identity", table_name="availability_observations")
    op.drop_table("availability_observations")
