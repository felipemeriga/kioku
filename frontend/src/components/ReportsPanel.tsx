import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Drawer,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { apiFetch } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { ReadableContent } from "./agent-evidence/ReadableContent";
import type { EvidenceLocation } from "../lib/agentEvidenceApi";
import "./ReportsPanel.css";

type Source = {
  id: string;
  kind: string;
  date: string;
  text: string;
  entry_id?: string;
  journal_date?: string;
  event_id?: string;
  session_id?: string;
  url?: string;
};
type ReportSummary = {
  id: string;
  kind: "weekly" | "monthly";
  period_start: string;
  period_end: string;
  timezone: string;
  cutoff: string;
  status: "draft" | "final";
  revision: number;
  generated_at: string;
  coverage: {
    github: string;
    journal_entries: number;
    journal_entries_included: number;
    original_events_included: number;
    original_events: number;
  };
};
type Report = ReportSummary & {
  content: {
    title: string;
    summary: string;
    summary_source_ids: string[];
    sections: {
      heading: string;
      items: { text: string; source_ids: string[]; evidence_quote: string }[];
    }[];
  };
  sources: Source[];
};
function periodLabel(report: ReportSummary) {
  const date = new Date(`${report.period_start}T12:00:00Z`);
  return report.kind === "monthly"
    ? date.toLocaleDateString(undefined, {
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      })
    : `${report.period_start} – ${report.period_end}`;
}
function dateLabel(value: string, timezone: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  });
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export default function ReportsPanel({
  folderId,
  onOpenHistory,
  onOpenEvidence,
}: {
  folderId: string;
  onOpenHistory: (day: string, entryId?: string) => void;
  onOpenEvidence: (location: EvidenceLocation) => void;
}) {
  const { user } = useAuth();
  const client = useQueryClient();
  const stateKey = `kioku.report-return:${user?.id ?? "anonymous"}:${folderId}`;
  const [initial] = useState(() => {
    const defaults = {
      kind: "weekly" as "weekly" | "monthly",
      selected: null as string | null,
      revision: null as number | null,
      offset: 0,
    };
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("report");
    if (requested && UUID.test(requested)) {
      const value = Number(params.get("report_revision"));
      return {
        kind:
          params.get("report_kind") === "monthly"
            ? ("monthly" as const)
            : ("weekly" as const),
        selected: requested,
        revision:
          Number.isSafeInteger(value) && value > 0 && value < 1000000
            ? value
            : null,
        offset: 0,
      };
    }
    try {
      const saved = JSON.parse(sessionStorage.getItem(stateKey) ?? "null") as
        | (typeof defaults & { savedAt: number })
        | null;
      if (
        saved &&
        Date.now() - saved.savedAt < 600000 &&
        ["weekly", "monthly"].includes(saved.kind) &&
        (saved.selected === null || UUID.test(saved.selected)) &&
        (saved.revision === null ||
          (Number.isSafeInteger(saved.revision) && saved.revision > 0)) &&
        Number.isSafeInteger(saved.offset) &&
        saved.offset >= 0 &&
        saved.offset <= 1000
      )
        return saved;
    } catch {
      /* Optional UI state must never prevent opening Reports. */
    }
    return defaults;
  });
  const [kind, setKind] = useState(initial.kind);
  const [selected, setSelected] = useState(initial.selected);
  const [revision, setRevision] = useState(initial.revision);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [offset, setOffset] = useState(initial.offset);
  useEffect(() => {
    try {
      sessionStorage.setItem(
        stateKey,
        JSON.stringify({
          kind,
          selected,
          revision,
          offset,
          savedAt: Date.now(),
        })
      );
    } catch {
      /* Storage can be disabled. */
    }
  }, [stateKey, kind, selected, revision, offset]);
  const [settingsError, setSettingsError] = useState("");
  const [saving, setSaving] = useState(false);
  const listKey = ["period-reports", user?.id, folderId, kind, offset];
  const list = useQuery({
    queryKey: listKey,
    queryFn: async () =>
      (await (
        await apiFetch(
          `/api/folders/${folderId}/reports?kind=${kind}&offset=${offset}`
        )
      ).json()) as {
        reports: ReportSummary[];
        timezone: string;
        has_more: boolean;
      },
    staleTime: 30_000,
    retry: 1,
  });
  const id = selected ?? list.data?.reports[0]?.id;
  const detail = useQuery({
    queryKey: ["period-report", user?.id, folderId, id, revision],
    enabled: !!id,
    queryFn: async () =>
      (await (
        await apiFetch(
          `/api/folders/${folderId}/reports/${id}${
            revision ? `?revision=${revision}` : ""
          }`
        )
      ).json()) as {
        report: Report;
        revisions: { revision: number; generated_at: string }[];
      },
    staleTime: 30_000,
    retry: 1,
  });
  const report = detail.data?.report;
  const zone = list.data?.timezone ?? "UTC";
  const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const showSources = (ids: string[]) =>
    setSources(report?.sources.filter((s) => ids.includes(s.id)) ?? []);
  const openSource = (source: Source) => {
    setSources(null);
    if (source.kind === "original" && source.session_id)
      onOpenEvidence({
        folderId,
        sessionId: source.session_id,
        eventId: source.event_id,
        timezone: report?.timezone || zone,
        mode: "conversation",
      });
    else onOpenHistory(source.journal_date ?? source.date, source.entry_id);
  };
  const changeZone = async (timezone: string) => {
    setSettingsError("");
    setSaving(true);
    try {
      await apiFetch(`/api/folders/${folderId}/report-settings`, {
        method: "PUT",
        body: JSON.stringify({ timezone }),
      });
      setSelected(null);
      setRevision(null);
      setOffset(0);
      await client.invalidateQueries({
        queryKey: ["period-reports", user?.id, folderId],
      });
    } catch (error) {
      setSettingsError(
        error instanceof Error
          ? error.message
          : "Could not update report timezone. Try again."
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Box className="reports-panel">
      <Stack
        direction={{ xs: "column", sm: "row" }}
        gap={2}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        sx={{ mb: 2 }}
      >
        <ToggleButtonGroup
          exclusive
          size="small"
          value={kind}
          aria-label="Report period"
          onChange={(_, value: "weekly" | "monthly" | null) => {
            if (value) {
              setKind(value);
              setSelected(null);
              setRevision(null);
              setOffset(0);
            }
          }}
        >
          <ToggleButton value="weekly">Weekly</ToggleButton>
          <ToggleButton value="monthly">Monthly</ToggleButton>
        </ToggleButtonGroup>
        <Stack direction="row" gap={1} alignItems="center">
          <Typography variant="caption">{zone}</Typography>
          {localZone !== zone && (
            <Button
              size="small"
              disabled={saving}
              onClick={() => void changeZone(localZone)}
            >
              Use my timezone
            </Button>
          )}
          <Tooltip title="Mihari updates the current week daily and the current month weekly when sources change. Completed periods retain their revisions. Dates use this repository’s report timezone.">
            <IconButton size="small" aria-label="About report updates">
              <InfoOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>
      {settingsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {settingsError}
        </Alert>
      )}
      {list.isLoading ? (
        <Stack direction="row" gap={1} role="status">
          <CircularProgress size={18} />
          Loading reports…
        </Stack>
      ) : list.isError ? (
        <Alert
          severity="error"
          action={<Button onClick={() => void list.refetch()}>Retry</Button>}
        >
          Could not load reports. Your history is still available.
        </Alert>
      ) : !list.data?.reports.length && !selected ? (
        <Box className="reports-empty">
          <Typography variant="h6">No {kind} reports yet</Typography>
          <Typography color="text.secondary">
            Mihari creates reports from recorded activity on its next pass.
          </Typography>
          <Button sx={{ mt: 1 }} onClick={() => void list.refetch()}>
            Check again
          </Button>
        </Box>
      ) : (
        <div className="reports-layout">
          <nav className="reports-periods" aria-label={`${kind} reports`}>
            <Typography sx={{ fontWeight: 650, p: 1.5 }}>
              {kind === "weekly" ? "Weekly briefings" : "Monthly briefings"}
            </Typography>
            {list.data?.reports.map((item) => (
              <button
                key={item.id}
                className={id === item.id ? "selected" : ""}
                aria-current={id === item.id ? "true" : undefined}
                onClick={() => {
                  setSelected(item.id);
                  setRevision(null);
                }}
              >
                <strong>{periodLabel(item)}</strong>
                <span>
                  {item.status === "draft" ? "In progress" : "Completed period"}
                </span>
              </button>
            ))}
            <Stack direction="row" justifyContent="space-between">
              <Button
                disabled={offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - 50));
                  setSelected(null);
                  setRevision(null);
                }}
              >
                Newer
              </Button>
              <Button
                disabled={!list.data?.has_more || offset >= 1000}
                onClick={() => {
                  setOffset(Math.min(1000, offset + 50));
                  setSelected(null);
                  setRevision(null);
                }}
              >
                Older
              </Button>
            </Stack>
          </nav>
          <article className="reports-document" aria-label="Selected report">
            {detail.isLoading ? (
              <Stack direction="row" gap={1} role="status">
                <CircularProgress size={18} />
                Loading report…
              </Stack>
            ) : detail.isError ? (
              <Alert
                severity="error"
                action={
                  <Button onClick={() => void detail.refetch()}>Retry</Button>
                }
              >
                Could not load this report.
              </Alert>
            ) : (
              report && (
                <>
                  <header>
                    <Typography color="text.secondary" variant="body2">
                      {report.kind === "weekly" ? "Weekly" : "Monthly"} briefing
                      · {periodLabel(report)}
                    </Typography>
                    <Typography
                      component="h3"
                      variant="h4"
                      sx={{
                        fontSize: { xs: 24, md: 30 },
                        mt: 2,
                        fontWeight: 650,
                      }}
                    >
                      {report.content.title}
                    </Typography>
                    <ReadableContent text={report.content.summary} />
                    <Button
                      size="small"
                      onClick={() =>
                        showSources(report.content.summary_source_ids)
                      }
                    >
                      Summary sources
                    </Button>
                    <Stack
                      direction="row"
                      flexWrap="wrap"
                      gap={1}
                      sx={{ mt: 2 }}
                    >
                      <Chip
                        size="small"
                        label={
                          report.status === "draft"
                            ? "In progress"
                            : "Completed period"
                        }
                        variant="outlined"
                      />
                      <Typography
                        variant="caption"
                        sx={{ alignSelf: "center" }}
                      >
                        Sources through{" "}
                        {dateLabel(report.cutoff, report.timezone)} ·{" "}
                        {report.timezone}
                      </Typography>
                    </Stack>
                    <Stack
                      direction="row"
                      gap={2}
                      flexWrap="wrap"
                      alignItems="center"
                      sx={{ mt: 2 }}
                    >
                      <Typography variant="caption" color="text.secondary">
                        Updated{" "}
                        {dateLabel(report.generated_at, report.timezone)}
                      </Typography>
                      <FormControl size="small" sx={{ minWidth: 145 }}>
                        <InputLabel id="report-version-label">
                          Revision
                        </InputLabel>
                        <Select
                          labelId="report-version-label"
                          label="Revision"
                          value={report.revision}
                          onChange={(e) => {
                            const next = Number(e.target.value);
                            if (Number.isSafeInteger(next) && next > 0)
                              setRevision(next);
                          }}
                        >
                          {detail.data?.revisions.map((v) => (
                            <MenuItem key={v.revision} value={v.revision}>
                              Revision {v.revision}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </Stack>
                  </header>
                  {report.content.sections.map((section, index) => (
                    <section key={index} className="reports-section">
                      <Typography
                        component="h4"
                        variant="h6"
                        sx={{ fontSize: 18, mb: 2 }}
                      >
                        {section.heading}
                      </Typography>
                      {section.items.map((item, n) => (
                        <Box key={n} sx={{ mb: 2.5 }}>
                          <ReadableContent text={item.text} />
                          <Button
                            size="small"
                            sx={{ px: 0 }}
                            onClick={() => showSources(item.source_ids)}
                          >
                            View evidence
                          </Button>
                        </Box>
                      ))}
                    </section>
                  ))}
                  <footer>
                    <Button onClick={() => setSources(report.sources)}>
                      Supporting sources
                    </Button>
                    <Button
                      onClick={() =>
                        onOpenHistory(
                          report.sources.find((s) => s.kind === "journal")
                            ?.date ?? report.period_start
                        )
                      }
                    >
                      Open in History
                    </Button>
                    <Tooltip
                      title={`Journal entries included: ${report.coverage.journal_entries_included}/${report.coverage.journal_entries}. Original results sampled: ${report.coverage.original_events_included}/${report.coverage.original_events}. GitHub: ${report.coverage.github}. Agent reports and Git commits do not prove deployment.`}
                    >
                      <IconButton
                        aria-label="Report source coverage"
                        size="small"
                      >
                        <InfoOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </footer>
                </>
              )
            )}
          </article>
        </div>
      )}
      <Drawer
        anchor="right"
        open={sources !== null}
        onClose={() => setSources(null)}
        PaperProps={{
          sx: { width: { xs: "100%", sm: 560 }, maxWidth: "100vw", p: 3 },
        }}
      >
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
        >
          <Typography variant="h6">Supporting evidence</Typography>
          <IconButton
            aria-label="Close evidence"
            onClick={() => setSources(null)}
          >
            <CloseIcon />
          </IconButton>
        </Stack>
        {sources?.map((source) => (
          <Box key={source.id} className="reports-source">
            <Chip
              size="small"
              label={source.kind.replaceAll("_", " ")}
              variant="outlined"
            />
            <Typography variant="caption" sx={{ ml: 1 }}>
              {source.date}
            </Typography>
            <ReadableContent text={source.text} />
            {source.url &&
            /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/(commit|pull)\/[a-f0-9]+$/.test(
              source.url
            ) ? (
              <Button
                component="a"
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open on GitHub
              </Button>
            ) : (
              <Button onClick={() => openSource(source)}>
                Open {source.kind === "original" ? "original" : "in History"}
              </Button>
            )}
          </Box>
        ))}
      </Drawer>
    </Box>
  );
}
