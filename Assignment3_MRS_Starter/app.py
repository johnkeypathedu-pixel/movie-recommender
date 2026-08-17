"""Streamlit interface for the Assessment 3 starter prototype."""

import pandas as pd
import plotly.express as px
import streamlit as st

from mrs_core import RecommendationEngine, User, demo_catalogue


st.set_page_config(page_title="Movie Recommendation System", page_icon="🎬", layout="wide")


@st.cache_resource
def load_demo_data():
    catalogue = demo_catalogue()
    return catalogue, RecommendationEngine(catalogue), User("U001", "Demo User")


catalogue, engine, user = load_demo_data()

st.title("🎬 AI Movie Recommendation System")
st.caption("Assessment 3 starter prototype — replace demo data and credentials before submission.")

with st.sidebar:
    page = st.radio("Navigate", ["Discover", "Dashboard", "Admin Console"])

if page == "Discover":
    st.header("Search and rate movies")
    query = st.text_input("Search by title or genre", placeholder="Try: adventure")
    results = engine.search_movies(query)

    for movie in results:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.subheader(movie.title)
            left.write(f"{movie.year} · {', '.join(movie.genres)} · ⭐ {movie.average_rating:.1f}")
            score = right.slider("Your rating", 1, 5, 5, key=f"rating_{movie.movie_id}")
            if right.button("Save rating", key=f"save_{movie.movie_id}"):
                user.rate_movie(movie.movie_id, score)
                movie.add_rating(score)
                if movie.movie_id not in user.watch_history:
                    user.watch_history.append(movie.movie_id)
                st.success(f"Saved your rating for {movie.title}.")

    st.subheader("Recommended for you")
    recommendations = engine.recommend(user)
    st.write(" · ".join(movie.title for movie in recommendations) or "Rate a movie to personalise recommendations.")

elif page == "Dashboard":
    st.header(f"{user.name}'s dashboard")
    recommendations = engine.recommend(user)
    st.subheader("Top recommendations")
    st.write(" · ".join(movie.title for movie in recommendations))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Trending movies")
        trending = sorted(catalogue, key=lambda movie: movie.watch_count, reverse=True)[:5]
        st.dataframe(pd.DataFrame({"Movie": [m.title for m in trending], "Views": [m.watch_count for m in trending]}), hide_index=True)
    with col2:
        st.subheader("Your watch history and ratings")
        history = [next(m for m in catalogue if m.movie_id == movie_id).title for movie_id in user.get_user_history()]
        st.write(history or "No watch history yet.")
        st.write(user.ratings or "No ratings yet.")

    chart_data = pd.DataFrame({"Movie": [m.title for m in catalogue], "Average rating": [m.average_rating for m in catalogue]})
    st.plotly_chart(px.bar(chart_data, x="Movie", y="Average rating", title="Catalogue average ratings"), use_container_width=True)

else:
    st.header("Administrator console")
    key = st.text_input("Admin login key", type="password")
    if key == "MRS-ADMIN-2026":
        st.success("Administrator access granted.")
        st.subheader("Catalogue management")
        st.dataframe(pd.DataFrame({"ID": [m.movie_id for m in catalogue], "Title": [m.title for m in catalogue], "Views": [m.watch_count for m in catalogue]}), hide_index=True)
        st.info("Extend this page with add, edit, and remove forms before submission.")
        st.subheader("User engagement trend")
        engagement = pd.DataFrame({"Movie": [m.title for m in catalogue], "Views": [m.watch_count for m in catalogue]})
        st.plotly_chart(px.bar(engagement.sort_values("Views", ascending=False), x="Movie", y="Views"), use_container_width=True)
    elif key:
        st.error("Invalid administrator key.")
