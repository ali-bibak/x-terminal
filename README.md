# X Terminal

**A Bloomberg-style LiveOps dashboard for X (Twitter) powered by Grok**

<p align="center">
  <img src="frontend/static/x-logo.svg" width="60" alt="X Logo">
  &nbsp;&nbsp;+&nbsp;&nbsp;
  <img src="frontend/static/grok.svg" width="60" alt="Grok Logo">
</p>

X Terminal aggregates X posts into time-based "bars" (like market data) and uses Grok AI to generate summaries and digests. Instead of drowning in a firehose of posts, get structured insights about what's happening with topics you care about.

## ✨ Features

- **Topic Watching** — Track any topic via X search query (e.g., `$TSLA`, `"AI news"`)
- **Multi-Resolution Bars** — Switch between 15s, 30s, 1m, 5m, 15m, 30m, 1h views instantly
- **AI Summaries** — Grok-powered summaries for each bar (what happened?)
- **Topic Digests** — One-shot analysis across multiple bars (what's the trend?)
- **Real-time Monitoring** — Live metrics, rate limits, and activity feed
- **Terminal Aesthetic** — Dark theme with Bloomberg/terminal vibes

## 🏗️ Architecture

```
┌─────────────────┐     HTTP/JSON     ┌─────────────────────────────────────────┐
│                 │◄────────────────► │  Python FastAPI Backend                 │
│  Next.js/Svelte │                   │                                         │
│  Frontend       │                   │  ┌───────────────────────────────────┐  │
│                 │                   │  │   Core / Aggregation Layer        │  │
│                 │                   │  ├───────────────────────────────────┤  │
│                 │                   │  │  TopicManager   DigestService     │  │
│                 │                   │  │  TickStore      BarStore          │  │
│                 │                   │  │  BarGenerator   BarScheduler      │  │
│                 │                   │  └────────┬───────────────┬──────────┘  │
│                 │                   │           │               │             │
│                 │                   │  ┌────────▼──────┐  ┌─────▼──────────┐  │
│                 │                   │  │ X Adapter     │  │ Grok Adapter   │  │
│                 │                   │  │ (Polling/Rate)│  │ (Prompt Eng.)  │  │
│                 │                   │  └────────┬──────┘  └─────┬──────────┘  │
│                 │                   │           │               │             │
│                 │                   └───────────┼───────────────┼─────────────┘
│                 │                               │               │
│                 │                   ┌───────────▼───┐       ┌───▼──────────┐
│                 │                   │ X API         │       │ xAI Grok API │
│                 │                   └───────────────┘       └──────────────┘
└─────────────────┘
```

### Low-Latency Architecture

X Terminal uses a hybrid approach for speed and quality:

1. **TickStore** — Stores raw X posts (ticks) in memory
2. **BarScheduler** — Periodically generates bars + Grok summaries in background
3. **BarStore** — Caches pre-computed bars for instant GET access (~10ms)
4. **On-Demand Fallback** — If bars aren't cached, generates them instantly from ticks (without summaries) to ensure responsiveness

This enables:
- ⚡ **Instant dashboards** (always fast)
- 🤖 **AI Summaries** (populated asynchronously)
- 🔄 **Automatic backfilling** of historical data

## 📁 Project Structure

```
x-terminal/
├── backend/                 # Python FastAPI backend
│   ├── adapter/
│   │   ├── x/              # X (Twitter) API adapter
│   │   ├── grok/           # Grok AI adapter
│   │   ├── models.py       # Shared Pydantic models (Tick)
│   │   └── rate_limiter.py # Shared rate limiting
│   ├── aggregator/         # TickStore, BarGenerator, BarStore
│   ├── core/               # TopicManager, TickPoller, BarScheduler
│   ├── api/                # FastAPI routes
│   ├── monitoring/         # 📊 Metrics, health, activity feed
│   ├── database/           # SQLite persistence
│   ├── main.py             # App entry point
│   └── tests/              # pytest tests
├── frontend/               # Svelte frontend
│   └── src/
└── context.md              # Project specification
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- X API Bearer Token ([console.x.com](https://console.x.com))
- xAI API Key ([x.ai](https://x.ai))

### Backend Setup

```bash
cd backend

# Create virtual environment (using setup script)
./setup.sh
# Or manually:
# python -m venv venv
# source venv/bin/activate
# pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
#   X_BEARER_TOKEN=your_x_bearer_token
#   XAI_API_KEY=your_xai_api_key

# Run the server
./run.sh
# Or: AUTO_POLL=true ./run.sh (to start polling immediately)
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## 🔌 API Endpoints

### Topics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/topics` | List all topics |
| `POST` | `/api/v1/topics` | Create a topic |
| `GET` | `/api/v1/topics/{id}` | Get topic details |
| `DELETE` | `/api/v1/topics/{id}` | Remove topic |
| `POST` | `/api/v1/topics/{id}/pause` | Pause polling |
| `POST` | `/api/v1/topics/{id}/resume` | Resume polling |
| `PATCH` | `/api/v1/topics/{id}/resolution` | Change resolution |
| `GET` | `/api/v1/topics/{id}/bars` | Get bar timeline (fast) |
| `GET` | `/api/v1/topics/{id}/bars/latest` | Get latest bar |
| `POST` | `/api/v1/topics/{id}/poll` | Manual poll trigger |
| `POST` | `/api/v1/topics/{id}/backfill` | Generate historical bars + summaries |
| `POST` | `/api/v1/topics/{id}/digest` | Generate AI digest |

### Monitoring 📊

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/monitor/dashboard` | Full dashboard data |
| `GET` | `/api/v1/monitor/health` | System health & components |
| `GET` | `/api/v1/monitor/metrics` | Performance metrics |
| `GET` | `/api/v1/monitor/rate-limits` | API rate limit status |
| `GET` | `/api/v1/monitor/activity` | Real-time event feed |
| `GET` | `/api/v1/monitor/topics` | Detailed topic stats |
| `GET` | `/api/v1/monitor/live-stats` | Lightweight live stats |

### Example: Create and Monitor a Topic

```bash
# 1. Create a topic
curl -X POST http://localhost:8000/api/v1/topics \
  -H "Content-Type: application/json" \
  -d '{
    "label": "$TSLA",
    "query": "$TSLA OR Tesla stock",
    "resolution": "1m"
  }'

