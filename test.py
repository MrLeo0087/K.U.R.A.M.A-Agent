def get_active_user_emails(users: list) -> list:
    """Filters a list of user dictionaries and extracts active user emails."""
    return [user["email"] for user in users if user.get("status") == "active" and "email" in user]