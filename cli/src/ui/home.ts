export type HomeAction =
  | "ls" | "search" | "briefing" | "init"
  | "status" | "doctor" | "login" | "logout" | "quit";

export interface HomeState {
  signedIn: boolean;
  email?: string;
  rootFolders?: number;
  apiBase: string;
  inRepo: boolean;
  repoWired: boolean;
}

export interface HomeItem { name: string; value: HomeAction; }

export function buildMenu(state: HomeState): HomeItem[] {
  if (!state.signedIn) {
    return [
      { name: "Sign in", value: "login" },
      { name: "Quit", value: "quit" },
    ];
  }

  const items: HomeItem[] = [
    { name: "Browse workspace", value: "ls" },
    { name: "Search memory", value: "search" },
  ];

  if (state.inRepo && state.repoWired) {
    items.push({ name: "This repo's briefing", value: "briefing" });
  }
  if (state.inRepo && !state.repoWired) {
    items.push({ name: "Initialize this repo", value: "init" });
  }

  items.push({ name: "Status", value: "status" });
  items.push({ name: "Diagnostics (doctor)", value: "doctor" });
  items.push({ name: "Sign out", value: "logout" });
  items.push({ name: "Quit", value: "quit" });

  return items;
}
