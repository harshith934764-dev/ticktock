# Tick Tock — Production Security Update

This package is based on the working Tick Tock build. It preserves the existing SQLite schema/data and adds production-oriented protections without resetting the database.

## Included
- Secure session-cookie settings for HTTPS production.
- Cross-site Origin/Referer checks for state-changing browser requests.
- Lightweight rate limits for login, registration, OTP, password reset, and uploads.
- Safer upload validation with size, extension/MIME, and basic video signature checks.
- Security response headers.
- Safe database indexes created with `IF NOT EXISTS`; no rows are deleted.
- Existing Google Sign-In and Home functionality retained.

## Required Render environment variable
Set a strong random `SECRET_KEY` in Render Environment Variables. Keep Google, Resend, and Razorpay secrets only in Render Environment Variables; never commit them to GitHub.

## Important
This hardening is one production layer, not a complete security audit. Before public launch, add persistent storage/backups, centralized rate limiting/WAF as traffic grows, admin moderation, privacy/terms, account deletion, monitoring, and a proper persistent database/media architecture.
