// Typed client over the generated OpenAPI schema (src/lib/api/schema.d.ts, `npm run gen:api`).
// Only this thin wrapper is hand-written; schema.d.ts is generated and must not be edited.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "", credentials: "include" });

export type Schemas = components["schemas"];
export type JobRow = Schemas["JobRow"];
export type JobDetail = Schemas["JobDetail"];
export type ApprovalOut = Schemas["ApprovalOut"];
export type ProposalCard = Schemas["ProposalCard"];
export type ThreadOut = Schemas["ThreadOut"];
export type RunOut = Schemas["RunOut"];
export type RunDetail = Schemas["RunDetail"];
export type Analytics = Schemas["Analytics"];
export type UserOut = Schemas["UserOut"];
export type HealthOut = Schemas["HealthOut"];
export type MemoryOut = Schemas["MemoryOut"];
export type EvidenceOut = Schemas["EvidenceOut"];
export type SavedSearchOut = Schemas["SavedSearchOut"];

/** Turns an openapi-fetch result into data or a thrown, human-readable error. */
export function unwrap<T>(r: { data?: T; error?: unknown; response: Response }): T {
  if (r.error !== undefined || !r.response.ok) {
    const e = r.error as { detail?: unknown } | undefined;
    const d = e?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).join("; ") : `HTTP ${r.response.status}`;
    throw Object.assign(new Error(msg), { status: r.response.status });
  }
  return r.data as T;
}
