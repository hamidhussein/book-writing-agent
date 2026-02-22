export type RunMode = "toc" | "refine_toc" | "chapter" | "export";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface OutlineChapter {
  number: number;
  title: string;
  bullet_points: string[];
}

export interface BookProject {
  id: string;
  title: string;
  genre: string;
  target_audience: string;
  language: string;
  tone: string;
  target_word_count: number;
  status: string;
  outline_json: {
    synopsis?: string;
    chapters?: OutlineChapter[];
  };
  metadata_json: Record<string, unknown>;
}

export interface Chapter {
  id: string;
  project: string;
  number: number;
  title: string;
  content: string;
  summary: string;
  status: string;
}

export interface AgentRun {
  id: string;
  trace_id: string;
  project: string;
  mode: RunMode;
  status: RunStatus;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown>;
  timings_json: Record<string, unknown>;
  error_message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