# 2. Poll for data (or use AUTO_POLL=true)
curl -X POST http://localhost:8000/api/v1/topics/tsla/poll

# 3. Get bars (instant response)
curl "http://localhost:8000/api/v1/topics/tsla/bars?resolution=15s&limit=50"

# 4. Backfill historical summaries
curl -X POST "http://localhost:8000/api/v1/topics/tsla/backfill" \
  -H "Content-Type: application/json" \
  -d '{"resolution": "1m", "count": 5}'

# 5. Generate digest
curl -X POST "http://localhost:8000/api/v1/topics/tsla/digest?lookback_bars=12"
```

## 📊 Monitoring Dashboard

The monitoring endpoints provide high-ROI observability:

### Rate Limits (`/monitor/rate-limits`)
```json
{
  "categories": {
    "x_search": {
      "limit": 300,
      "remaining": 245,
      "usage_percent": "18.3%",
      "status": "ok",
      "emoji": "🟢"
    },
    "grok_fast": {
      "limit": 60,
      "remaining": 12,
      "usage_percent": "80.0%",
      "status": "warning",
      "emoji": "🟡"
    }
  }
}
```

### System Health (`/monitor/health`)
```json
{
  "status": "healthy",
  "components": {
    "x_adapter": {"status": "healthy"},
    "grok_adapter": {"status": "healthy"},
    "poller": {"status": "healthy", "details": {"interval": 15}},
    "bar_scheduler": {"status": "healthy"}
  }
}
```

## 🧪 Testing

```bash
cd backend
source venv/bin/activate

# Run all tests
./test.sh
# Or: pytest -v --disable-warnings

# Run specific test file
pytest tests/test_aggregator.py -v

# Run with coverage
pytest --cov=. --cov-report=html
```

## 🛠️ CLI Tools

### X Adapter CLI
```bash
cd backend
python -m adapter.x.cli

# Commands:
#   search <query> [minutes] [max_results]  - Search posts
#   bar <query> <minutes_ago> <window_min>  - Fetch bar window
#   ratelimit                               - Check rate limit status
```

### Grok Adapter CLI
```bash
cd backend
python -m adapter.grok.cli

# Commands:
#   barsum   - Generate bar summary
#   topicdig - Create topic digest
#   intel    - Summarize a user
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `X_BEARER_TOKEN` | X API Bearer Token | Required |
| `XAI_API_KEY` | xAI Grok API Key | Required |
| `GROK_MODEL_FAST` | Fast model for summaries | `grok-4-1-fast` |
| `GROK_MODEL_REASONING` | Reasoning model for digests | `grok-4-1-fast-reasoning` |
| `AUTO_POLL` | Enable background polling | `false` |
| `POLL_INTERVAL` | Polling interval (seconds) | `15` |
| `PORT` | Server port | `8000` |

### Resolution Options

| Resolution | Description |
|------------|-------------|
| `15s` | Minimum - for hackathon demos |
| `30s` | Half-minute granularity |
| `1m` | Default - per minute |
| `5m` | 5-minute windows |
| `15m` | Quarter-hour |
| `30m` | Half-hour |
| `1h` | Hourly aggregation |

## 📊 Data Models

### Tick
Individual X post with metrics:
```python
{
  "id": "1234567890",
  "author": "elonmusk",
  "text": "Tesla is the future...",
  "timestamp": "2024-01-15T12:00:00Z",
  "metrics": {"like_count": 1000, "retweet_count": 200},
  "topic": "$TSLA"
}
```

### Bar
Time-windowed aggregate:
```python
{
  "topic": "$TSLA",
  "resolution": "1m",
  "start": "2024-01-15T12:00:00Z",
  "end": "2024-01-15T12:01:00Z",
  "post_count": 42,
  "total_likes": 5000,
  "summary": "Tesla stock discussed amid...",
  "sentiment": 0.85,
  "highlight_posts": ["1234567890", "1234567891"]
}
```

### Digest
AI-generated summary across bars:
```python
{
  "topic": "$TSLA",
  "time_range": "Last 1 hour",
  "overall_summary": "Tesla dominated discussion...",
  "key_developments": ["Q4 earnings beat", "New factory announced"],
  "sentiment_trend": "improving",
  "recommendations": ["Monitor earnings call reactions"]
}
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with ❤️ for the xAI Hackathon
