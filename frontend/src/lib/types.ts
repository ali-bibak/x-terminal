export type FactCheckStatus = "NOT_CHECKED" | "CHECKED" | "FALSE";

// API Request/Response Types
// Generated from backend/api/__init__.py

export interface CreateTopicRequest {
  label: string;
  query: string;
  resolution?: string;
}

export interface TopicResponse {
  id: string;
  label: string;
  query: string;
  resolution: string;
  status: string;
  created_at: string;
  last_poll: string | null;
  last_error: string | null;
  poll_count: number;
  tick_count: number;
}

export interface BarResponse {
  topic: string;
  resolution: string;
  start: string;
  end: string;
  post_count: number;
  total_likes: number;
  total_retweets: number;
  total_replies: number;
  total_quotes: number;
  sample_post_ids: string[];
  summary: string | null;
  sentiment: string | null;
  key_themes: string[];
  highlight_posts: string[];
}

export interface DigestResponse {
  topic: string;
  generated_at: string;
  time_range: string;
  overall_summary: string;
  key_developments: string[];
  trending_elements: string[];
  sentiment_trend: string;
  recommendations: string[];
}

export interface HealthResponse {
  status: string;
  timestamp: string;
  topics_count: number;
  active_topics: number;
}

export interface PollResponse {
  success: boolean;
  message: string;
  bar?: BarResponse;
}

export const nullopt = Symbol("nullopt");

export type Optional<T> = T | typeof nullopt;
