CREATE TABLE `instagram_collection` (
	`account_username` text PRIMARY KEY NOT NULL,
	`requested_at` integer DEFAULT 0 NOT NULL,
	`started_request_at` integer DEFAULT 0 NOT NULL,
	`completed_request_at` integer DEFAULT 0 NOT NULL,
	`started_at` integer DEFAULT 0 NOT NULL,
	`completed_at` integer DEFAULT 0 NOT NULL,
	`last_seen` integer DEFAULT 0 NOT NULL,
	`error` text DEFAULT '' NOT NULL
);
