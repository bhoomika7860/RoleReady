import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ApiError, setUnauthenticatedHandler } from "@/api/client";
import App from "@/App";
import { ToastProvider } from "@/components/ui";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => err instanceof ApiError && err.retryable && count < 2,
    },
  },
});

// Any 401 from a data request means the session ended: clear it so route guards redirect to /login.
setUnauthenticatedHandler(() => { queryClient.setQueryData<unknown>(["me"], null); });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ToastProvider>
            <App />
          </ToastProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
