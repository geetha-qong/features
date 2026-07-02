import "@testing-library/jest-dom";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// React Testing Library unmounts the rendered tree after each test
// to keep DOM state isolated and prevent leaks between specs.
afterEach(() => {
  cleanup();
});
