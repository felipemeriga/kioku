import { useId, type ReactNode } from "react";
import { ReadableContent } from "./agent-evidence/ReadableContent";

function SourceIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 5h11v15H8zM5 16H3V2h12v2M11 9h5M11 13h5M11 17h3" />
    </svg>
  );
}
function MergeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="6" cy="5" r="2" />
      <circle cx="6" cy="19" r="2" />
      <circle cx="18" cy="5" r="2" />
      <path d="M6 7v10M18 7c0 7-12 3-12 10" />
    </svg>
  );
}

export type ReportFinding = {
  text: string;
  source_ids: string[];
  evidence_quote: string;
};
export type ReportUpdate = ReportFinding & {
  date: string;
  title: string;
  detail: string;
};
export type ReportTopic = {
  id: string;
  title: string;
  subtitle: string;
  updates: ReportUpdate[];
  final_state: { status: string; items: ReportFinding[] };
};
export type ReportMerge = {
  at: string;
  date: string;
  pr_number: number | null;
  sha: string;
  title: string;
  source_ids: string[];
  evidence_quote: string;
};
export type TimelineReportContent = {
  format_version: 2;
  title: string;
  summary: string;
  summary_source_ids: string[];
  outcomes: ReportFinding[];
  topics: ReportTopic[];
  merges: ReportMerge[];
};
export type LegacyReportContent = {
  format_version?: 1;
  title: string;
  summary: string;
  summary_source_ids: string[];
  sections: { heading: string; items: ReportFinding[] }[];
};
export type ReportContent = TimelineReportContent | LegacyReportContent;

function calendarDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
    ? parsed
    : null;
}
function dayLabel(value: string, options: Intl.DateTimeFormatOptions): string {
  return (
    calendarDate(value)?.toLocaleDateString("en-US", {
      ...options,
      timeZone: "UTC",
    }) ?? "Date unavailable"
  );
}
function weekStart(value: string): string {
  const date = calendarDate(value);
  if (!date) return "";
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}
function groupByDate<T extends { date: string }>(items: T[], monthly: boolean) {
  const groups = new Map<string, T[]>();
  for (const item of [...items].sort((a, b) => a.date.localeCompare(b.date))) {
    const key = monthly ? weekStart(item.date) : item.date;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()];
}
export function ReportSourcesButton({
  ids,
  label,
  sourceIds,
  onOpen,
}: {
  ids: string[];
  label: string;
  sourceIds: ReadonlySet<string>;
  onOpen: (ids: string[], title: string) => void;
}) {
  const selected = [...new Set(ids)].filter((id) => sourceIds.has(id));
  return selected.length ? (
    <button
      type="button"
      className="reports-source-button"
      aria-label={`Sources for ${label}`}
      onClick={() => onOpen(selected, label)}
    >
      <SourceIcon />
      Sources ({selected.length})
    </button>
  ) : null;
}
function Part({
  id,
  number,
  title,
  caption,
  children,
}: {
  id: string;
  number: number;
  title: string;
  caption: string;
  children: ReactNode;
}) {
  return (
    <section
      className="reports-part"
      id={id}
      tabIndex={-1}
      aria-labelledby={`${id}-title`}
    >
      <div className="reports-part-heading">
        <span className="reports-part-number" aria-hidden="true">
          {number}
        </span>
        <div>
          <h4 id={`${id}-title`}>{title}</h4>
          <p>{caption}</p>
        </div>
      </div>
      {children}
    </section>
  );
}
export default function ReportTimeline({
  content,
  kind,
  timezone,
  sourceIds,
  onOpenSources,
}: {
  content: TimelineReportContent;
  kind: "weekly" | "monthly";
  timezone: string;
  sourceIds: ReadonlySet<string>;
  onOpenSources: (ids: string[], title: string) => void;
}) {
  const prefix = useId();
  const monthly = kind === "monthly";
  const ids = {
    merges: `${prefix}-merges`,
    work: `${prefix}-work`,
    state: `${prefix}-state`,
  };
  const sources = (items: { source_ids: string[] }[], label: string) => (
    <ReportSourcesButton
      ids={items.flatMap((item) => item.source_ids)}
      label={label}
      sourceIds={sourceIds}
      onOpen={onOpenSources}
    />
  );
  const mergeList = (items: ReportMerge[], showDay: boolean) => (
    <ul className="reports-merge-list">
      {[...items]
        .sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
        .map((merge) => (
          <li className="reports-merge-item" key={`${merge.sha}:${merge.at}`}>
            <MergeIcon />
            <time dateTime={merge.at}>
              {showDay && `${dayLabel(merge.date, { weekday: "short" })} `}
              {Number.isFinite(Date.parse(merge.at))
                ? new Date(merge.at).toLocaleTimeString("en-GB", {
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZone: timezone,
                  })
                : "—"}
            </time>
            <div className="reports-merge-copy">
              <button
                type="button"
                onClick={() =>
                  onOpenSources(
                    merge.source_ids,
                    merge.pr_number
                      ? `PR #${merge.pr_number}`
                      : `Commit ${merge.sha.slice(0, 8)}`
                  )
                }
              >
                {merge.pr_number
                  ? `#${merge.pr_number}`
                  : merge.sha.slice(0, 8)}
              </button>{" "}
              {merge.title}
            </div>
          </li>
        ))}
    </ul>
  );
  const updates = (items: ReportUpdate[]) => (
    <div className="reports-topic-days">
      {groupByDate(items, false).map(([date, dated]) => (
        <section
          className="reports-topic-update"
          key={date}
          aria-label={dayLabel(date, {
            weekday: "long",
            month: "short",
            day: "numeric",
          })}
        >
          <div className="reports-update-date">
            {dayLabel(date, {
              weekday: "long",
              month: "short",
              day: "numeric",
            })}
          </div>
          {dated.map((update, index) => (
            <div className="reports-entry" key={`${date}:${index}`}>
              <h5>{update.title}</h5>
              <ReadableContent text={update.text} />
              {update.detail && (
                <details className="reports-context">
                  <summary>Context and limits</summary>
                  <ReadableContent text={update.detail} />
                </details>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
  const groups = groupByDate(content.merges, monthly);
  return (
    <>
      <nav className="reports-section-nav" aria-label="Report sections">
        {(
          [
            ["merges", "Merges"],
            ["work", "Work timeline"],
            ["state", "Final state"],
          ] as const
        ).map(([name, label]) => (
          <button
            type="button"
            key={name}
            onClick={() => {
              const target = document.getElementById(ids[name]);
              target?.scrollIntoView({ block: "start" });
              target?.focus({ preventScroll: true });
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <Part
        id={ids.merges}
        number={1}
        title="Merged to main"
        caption={`Principal-branch changes, grouped by ${
          monthly ? "week" : "day"
        }`}
      >
        {!groups.length ? (
          <p className="reports-section-empty">
            No principal-branch merges recorded in this period.
          </p>
        ) : (
          groups.map(([date, merges], index) =>
            monthly ? (
              <details
                className="reports-week-merge"
                key={date}
                open={index === groups.length - 1}
              >
                <summary>
                  Week of {dayLabel(date, { month: "long", day: "numeric" })} ·{" "}
                  {merges.length} {merges.length === 1 ? "merge" : "merges"}
                </summary>
                {mergeList(merges, true)}
                {sources(merges, `Week of ${date} merges`)}
              </details>
            ) : (
              <section
                className="reports-merge-day"
                key={date}
                aria-label={`${dayLabel(date, { weekday: "long" })} merges`}
              >
                <div className="reports-merge-date">
                  <strong>{dayLabel(date, { weekday: "long" })}</strong>
                  {dayLabel(date, { month: "short", day: "numeric" })}
                </div>
                <div>
                  {mergeList(merges, false)}
                  {sources(
                    merges,
                    `${dayLabel(date, { weekday: "long" })} merges`
                  )}
                </div>
              </section>
            )
          )
        )}
      </Part>
      <Part
        id={ids.work}
        number={2}
        title="How the work progressed"
        caption={
          monthly
            ? "Connected topics, with weekly updates and expandable days"
            : "Dated updates, connected within each topic"
        }
      >
        {!content.topics.length && (
          <p className="reports-section-empty">
            No work updates recorded in this period.
          </p>
        )}
        {content.topics.map((topic, index) => {
          const weeks = groupByDate(topic.updates, true);
          return (
            <details
              className="reports-work-topic"
              key={topic.id}
              open={index === 0}
            >
              <summary>
                <div>
                  <strong>{topic.title}</strong>
                  {topic.subtitle && <span>{topic.subtitle}</span>}
                </div>
              </summary>
              {monthly
                ? weeks.map(([week, items], weekIndex) => (
                    <details
                      className="reports-topic-week"
                      key={week}
                      open={weekIndex === weeks.length - 1}
                    >
                      <summary>
                        Week of{" "}
                        {dayLabel(week, { month: "long", day: "numeric" })}
                      </summary>
                      <ul className="reports-week-preview">
                        {[...new Set(items.map((item) => item.title))]
                          .slice(0, 2)
                          .map((title) => (
                            <li key={title}>{title}</li>
                          ))}
                      </ul>
                      <details className="reports-context">
                        <summary>Show daily updates ({items.length})</summary>
                        {updates(items)}
                      </details>
                    </details>
                  ))
                : updates(topic.updates)}
              {sources(topic.updates, topic.title)}
            </details>
          );
        })}
      </Part>
      <Part
        id={ids.state}
        number={3}
        title="Final state at cutoff"
        caption="What landed, what was observed, and what remains uncertain"
      >
        {content.topics.map((topic) => (
          <section className="reports-state-row" key={topic.id}>
            <div>
              <h5>{topic.title}</h5>
              {topic.final_state.status && (
                <span
                  className={`reports-tag${
                    /^(merged|completed|changes merged|code merged|landed)$/i.test(
                      topic.final_state.status.replaceAll("_", " ").trim()
                    )
                      ? " reports-tag-merged"
                      : ""
                  }`}
                >
                  {topic.final_state.status.replaceAll("_", " ")}
                </span>
              )}
            </div>
            <div>
              {topic.final_state.items.map((item, index) => (
                <ReadableContent key={index} text={item.text} />
              ))}
              {sources(topic.final_state.items, `${topic.title} final state`)}
            </div>
          </section>
        ))}
      </Part>
    </>
  );
}
