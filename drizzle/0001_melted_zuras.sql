CREATE TABLE `social_accounts` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`platform` text NOT NULL,
	`external_id` text NOT NULL,
	`display_name` text NOT NULL,
	`username` text,
	`page_id` text,
	`token_ciphertext` text NOT NULL,
	`token_iv` text NOT NULL,
	`status` text DEFAULT 'connected' NOT NULL,
	`connected_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `social_accounts_external_id_unique` ON `social_accounts` (`external_id`);