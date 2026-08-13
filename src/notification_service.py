from src.db_service import (
    create_notification,
    get_notifications_for_user,
    count_unread_notifications,
    mark_notification_read,
    mark_all_notifications_read,
)


def notify_new_application(vacancy_owner_id, applicant_name, vacancy_title, vacancy_id):
    message = f"Pelamar baru: {applicant_name} melamar {vacancy_title}"
    return create_notification(vacancy_owner_id, "new_application", message, vacancy_id)


def notify_application_status(user_id, status, vacancy_title, vacancy_id):
    status_label = {"pending": "Pending", "reviewed": "Ditinjau",
                    "accepted": "Diterima", "rejected": "Ditolak"}
    label = status_label.get(status, status)
    message = f"Lamaran untuk {vacancy_title} telah {label}"
    return create_notification(user_id, "status_update", message, vacancy_id)


def notify_new_message(receiver_id, sender_name, vacancy_title, vacancy_id):
    message = f"Pesan baru dari {sender_name} mengenai {vacancy_title}"
    return create_notification(receiver_id, "new_message", message, vacancy_id)


def get_notifications(user_id, limit=20):
    return get_notifications_for_user(user_id, limit)


def get_unread_count(user_id):
    return count_unread_notifications(user_id)


def read_notification(notif_id, user_id):
    return mark_notification_read(notif_id, user_id)


def read_all_notifications(user_id):
    return mark_all_notifications_read(user_id)
