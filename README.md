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
- **Time Bars** — Posts aggregated into 5m, 10m, or hourly windows with metrics
- **AI Summaries** — Grok-powered summaries for each bar (what happened?)
- **Topic Digests** — One-shot analysis across multiple bars (what's the trend?)
- **Terminal Aesthetic** — Dark theme with Bloomberg/terminal vibes

## 🏗️ Architecture

```
┌─────────────────┐     HTTP/JSON     ┌─────────────────────────────────┐
│                 │◄────────────────► │  Python FastAPI Backend         │
│  Next.js/Svelte │                   │                                 │
│  Frontend       │                   │  ┌─────────┐  ┌─────────────┐  │
│                 │                   │  │ X       │  │ Grok        │  │
└─────────────────┘                   │  │ Adapter │  │ Adapter     │  │
                                      │  └────┬────┘  └──────┬──────┘  │
                                      │       │              │         │
                                      │  ┌────▼──────────────▼─────┐  │
                                      │  │   BarAggregator         │  │
                                      │  │   TopicManager          │  │
                                      │  │   DigestService         │  │
                                      │  └─────────────────────────┘  │
                                      └─────────────────────────────────┘
                                                    │
                                      ┌─────────────┴─────────────┐
                                      ▼                           ▼
                               X API (Twitter)              xAI Grok API
```

## 📁 Project Structure

```
x-terminal/
├── backend/                 # Python FastAPI backend
│   ├── adapter/
│   │   ├── x/              # X (Twitter) API adapter
│   │   ├── grok/           # Grok AI adapter
│   │   ├── models.py       # Shared Pydantic models (Tick)
│   │   └── rate_limiter.py # Shared rate limiting
│   ├── aggregator/         # BarAggregator, DigestService
│   ├── core/               # TopicManager, TickPoller
│   ├── api/                # FastAPI routes
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
- X API Bearer Token ([developer.x.com](https://developer.x.com))
- xAI API Key ([x.ai](https://x.ai))

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
#   X_BEARER_TOKEN=your_x_bearer_token
#   XAI_API_KEY=your_xai_api_key

# Run the server
uvicorn main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/topics` | List all topics |
| `POST` | `/api/v1/topics` | Create a topic |
| `GET` | `/api/v1/topics/{id}` | Get topic details |
| `DELETE` | `/api/v1/topics/{id}` | Remove topic |
| `POST` | `/api/v1/topics/{id}/pause` | Pause polling |
| `POST` | `/api/v1/topics/{id}/resume` | Resume polling |
| `GET` | `/api/v1/topics/{id}/bars` | Get bar timeline |
| `GET` | `/api/v1/topics/{id}/bars/latest` | Get latest bar |
| `POST` | `/api/v1/topics/{id}/poll` | Manual poll trigger |
| `POST` | `/api/v1/topics/{id}/digest` | Generate AI digest |

### Example: Create and Monitor a Topic

```bash
# 1. Create a topic
curl -X POST http://localhost:8000/api/v1/topics \
  -H "Content-Type: application/json" \
  -d '{
    "label": "$TSLA",
    "query": "$TSLA OR Tesla stock",
    "resolution": "5m"
  }'

# 2. Poll for data
curl -X POST http://localhost:8000/api/v1/topics/tsla/poll

# 3. Get bars
curl "http://localhost:8000/api/v1/topics/tsla/bars?limit=50"

# 4. Generate digest
curl -X POST "http://localhost:8000/api/v1/topics/tsla/digest?lookback_bars=12"
```

## 🧪 Testing

```bash
cd backend
source venv/bin/activate

# Run all tests
pytest -v

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
| `POLL_INTERVAL` | Polling interval (seconds) | `300` |
| `PORT` | Server port | `8000` |

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
  "resolution": "5m",
  "start": "2024-01-15T12:00:00Z",
  "end": "2024-01-15T12:05:00Z",
  "post_count": 42,
  "total_likes": 5000,
  "summary": "Tesla stock discussed amid...",
  "sentiment": "positive",
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

