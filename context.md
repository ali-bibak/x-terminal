# X Terminal – LiveOps Dashboard for X + Grok

# X Terminal – Tick → Bar LiveOps Dashboard for X + Grok

## High-Level Vision

This repo implements **X Terminal**, a **terminal-style LiveOps console** for X powered by **Grok**.

Instead of showing a raw firehose of posts, X Terminal:

- Lets a user **pick topics to watch** (e.g. `$TSLA`, “LA earthquake”).
- Treats individual X posts as **ticks**.
- Aggregates ticks into **time bars** (e.g. 5m, 10m windows).
- Shows, for each topic:
  - A **timeline of bars** (what happened, step by step),
  - A **one-shot digest** capturing “what’s going on with this topic lately?”.

The goal is to give a **Bloomberg-ish terminal vibe** for topics on X, but scoped to a **24-hour hackathon**: prioritize *clarity, reliability, and demoability* over completeness or generality.

---

## Tech & Project Defaults

When generating or editing code, follow these defaults:

- **Frontend**: Next.js (App Router), React, **TypeScript**, Tailwind CSS.
- **Backend**: Separate **Python FastAPI** service.
- **Communication**: Frontend calls Python backend via HTTP (JSON).
- **Styling**:
  - Dark theme, **terminal / Bloomberg / X** vibe.
- **State management**:
  - React hooks + local component state.
  - Simple `useState/useEffect` and lightweight context where needed.
- **Data storage**:
  - For the hackathon MVP, use **in-memory** state on the server for:
    - topics,
    - ticks (short-lived),
    - bars,
    - cached digests (if any).
  - No DB for now.
- **APIs**:
  - Integrate with **Grok** (xAI) and **X APIs** where possible.
  - Build importable adapter modules (e.g. `adapter/x/`, `adapter/grok`) using Pydantic models and `xai-sdk` where appropriate.

- **Next.js frontend**:
  - Renders the terminal-style dashboard:
    - Sidebar: topics list + “add topic” form.
    - Main pane: timeline of bars for the selected topic, plus a digest panel.
  - Calls the Python backend for all topic, bar, and digest data.

- **Python FastAPI backend**:
  - Exposes endpoints like:
    - `GET  /api/topics` – list watched topics
    - `POST /api/topics` – start watching a topic
    - `DELETE /api/topics/{topicId}` – stop watching a topic
    - `GET  /api/topics/{topicId}/bars` – per-topic bar timeline
    - `POST /api/topics/{topicId}/digest` – one-shot digest over recent bars
    - `GET  /api/health` – simple health check
  - Implements:
    - Adapters for **X** and **Grok**.
    - a simple feed for fetching posts related to a topic as ticks,
    - a **BarAggregator** that rolls ticks into time bars,
    - a **Digest** that calls Grok over recent bars,
    - a shared **rate limiter** for X and Grok,
    - in-memory registries for topics, ticks, and bars.

**Very important:**  
We optimize for a **smooth demo** and a **coherent UX**, not for large-scale production. Keep the architecture simple and direct.

---

## Core Product Concept

### Topics, Ticks, Bars, and Digests

The core mental model is borrowed from markets:

- **Topic** — what the user cares about:
  - Examples: `$TSLA`, `"Starship"`, `"LA earthquake"`.
  - Backed by an X search query or filtered stream; the user sees it by friendly label.

- **Tick** — an individual X post:
  - A post matching the topic’s query.
  - Minimal fields: `id`, `author`, `text`, `timestamp`, `permalink`, simple metrics.

- **Bar** — a time-bucketed aggregate for a single topic:
  - Example: a 5-minute window.
  - Contains:
    - `start`, `end`,
    - `post_count`,
    - aggregated metrics,
    - a few `sample_posts`,
    - a short LLM **bar summary** (optional but nice).

- **Timeline (per topic)** — the ordered sequence of bars:
  - This is the main view for a selected topic.
  - Shows how the conversation evolves bar by bar.

- **Digest (per topic)** — a one-shot summary over recent bars:
  - Example: “What’s been happening with `$TSLA` over the last hour (last 12×5m bars)?”
  - Computed by Grok using the bar data as input.

Stretch ideas (if time allows):

- Highlight **key accounts** that dominate bars.
- Apply hardcoded **tags** (e.g. `ragebait`, `wholesome`, `finance`, `tech`) at the bar or digest level.
- A **global timeline** that merges “important” bars across all watched topics.

---

## MVP UX

Target: a simple dashboard where a user can add a topic, see bars, and get a digest.

Suggested layout:

- **Left: Topics Pane**
  - List of watched topics.
  - “Add topic” form: label + X query + resolution (e.g. `5m`).
  - Basic state: active vs stopped.

- **Right: Main Topic View**
  - **Timeline of Bars** (for selected topic):
    - Vertical list (or compact chart) of bars with:
      - time window (e.g. `05:00–05:05`),
      - `post_count` + mini metrics,
      - bar summary,
      - optional sample posts.
  - **Digest Panel**:
    - Button: “Generate digest”.
    - Shows last generated digest for that topic (built from recent bars).

Optional:

- A minimal **“Global” tab** where you show notable bars across topics sorted by time.

We do **not** need a general-purpose terminal command language or multiple page layouts anymore. One clean dashboard with topics + bar timelines + digests is enough.

---

## Backend Behaviour (MVP)

### Topics

- `POST /api/v1/topics`
  - Register a topic with:
    - `label` (e.g. `$TSLA`),
    - `query` (X search string),
    - `resolutions` (e.g. `["5m"]`).
  - Start background tick fetching and bar aggregation for that topic.

- `GET /api/v1/topics`
  - Return list of current topics and basic metadata.

- `DELETE /api/v1/topics/{topicId}`
  - Stop watching a topic (keep bars in memory until restart).

### Bars & Timelines

- `GET /api/v1/topics/{topicId}/ticks`
  - Returns the posts belonging to a topic

- `GET /api/v1/topics/{topicId}/bars`
  - Returns the **bar timeline** for that topic.
  - Query params:
    - `resolution` (default `"5m"`),
    - `limit` (e.g. last 50 bars).

Backend details:

- **TickFetcher / XAdapter**:
  - Periodically polls X for each active topic.
  - Emits ticks into an in-memory `Ticks` and then through to `BarAggregator`.

- **BarAggregator**:
  - Maintains open bars per topic/resolution.
  - When a tick arrives:
    - Determine which time bucket it belongs to.
    - Update bar metrics and sample posts.
  - When a bar window closes:
    - Optionally trigger a bar-level Grok summary.
    - Store the closed bar in memory as part of the topic’s timeline.

### Digest

- `POST /api/topics/{topicId}/digest`
  - Fetch the last N bars (configurable via body: `lookback_bars`).
  - Call Grok with a prompt describing those bars.
  - Return a **digest** suitable for display.

Caching digests is optional; simplest is to compute on demand.

---

## Model Smart Routing (Simple Version)

We may have different Grok modes (FAST vs reasoning), but the routing can be simple and explicit:

- **Bar Summaries**:
  - Use a **fast mode** (cheaper, lower latency).
  - Short, structured summaries focused on what changed in this window.

- **Digests**:
  - Use a **more careful / reasoning mode** if available.
  - Higher-quality, more contextual summary over many bars.

Implementation sketch:

- A small function like:

  ```py
  def route_grok_request(kind: Literal["bar_summary", "digest"], payload: dict) -> GrokResponse:
      ...