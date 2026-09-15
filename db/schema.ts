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

export const browserLikeEvents = sqliteTable("browser_like_events", {
  eventId: text("event_id").primaryKey(),
  accountUsername: text("account_username").notNull(),
  shortcode: text("shortcode").notNull(),
  status: text("status").notNull(),
  likedAt: text("liked_at"),
  observedAt: text("observed_at").notNull(),
  groupsJson: text("groups_json").notNull().default("[]"),
  metadataJson: text("metadata_json").notNull().default("{}"),
}, (table) => [uniqueIndex("browser_like_events_account_post_idx").on(table.accountUsername, table.shortcode)]);

export const instagramManualAgent = sqliteTable("instagram_manual_agent", {
  accountUsername: text("account_username").primaryKey(),
  lastSeen: integer("last_seen").notNull(),
});
export const instagramManualLikes = sqliteTable("instagram_manual_likes", {
  id: text("id").primaryKey(),
  accountUsername: text("account_username").notNull(),
  shortcode: text("shortcode").notNull(),
  requestedBy: text("requested_by").notNull(),
  status: text("status").notNull(),
  requestedAt: integer("requested_at").notNull(),
  finishedAt: integer("finished_at"),
  message: text("message").notNull().default(""),
}, table => [
  uniqueIndex("instagram_manual_likes_one_active_post").on(table.accountUsername, table.shortcode)
    .where(sql`${table.status} IN ('pending', 'executing')`),
  uniqueIndex("instagram_manual_likes_one_executing_account").on(table.accountUsername)
    .where(sql`${table.status} = 'executing'`),
]);

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

export const followerEvents = sqliteTable("follower_events", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  externalId: text("external_id").notNull(),
  username: text("username").notNull(),
  eventType: text("event_type").notNull(),
  batchId: text("batch_id").notNull(),
  detectedAt: text("detected_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => [
  uniqueIndex("follower_events_target_type_batch_idx").on(table.externalId, table.eventType, table.batchId),
]);

export const relationImports = sqliteTable("relation_imports", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  batchId: text("batch_id").notNull().unique(),
  followersCount: integer("followers_count").notNull(),
  followingCount: integer("following_count").notNull(),
  importedAt: text("imported_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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
  followerCount: integer("follower_count"),
  followingCount: integer("following_count"),
  mediaCount: integer("media_count"),
  isPrivate: integer("is_private", { mode: "boolean" }),
  lastPostAt: text("last_post_at"),
  activityScore: integer("activity_score"),
  italianSignal: integer("italian_signal", { mode: "boolean" }),
  femaleSelfDeclared: integer("female_self_declared", { mode: "boolean" }),
  followsYou: integer("follows_you", { mode: "boolean" }),
  youFollow: integer("you_follow", { mode: "boolean" }),
  previousFollowsYou: integer("previous_follows_you", { mode: "boolean" }),
  relationBatch: text("relation_batch"),
  unfollowedYouAt: text("unfollowed_you_at"),
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

export const plannerExclusions = sqliteTable("planner_exclusions", {
  externalId: text("external_id").notNull(),
  actionKind: text("action_kind").notNull(),
  reason: text("reason").notNull().default("saltato dall’utente"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => [
  uniqueIndex("planner_exclusions_target_kind_idx").on(table.externalId, table.actionKind),
]);

export const plannerSettings = sqliteTable("planner_settings", {
  id: integer("id").primaryKey(),
  followsPerDay: integer("follows_per_day").notNull().default(12),
  commentsPerDay: integer("comments_per_day").notNull().default(0),
  unfollowsPerDay: integer("unfollows_per_day").notNull().default(1000),
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
