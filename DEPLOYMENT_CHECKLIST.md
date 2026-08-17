# Streamlit deployment checklist

## Target platform

Recommended target: Streamlit Community Cloud.

The repository should contain `requirements.txt` at the repository root and the entrypoint should be `src/app.py`. Streamlit Community Cloud supports an entrypoint in a subdirectory while keeping `requirements.txt` at the root.

## Before publishing

- [ ] Confirm `requirements.txt` is present at the repository root.
- [ ] Confirm `src/app.py`, `src/database.py`, and `src/recommender.py` are committed.
- [ ] Confirm `data/mrs.db` and the required seed data are included for the demonstration.
- [ ] Confirm `.streamlit/secrets.toml` is not committed.
- [ ] Create a unique production admin key.
- [ ] Replace the placeholder value in `.streamlit/secrets.toml.example` locally when preparing deployment settings.
- [ ] Decide whether the deployed app will use the included SQLite demonstration database or a persistent hosted database.

## Streamlit Community Cloud steps

1. Create or select a GitHub repository containing this project.
2. Push the Assessment 3 project files to the repository.
3. Open Streamlit Community Cloud and choose **Create app**.
4. Select the GitHub repository, branch, and entrypoint `src/app.py`.
5. Open **Advanced settings** and select a supported Python version.
6. Paste the contents of the real secrets file into the Secrets field:

   ```toml
   ADMIN_KEY = "your-unique-production-key"
   ```

7. Deploy the app and wait for the build to complete.
8. Open the generated `streamlit.app` URL in a private browser window.
9. Test registration, sign-in, search, rating, dashboard, admin-key access, CRUD, and analytics.
10. Record the public URL in the submission document.

## Deployment caveat

SQLite is suitable for this assessment demonstration, but hosted app files may be reset when the app restarts or redeploys. A hosted database should be used if ratings and catalogue changes must persist permanently.

## Rollback plan

If the deployed app fails, revert to the last working GitHub commit and redeploy. Keep the local working database and source files unchanged until the public smoke test passes.

## Evidence required for the assessment

- Public application URL.
- Three-to-five sentence deployment summary.
- Screenshot showing the public app loading.
- Screenshot showing a user journey on the public app.
- Screenshot showing the admin console and engagement analytics.
