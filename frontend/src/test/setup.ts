import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrolling; the app shell scrolls to top on navigation.
window.scrollTo = (() => {}) as typeof window.scrollTo;
