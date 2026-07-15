/**
 * Vitest setup — runs once per test file.
 *
 * Pulls in @testing-library/jest-dom so test files can use matchers
 * like `toBeInTheDocument()` and `toHaveTextContent()`. Auto-cleanup
 * unmounts any rendered React trees between tests so they don't leak.
 */

import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
