import type {
  BarResponse,
  CreateTopicRequest,
  DigestResponse,
  PollResponse,
  TopicResponse,
} from "./types";

const BASE_URL = "http://localhost:8000";

const api = {
  listTopics: async (): Promise<TopicResponse[]> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics`);
    return response.json();
  },
  createTopic: async (topic: CreateTopicRequest): Promise<TopicResponse> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(topic),
    });
    return response.json();
  },
  getTopic: async (id: string): Promise<TopicResponse> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}`);
    return response.json();
  },
  deleteTopic: async (id: string): Promise<void> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(`Failed to delete topic: ${response.statusText}`);
    }
  },
  pauseTopic: async (id: string): Promise<void> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}/pause`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(`Failed to pause topic: ${response.statusText}`);
    }
  },
  resumeTopic: async (id: string): Promise<void> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}/resume`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(`Failed to resume topic: ${response.statusText}`);
    }
  },
  getBars: async (id: string, resolution: string): Promise<BarResponse[]> => {
    const response = await fetch(
      `${BASE_URL}/api/v1/topics/${id}/bars?resolution=${resolution}`,
    );
    return response.json();
  },
  getLatestBar: async (id: string): Promise<BarResponse> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}/bars/latest`);
    return response.json();
  },
  pollTopic: async (id: string): Promise<PollResponse> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}/poll`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(`Failed to poll topic: ${response.statusText}`);
    }
    return response.json();
  },
  pollAllTopics: async (): Promise<void> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/poll`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(`Failed to poll all topics: ${response.statusText}`);
    }
    // Ignore response, will always be true
  },
  createDigest: async (id: string): Promise<DigestResponse> => {
    const response = await fetch(`${BASE_URL}/api/v1/topics/${id}/digest`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(`Failed to create digest: ${response.statusText}`);
    }
    return response.json();
  },
};

export default api;
