// Illustrative data only. Replace this module when authenticated remotes APIs exist.
export interface RemotePreview {
  id: string;
  name: string;
  platform: string;
  host: string;
  connected: string;
  online: boolean;
  heartbeat: string;
  lastSync: string;
  issue?: string;
  repos: {
    name: string;
    path: string;
    imported: number;
    pending: number;
    lastSync: string;
    status: "Up to date" | "Needs attention" | "Syncing";
  }[];
  agents: {
    name: string;
    status: "Recently active" | "Running" | "Unknown";
    project?: string;
    session?: string;
    activity: string;
    collection: string;
  }[];
  activity: { text: string; detail: string; time: string }[];
}

export const remotesPreview: RemotePreview[] = [
  {
    id: "dev",
    name: "meriga-dev",
    platform: "Linux",
    host: "ghgkv.cxvh.cosm.link",
    connected: "Oct 20",
    online: true,
    heartbeat: "8s ago",
    lastSync: "2m ago",
    issue: "Codex memories haven’t synced yet",
    repos: [
      {
        name: "c360-lead",
        path: "~/GIT/c360-lead",
        imported: 56,
        pending: 0,
        lastSync: "2m ago",
        status: "Needs attention",
      },
      {
        name: "kioku",
        path: "~/GIT/kioku",
        imported: 18,
        pending: 0,
        lastSync: "4m ago",
        status: "Up to date",
      },
      {
        name: "ses-ingester",
        path: "~/GIT/ses-ingester",
        imported: 12,
        pending: 3,
        lastSync: "6m ago",
        status: "Syncing",
      },
    ],
    agents: [
      {
        name: "Claude Code",
        status: "Recently active",
        project: "c360-lead / player investigation",
        session: "aea55265",
        activity: "Activity 35s ago",
        collection: "Native memory collection is up to date.",
      },
      {
        name: "Codex",
        status: "Running",
        project: "c360-lead",
        activity: "Session activity unknown",
        collection: "Process detected. No extracted memories yet.",
      },
    ],
    activity: [
      {
        text: "4 memories received",
        detail: "Claude Code · c360-lead",
        time: "2m ago",
      },
      { text: "kioku is up to date", detail: "No new changes", time: "4m ago" },
    ],
  },
  {
    id: "mac",
    name: "Felipe’s MacBook",
    platform: "macOS",
    host: "MacBook Pro",
    connected: "Oct 21",
    online: true,
    heartbeat: "12s ago",
    lastSync: "2m ago",
    repos: [
      {
        name: "kioku",
        path: "~/personal_projects/kioku",
        imported: 24,
        pending: 0,
        lastSync: "2m ago",
        status: "Up to date",
      },
      {
        name: "hive",
        path: "~/personal_projects/hive",
        imported: 8,
        pending: 0,
        lastSync: "5m ago",
        status: "Up to date",
      },
    ],
    agents: [
      {
        name: "Claude Code",
        status: "Unknown",
        activity: "No recent session observed",
        collection: "Available on this machine.",
      },
      {
        name: "Codex",
        status: "Unknown",
        activity: "No recent session observed",
        collection: "Available on this machine.",
      },
    ],
    activity: [
      { text: "kioku is up to date", detail: "No new changes", time: "2m ago" },
    ],
  },
  {
    id: "home",
    name: "home-workstation",
    platform: "Linux",
    host: "Ubuntu",
    connected: "Oct 18",
    online: false,
    heartbeat: "6h ago",
    lastSync: "6h ago",
    repos: [],
    agents: [],
    activity: [],
  },
];
