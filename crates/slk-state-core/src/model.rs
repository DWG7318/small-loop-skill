//! Closed request and identity types shared by state writers and readers.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Supervisor,
    Overwatcher,
    Checker,
    Worker,
}

impl Role {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Supervisor => "supervisor",
            Self::Overwatcher => "overwatcher",
            Self::Checker => "checker",
            Self::Worker => "worker",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "supervisor" => Some(Self::Supervisor),
            "overwatcher" => Some(Self::Overwatcher),
            "checker" => Some(Self::Checker),
            "worker" => Some(Self::Worker),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ObservationKind {
    DeliveryUnconfirmed,
    DeliveryRetrying,
    ActivityUnproven,
    RecordConflict,
    RecoveryEscalated,
    ProjectionRefreshRequested,
    OverwatcherClosed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ObservationMode {
    ForegroundActiveTurn,
}

impl ObservationMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ForegroundActiveTurn => "FOREGROUND_ACTIVE_TURN",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OverwatchCheckResult {
    Clear,
    Anomaly,
    NotApplicable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OverwatchAnomalyCode {
    ActivityUnproven,
    DeliveryUnconfirmed,
    CommunicationRecoveryRequired,
    LoopStalled,
    DuplicateOperation,
    EndpointDrift,
    DuplicateRunIdentity,
    ProjectionMismatch,
    RecordConflict,
    OverwatcherActiveDegraded,
    OverwatcherInactive,
    TerminalCloseRequired,
}

impl OverwatchCheckResult {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Clear => "CLEAR",
            Self::Anomaly => "ANOMALY",
            Self::NotApplicable => "NOT_APPLICABLE",
        }
    }
}

impl ObservationKind {
    pub fn as_str(self) -> &'static str {
        use ObservationKind::*;
        match self {
            DeliveryUnconfirmed => "DELIVERY_UNCONFIRMED",
            DeliveryRetrying => "DELIVERY_RETRYING",
            ActivityUnproven => "ACTIVITY_UNPROVEN",
            RecordConflict => "RECORD_CONFLICT",
            RecoveryEscalated => "RECOVERY_ESCALATED",
            ProjectionRefreshRequested => "PROJECTION_REFRESH_REQUESTED",
            OverwatcherClosed => "OVERWATCHER_CLOSED",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EventType {
    RunInitialized,
    OverwatcherBound,
    PlanRevised,
    RoleRegistered,
    RoleReplaced,
    ModelChanged,
    SessionRebound,
    ExemptionGranted,
    D2Started,
    D2Passed,
    D2Failed,
    RunSuperseded,
    RunAbandoned,
    RunClosed,
    CellDispatched,
    D1Started,
    D1Incomplete,
    D1Passed,
    D1Failed,
    ReworkRequested,
    CellSplit,
    CandidateForwarded,
    WorkStarted,
    WorkProgress,
    BlockerReported,
    ChangeRecorded,
    D0Completed,
    CandidateSubmitted,
    ResourceContended,
    ResourceRecovered,
    EvidenceRegistered,
    TokenHandedOff,
    TransportFailed,
    TransportStarted,
}

impl EventType {
    pub fn is_owned_by(self, role: Role) -> bool {
        use EventType::*;
        match self {
            RunInitialized | OverwatcherBound | PlanRevised | ModelChanged | SessionRebound
            | ExemptionGranted | D2Started | D2Passed | D2Failed | RunSuperseded | RunAbandoned
            | RunClosed => role == Role::Supervisor,
            RoleRegistered | RoleReplaced => role == Role::Supervisor || role == Role::Checker,
            CellDispatched | D1Started | D1Incomplete | D1Passed | D1Failed | ReworkRequested
            | CellSplit | CandidateForwarded => role == Role::Checker,
            WorkStarted | WorkProgress | BlockerReported | ChangeRecorded | D0Completed
            | CandidateSubmitted => role == Role::Worker,
            ResourceContended | ResourceRecovered | TokenHandedOff | TransportFailed
            | TransportStarted => role != Role::Overwatcher,
            EvidenceRegistered => true,
        }
    }

    pub fn as_str(self) -> &'static str {
        use EventType::*;
        match self {
            RunInitialized => "RUN_INITIALIZED",
            OverwatcherBound => "OVERWATCHER_BOUND",
            PlanRevised => "PLAN_REVISED",
            RoleRegistered => "ROLE_REGISTERED",
            RoleReplaced => "ROLE_REPLACED",
            ModelChanged => "MODEL_CHANGED",
            SessionRebound => "SESSION_REBOUND",
            ExemptionGranted => "EXEMPTION_GRANTED",
            D2Started => "D2_STARTED",
            D2Passed => "D2_PASSED",
            D2Failed => "D2_FAILED",
            RunSuperseded => "RUN_SUPERSEDED",
            RunAbandoned => "RUN_ABANDONED",
            RunClosed => "RUN_CLOSED",
            CellDispatched => "CELL_DISPATCHED",
            D1Started => "D1_STARTED",
            D1Incomplete => "D1_INCOMPLETE",
            D1Passed => "D1_PASSED",
            D1Failed => "D1_FAILED",
            ReworkRequested => "REWORK_REQUESTED",
            CellSplit => "CELL_SPLIT",
            CandidateForwarded => "CANDIDATE_FORWARDED",
            WorkStarted => "WORK_STARTED",
            WorkProgress => "WORK_PROGRESS",
            BlockerReported => "BLOCKER_REPORTED",
            ChangeRecorded => "CHANGE_RECORDED",
            D0Completed => "D0_COMPLETED",
            CandidateSubmitted => "CANDIDATE_SUBMITTED",
            ResourceContended => "RESOURCE_CONTENDED",
            ResourceRecovered => "RESOURCE_RECOVERED",
            EvidenceRegistered => "EVIDENCE_REGISTERED",
            TokenHandedOff => "TOKEN_HANDED_OFF",
            TransportFailed => "TRANSPORT_FAILED",
            TransportStarted => "TRANSPORT_STARTED",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectIdentity {
    pub project_id: String,
    pub name: String,
    pub repository_url: Option<String>,
    pub last_known_path: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoDefinition {
    pub go_id: String,
    pub ordinal: u32,
    pub title: String,
    pub objective: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellDefinition {
    pub go_id: String,
    pub cell_id: String,
    pub ordinal: u32,
    pub title: String,
    pub objective: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RoleIdentity {
    pub role_instance_id: String,
    pub role: Role,
    pub agent_runtime: String,
    pub provider: String,
    pub model: String,
    pub reasoning: String,
    pub session_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EndpointIdentity {
    pub endpoint_version: u32,
    pub transport_adapter: String,
    pub host_identity: String,
    pub session_id: String,
    pub native_address: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InitRunRequest {
    pub project: ProjectIdentity,
    pub run_id: String,
    #[serde(default)]
    pub predecessor_run_id: Option<String>,
    #[serde(default)]
    pub run_name: Option<String>,
    #[serde(default)]
    pub run_description: Option<String>,
    #[serde(default)]
    pub source_kind: Option<String>,
    #[serde(default)]
    pub source_project_name: Option<String>,
    pub goal: String,
    pub boundaries: Value,
    pub go_nodes: Vec<GoDefinition>,
    pub cell_nodes: Vec<CellDefinition>,
    pub supervisor: RoleIdentity,
    pub supervisor_endpoint: EndpointIdentity,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WriteRequest {
    pub event_id: String,
    pub run_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub attempt: Option<u32>,
    pub plan_revision: u32,
    pub role_instance_id: String,
    pub event_type: EventType,
    pub details: Value,
    pub corrects_event_id: Option<String>,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RegisterRoleRequest {
    pub event_id: String,
    pub run_id: String,
    pub identity: RoleIdentity,
    pub endpoint: EndpointIdentity,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BindOverwatcherRequest {
    pub event_id: String,
    pub run_id: String,
    pub identity: RoleIdentity,
    pub endpoint: EndpointIdentity,
    pub observation_mode: ObservationMode,
    pub cadence_seconds: u32,
    pub foreground_turn_id: String,
    pub native_active_session_evidence_ref: String,
    pub reason: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OverwatchCycleChecklist {
    pub run_position: OverwatchCheckResult,
    pub role_bindings: OverwatchCheckResult,
    pub direct_handoffs: OverwatchCheckResult,
    pub cell_lifecycle: OverwatchCheckResult,
    pub stall_and_duplicates: OverwatchCheckResult,
    pub bi_projection: OverwatchCheckResult,
    pub active_session: OverwatchCheckResult,
    pub terminal_closure: OverwatchCheckResult,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OverwatchCycleRequest {
    pub cycle_id: String,
    pub run_id: String,
    pub plan_revision: u32,
    pub role_instance_id: String,
    pub session_id: String,
    pub foreground_turn_id: String,
    pub cycle_sequence: u64,
    pub cadence_seconds: u32,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub attempt: Option<u32>,
    pub token_sequence: u64,
    pub token_holder_role_instance_id: String,
    pub latest_event_id: String,
    pub latest_message_id: Option<String>,
    pub checklist: OverwatchCycleChecklist,
    pub anomaly_codes: Vec<OverwatchAnomalyCode>,
    pub evidence_refs: Vec<String>,
    pub native_active_session_evidence_ref: String,
    pub started_at: String,
    pub completed_at: String,
    pub next_cycle_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TokenHandoffRequest {
    pub event_id: String,
    pub message_id: String,
    pub run_id: String,
    pub go_id: String,
    pub cell_id: String,
    pub token_sequence: u64,
    pub from_role_instance_id: String,
    pub to_role_instance_id: String,
    pub endpoint_version: u32,
    pub payload_type: String,
    pub payload_sha256: String,
    pub payload_location: Option<String>,
    pub occurred_at: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum NativeStartStatus {
    Started,
}

impl NativeStartStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Started => "STARTED",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeliveryStartEvidence {
    pub evidence_id: String,
    pub stored_path: String,
    pub sha256: String,
    pub message_id: String,
    pub endpoint_sha256: String,
    pub envelope_sha256: String,
    pub native_status: NativeStartStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommitDeliveryStartRequest {
    pub event_id: String,
    pub transport_receipt_id: String,
    pub run_id: String,
    pub go_id: String,
    pub cell_id: String,
    pub attempt: u32,
    pub plan_revision: u32,
    pub expected_runtime_revision: u64,
    pub message_id: String,
    pub token_sequence: u64,
    pub from_role_instance_id: String,
    pub to_role_instance_id: String,
    pub endpoint_version: u32,
    pub payload_type: String,
    pub payload_sha256: String,
    pub start_evidence: DeliveryStartEvidence,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeSnapshot {
    pub run_id: String,
    pub runtime_revision: u64,
    pub plan_revision: u32,
    pub token_sequence: u64,
    pub token_holder_role_instance_id: String,
    pub latest_event_id: String,
    pub latest_message_id: Option<String>,
    pub method_version: String,
    pub overwatcher_binding_revision: Option<u64>,
    pub overwatcher_status: Option<String>,
    pub committed_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationalObservationRequest {
    pub observation_id: String,
    pub run_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub attempt: Option<u32>,
    pub plan_revision: u32,
    pub role_instance_id: String,
    pub kind: ObservationKind,
    pub related_event_id: Option<String>,
    pub message_id: Option<String>,
    pub evidence_refs: Vec<String>,
    pub details: Value,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CloseOverwatcherRequest {
    pub event_id: String,
    pub run_id: String,
    pub archive_evidence_ref: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RevisePlanRequest {
    pub event_id: String,
    pub run_id: String,
    pub snapshot: Value,
    pub reason: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplaceRoleRequest {
    pub event_id: String,
    pub run_id: String,
    pub old_role_instance_id: String,
    pub replacement: RoleIdentity,
    pub endpoint: EndpointIdentity,
    pub reason: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RebindSessionRequest {
    pub event_id: String,
    pub run_id: String,
    pub role_instance_id: String,
    pub endpoint: EndpointIdentity,
    pub reason: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OwnerDecision {
    ApproveRunIdentityReconciliation,
    ApproveMethodContractAdoption,
    ApproveReconciliationAndAdoption,
}

impl OwnerDecision {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ApproveRunIdentityReconciliation => "APPROVE_RUN_IDENTITY_RECONCILIATION",
            Self::ApproveMethodContractAdoption => "APPROVE_METHOD_CONTRACT_ADOPTION",
            Self::ApproveReconciliationAndAdoption => "APPROVE_RECONCILIATION_AND_ADOPTION",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OwnerAuthorizationEvidence {
    pub source_thread_id: String,
    pub message_id: String,
    pub content_sha256: String,
    pub decision: OwnerDecision,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunStateSnapshot {
    pub run_id: String,
    pub project_id: String,
    pub slk_version: String,
    pub state: String,
    pub closure_state: String,
    pub archived_at: Option<String>,
    pub superseded_by_run_id: Option<String>,
    pub predecessor_run_id: Option<String>,
    pub event_count: u64,
    pub latest_event_id: String,
    pub token_sequence: u64,
    pub token_holder_role_instance_id: String,
    pub role_count: u64,
    pub evidence_count: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReconcileRunIdentitiesRequest {
    pub receipt_id: String,
    pub canonical_run_id: String,
    pub canonical_snapshot: RunStateSnapshot,
    pub source_snapshots: Vec<RunStateSnapshot>,
    pub owner_authorization: OwnerAuthorizationEvidence,
    pub reason: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PreservedAssertion {
    Preserved,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OverwatcherAssertion {
    Absent,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MethodCompatibilityAssertions {
    pub topology: PreservedAssertion,
    pub role_bindings: PreservedAssertion,
    pub token: PreservedAssertion,
    pub engineering_history: PreservedAssertion,
    pub overwatcher: OverwatcherAssertion,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdoptMethodContractRequest {
    pub receipt_id: String,
    pub run_id: String,
    pub expected_snapshot: RunStateSnapshot,
    pub from_version: String,
    pub to_version: String,
    pub owner_authorization: OwnerAuthorizationEvidence,
    #[serde(default)]
    pub reconciliation_receipt_id: Option<String>,
    pub compatibility: MethodCompatibilityAssertions,
    pub reason: String,
    pub occurred_at: String,
}
