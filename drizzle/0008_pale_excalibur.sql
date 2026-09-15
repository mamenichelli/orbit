CREATE TABLE `instagram_manual_agent` (
	`account_username` text PRIMARY KEY NOT NULL,
	`last_seen` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `instagram_manual_likes` (
	`id` text PRIMARY KEY NOT NULL,
	`account_username` text NOT NULL,
	`shortcode` text NOT NULL,
	`requested_by` text NOT NULL,
	`status` text NOT NULL,
	`requested_at` integer NOT NULL,
	`finished_at` integer,
	`message` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `instagram_manual_likes_one_active_account` ON `instagram_manual_likes` (`account_username`) WHERE "instagram_manual_likes"."status" IN ('pending', 'executing');