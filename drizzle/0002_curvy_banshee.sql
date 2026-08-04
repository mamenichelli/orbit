CREATE TABLE `relationship_candidates` (
	`external_id` text PRIMARY KEY NOT NULL,
	`display_name` text NOT NULL,
	`platform` text NOT NULL,
	`score` integer DEFAULT 0 NOT NULL,
	`last_interaction` text,
	`follows_you` integer,
	`you_follow` integer,
	`last_seen_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE TABLE `review_state` (
	`id` integer PRIMARY KEY NOT NULL,
	`last_run` text,
	`next_run` text NOT NULL
);
