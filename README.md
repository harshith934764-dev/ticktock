# Tick Tock — Supabase PostgreSQL Production Build

This build is prepared to use **Supabase PostgreSQL** when the Render environment variable `DATABASE_URL` is present. SQLite is retained only as a local-development fallback.

## Production setup
1. Create the Supabase PostgreSQL project.
2. Use the Supabase **Session pooler** connection string for the hosted Flask service.
3. In Render, add `DATABASE_URL` with that connection string. **Never commit it to GitHub or send it in chat.**
4. Deploy. Tick Tock will create its required PostgreSQL tables automatically.
5. Because the old SQLite data is intentionally being left behind, the new Supabase database starts clean.

Existing application features and Google Sign-In are preserved.
