CREATE TABLE `users` (
	`id` text PRIMARY KEY NOT NULL,
	`google_sub` text NOT NULL,
	`email` text NOT NULL,
	`name` text NOT NULL,
	`avatar_url` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_users_google_sub` ON `users` (`google_sub`);
--> statement-breakpoint
CREATE INDEX `idx_users_email` ON `users` (`email`);
--> statement-breakpoint
CREATE TABLE `auth_sessions` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`expires_at` text NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_auth_sessions_user_expires` ON `auth_sessions` (`user_id`,`expires_at`);
--> statement-breakpoint
DROP TABLE IF EXISTS `reviews`;
--> statement-breakpoint
DROP TABLE IF EXISTS `listings`;
--> statement-breakpoint
CREATE TABLE `listings` (
	`id` text PRIMARY KEY NOT NULL,
	`university_id` text NOT NULL,
	`owner_user_id` text NOT NULL,
	`title` text NOT NULL,
	`address` text NOT NULL,
	`description` text NOT NULL,
	`monthly_rent` integer NOT NULL,
	`room_type` text NOT NULL,
	`area_ping` real NOT NULL,
	`walk_minutes` integer NOT NULL,
	`latitude` real NOT NULL,
	`longitude` real NOT NULL,
	`highlights` text NOT NULL,
	`contact_method` text NOT NULL,
	`contact_value` text NOT NULL,
	`status` text DEFAULT 'published' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`university_id`) REFERENCES `universities`(`id`) ON UPDATE no action ON DELETE restrict,
	FOREIGN KEY (`owner_user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE restrict
);
--> statement-breakpoint
CREATE INDEX `idx_listings_university_status` ON `listings` (`university_id`,`status`);
--> statement-breakpoint
CREATE INDEX `idx_listings_owner_created` ON `listings` (`owner_user_id`,`created_at`);
--> statement-breakpoint
CREATE TABLE `reviews` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`listing_id` text NOT NULL,
	`author_name` text NOT NULL,
	`rating` integer NOT NULL CHECK (`rating` BETWEEN 1 AND 5),
	`content` text NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`listing_id`) REFERENCES `listings`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_reviews_listing_created` ON `reviews` (`listing_id`,`created_at`);
--> statement-breakpoint
PRAGMA optimize;
