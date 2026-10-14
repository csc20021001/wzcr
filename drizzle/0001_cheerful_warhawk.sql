CREATE INDEX `idx_listings_university_id` ON `listings` (`university_id`);--> statement-breakpoint
CREATE INDEX `idx_reviews_listing_created` ON `reviews` (`listing_id`,`created_at`);