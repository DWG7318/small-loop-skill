import { MESSAGE_CATALOG } from "../messages/catalog";
import { projectAuthoritativeMessages } from "../messages/messageFeed";
import { runFixture, twoRunFixture } from "../test/fixtures";
import type { WebBiArchiveRecord } from "./worker";
import type { WebBiApi } from "./webApi";

const device = { device_id: "PC-DWG-01", device_name: "工作电脑 A" };

function withOverwatcher(run: typeof runFixture) {
  return {
    ...run,
    roles: [
      ...run.roles,
      {
        ...run.roles[0]!,
        role: "overwatcher" as const,
        role_instance_id: "overwatcher-a",
        agent_runtime: "LCaS",
        model: "gpt-6-luna",
        reasoning: "high",
        session_id: "overwatcher-session-a",
      },
    ],
  };
}

function record(run = runFixture): WebBiArchiveRecord {
  return {
    device,
    run,
    messages: projectAuthoritativeMessages(run, MESSAGE_CATALOG),
    updated_at: "2026-10-04T00:00:00Z",
  };
}

export const webBiFixtureApi: WebBiApi = {
  listRuns: async (archived) => twoRunFixture.runDetails
    .filter((run) => Boolean(run.summary.archived_at) === archived)
    .map((run) => record(withOverwatcher(run))),
  getRun: async (_deviceId, runId) => {
    const run = twoRunFixture.runDetails.find((candidate) => candidate.run_id === runId);
    if (!run) throw new Error("SLK_WEBBI_RUN_NOT_FOUND");
    return record(withOverwatcher(run));
  },
  catalog: async () => MESSAGE_CATALOG,
  getNotificationSettings: async () => ({
    enabled: false,
    server_url: "https://ntfy.lcsp.work",
    topic: "slk-owner",
    auth_mode: "none",
    username: null,
    has_secret: false,
    selection_mode: "selected",
    selected_message_types: ["EVENT:D1_FAILED", "OW_OBSERVATION:ACTIVITY_UNPROVEN"],
    config_version: 1,
  }),
  saveNotificationSettings: async (input) => ({
    ...input,
    username: input.username ?? null,
    has_secret: Boolean(input.secret),
    config_version: 2,
  }),
  testNotification: async () => undefined,
};
