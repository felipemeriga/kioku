import { Fragment, useEffect, useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  Stack,
  Tooltip,
} from "@mui/material";
import { apiFetch } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { ReadableContent } from "./agent-evidence/ReadableContent";
import type { EvidenceLocation } from "../lib/agentEvidenceApi";
import ReportTimeline, {
  ReportSourcesButton,
  type ReportContent,
  type TimelineReportContent,
} from "./ReportTimeline";
import "./ReportsPanel.css";

type Source = {
  id: string;
  kind: string;
  date: string;
  observed_at?: string;
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
  content: ReportContent;
  sources: Source[];
};
const isTimelineReport = (
  content: ReportContent
): content is TimelineReportContent => content.format_version === 2;
function periodLabel(report: ReportSummary) {
  const start = new Date(`${report.period_start}T12:00:00Z`);
  const end = new Date(`${report.period_end}T12:00:00Z`);
  if (report.kind === "monthly")
    return start.toLocaleDateString("en-US", {
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    });
  const first = start.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
  const last = end.toLocaleDateString("en-US", {
    ...(start.getUTCMonth() !== end.getUTCMonth()
      ? { month: "short" as const }
      : {}),
    day: "numeric",
    timeZone: "UTC",
  });
  return `${first}–${last}`;
}
function reportRange(report: ReportSummary) {
  return report.kind === "weekly"
    ? `Week of ${new Date(
        `${report.period_start}T12:00:00Z`
      ).toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      })}`
    : `${new Date(`${report.period_start}T12:00:00Z`).toLocaleDateString(
        "en-US",
        { month: "long", day: "numeric", timeZone: "UTC" }
      )}–${new Date(`${report.period_end}T12:00:00Z`).getUTCDate()}, ${new Date(
        `${report.period_start}T12:00:00Z`
      ).getUTCFullYear()}`;
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
  const [sources, setSources] = useState<{
    title: string;
    items: Source[];
  } | null>(null);
  const sourceTitleId = useId();
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
  const showSources = (ids: string[], title = "Supporting evidence") =>
    setSources({
      title,
      items: report?.sources.filter((s) => ids.includes(s.id)) ?? [],
    });
  const sourceIds = new Set(report?.sources.map((source) => source.id) ?? []);
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
  const changeKind = (next: "weekly" | "monthly") => {
    setKind(next);
    setSelected(null);
    setRevision(null);
    setOffset(0);
    setSources(null);
  };
  const chooseReport = (next: string) => {
    if (!list.data?.reports.some((item) => item.id === next)) return;
    setSelected(next);
    setRevision(null);
    setSources(null);
  };
  const paginate = (direction: -1 | 1) => {
    setOffset(Math.min(1000, Math.max(0, offset + direction * 50)));
    setSelected(null);
    setRevision(null);
    setSources(null);
  };
  return (
    <Box className="reports-panel">
      <div className="reports-toolbar">
        <div className="reports-segmented" aria-label="Report period">
          <button
            type="button"
            aria-pressed={kind === "weekly"}
            onClick={() => changeKind("weekly")}
          >
            Weekly
          </button>
          <button
            type="button"
            aria-pressed={kind === "monthly"}
            onClick={() => changeKind("monthly")}
          >
            Monthly
          </button>
        </div>
        <div className="reports-timezone">
          <span>{zone}</span>
          {localZone !== zone && (
            <button
              type="button"
              className="reports-text-action"
              disabled={saving}
              onClick={() => void changeZone(localZone)}
            >
              Use my timezone
            </button>
          )}
          <Tooltip title="New commits on the watched branch trigger reviews of the current week and month. Otherwise, weekly reports update daily and monthly reports weekly when sources change. Reviews are queued; previous revisions remain available.">
            <button
              type="button"
              className="reports-info"
              aria-label="About report updates"
            >
              i
            </button>
          </Tooltip>
        </div>
      </div>
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
          <h3>No {kind} reports yet</h3>
          <p>Mihari creates reports from recorded activity on its next pass.</p>
          <Button onClick={() => void list.refetch()}>Check again</Button>
        </Box>
      ) : (
        <div className="reports-layout">
          <nav className="reports-periods" aria-label={`${kind} reports`}>
            <div className="reports-period-caption">
              {kind === "weekly" ? "Weekly reports" : "Monthly reports"}
            </div>
            <select
              className="reports-mobile-period"
              aria-label="Choose report period"
              value={
                list.data?.reports.some((item) => item.id === id) ? id : ""
              }
              onChange={(event) => chooseReport(event.target.value)}
            >
              <option value="" disabled>
                Choose a period
              </option>
              {list.data?.reports.map((item) => (
                <option key={item.id} value={item.id}>
                  {periodLabel(item)}
                </option>
              ))}
            </select>
            <div
              className="reports-period-scroll"
              role="region"
              aria-label={`Available ${kind} reports`}
              tabIndex={0}
            >
              {list.data?.reports.map((item, index, items) => (
                <Fragment key={item.id}>
                  {kind === "weekly" &&
                    (index === 0 ||
                      items[index - 1].period_start.slice(0, 7) !==
                        item.period_start.slice(0, 7)) && (
                      <h4 className="reports-period-month">
                        {new Date(
                          `${item.period_start}T12:00:00Z`
                        ).toLocaleDateString("en-US", {
                          month: "long",
                          year: "numeric",
                          timeZone: "UTC",
                        })}
                      </h4>
                    )}
                  <button
                    type="button"
                    className={`reports-period${
                      id === item.id ? " selected" : ""
                    }`}
                    aria-current={id === item.id ? "true" : undefined}
                    onClick={() => chooseReport(item.id)}
                  >
                    <strong>{periodLabel(item)}</strong>
                    <span>
                      {item.status === "draft" ? "In progress" : "Completed"}
                    </span>
                  </button>
                </Fragment>
              ))}
            </div>
            <footer>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => paginate(-1)}
              >
                Newer
              </button>
              <button
                type="button"
                disabled={!list.data?.has_more || offset >= 1000}
                onClick={() => paginate(1)}
              >
                Older
              </button>
            </footer>
          </nav>
          <article className="reports-document" aria-label="Selected report">
            {detail.isLoading ? (
              <Stack
                direction="row"
                gap={1}
                className="reports-document-state"
                role="status"
              >
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
                  <header className="reports-report-head">
                    <div className="reports-report-meta">
                      <span>{reportRange(report)}</span>
                      <span className="reports-status">
                        {report.status === "draft"
                          ? "In progress"
                          : "Completed period"}
                      </span>
                    </div>
                    <h3>{report.content.title}</h3>
                    {isTimelineReport(report.content) ? (
                      <>
                        <div className="reports-standfirst">
                          <ReadableContent text={report.content.summary} />
                        </div>
                        {!!report.content.outcomes.length && (
                          <ul className="reports-outcomes">
                            {report.content.outcomes.map((outcome, index) => (
                              <li key={index}>
                                <ReadableContent text={outcome.text} />
                              </li>
                            ))}
                          </ul>
                        )}
                      </>
                    ) : (
                      <details className="reports-legacy-overview">
                        <summary>Overview</summary>
                        <div className="reports-standfirst">
                          <ReadableContent text={report.content.summary} />
                        </div>
                        <button
                          type="button"
                          className="reports-text-action"
                          onClick={() =>
                            showSources(
                              report.content.summary_source_ids,
                              "Summary sources"
                            )
                          }
                        >
                          Summary sources
                        </button>
                      </details>
                    )}
                    <div className="reports-report-footnote">
                      <span>
                        Sources through{" "}
                        {new Date(report.cutoff).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit",
                          timeZone: report.timezone,
                        })}{" "}
                        <Tooltip title="This report describes evidence available through the displayed time. Later changes appear in a subsequent revision.">
                          <button
                            type="button"
                            className="reports-info"
                            aria-label="What does the cutoff mean?"
                          >
                            i
                          </button>
                        </Tooltip>
                      </span>
                      <label className="reports-revision">
                        Revision{" "}
                        <select
                          aria-label="Revision"
                          value={report.revision}
                          onChange={(event) => {
                            const value = Number(event.target.value);
                            if (
                              Number.isSafeInteger(value) &&
                              value > 0 &&
                              detail.data?.revisions.some(
                                (item) => item.revision === value
                              )
                            )
                              setRevision(value);
                          }}
                        >
                          {detail.data?.revisions.map((item, index) => (
                            <option key={item.revision} value={item.revision}>
                              {item.revision}
                              {index === 0 ? " · latest" : " · earlier"}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  </header>
                  {isTimelineReport(report.content) ? (
                    <ReportTimeline
                      key={`${report.id}:${report.revision}`}
                      content={report.content}
                      kind={report.kind}
                      timezone={report.timezone}
                      sourceIds={sourceIds}
                      onOpenSources={showSources}
                    />
                  ) : (
                    <div className="reports-legacy-content">
                      {report.content.sections.map((section, index) => (
                        <section key={index} className="reports-legacy-section">
                          <h4>{section.heading}</h4>
                          {section.items.map((item, n) => (
                            <ReadableContent key={n} text={item.text} />
                          ))}
                          <ReportSourcesButton
                            ids={section.items.flatMap(
                              (item) => item.source_ids
                            )}
                            label={section.heading}
                            sourceIds={sourceIds}
                            onOpen={showSources}
                          />
                        </section>
                      ))}
                    </div>
                  )}
                  <footer className="reports-document-footer">
                    <button
                      type="button"
                      onClick={() =>
                        setSources({
                          title: "Report sources",
                          items: report.sources,
                        })
                      }
                    >
                      Report sources
                    </button>
                    <div>
                      <button
                        type="button"
                        onClick={() =>
                          onOpenHistory(
                            report.sources.find(
                              (source) => source.kind === "journal"
                            )?.date ?? report.period_start
                          )
                        }
                      >
                        Open in History
                      </button>
                      <Tooltip
                        title={`Journal entries included: ${report.coverage.journal_entries_included}/${report.coverage.journal_entries}. Original results sampled: ${report.coverage.original_events_included}/${report.coverage.original_events}. GitHub: ${report.coverage.github}.`}
                      >
                        <button
                          type="button"
                          className="reports-info"
                          aria-label="Report source coverage"
                        >
                          i
                        </button>
                      </Tooltip>
                    </div>
                  </footer>
                </>
              )
            )}
          </article>
        </div>
      )}
      <Dialog
        className="reports-source-dialog"
        open={sources !== null}
        onClose={() => setSources(null)}
        aria-labelledby={sourceTitleId}
        maxWidth={false}
        slotProps={{ paper: { className: "reports-source-modal" } }}
      >
        <div className="reports-dialog-head">
          <h4 id={sourceTitleId}>{sources?.title ?? "Supporting evidence"}</h4>
          <button
            type="button"
            aria-label="Close evidence"
            onClick={() => setSources(null)}
          >
            ×
          </button>
        </div>
        <div className="reports-dialog-body">
          {sources?.items.map((source) => (
            <section key={source.id} className="reports-source">
              <span className="reports-tag">
                {source.kind.replaceAll("_", " ")}
              </span>
              <span className="reports-source-date">
                {source.observed_at
                  ? dateLabel(source.observed_at, report?.timezone || zone)
                  : source.date}
              </span>
              <ReadableContent text={source.text} />
              {source.url &&
              /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/(commit|pull)\/[a-f0-9]+$/.test(
                source.url
              ) ? (
                <a
                  className="reports-source-action"
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open on GitHub
                </a>
              ) : ["original", "journal"].includes(source.kind) ? (
                <button
                  type="button"
                  className="reports-source-action"
                  onClick={() => openSource(source)}
                >
                  Open {source.kind === "original" ? "original" : "in History"}
                </button>
              ) : (
                <p className="reports-source-unavailable">
                  Source link unavailable.
                </p>
              )}
            </section>
          ))}
        </div>
      </Dialog>
    </Box>
  );
}
