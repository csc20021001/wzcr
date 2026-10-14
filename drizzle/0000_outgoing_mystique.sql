CREATE TABLE `listings` (
	`id` text PRIMARY KEY NOT NULL,
	`university_id` text NOT NULL,
	`title` text NOT NULL,
	`address` text NOT NULL,
	`monthly_rent` integer NOT NULL,
	`room_type` text NOT NULL,
	`area_ping` real NOT NULL,
	`walk_minutes` integer NOT NULL,
	`latitude` real NOT NULL,
	`longitude` real NOT NULL,
	`highlights` text NOT NULL,
	`featured` integer DEFAULT false NOT NULL,
	`seed_rating` real DEFAULT 0 NOT NULL,
	`seed_review_count` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`university_id`) REFERENCES `universities`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `reviews` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`listing_id` text NOT NULL,
	`author_name` text NOT NULL,
	`rating` integer NOT NULL,
	`content` text NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`listing_id`) REFERENCES `listings`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `universities` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`short_name` text NOT NULL,
	`city` text NOT NULL,
	`district` text NOT NULL,
	`latitude` real NOT NULL,
	`longitude` real NOT NULL,
	`address` text NOT NULL
);
