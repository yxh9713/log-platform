export type Session = {
  id: string;
  email: string;
  role: 'administrator' | 'user';
  company: { id: string; name: string; slug: string };
  expires_at: string;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api(
  path: string,
  body?: object,
  options: { method?: 'POST' | 'PUT' | 'DELETE'; signal?: AbortSignal } = {},
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/v1/${path}`, {
      method: options.method ?? (body === undefined ? 'GET' : 'POST'),
      signal: options.signal,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'logistics-web',
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(
      0,
      'Unable to reach the service. Check your connection and try again.',
    );
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      payload &&
      typeof payload === 'object' &&
      'message' in payload &&
      typeof payload.message === 'string'
        ? payload.message
        : 'The service is unavailable. Please try again.';
    throw new ApiError(response.status, message);
  }
  return payload;
}

export function parseSession(value: unknown): Session {
  if (
    value &&
    typeof value === 'object' &&
    'id' in value &&
    typeof value.id === 'string' &&
    'email' in value &&
    typeof value.email === 'string' &&
    'role' in value &&
    (value.role === 'administrator' || value.role === 'user') &&
    'expires_at' in value &&
    typeof value.expires_at === 'string' &&
    Number.isFinite(Date.parse(value.expires_at)) &&
    'company' in value &&
    value.company &&
    typeof value.company === 'object' &&
    'id' in value.company &&
    typeof value.company.id === 'string' &&
    'name' in value.company &&
    typeof value.company.name === 'string' &&
    'slug' in value.company &&
    typeof value.company.slug === 'string'
  ) {
    return value as Session;
  }
  throw new ApiError(
    0,
    'The service returned an unexpected session. Please try again.',
  );
}
