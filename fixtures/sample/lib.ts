export function parseUser(raw: string): object {
  return JSON.parse(raw);
}

export function formatResponse(data: object): string {
  return JSON.stringify(data);
}

export default function getUser(id: string): object {
  const raw = fetchUser(id);
  return parseUser(raw);
}

function fetchUser(id: string): string {
  return `{"id":"${id}"}`;
}
