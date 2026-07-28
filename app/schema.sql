CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS meeting_resource (
    id uuid PRIMARY KEY,
    wecom_userid text NOT NULL UNIQUE,
    display_name text NOT NULL,
    priority integer NOT NULL DEFAULT 100,
    enabled boolean NOT NULL DEFAULT true,
    health_status text NOT NULL DEFAULT 'HEALTHY'
        CHECK (health_status IN ('HEALTHY', 'DEGRADED', 'DISABLED')),
    last_synced_at timestamptz,
    allocation_count bigint NOT NULL DEFAULT 0,
    allocated_seconds bigint NOT NULL DEFAULT 0,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_admin (
    userid text PRIMARY KEY,
    created_by text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS app_admin_userid_lower_uidx
    ON app_admin(lower(userid));

CREATE TABLE IF NOT EXISTS reservation (
    id uuid PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    applicant_userid text NOT NULL,
    resource_id uuid NOT NULL REFERENCES meeting_resource(id),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    meetingid text UNIQUE,
    status text NOT NULL,
    settings_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    join_info_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error_code text,
    last_error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_at > start_at)
);

CREATE INDEX IF NOT EXISTS reservation_applicant_start_idx
    ON reservation(applicant_userid, start_at DESC);
CREATE INDEX IF NOT EXISTS reservation_status_idx
    ON reservation(status);

CREATE TABLE IF NOT EXISTS resource_calendar_slot (
    id uuid PRIMARY KEY,
    resource_id uuid NOT NULL REFERENCES meeting_resource(id),
    reservation_id uuid REFERENCES reservation(id),
    source_type text NOT NULL CHECK (source_type IN ('RESERVATION', 'EXTERNAL')),
    source_id text NOT NULL,
    busy_range tstzrange NOT NULL,
    status text NOT NULL CHECK (status IN ('HELD', 'ACTIVE', 'RELEASED')),
    hold_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (resource_id, source_type, source_id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'resource_calendar_slot_no_overlap'
    ) THEN
        ALTER TABLE resource_calendar_slot
            ADD CONSTRAINT resource_calendar_slot_no_overlap
            EXCLUDE USING gist (
                resource_id WITH =,
                busy_range WITH &&
            )
            WHERE (status IN ('HELD', 'ACTIVE'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS system_policy (
    id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    buffer_minutes integer NOT NULL DEFAULT 10,
    min_lead_minutes integer NOT NULL DEFAULT 15,
    max_duration_minutes integer NOT NULL DEFAULT 480,
    max_advance_days integer NOT NULL DEFAULT 90,
    max_pending_per_user integer NOT NULL DEFAULT 10,
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO system_policy (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS operation_log (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL,
    actor_userid text NOT NULL,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id text,
    result text NOT NULL,
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS operation_log_created_idx
    ON operation_log(created_at DESC);
