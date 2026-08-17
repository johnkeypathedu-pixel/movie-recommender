# ITS74004 Assessment 3
## AI-Powered Movie Recommendation System

**Student:** [Insert name]  
**Student ID:** [Insert student ID]  
**Deployed application URL:** https://movie-recommender-john-loh.streamlit.app/

## 1. System overview

The Movie Recommendation System (MRS) is a Streamlit application that uses a movie catalogue, user ratings, and viewing activity to produce personalised recommendations. It also provides dashboard insights about recommended movies, popular genres, watch history, ratings, and user engagement. Administrators can manage the movie catalogue and review engagement analytics through a protected console.

The application uses SQLite for local persistence, pandas and Plotly for data analysis and visualisation, and a hybrid recommendation engine using content-based filtering and collaborative filtering.

## 2. Question 1.A — System design

### Task 1.1 — UML class diagram

The complete UML design is provided in [PartA_Q1_Design.md](../Q1_Design/PartA_Q1_Design.md). It models the following classes:

- `Person`: shared identity and authentication behaviour.
- `User`: registered viewer with preferences, ratings, and watch history.
- `Admin`: privileged user with catalogue and analytics permissions.
- `Movie`: catalogue item with title, genres, release information, and aggregate ratings.
- `Rating`: a user's score for a movie.
- `WatchHistory`: a user's viewing event and completion percentage.
- `RecommendationEngine`: service that analyses behaviour and ranks recommendations.

The UML diagram shows inheritance from `Person` to `User` and `Admin`, relationships between users, movies, ratings, and watch history, and dependencies from the recommendation engine to the behavioural data.

### Task 1.2 — Attributes and methods

The attributes and methods are described with their purpose and rationale in [PartA_Q1_Design.md](../Q1_Design/PartA_Q1_Design.md). The design separates a movie's aggregate rating from an individual user's rating and represents watch history explicitly because both are required recommendation signals and dashboard outputs.

### Task 1.3 — Recommendation logic and data analysis

The system analyses explicit feedback, such as ratings, and implicit feedback, such as completed or abandoned viewing sessions. Highly rated and highly completed movies contribute to a user's inferred genre preferences. Movies already rated by the user are filtered out, and remaining candidates are scored and ranked.

For users with limited ratings, the system uses content-based filtering by comparing genre features. For users with sufficient ratings, it combines collaborative filtering and content-based filtering. The hybrid score is used to rank the final recommendations. New ratings refresh the recommendation engine so that subsequent dashboard views reflect the user's latest activity.

## 3. Question 2.A — Interface design

The application is implemented as a Streamlit GUI. The sidebar provides navigation between Sign in, Search & rate, User dashboard, and Admin console. User data and catalogue data are stored in SQLite, while pandas and Plotly support dashboard analysis.

### Demonstration login credentials

Include these credentials in the final submission so the lecturer can test the application:

- **User account:** username `alice`, password `Demo1234!`
- **Administrator account:** username `admin`, password `AdminPass!23`
- **Administrator key:** *(unique value set — see the submitted Word document; deliberately not recorded here since this repository is public)*

Do not include a production secret in the document. Use a dedicated demonstration key for marking.

### Task 2.1 — Search, rating, and recommendations

The Search & rate page allows a signed-in user to:

1. Search for movies by title.
2. Filter and sort catalogue results.
3. Select a movie and submit a rating from 0.5 to 5.0.
4. Record watch completion and device information.
5. View refreshed recommendations after saving a rating.

**Evidence to insert:**

- Existing: `screenshots/01_signin.png` — initial sign-in page.
- Existing: `screenshots/01b_signin_filled.png` — sign-in form with demo credentials entered.
- To capture: signed-in Search & rate page.
- To capture: movie search results.
- To capture: rating saved and recommendations displayed.

### Task 2.2 — Registered-user dashboard

The User dashboard provides the four required features:

- Top recommendations based on the user's ratings and inferred preferences.
- Trending movies and popular genres.
- The user's watch history and rating log.
- Data visualisations for genre preferences, ratings, and engagement trends.

**Evidence to insert:**

- To capture: dashboard recommendations.
- To capture: trending movies and popular genres.
- To capture: watch history and ratings log.
- To capture: dashboard charts.

### Task 2.3 — Administrator console

The administrator console is separated from the user pages. Access requires an administrator account and the unique `ADMIN_KEY`. The console provides:

- Add movie.
- Edit movie details.
- Remove a movie from the catalogue.
- View registered users.
- Analyse most-watched movies, genre popularity, and engagement trends.

