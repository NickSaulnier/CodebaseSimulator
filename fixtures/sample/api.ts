import getUser, { formatResponse } from "./lib.js";

export function handleRequest(id: string): string {
  const u = getUser(id);
  return formatResponse(u);
}
