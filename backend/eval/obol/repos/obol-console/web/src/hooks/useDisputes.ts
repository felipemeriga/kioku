import { useQuery } from '@tanstack/react-query';
import { consoleApi } from '../api/client.js';

export function useDisputes() {
  return useQuery({
    queryKey: ['disputes'],
    queryFn: () => consoleApi.listDisputes(),
    staleTime: 60_000,
  });
}
