import { ApiError } from "@/api/client";

/** The single mapping from backend error codes to user-facing copy. */
const COPY: Record<string, string> = {
  NETWORK: "Can't reach RoleReady right now. Check your connection and try again.",
  TIMEOUT: "This is taking longer than expected. Your input is saved — try again in a moment.",
  UNAUTHENTICATED: "Your session has ended. Please log in again.",
  RATE_LIMITED: "Too many attempts. Please wait a moment and try again.",
  AI_UNAVAILABLE: "AI features are paused right now. Scoring of objective questions, plans and practice still work.",
  AI_QUOTA_EXCEEDED: "You've reached the AI usage limit for now. Non-AI features keep working.",
  AI_TIMEOUT: "The AI service took too long. Your input is saved — try again.",
  AI_PROVIDER_ERROR: "The AI service returned an error. Your input is saved — try again.",
  AI_INVALID_OUTPUT: "The AI service didn't return a usable answer. Your input is saved — try again.",
  INTERNAL_ERROR: "Something went wrong on our side. Please try again.",
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message || COPY[err.code] || "Something went wrong.";
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

export function friendlyCode(err: unknown): string | undefined {
  return err instanceof ApiError ? err.code : undefined;
}
