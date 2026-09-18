/**
 * QueryState — small helper to render loading / error / empty states uniformly
 * around a react-query result.
 */
import type { ReactNode } from 'react';
import { ApiError } from '../api/http.js';

export interface QueryStateProps {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  children: ReactNode;
}

export function QueryState({ isLoading, isError, error, children }: QueryStateProps): JSX.Element {
  if (isLoading) return <p className="loading">Loading…</p>;
  if (isError) {
    const message =
      error instanceof ApiError
        ? `${error.message} (request ${error.requestId ?? 'n/a'})`
        : error instanceof Error
          ? error.message
          : 'Something went wrong.';
    return (
      <p className="error" role="alert">
        {message}
      </p>
    );
  }
  return <>{children}</>;
}
