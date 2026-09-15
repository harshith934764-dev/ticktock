# Tick Tock — Supabase PostgreSQL Production Build

This build is prepared to use **Supabase PostgreSQL** when the Render environment variable `DATABASE_URL` is present. SQLite is retained only as a local-development fallback.

## Production setup
1. Create the Supabase PostgreSQL project.
2. Use the Supabase **Session pooler** connection string for the hosted Flask service.
3. In Render, add `DATABASE_URL` with that connection string. **Never commit it to GitHub or send it in chat.**
4. Deploy. Tick Tock will create its required PostgreSQL tables automatically.
5. Because the old SQLite data is intentionally being left behind, the new Supabase database starts clean.

Existing application features and Google Sign-In are preserved.


## Supabase Storage
Create public buckets named `videos` and `avatars`. Add `SUPABASE_SERVICE_ROLE_KEY` in Render. `SUPABASE_URL` is optional when DATABASE_URL uses a normal Supabase pooler username because the app can derive the project URL. Never expose the service-role key to the browser or commit it to GitHub.
