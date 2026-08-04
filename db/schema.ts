import { sql } from "drizzle-orm";
import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

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
