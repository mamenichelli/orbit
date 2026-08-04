CREATE TABLE `daily_actions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`action_date` text NOT NULL,
	`external_id` text NOT NULL,
	`action_type` text NOT NULL,
	`probability` integer DEFAULT 0 NOT NULL,
	`reason` text NOT NULL,
	`status` text DEFAULT 'pending' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`completed_at` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `daily_actions_date_target_type_idx` ON `daily_actions` (`action_date`,`external_id`,`action_type`);--> statement-breakpoint
CREATE TABLE `growth_targets` (
	`external_id` text PRIMARY KEY NOT NULL,
	`username` text NOT NULL,
	`display_name` text NOT NULL,
	`platform` text DEFAULT 'Instagram' NOT NULL,
	`profile_url` text,
	`source` text DEFAULT 'organic_interaction' NOT NULL,
	`source_detail` text,
	`interactions` integer DEFAULT 0 NOT NULL,
	`score` integer DEFAULT 0 NOT NULL,
	`follows_you` integer,
	`you_follow` integer,
	`first_seen_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`last_interaction` text,
	`followed_at` text,
	`review_after` text,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `growth_targets_username_unique` ON `growth_targets` (`username`);--> statement-breakpoint
CREATE TABLE `planner_settings` (
	`id` integer PRIMARY KEY NOT NULL,
	`follows_per_day` integer DEFAULT 12 NOT NULL,
	`comments_per_day` integer DEFAULT 10 NOT NULL,
	`unfollows_per_day` integer DEFAULT 8 NOT NULL,
	`review_days` integer DEFAULT 10 NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
