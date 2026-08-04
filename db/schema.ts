import { sql } from "drizzle-orm";
import { integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const protectedProfiles = sqliteTable("protected_profiles", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  externalId: text("external_id").notNull().unique(),
  displayName: text("display_name").notNull(),
  platform: text("platform").notNull(),
  reason: text("reason").notNull().default("contatto personale"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const actionQueue = sqliteTable("action_queue", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  externalId: text("external_id").notNull(),
  actionType: text("action_type").notNull(),
  status: text("status").notNull().default("approved"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const auditEvents = sqliteTable("audit_events", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  eventType: text("event_type").notNull(),
  payload: text("payload").notNull().default("{}"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const relationshipCandidates = sqliteTable("relationship_candidates", {
  externalId: text("external_id").primaryKey(),
  displayName: text("display_name").notNull(),
  platform: text("platform").notNull(),
  score: integer("score").notNull().default(0),
  lastInteraction: text("last_interaction"),
  followsYou: integer("follows_you", { mode: "boolean" }),
  youFollow: integer("you_follow", { mode: "boolean" }),
  lastSeenAt: text("last_seen_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const reviewState = sqliteTable("review_state", {
  id: integer("id").primaryKey(),
  lastRun: text("last_run"),
  nextRun: text("next_run").notNull(),
});

export const growthTargets = sqliteTable("growth_targets", {
  externalId: text("external_id").primaryKey(),
  username: text("username").notNull().unique(),
  displayName: text("display_name").notNull(),
  platform: text("platform").notNull().default("Instagram"),
  profileUrl: text("profile_url"),
  source: text("source").notNull().default("organic_interaction"),
  sourceDetail: text("source_detail"),
  interactions: integer("interactions").notNull().default(0),
  score: integer("score").notNull().default(0),
  followsYou: integer("follows_you", { mode: "boolean" }),
  youFollow: integer("you_follow", { mode: "boolean" }),
  firstSeenAt: text("first_seen_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  lastInteraction: text("last_interaction"),
  followedAt: text("followed_at"),
  reviewAfter: text("review_after"),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const dailyActions = sqliteTable("daily_actions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  actionDate: text("action_date").notNull(),
  externalId: text("external_id").notNull(),
  actionType: text("action_type").notNull(),
  probability: integer("probability").notNull().default(0),
  reason: text("reason").notNull(),
  status: text("status").notNull().default("pending"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  completedAt: text("completed_at"),
}, (table) => [
  uniqueIndex("daily_actions_date_target_type_idx").on(table.actionDate, table.externalId, table.actionType),
]);

export const plannerSettings = sqliteTable("planner_settings", {
  id: integer("id").primaryKey(),
  followsPerDay: integer("follows_per_day").notNull().default(12),
  commentsPerDay: integer("comments_per_day").notNull().default(10),
  unfollowsPerDay: integer("unfollows_per_day").notNull().default(8),
  reviewDays: integer("review_days").notNull().default(10),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const socialAccounts = sqliteTable("social_accounts", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  platform: text("platform").notNull(),
  externalId: text("external_id").notNull().unique(),
  displayName: text("display_name").notNull(),
  username: text("username"),
  pageId: text("page_id"),
  tokenCiphertext: text("token_ciphertext").notNull(),
  tokenIv: text("token_iv").notNull(),
  status: text("status").notNull().default("connected"),
  connectedAt: text("connected_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});
