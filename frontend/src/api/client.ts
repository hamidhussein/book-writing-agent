import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8010/api";
const API_TOKEN = (import.meta.env.VITE_API_TOKEN || "").trim();

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 90_000
});

api.interceptors.request.use((config) => {
  if (API_TOKEN) {
    config.headers = config.headers || {};
    if (!("Authorization" in config.headers)) {
      (config.headers as Record<string, string>).Authorization = `Token ${API_TOKEN}`;
    }
  }
  return config;
});

export type HttpError = {
  message: string;
  response?: {
    status: number;
    data: unknown;
  };
};
