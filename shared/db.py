import streamlit as st
from supabase import create_client

def get_supabase():
    url = st.secrets["https://wvbrpclzdvcvkbgehxfu.supabase.co"]
    key = st.secrets["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind2YnJwY2x6ZHZjdmtiZ2VoeGZ1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI0OTEyNDAsImV4cCI6MjA4ODA2NzI0MH0.DnMn4u5drKcETVTv4tFKz-7uv5AEisU36q1hEm0rE2k"]
    return create_client(url, key)
