//! Closed request and identity types shared by state writers and readers.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Supervisor,
    Checker,
    Worker,
}

impl Role {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Supervisor => "supervisor",
            Self::Checker => "checker",
            Self::Worker => "worker",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "supervisor" => Some(Self::Supervisor),
            "checker" => Some(Self::Checker),
            "worker" => Some(Self::Worker),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EventType {
    RunInitialized,
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
}

impl EventType {
    pub fn is_owned_by(self, role: Role) -> bool {
        use EventType::*;
        match self {
            RunInitialized | PlanRevised | ModelChanged | SessionRebound | ExemptionGranted
            | D2Started | D2Passed | D2Failed | RunSuperseded | RunAbandoned | RunClosed => {
                role == Role::Supervisor
            }
            RoleRegistered | RoleReplaced => role == Role::Supervisor || role == Role::Checker,
            CellDispatched | D1Started | D1Passed | D1Failed | ReworkRequested | CellSplit
            | CandidateForwarded => role == Role::Checker,
            WorkStarted | WorkProgress | BlockerReported | ChangeRecorded | D0Completed
            | CandidateSubmitted => role == Role::Worker,
            ResourceContended | ResourceRecovered | TokenHandedOff | TransportFailed
            | EvidenceRegistered => true,
        }
    }

    pub fn as_str(self) -> &'static str {
        use EventType::*;
        match self {
            RunInitialized => "RUN_INITIALIZED",
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
