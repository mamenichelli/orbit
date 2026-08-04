CREATE TABLE `follower_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`external_id` text NOT NULL,
	`username` text NOT NULL,
	`event_type` text NOT NULL,
	`batch_id` text NOT NULL,
	`detected_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `follower_events_target_type_batch_idx` ON `follower_events` (`external_id`,`event_type`,`batch_id`);--> statement-breakpoint
CREATE TABLE `relation_imports` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`batch_id` text NOT NULL,
	`followers_count` integer NOT NULL,
	`following_count` integer NOT NULL,
	`imported_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `relation_imports_batch_id_unique` ON `relation_imports` (`batch_id`);--> statement-breakpoint
ALTER TABLE `growth_targets` ADD `previous_follows_you` integer;--> statement-breakpoint
ALTER TABLE `growth_targets` ADD `relation_batch` text;--> statement-breakpoint
ALTER TABLE `growth_targets` ADD `unfollowed_you_at` text;