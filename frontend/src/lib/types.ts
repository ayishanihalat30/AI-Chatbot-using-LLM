export type Lang = "en" | "ml" | "hi" | "ta" | "kn" | "te" | "ar" | "fr";
export type Length = "short" | "medium" | "detailed";
export type Style = "balanced" | "friendly" | "professional" | "technical" | "simple";
export type Mode = "general" | "programming" | "career" | "education";

export interface Preferences {
  language: Lang;
  answer_length: Length;
  answer_style: Style;
  memory_enabled: boolean;
}
export interface User {
  id: string;
  email: string;
  preferences: Preferences;
}
export interface Citation {
  n: number;
  document_id: string;
  filename: string;
  page: number | null;
  snippet: string;
}
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[] | null;
  created_at?: string;
}
export interface Chat {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface ChatDetail extends Chat {
  messages: Message[];
}
export interface Doc {
  id: string;
  filename: string;
  mime: string;
  size: number;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  summary: string | null;
  chunk_count: number;
  created_at: string;
}
export interface Memory {
  id: string;
  content: string;
  created_at: string;
}
