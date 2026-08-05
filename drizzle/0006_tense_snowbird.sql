CREATE TABLE `planner_exclusions` (
	`external_id` text NOT NULL,
	`action_kind` text NOT NULL,
	`reason` text DEFAULT 'saltato dall’utente' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `planner_exclusions_target_kind_idx` ON `planner_exclusions` (`external_id`,`action_kind`);--> statement-breakpoint
PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_planner_settings` (
	`id` integer PRIMARY KEY NOT NULL,
	`follows_per_day` integer DEFAULT 12 NOT NULL,
	`comments_per_day` integer DEFAULT 0 NOT NULL,
	`unfollows_per_day` integer DEFAULT 1000 NOT NULL,
	`review_days` integer DEFAULT 10 NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
INSERT INTO `__new_planner_settings`("id", "follows_per_day", "comments_per_day", "unfollows_per_day", "review_days", "updated_at") SELECT "id", "follows_per_day", "comments_per_day", "unfollows_per_day", "review_days", "updated_at" FROM `planner_settings`;--> statement-breakpoint
DROP TABLE `planner_settings`;--> statement-breakpoint
ALTER TABLE `__new_planner_settings` RENAME TO `planner_settings`;--> statement-breakpoint
PRAGMA foreign_keys=ON;
