CREATE TABLE `browser_like_events` (
	`event_id` text PRIMARY KEY NOT NULL,
	`account_username` text NOT NULL,
	`shortcode` text NOT NULL,
	`status` text NOT NULL,
	`liked_at` text,
	`observed_at` text NOT NULL,
	`groups_json` text DEFAULT '[]' NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `browser_like_events_account_post_idx` ON `browser_like_events` (`account_username`,`shortcode`);