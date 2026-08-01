// Explicit expect.extend/cleanup rather than relying on Vitest's `globals:
// true` (not enabled here - every test file imports expect/afterEach/etc.
// itself) or jest-dom's default side-effect import, both of which assume a
// jest-style global test API. Without the explicit cleanup() call, RTL
// doesn't know how to hook into Vitest's afterEach, so each test's rendered
// DOM piles up across tests in the same file instead of unmounting between
// them.
import { cleanup } from "@testing-library/react";
import * as matchers from "@testing-library/jest-dom/matchers";
import { afterEach, expect } from "vitest";

expect.extend(matchers);
afterEach(cleanup);
