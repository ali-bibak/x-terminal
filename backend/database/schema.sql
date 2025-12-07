-- Topics being watched
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    last_polled_at TIMESTAMP
);

-- Time-bucketed bars (aggregated data)
CREATE TABLE IF NOT EXISTS bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    post_count INTEGER DEFAULT 0,
    summary TEXT,
    sentiment_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
    UNIQUE(topic_id, start_time)
);

-- Individual ticks (posts from X)
CREATE TABLE IF NOT EXISTS ticks (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    bar_id INTEGER,
    author_id TEXT,
    author_username TEXT,
    text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    like_count INTEGER DEFAULT 0,
    retweet_count INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
    FOREIGN KEY (bar_id) REFERENCES bars(id) ON DELETE SET NULL
);

-- Topic digests (multi-bar analysis)
CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    summary TEXT NOT NULL,
    key_trends TEXT,
    recommendations TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_bars_topic_time ON bars(topic_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_ticks_topic_time ON ticks(topic_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_digests_topic_time ON digests(topic_id, created_at DESC);