For the final submission, describe the configured admin key without exposing a production secret. Use a temporary demonstration key in screenshots if required.

**Evidence to insert:**

- To capture: admin key prompt.
- To capture: catalogue management.
- To capture: add, edit, and remove movie workflow.
- To capture: engagement analytics.

### Task 2.4 — Streamlit deployment

**Deployed application URL:** https://movie-recommender-john-loh.streamlit.app/

The application is deployed on Streamlit Community Cloud, connected to the GitHub repository `johnkeypathedu-pixel/movie-recommender` on the `main` branch with entrypoint `src/app.py`, while `requirements.txt` (Streamlit, pandas, NumPy, scikit-learn, Plotly, requests) is kept at the repository root as Streamlit Cloud requires. Deployment secrets (`ADMIN_KEY` and `MRS_DB`) are configured in the app's Secrets panel rather than committed to the repository; `MRS_DB` points the app at a writable runtime copy of the SQLite database (`/tmp/mrs.db`), seeded on first boot from the committed `data/mrs.db`, since Streamlit Cloud's filesystem is read-only outside `/tmp`. During debugging, the deployed app was crashing with a generic "Error running app" whenever a user opened Search & rate or the Dashboard; the server logs showed a clean boot with no Python traceback, which pointed to the container being killed for exceeding its memory limit rather than a code exception. Profiling `RecommendationEngine.refresh()` locally confirmed this: it was eagerly building two dense 9,742 × 9,742 item-similarity matrices (content-based and collaborative) over the full MovieLens catalogue, peaking at over 2.1 GiB of RAM in a single call. The engine was refactored to compute similarity one row at a time, on demand, for only the handful of movies a given user has actually rated, which dropped peak memory to about 11 MiB with identical recommendation output, and the app was redeployed and re-verified end-to-end (sign-in, search, rating, dashboard charts, and the admin console) after the fix.

The `ADMIN_KEY` secret has been rotated from the codebase's fallback default to a unique production value, confirmed working against the live app. The value itself is recorded only in the submitted Word document and Streamlit's encrypted secrets store, not in this public repository.

## 4. Testing evidence

Local testing was performed using a writable copy of the SQLite database because the OneDrive database directory restricts SQLite write operations.

The following behaviours were verified:

- The application launched successfully.
- The recommendation engine loaded the movie catalogue and ratings.
- User sign-in worked.
- Movie rating and watch completion were saved.
- User recommendations were generated.
- The dashboard displayed recommendations, trends, watch history, ratings, and preference data.
- Incorrect admin keys were rejected.
- Correct admin keys unlocked catalogue management and engagement analytics.

The interactive checks used a temporary writable database copy located outside OneDrive. The production project database was not modified during testing. The database-copy workaround should be mentioned in the technical notes only if required; it is not part of the user-facing application journey.

## 5. Evidence matrix

| Rubric item | Evidence source | Status |
|---|---|---|
| Q1.1 UML diagram | `Q1_Design/PartA_Q1_Design.md` | Complete |
| Q1.2 attributes and methods | `Q1_Design/PartA_Q1_Design.md` | Complete |
| Q1.3 recommendation logic | `Q1_Design/PartA_Q1_Design.md` | Complete |
| Q2.1 search and rating | App plus manual screenshots | Screenshots required |
| Q2.2 dashboard | App plus four dashboard screenshots | Screenshots required |
| Q2.3 admin console | App plus admin-key, CRUD, and analytics screenshots | Screenshots required |
| Q2.4 deployment | Public URL and deployment summary | Deployed and functionally verified end-to-end; needs a unique `ADMIN_KEY` before submission |

## 6. Source-code appendix

The implementation files are located in the `src` folder:

- `app.py` — Streamlit interface and session control.
- `database.py` — SQLite schema and database operations.
- `recommender.py` — hybrid recommendation engine.
- `seed_data.py` — MovieLens data import and demo account creation.
- `capture_screenshots.py` — optional automated screenshot helper.

## 7. Final submission checklist

- [ ] Insert student details.
- [ ] Insert UML diagram into the final document.
- [ ] Insert screenshots for every required user journey.
- [ ] Confirm add, edit, and remove movie actions work.
- [ ] Configure a secure deployment `ADMIN_KEY`.
- [ ] Deploy the app publicly.
- [ ] Test the public URL in a private browser window.
- [ ] Insert the public URL.
- [ ] Attach or include the source code.
- [ ] Remove temporary credentials and debugging material from the final submission.
