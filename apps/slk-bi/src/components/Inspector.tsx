import type {
  EventProjection,
  EvidenceProjection,
  PlanRevisionProjection,
  RoleProjection,
} from "../contracts";

export type InspectorSelection =
  | { kind: "role"; value: RoleProjection }
  | { kind: "event"; value: EventProjection }
  | { kind: "plan"; value: PlanRevisionProjection }
  | { kind: "evidence"; value: EvidenceProjection };

interface InspectorProps {
  selection?: InspectorSelection;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="inspector-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function RoleDetails({ role }: { role: RoleProjection }) {
  return (
    <>
      <p className="eyebrow">{role.role} provenance</p>
      <h2>{role.role_instance_id}</h2>
      <dl>
        <Row label="Agent" value={role.agent_runtime} />
        <Row label="Provider" value={role.provider} />
        <Row label="Model" value={role.model} />
        <Row label="Reasoning" value={role.reasoning} />
        <Row label="Session" value={role.session_id} />
        <Row label="Lifecycle" value={role.lifecycle} />
        <Row label="State" value={role.display_state} />
      </dl>
      {role.predecessor_role_instance_id ? (
        <p className="provenance-note">Replaced {role.predecessor_role_instance_id}</p>
      ) : null}
      <h3>Endpoint history</h3>
      <ol className="endpoint-list">
        {role.endpoints.map((endpoint) => (
          <li key={endpoint.endpoint_version}>
            <div>
              <strong>v{endpoint.endpoint_version}</strong>
              <span>{endpoint.state}</span>
            </div>
            <code>{endpoint.session_id}</code>
            <small>
              {endpoint.transport_adapter} · {endpoint.host_identity}
            </small>
          </li>
        ))}
      </ol>
    </>
  );
}

export function Inspector({ selection }: InspectorProps) {
  return (
    <aside className="inspector" aria-label="Inspector">
      {!selection ? (
        <>
          <p className="eyebrow">Inspector</p>
          <h2>Recorded facts</h2>
          <p className="muted-copy">Select a role, event, plan revision, or evidence record.</p>
        </>
      ) : selection.kind === "role" ? (
        <RoleDetails role={selection.value} />
      ) : selection.kind === "event" ? (
        <>
          <p className="eyebrow">Authored event</p>
          <h2>{selection.value.event_type.replaceAll("_", " ")}</h2>
          <dl>
            <Row label="Event ID" value={selection.value.event_id} />
            <Row label="Author" value={selection.value.author_role_instance_id} />
            <Row label="GO" value={selection.value.go_id} />
            <Row label="CELL" value={selection.value.cell_id} />
            <Row label="Attempt" value={selection.value.attempt} />
            <Row label="Corrects" value={selection.value.corrects_event_id} />
            <Row label="Occurred" value={selection.value.occurred_at} />
          </dl>
          <pre>{selection.value.details_json}</pre>
        </>
      ) : selection.kind === "plan" ? (
        <>
          <p className="eyebrow">Plan history</p>
          <h2>Revision {selection.value.revision}</h2>
          <dl>
            <Row label="Author" value={selection.value.author_role_instance_id} />
            <Row label="Reason" value={selection.value.reason} />
            <Row label="Previous" value={selection.value.previous_revision} />
            <Row label="Created" value={selection.value.created_at} />
          </dl>
        </>
      ) : (
        <>
          <p className="eyebrow">Evidence record</p>
          <h2>{selection.value.evidence_id}</h2>
          <dl>
            <Row label="Type" value={selection.value.evidence_type} />
            <Row label="Producer" value={selection.value.producing_role_instance_id} />
            <Row label="Path" value={selection.value.stored_path} />
            <Row label="SHA-256" value={selection.value.sha256} />
            <Row label="Bytes" value={selection.value.byte_length} />
          </dl>
        </>
      )}
    </aside>
  );
}
