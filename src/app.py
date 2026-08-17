"""app.py — Streamlit front-end for Your Movie Pal.

Run locally::

    streamlit run app.py

Pages (selected via the sidebar radio):
    • Sign in / register            (default)
    • Search & rate
    • User dashboard                (requires sign-in)
    • Admin console                 (requires admin key from st.secrets)
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import database as db
import recommender as rec
# ---------- config & bootstrap ----------

st.set_page_config(
    page_title="Your Movie Pal",
    page_icon="🎬",
    layout="wide",
)

db.init_schema()  # no-op if schema already exists


# light-weight password hashing (kept here so demo accounts work without
# extra dependencies). Replace with bcrypt/argon2 in production.
def _hash(pw: str) -> str:
    salt = "mrs-static-salt"
    return hashlib.sha256(f"{salt}:{pw}".encode()).hexdigest()


# Demo account helpers
DEMO_USERS = {
    "alice": "Demo1234!",
    "bob": "Demo1234!",
    "charlie": "Demo1234!",
    "dana": "Demo1234!",
    "evan": "Demo1234!",
    "admin": "AdminPass!23",
}


def get_admin_key() -> str:
    """Read the admin key from Streamlit secrets, env var, or a default.

    For local dev only. In production use ``st.secrets["ADMIN_KEY"]``.
    """
    try:
        return st.secrets["ADMIN_KEY"]
    except (KeyError, FileNotFoundError):
        return os.environ.get("ADMIN_KEY", "admin-demo-key")


# ---------- session-state init ----------

DEFAULTS = {
    "logged_in_user": None,        # user dict or None
    "is_admin": False,             # True iff logged in with admin privileges
    "admin_unlocked": False,       # True only after the unique admin key is entered
    "page": "Sign in",
    # engine is initialised lazily on first recommendation request
    "engine_built": False,
}


def _ensure_session() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v


_ensure_session()


def _ensure_engine() -> rec.RecommendationEngine:
    if not st.session_state.engine_built:
        eng = rec.get_engine()
        eng.refresh()
        st.session_state.engine_built = True
    return rec.get_engine()


# ---------- sidebar ----------

def render_sidebar() -> None:
    st.sidebar.title("🎬 Your Movie Pal")
    user = st.session_state.logged_in_user
    if user:
        role = user["role"]
        st.sidebar.markdown(f"**Signed in as**  \n{user['display_name']} ({role.lower()})")
        if st.sidebar.button("Sign out"):
            st.session_state.logged_in_user = None
            st.session_state.is_admin = False
            st.session_state.admin_unlocked = False
            st.session_state.page = "Sign in"
            st.rerun()
    else:
        st.sidebar.markdown("**Not signed in**")

    st.sidebar.divider()
    pages = ["Sign in"]
    if user:
        if st.session_state.is_admin:
            pages += ["Admin console"]
        else:
            pages += ["Search & rate", "User dashboard"]
    # If the previously requested page (e.g. "Search & rate") is no longer in
    # the options (e.g. after sign-out), fall back to the first one.
    if st.session_state.page not in pages:
        st.session_state.page = pages[0]
    # Use ``index`` to align the radio with session state without binding the
    # widget to a key (binding would prevent programmatic updates elsewhere).
    radio_index = pages.index(st.session_state.page)
    choice = st.sidebar.radio("Navigate", pages, index=radio_index)
    st.session_state.page = choice


# ---------- pages ----------

def page_signin() -> None:
    st.title("🎬 Your Movie Pal")

    tab_signin, tab_register = st.tabs(["Sign in", "Register a new account"])

    with tab_signin:
        st.subheader("Sign in")
        col1, col2 = st.columns(2)
        with col1:
            username = st.text_input("Username", key="signin_username").strip().lower()
        with col2:
            password = st.text_input("Password", type="password", key="signin_password")

        if st.button("Sign in", type="primary", key="signin_btn"):
            user = db.find_user_by_username(username)
            if not user or user["password_hash"] != _hash(password):
                st.error("Invalid username or password.")
            else:
                db.touch_last_login(user["user_id"])
                st.session_state.logged_in_user = user
                st.session_state.is_admin = user["role"] == "ADMIN"
                st.session_state.admin_unlocked = False
                target_page = (
                    "Admin console" if user["role"] == "ADMIN" else "Search & rate"
                )
                st.session_state.page = target_page
                st.success(f"Welcome back, {user['display_name']}.")
                st.rerun()

    with tab_register:
        st.subheader("Register")
        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("Username (must be unique)")
            display_name = st.text_input("Display name")
            password = st.text_input("Password", type="password")
            geo = st.text_input("Region code (e.g. MY, SG)", value="MY")
            ok = st.form_submit_button("Create account")
        if ok:
            if not username or not display_name or not password:
                st.error("All fields are required.")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters.")
            elif db.find_user_by_username(username.strip().lower()):
                st.error("That username is already taken.")
            else:
                uid = db.create_user(
                    username.strip().lower(),
                    display_name,
                    _hash(password),
                    role="USER",
                    geo_id=geo.strip().upper(),
                )
                st.success(
                    f"Account '{username}' created (id={uid}). You can sign in now."
                )


def page_search() -> None:
    user = st.session_state.logged_in_user
    if not user:
        st.warning("Please sign in to rate movies and personalise recommendations.")
        st.stop()
    st.title("🔍 Search & rate")

    eng = _ensure_engine()

    cols = st.columns([1, 1, 2])
    with cols[0]:
        search = st.text_input("Title contains", "")
    with cols[1]:
        # Pull distinct genres for filter
        with db.connect() as conn:
            all_genres = conn.execute("SELECT genres FROM movies").fetchall()
        genre_set = sorted({g for row in all_genres for g in (row["genres"] or "").split("|") if g})
        chosen_genre = st.selectbox("Genre filter", ["(any)"] + genre_set)
    with cols[2]:
        sort = st.selectbox(
            "Sort by",
            ["title", "rating", "popularity", "year"],
            index=1,
        )

    search_arg = search if search else None
    genre_arg = None if chosen_genre == "(any)" else chosen_genre

    movies = db.list_movies(limit=200, search=search_arg, genre=genre_arg, sort_by=sort)
    total = db.count_movies(search=search_arg, genre=genre_arg)
    st.caption(f"{total} match{'es' if total != 1 else ''}. Showing first {len(movies)}.")

    # --- rating UI ---
    with st.form("rate_form", clear_on_submit=True):
        if not movies:
            st.info("No movies match — try clearing the filters.")
        else:
            options = [f"{m['title']}  ·  ({m['release_year'] or '—'})  ·  ⭐ {m['average_rating']:.2f} ({m['rating_count']} ratings)" for m in movies]
            chosen = st.selectbox("Pick a movie", options, index=0)
            movie = movies[options.index(chosen)]
            cols2 = st.columns([2, 1])
            with cols2[0]:
                score = st.slider("Your rating", 0.5, 5.0, value=4.0, step=0.5)
            submit = st.form_submit_button("Save rating")
            if submit:
                db.add_rating(user["user_id"], movie["movie_id"], score)
                # A rating indicates that the user watched the movie; record a
                # completed viewing event without exposing a watch-percentage control.
                db.add_watch_event(user["user_id"], movie["movie_id"], 1.0)
                rec.reset_engine()
                st.session_state.engine_built = False
                _ensure_engine()
                st.success(
                    f"Recorded **{movie['title']}** with your rating {score:.1f}."
                )
                st.balloons()

        # --- live recommendations preview ---
    st.divider()
    st.subheader("Recommendations for you (refreshed after each rating)")
    recs = eng.generate_recommendations(user["user_id"], k=8)
    if not recs:
        st.info("Rate a few movies to see recommendations!")
    else:
        cols3 = st.columns(2)
        for i, r in enumerate(recs):
            with cols3[i % 2]:
                st.markdown(
                    f"**{r['title']}**  \n"
                    f"_{r['genres'].replace('|', ' · ')}_"
                )


def page_dashboard() -> None:
    user = st.session_state.logged_in_user
    if not user:
        st.warning("Please sign in.")
        st.stop()

    st.title(f"👋 Hello, {user['display_name']}")

    eng = _ensure_engine()

    # ---- top recommendations ----
    st.subheader("Top picks for you")
    recs = eng.generate_recommendations(user["user_id"], k=10)
    if recs:
        st.markdown(
            "\n".join(
                f"{i}. **{r['title']}** — _{r['genres'].replace('|', ' · ')}_"
                for i, r in enumerate(recs, start=1)
            )
        )
    else:
        st.info("Rate a few movies to start receiving personal recommendations.")

    col1, col2 = st.columns(2)
    with col1:
        # ---- trending / popular genres ----
        st.subheader("Trending & popular genres")
        # Most-watched movies (recent 30 days, but stable for the demo dataset)
        rows = db.most_watched_movies(limit=8, days=None)
        if rows:
            df = pd.DataFrame(rows)
            fig2 = px.bar(
                df.sort_values("watches", ascending=True),
                x="watches",
                y="title",
                orientation="h",
                title="Most-watched movies (catalogue-wide)",
                labels={"watches": "Watch events", "title": "Movie"},
            )
            fig2.update_layout(height=380)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.caption("No watch events yet — watch a movie to populate this.")

        genres = db.genre_popularity()[:8]
        if genres:
            df = pd.DataFrame(genres)
            fig3 = px.bar(
                df.sort_values("movie_count", ascending=True),
                x="movie_count",
                y="genre",
                orientation="h",
                title="Popular genres",
                labels={"movie_count": "", "genre": "Genre"},
            )
            fig3.update_layout(height=320, showlegend=False)
            st.plotly_chart(fig3, use_container_width=True)

    with col2:
        # ---- watch history ----
        st.subheader("Your watch history")
        hist = db.list_history_by_user(user["user_id"], limit=50)
        if hist:
            df = pd.DataFrame(hist)
            df["completion_pct"] = (df["completion_pct"] * 100).round(1)
            st.dataframe(
                df[["title", "watched_at", "device"]].rename(
                    columns={
                        "watched_at": "When",
                        "device": "Device",
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No watch events recorded for your account yet.")

        # ---- ratings log ----
        st.subheader("Your ratings log")
        ratings = db.list_ratings_by_user(user["user_id"], limit=100)
        if ratings:
            df = pd.DataFrame(ratings)
            st.dataframe(
                df[["title", "score", "timestamp"]].rename(
                    columns={"timestamp": "Rated at"}
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No ratings yet — head to **Search & rate** to begin.")

# ---------- admin ----------

def page_admin() -> None:
    st.title("🛠️ Admin console")
    if not st.session_state.is_admin:
        st.error("Administrator account required.")
        st.stop()

    if not st.session_state.admin_unlocked:
        st.warning(
            "**Admin access required.** This panel is gated by the "
            "`ADMIN_KEY` secret. Enter the key below to unlock it."
        )
        key_input = st.text_input("Admin key", type="password")
        if st.button("Unlock"):
            if key_input == get_admin_key():
                st.session_state.admin_unlocked = True
                st.success("Admin console unlocked.")
                st.rerun()
            else:
                st.error("Wrong admin key.")
        st.stop()

    tab_crud, tab_analytics, tab_users = st.tabs(
        ["Manage catalogue", "Engagement analytics", "Users"]
    )

    with tab_crud:
        st.subheader("Movies")
        mode = st.radio("Mode", ["List", "Add new"], horizontal=True, key="admin_mode")
        if mode == "List":
            search = st.text_input("Search title", key="admin_search")
            rows = db.list_movies(limit=200, search=search, sort_by="title")
            df = pd.DataFrame(rows)
            df = df[
                ["movie_id", "title", "release_year", "genres",
                 "average_rating", "rating_count"]
            ].rename(
                columns={
                    "movie_id": "ID",
                    "title": "Title",
                    "release_year": "Year",
                    "genres": "Genres",
                    "average_rating": "Avg ★",
                    "rating_count": "Ratings",
                }
            )
            st.dataframe(df, hide_index=True, use_container_width=True, height=400)

            edit_id = st.number_input(
                "Edit / remove movie ID", min_value=1, value=int(rows[0]["movie_id"]) if rows else 1,
                step=1,
            )
            movie = db.get_movie(int(edit_id))
            if movie:
                with st.form("edit_movie"):
                    st.write(f"Currently editing: **{movie['title']}** (id={movie['movie_id']})")
                    new_title = st.text_input("Title", movie["title"])
                    new_genres = st.text_input("Genres (| separated)", movie["genres"])
                    new_year = st.number_input(
                        "Release year",
                        min_value=1900, max_value=2030,
                        value=int(movie["release_year"]) if movie["release_year"] else 2000,
                    )
                    new_rating = st.text_input(
                        "Content rating (PG/PG-13/R/18+ etc.)",
                        movie["content_rating"] or "",
                    )
                    cols = st.columns(2)
                    save_clicked = cols[0].form_submit_button("Save changes")
                    delete_clicked = cols[1].form_submit_button(
                        "Remove movie", type="secondary"
                    )
                    if save_clicked:
                        db.update_movie(
                            int(edit_id),
                            {
                                "title": new_title,
                                "genres": new_genres,
                                "release_year": int(new_year),
                                "content_rating": new_rating or None,
                            },
                        )
                        rec.reset_engine()
                        st.session_state.engine_built = False
                        st.success("Movie updated. Recommender cache invalidated.")
                    if delete_clicked:
                        db.delete_movie(int(edit_id))
                        rec.reset_engine()
                        st.session_state.engine_built = False
                        st.success(f"Deleted movie id={int(edit_id)}.")
                        st.rerun()
            else:
                st.info("Movie with that ID doesn't exist.")

        else:  # add new
            with st.form("add_movie", clear_on_submit=True):
                st.write("Add a new movie to the catalogue")
                new_id = st.number_input(
                    "Movie ID (new)", min_value=100_000, value=200_000, step=1
                )
                new_title = st.text_input("Title")
                new_genres = st.text_input("Genres (| separated, MovieLens style)")
                new_year = st.number_input(
                    "Release year", min_value=1900, max_value=2030, value=2024
                )
                new_rating = st.text_input("Content rating", "")
                ok = st.form_submit_button("Add")
                if ok:
                    if not new_title or not new_genres:
                        st.error("Title and genres are required.")
                    else:
                        db.upsert_movie(
                            movie_id=int(new_id),
                            title=new_title,
                            genres=new_genres,
                            release_year=int(new_year),
                            content_rating=new_rating or None,
                        )
                        rec.reset_engine()
                        st.session_state.engine_built = False
                        st.success(f"Added '{new_title}' (id={int(new_id)}).")

    with tab_analytics:
        st.subheader("Engagement trends")
        days = st.slider("Window (days)", 1, 90, 30)
        rows = db.engagement_over_time(days=days)
        if rows:
            df = pd.DataFrame(rows)
            fig = px.line(
                df, x="day", y="events",
                markers=True,
                title=f"Watch events per day (last {days} days)",
            )
            st.plotly_chart(fig, use_container_width=True)

            fig2 = px.line(
                df, x="day", y="avg_completion",
                markers=True,
                title=f"Average completion % per day",
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Not enough data yet.")

        st.divider()
        rows = db.most_watched_movies(limit=10, days=None)
        if rows:
            df = pd.DataFrame(rows)
            fig = px.bar(
                df.sort_values("watches", ascending=True),
                x="watches", y="title",
                orientation="h",
                color="avg_completion",
                color_continuous_scale="Teal",
                title="Most-watched movies (with average completion %)",
                labels={"watches": "Events", "title": "Movie", "avg_completion": "Avg %"},
            )
            st.plotly_chart(fig, use_container_width=True)

        rows = db.genre_popularity()
        if rows:
            df = pd.DataFrame(rows).head(15)
            fig = px.bar(
                df.sort_values("movie_count", ascending=True),
                x="movie_count", y="genre",
                orientation="h",
                title="Number of rated movies per genre",
                labels={"movie_count": "", "genre": "Genre"},
            )
            st.plotly_chart(fig, use_container_width=True)

    with tab_users:
        st.subheader("Registered users")
        users = db.list_users()
        df = pd.DataFrame(users).rename(
            columns={
                "user_id": "ID",
                "username": "Username",
                "display_name": "Display name",
                "role": "Role",
                "geo_id": "Region",
                "registration_date": "Registered",
                "last_login_at": "Last login",
            }
        )
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.caption(f"Total users: {len(users)} (admin: {sum(1 for u in users if u['role'] == 'ADMIN')})")


# ---------- entry ----------

def main() -> None:
    render_sidebar()
    page = st.session_state.page
    if page == "Sign in":
        page_signin()
    elif page == "Search & rate":
        page_search()
    elif page == "User dashboard":
        page_dashboard()
    elif page == "Admin console":
        page_admin()
    else:
        page_signin()


if __name__ == "__main__":
    main()
