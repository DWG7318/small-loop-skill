import type { EventProjection } from "../contracts";

interface TimelineProps {
  events: EventProjection[];
  onSelect: (event: EventProjection) => void;
}

function summary(event: EventProjection) {
  try {
    const details = JSON.parse(event.details_json) as Record<string, unknown>;
    return typeof details.summary === "string"
      ? details.summary
      : event.event_type.replaceAll("_", " ").toLowerCase();
  } catch {
    return event.event_type.replaceAll("_", " ").toLowerCase();
  }
}

export function Timeline({ events, onSelect }: TimelineProps) {
  return (
    <section className="timeline-section" aria-labelledby="timeline-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Authored history</p>
          <h2 id="timeline-heading">Timeline</h2>
        </div>
        <span>{events.length} facts</span>
      </div>
      <ol className="timeline-list">
        {events.map((event) => (
          <li key={event.event_id} className={event.corrects_event_id ? "is-correction" : ""}>
            <button type="button" onClick={() => onSelect(event)}>
              <span className="timeline-marker" aria-hidden="true" />
              <span className="timeline-body">
                <span className="timeline-meta">
                  <code>{event.event_type}</code>
                  <time dateTime={event.occurred_at}>{event.occurred_at}</time>
                </span>
                {event.corrects_event_id ? (
                  <small>Correction of {event.corrects_event_id}</small>
                ) : null}
                <strong>{summary(event)}</strong>
                <small>
                  {event.author_role_instance_id}
                  {event.cell_id ? ` · ${event.cell_id}` : ""}
                </small>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
