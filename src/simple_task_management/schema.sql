-- Schema version 1. Applied once to an empty database; later changes go in db.MIGRATIONS.

CREATE TABLE users (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT    NOT NULL,
    username             TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash        TEXT    NOT NULL,
    is_admin             INTEGER NOT NULL DEFAULT 0,
    is_active            INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    theme                TEXT    NOT NULL DEFAULT 'system'
                                 CHECK (theme IN ('system', 'light', 'dark')),
    created_at           TEXT    NOT NULL
);

CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY,
    title        TEXT    NOT NULL,
    notes        TEXT    NOT NULL DEFAULT '',
    due_date     TEXT    NOT NULL,              -- YYYY-MM-DD
    status       TEXT    NOT NULL DEFAULT 'todo'
                         CHECK (status IN ('todo', 'doing', 'done')),
    repeat       TEXT    NOT NULL DEFAULT 'none'
                         CHECK (repeat IN ('none', 'weekly', 'monthly', 'quarterly', 'yearly')),
    repeat_day   INTEGER,                       -- anchor day of month for monthly+ repeats
    series_id    INTEGER,                       -- id of the first task in a recurring chain
    prev_task_id INTEGER REFERENCES tasks (id) ON DELETE SET NULL,
    created_by   INTEGER REFERENCES users (id),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    done_at      TEXT
);

-- One task can only ever have one next occurrence.
CREATE UNIQUE INDEX tasks_prev_task ON tasks (prev_task_id);
CREATE INDEX tasks_status_due ON tasks (status, due_date);

CREATE TABLE task_assignees (
    task_id  INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users (id),
    added_at TEXT    NOT NULL,
    PRIMARY KEY (task_id, user_id)
) WITHOUT ROWID;

CREATE INDEX task_assignees_user ON task_assignees (user_id);

CREATE TABLE updates (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    author_id  INTEGER REFERENCES users (id),   -- NULL for system entries
    kind       TEXT    NOT NULL CHECK (kind IN ('comment', 'event')),
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE INDEX updates_task ON updates (task_id, created_at);

CREATE TABLE sessions (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    csrf_token TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);
