# X Terminal

**A Bloomberg-style LiveOps dashboard for X powered by Grok**

<p align="center">
  <img src="frontend/static/x-logo.svg" width="60" alt="X Logo">
  &nbsp;&nbsp;×&nbsp;&nbsp;
  <img src="frontend/static/grok.svg" width="60" alt="Grok Logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Grok-4.1-purple?logo=x&logoColor=white" alt="Grok">
  <img src="https://img.shields.io/badge/Built%20in-24%20hours-orange" alt="Built in 24 hours">
</p>

---

## 💡 The Problem

X is a **firehose**. Following topics like `$TSLA` or `"AI news"` means drowning in noise with no structure, no trends, no signal.

## ✅ The Solution

X Terminal treats posts like **market ticks** and aggregates them into **time bars**:

| Raw X Feed | X Terminal |
|------------|------------|
| Endless scroll of posts | Structured time bars (15s → 1h) |
| No summary | AI-powered summaries per bar |
| No sentiment | Sentiment scoring (0.0 → 1.0) |
| Can't compare timeframes | Switch resolutions instantly |
| Spam mixed with signal | Spam-aware analysis |



---

## 🎯 Key Innovations

| Innovation | Description |
|------------|-------------|
| **Tick → Bar Model** | First to apply market data patterns to social media monitoring |
| **Multi-Resolution** | Switch 15s ↔ 1h views instantly — same data, different zoom |
| **Spam-Aware AI** | Grok ignores pump-and-dump, bots, and scams in analysis |
| **Hybrid Architecture** | Pre-computed bars + on-demand fallback = always fast (<50ms) |
| **Sentiment as Float** | Precise 0.0–1.0 scoring, not vague "positive/negative" |

---

## ✨ Features

- **Topic Watching** — Track any topic via X search query (e.g., `$TSLA`, `"LA earthquake"`)
- **Multi-Resolution Bars** — Switch between 15s, 30s, 1m, 5m, 15m, 30m, 1h views instantly
- **AI Summaries** — Grok-powered summaries for each bar (what happened?)
- **Topic Digests** — One-shot analysis across multiple bars (what's the trend?)
- **Real-time Monitoring** — Live metrics, rate limits, and activity feed
- **Spam Filtering** — Summaries ignore scams, bots, and pump-and-dump noise
- **Terminal Aesthetic** — Dark theme with Bloomberg/terminal vibes

---

## 🏗️ Architecture

```
┌─────────────────┐     HTTP/JSON     ┌─────────────────────────────────────────┐
│                 │◄────────────────► │  Python FastAPI Backend                 │
│  Svelte         │                   │                                         │
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
│                 │                   │  │ (Polling)     │  │ (Summarization)│  │
│                 │                   │  └────────┬──────┘  └─────┬──────────┘  │
│                 │                   │           │               │             │
│                 │                   └───────────┼───────────────┼─────────────┘
│                 │                               │               │
│                 │                   ┌───────────▼───┐       ┌───▼──────────┐
│                 │                   │ X API         │       │ xAI Grok API │
│                 │                   └───────────────┘       └──────────────┘
└─────────────────┘
```

### Low-Latency Design

| Component | Role | Latency |
|-----------|------|---------|
| **TickStore** | Raw X posts in memory |
| **BarScheduler** | Background bar generation + Grok |
| **BarStore** | Pre-computed bars cache |
| **On-Demand Fallback** | Generate from ticks if not cached |

Result: **Dashboards are always instant**, AI summaries populate asynchronously.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- X API Bearer Token ([console.x.com](https://console.x.com))
- xAI API Key ([x.ai](https://x.ai))

### Backend

```bash
cd backend
./setup.sh                    # Create venv + install deps
cp .env.example .env          # Add your API keys
AUTO_POLL=true ./run.sh       # Start with auto-polling
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## 🔌 API Reference

### Topics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/topics` | Create a topic |
| `GET` | `/api/v1/topics` | List all topics |
| `GET` | `/api/v1/topics/{id}` | Get topic details |
| `DELETE` | `/api/v1/topics/{id}` | Remove topic |
| `POST` | `/api/v1/topics/{id}/pause` | Pause polling |
| `POST` | `/api/v1/topics/{id}/resume` | Resume polling |

### Bars & Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/topics/{id}/bars` | Get bar timeline ⚡ |
| `GET` | `/api/v1/topics/{id}/bars/latest` | Get latest bar |
| `POST` | `/api/v1/topics/{id}/backfill` | Generate historical bars + summaries |
| `POST` | `/api/v1/topics/{id}/digest` | Generate AI digest across bars |
| `POST` | `/api/v1/topics/{id}/poll` | Manual poll trigger |

### Monitoring 📊

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/monitor/dashboard` | Full dashboard data |
| `GET` | `/api/v1/monitor/health` | System health & components |
| `GET` | `/api/v1/monitor/rate-limits` | API rate limit status |
| `GET` | `/api/v1/monitor/activity` | Real-time event feed |
| `GET` | `/api/v1/monitor/metrics` | Performance metrics |

---

## 📊 Data Models

### Bar (Core Unit)

```json
{
  "topic": "$TSLA",
  "resolution": "1m",
  "start": "2024-01-15T12:00:00Z",
  "end": "2024-01-15T12:01:00Z",
  "post_count": 42,
  "total_likes": 5000,
  "total_retweets": 1200,
  "summary": "Tesla stock rallied on delivery numbers...",
  "sentiment": 0.78,
  "key_themes": ["Deliveries", "Stock price", "Q4 outlook"],
  "highlight_posts": ["1234567890", "1234567891"]
}
```

### Digest (Multi-Bar Summary)

```json
{
  "topic": "$TSLA",
  "time_range": "Last 1 hour",
  "overall_summary": "Tesla dominated discussion with delivery beat...",
  "key_developments": ["Q4 deliveries exceeded expectations", "Stock up 5%"],
  "sentiment_trend": "improving",
  "notable_voices": ["@elonmusk", "@teslarati"]
}
```

---

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `X_BEARER_TOKEN` | X API Bearer Token | Required |
| `XAI_API_KEY` | xAI Grok API Key | Required |
| `GROK_MODEL_FAST` | Fast model for bar summaries | `grok-4-1-fast` |
| `GROK_MODEL_REASONING` | Reasoning model for digests | `grok-4-1-fast-reasoning` |
| `AUTO_POLL` | Enable background polling | `false` |
| `POLL_INTERVAL` | Polling interval (seconds) | `15` |

### Resolutions

| Resolution | Use Case |
|------------|----------|
| `15s` | Live demo / real-time monitoring |
| `1m` | Active topic tracking |
| `5m` | Standard monitoring |
| `1h` | Daily summaries |

---

## 🧪 Testing

```bash
cd backend
./test.sh  # Runs pytest with all tests
```

---

## 📁 Project Structure

```
x-terminal/
├── backend/
│   ├── adapter/
│   │   ├── x/              # X API integration
│   │   ├── grok/           # Grok AI integration
│   │   └── rate_limiter.py # Shared rate limiting
│   ├── aggregator/         # TickStore, BarGenerator, BarStore
│   ├── core/               # TopicManager, TickPoller, BarScheduler
│   ├── api/                # FastAPI routes
│   ├── monitoring/         # Metrics & observability
│   └── main.py
├── frontend/               # Svelte dashboard
└── context.md              # Project specification
```

---

Built with ❤️ for the xAI Hackathon
