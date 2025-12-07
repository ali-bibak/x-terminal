# X Terminal Backend

Python FastAPI backend for the X Terminal LiveOps dashboard, providing tick → bar → digest functionality for X topics.

## Features

- **GrokAdapter**: Structured API client for xAI's Grok with fallback implementations
- **XAdapter**: X API client for fetching posts as ticks
- **RateLimiter**: Flexible rate limiting supporting multiple APIs and strategies
- **Bar Summaries**: Fast, structured summaries of time-windowed post activity
- **Topic Digests**: Careful analysis over multiple bars with trends and recommendations
- **Shared Rate Limiting**: Common rate limiter across X and Grok APIs
- **Error Handling**: Comprehensive error handling and logging
- **Testing**: Unit tests with pytest

## Setup

1. **Clone and navigate to backend directory**
   ```bash
   cd backend
   ```

2. **Run setup script**
   ```bash
   ./setup.sh
   ```
   This creates a virtual environment and installs dependencies.

3. **Activate virtual environment**
   ```bash
   source venv/bin/activate
   ```

4. **Configure environment variables** (optional)
   Create a `.env` file:
   ```bash
   # Grok API (xAI)
   XAI_API_KEY=your_grok_api_key_here
   GROK_MODEL_FAST=grok-4-1-fast
   GROK_MODEL_REASONING=grok-4-1-fast-reasoning

   # X API - App-only authentication
   X_BEARER_TOKEN=your_x_bearer_token_here
   # Or user authentication:
   X_API_KEY=your_x_api_key
   X_API_SECRET=your_x_api_secret
   ```

## Usage

### CLI Testing

Test the adapters interactively:

**GrokAdapter:**
```bash
python -m adapter.grok.cli
```

Available commands:
- `intel` - Summarize a user handle
- `watch` - Generate monitor insight for a topic
- `factcheck` - Fact-check a URL + text
- `digest` - Build digest from highlights
- `barsum` - Summarize a bar of posts (X Terminal)
- `topicdig` - Create topic digest from bars (X Terminal)

**XAdapter:**
```bash
python -m adapter.x.cli
```

Available commands:
- `search` - Search recent posts by query
- `userposts` - Get posts from specific user

### Running Tests

```bash
./test.sh
# or
python -m pytest
```

### API Endpoints (Planned)

The backend will expose these FastAPI endpoints:

- `GET /api/v1/topics` - List watched topics
- `POST /api/v1/topics` - Start watching a topic
- `DELETE /api/v1/topics/{topicId}` - Stop watching a topic
- `GET /api/v1/topics/{topicId}/bars` - Get bar timeline
- `POST /api/v1/topics/{topicId}/digest` - Generate topic digest

## Architecture

### Core Components

- **GrokAdapter**: Main interface to Grok API with structured responses
- **XAdapter**: X API client for fetching posts as ticks
- **RateLimiter**: Flexible rate limiting with multiple strategies and categories
- **BarSummary**: Pydantic model for time-window summaries
- **TopicDigest**: Pydantic model for multi-bar analysis
- **Tick**: Pydantic model for individual posts from X

### Key Design Decisions

1. **Structured Responses**: All API calls return Pydantic models for type safety
2. **Fallback Implementations**: Deterministic fallbacks when API unavailable
3. **Rate Limiting**: Shared limiter prevents overwhelming the API
4. **Model Routing**: Fast model for summaries, careful model for digests
5. **Error Resilience**: Graceful degradation with comprehensive logging

### Data Flow

```
X Posts → Ticks → BarAggregator → Bars + Summaries → Digest
```

## Development

### Adding New Features

1. Define Pydantic models in `adapter/grok/__init__.py`
2. Add methods to `GrokAdapter` class
3. Implement fallback methods for offline testing
4. Add unit tests in `tests/`
5. Update CLI in `cli.py`

### Dependencies

- `fastapi>=0.100.0` - Web framework
- `pydantic>=2.5.3` - Data validation
- `xai-sdk==1.5.0` - Grok API client
- `requests` - HTTP client for X API
- `python-dotenv` - Environment management
- `pytest` - Testing framework
- `structlog` - Structured logging

## Testing Strategy

- **Unit Tests**: Core adapter functionality
- **Integration Tests**: API endpoint behavior
- **Fallback Tests**: Offline functionality
- **Rate Limiting Tests**: API throttling behavior

Run with verbose output:
```bash
python -m pytest -v
```

## Deployment

The backend is designed for simple deployment:

1. Container-ready with `requirements.txt`
2. Environment-based configuration
3. Health check endpoints
4. Graceful degradation without API access
